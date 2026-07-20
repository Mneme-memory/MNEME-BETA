"""
Embedding Migration / Backfill for Mneme
========================================

One mechanism, two audiences:
  (a) users moving from OpenAI embeddings (1536-d) to local bge-small (384-d),
  (b) users with unembedded rows (e.g. history imported before a provider fix).

Both are the same operation: find every message whose stored embedding is
missing or was produced by a *different* model than the current provider's,
then re-embed it with the CURRENT provider and stamp the correct `model`
provenance.

Design guarantees
-----------------
* Backup first — a timestamped SQLite snapshot is created (via the existing
  VACUUM INTO machinery on `Database.create_backup`) BEFORE any write. If the
  backup fails, the migration aborts and touches nothing.
* Idempotent + resumable — progress state IS the `embeddings.model` column.
  A re-run simply picks up whatever rows are still mismatched. No progress table.
* Interruption-safe — each message is re-embedded in its own auto-committed
  write (Database.execute_write commits per call), so a hard kill mid-run only
  loses the in-flight message, and the next run resumes cleanly.
* Background thread — mirrors server.py's `_run_startup_entity_backfill`
  threading pattern (daemon thread + shared status dict), no new scheme.
* Verify pass — re-counts mismatched rows at the end; reports `done` only if
  that count is 0, otherwise `partial` with the remaining count.

Mixed-dimension safety during a run: while the store holds both 1536-d and
384-d vectors, retrieval calls `embedder.cosine_similarity`, whose length guard
returns 0.0 for mismatched dimensions (see embeddings.py). Old vectors simply
score as unrelated until re-embedded — retrieval never crashes.
"""

import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional


# Matches background.py's embedding size guard.
LARGE_MSG_CHAR_LIMIT = 15000

# Per-provider similarity thresholds (local vectors are less spread out, so a
# higher cutoff is correct). Applied to the profile config on a completed run.
PROVIDER_SIMILARITY_THRESHOLD = {"local": 0.50, "openai": 0.25}
LOCAL_EMBEDDING_MODEL = "bge-small-en-v1.5"

# Rough per-message embedding time (seconds) for the ETA shown in the UI.
# Local ONNX CPU inference is ~0.05-0.15s/msg; use a conservative estimate.
_SECONDS_PER_MESSAGE = 0.15

_MAX_ERRORS_TRACKED = 20
_BATCH_SIZE = 25


class EmbeddingMigrationManager:
    """Owns the (single) migration job's state and background thread."""

    def __init__(self):
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._reset_state()

    def _reset_state(self):
        self.state = {
            "running": False,
            "phase": "idle",          # idle|backing_up|embedding|verifying|done|error
            "done_count": 0,          # messages re-embedded this run
            "target_count": 0,        # pending at the moment the run started
            "remaining_count": 0,     # live remaining (post-verify on completion)
            "errors": [],             # human-readable error strings (capped)
            "backup_path": None,
            "started_at": None,
            "finished_at": None,
            "message": "",            # short human-facing status line
        }

    # ------------------------------------------------------------------ status

    def is_running(self) -> bool:
        with self._lock:
            return self.state["running"]

    def snapshot(self) -> Dict:
        with self._lock:
            return dict(self.state)

    def build_status(self, db, embedder, config) -> Dict:
        """
        Full status payload for GET /api/embeddings/migration-status.

        Combines live DB detection (pending_count / total) with the job's
        in-memory progress. Safe to call whether or not a job is running.
        """
        provider = config.get("retrieval", {}).get("embedding_provider", "openai")
        current_model = getattr(embedder, "model", "") or ""
        target_provider = "local" if provider != "local" else provider
        target_model = LOCAL_EMBEDDING_MODEL if target_provider == "local" else current_model

        pending = db.count_messages_needing_migration(target_model, LARGE_MSG_CHAR_LIMIT)
        total = db.get_message_count()

        job = self.snapshot()
        # While running, prefer the live done/target so the bar advances even
        # though `pending` (recomputed from DB) is also shrinking in lockstep.
        eta_seconds = pending * _SECONDS_PER_MESSAGE
        estimated_minutes = round(eta_seconds / 60.0, 1)

        return {
            "pending_count": pending,
            "total": total,
            "current_provider": provider,
            "current_model": current_model,
            "target_provider": target_provider,
            "target_model": target_model,
            "estimated_minutes": estimated_minutes,
            # Job progress
            "running": job["running"],
            "phase": job["phase"],
            "done_count": job["done_count"],
            "target_count": job["target_count"],
            "errors": job["errors"],
            "backup_path": (Path(job["backup_path"]).name if job["backup_path"] else None),
            "message": job["message"],
        }

    # ------------------------------------------------------------------- start

    def start(self, db, embedder, config, backup_dir: str,
              cloud_backup_dir: Optional[str], keep_count: int,
              on_complete: Optional[Callable[[str], None]] = None) -> Dict:
        """
        Launch the migration in a background thread.

        `on_complete(provider)` is invoked (from the worker thread) only after a
        fully verified run (0 remaining) so the caller can persist the correct
        per-provider similarity_threshold. It is NOT called on partial/failed
        runs.

        Returns immediately with {"started": bool, "reason": str}.
        """
        with self._lock:
            if self.state["running"]:
                return {"started": False, "reason": "already_running"}
            self._reset_state()
            self.state["running"] = True
            self.state["phase"] = "backing_up"
            self.state["started_at"] = datetime.now(timezone.utc).isoformat()
            self.state["message"] = "Preparing backup..."

        self._thread = threading.Thread(
            target=self._run,
            args=(db, embedder, config, backup_dir, cloud_backup_dir, keep_count, on_complete),
            daemon=True,
        )
        self._thread.start()
        return {"started": True, "reason": "started"}

    # ------------------------------------------------------------------ worker

    def _set(self, **kwargs):
        with self._lock:
            self.state.update(kwargs)

    def _add_error(self, msg: str):
        with self._lock:
            if len(self.state["errors"]) < _MAX_ERRORS_TRACKED:
                self.state["errors"].append(msg)

    def _run(self, db, embedder, config, backup_dir, cloud_backup_dir, keep_count, on_complete):
        try:
            current_model = getattr(embedder, "model", "") or ""
            provider = config.get("retrieval", {}).get("embedding_provider", "openai")

            # --- 1. BACKUP FIRST (abort on failure) -----------------------
            # Dedicated sub-directory so migration snapshots aren't pruned by
            # the rolling startup-backup keep_count.
            pre_dir = str(Path(backup_dir) / "pre_migration")
            backup_path = db.create_backup(pre_dir, cloud_backup_dir=cloud_backup_dir, keep_count=keep_count)
            if not backup_path:
                self._set(
                    running=False, phase="error", finished_at=_now(),
                    message="Backup failed — migration aborted. Your data is unchanged.",
                )
                self._add_error("Could not create a database backup; nothing was migrated.")
                return
            self._set(backup_path=backup_path)

            # --- 2. EMBED --------------------------------------------------
            target = db.count_messages_needing_migration(current_model, LARGE_MSG_CHAR_LIMIT)
            self._set(
                phase="embedding", target_count=target, done_count=0,
                message=f"Re-embedding {target} messages...",
            )

            failed_ids = set()
            done = 0
            while True:
                if self._should_stop():
                    break
                batch = db.get_messages_needing_migration(
                    current_model, limit=_BATCH_SIZE, max_chars=LARGE_MSG_CHAR_LIMIT
                )
                # Drop rows we've already failed on so we don't spin forever.
                batch = [m for m in batch if m["id"] not in failed_ids]
                if not batch:
                    break

                progressed = False
                for msg in batch:
                    if self._should_stop():
                        break
                    ok = self._reembed_one(db, embedder, msg, current_model)
                    if ok:
                        done += 1
                        progressed = True
                        self._set(done_count=done)
                    else:
                        failed_ids.add(msg["id"])

                if not progressed:
                    # Whole batch failed — avoid an infinite loop.
                    break

            # --- 3. VERIFY -------------------------------------------------
            self._set(phase="verifying", message="Verifying...")
            remaining = db.count_messages_needing_migration(current_model, LARGE_MSG_CHAR_LIMIT)
            self._set(remaining_count=remaining)

            if remaining == 0:
                # Persist the correct per-provider threshold on a verified run.
                if on_complete:
                    try:
                        on_complete(provider)
                    except Exception as e:
                        self._add_error(f"Threshold update failed: {e}")
                self._set(
                    running=False, phase="done", finished_at=_now(),
                    message=f"Done — {done} messages re-embedded. Backup saved.",
                )
            else:
                self._set(
                    running=False, phase="done", finished_at=_now(),
                    message=(f"Partial — {done} re-embedded, {remaining} still pending "
                             f"(likely errors). Backup saved; nothing was lost. "
                             f"Run again to resume."),
                )

        except Exception as e:
            self._add_error(str(e))
            self._set(
                running=False, phase="error", finished_at=_now(),
                message=f"Migration error: {e}. Your backup is safe and nothing was lost.",
            )

    def _should_stop(self) -> bool:
        # Reserved hook (e.g. for a future cancel button). Currently never set.
        return False

    def _reembed_one(self, db, embedder, msg: Dict, current_model: str) -> bool:
        """Re-embed a single message; replace its embedding row atomically-ish."""
        try:
            old_embedding_id = msg.get("embedding_id")
            vector = embedder.generate_embedding(msg["content"])
            new_id = db.add_embedding(vector=vector, model=current_model, cost=0.0)
            db.update_message_embedding(msg["id"], new_id)
            # Reclaim the stale row only after the message points at the new one.
            if old_embedding_id and old_embedding_id != new_id:
                try:
                    db.delete_embedding(old_embedding_id)
                except Exception:
                    pass  # orphan row is harmless; don't fail the message over it
            return True
        except Exception as e:
            self._add_error(f"msg {msg.get('id')}: {e}")
            return False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# Module-level singleton (one migration per server process).
migration_manager = EmbeddingMigrationManager()
