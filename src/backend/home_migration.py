"""
Home Migration for Mneme

The shared copy routine behind both data bridges:
- Relocation: moving a legacy install's user state out of the app folder
  into the resolved Mneme home (%LOCALAPPDATA%/Mneme).
- Import: first-run "Import from a previous Mneme" in the setup wizard.

Hard invariants (do not weaken):
- The source install is NEVER modified, moved, or deleted. Copy only.
- dst config.json is written LAST — its presence is what flips
  get_mneme_home() to the new location, so an interrupted copy leaves the
  resolver pointing at the still-intact source.
- Live SQLite files are copied through the sqlite3 backup API (the server
  may be running with open WAL files during relocation); a raw file copy
  of a hot WAL database can produce a corrupt snapshot.
- Every copied memory.db is verified (PRAGMA quick_check + message count
  against the source) before the copy is committed. Any failure removes
  everything this routine created and raises.

USAGE:
    from src.backend.home_migration import describe_install, copy_install
    info = describe_install(Path("C:/Users/x/Documents/GitHub/Mneme"))
    report = copy_install(src_root, dst_home)
"""

import json
import shutil
import sqlite3
from pathlib import Path

try:
    from src.backend.config import get_project_root
except ModuleNotFoundError:
    from config import get_project_root


class MigrationError(Exception):
    """Raised when an install copy cannot be completed safely."""
    pass


# Runtime droppings that should not travel to a new home
SKIP_NAMES = {".server.pid", ".launched", "memory.db-wal", "memory.db-shm"}

# The tray/server creates these in <home>/data before first-run setup begins.
# They are not user state and must not make an otherwise-empty destination look
# occupied to the import guard. Keep this narrower than SKIP_NAMES: a stray WAL
# or SHM file at the destination should still stop an import.
DESTINATION_RUNTIME_NAMES = {".server.pid", ".launched"}

# The live database filename — copied via the sqlite3 backup API
LIVE_DB_NAME = "memory.db"


def _read_config_file(root):
    """Read <root>/config.json as parsed JSON, or None if absent/invalid."""
    config_path = Path(root) / "config.json"
    if not config_path.exists():
        return None
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _data_dir_for(root, cfg):
    """
    Where an install's data/ tree lives.

    Follows the config's database_path template when present. Returns
    (data_dir, is_external) where is_external means the data lives at an
    absolute path outside the install folder (and must not be copied —
    the config already points at it and will keep working).
    """
    root = Path(root)
    template = ""
    if cfg:
        storage = cfg.get("storage", {})
        template = storage.get("database_path_template", storage.get("database_path", ""))

    if template and "{profile}" in template:
        base = template.split("{profile}")[0]
    elif template:
        # Resolved path — profile dir's parent
        base = str(Path(template).parent.parent)
    else:
        base = "./data/"

    base_path = Path(base)
    if base_path.is_absolute():
        try:
            base_path.resolve().relative_to(root.resolve())
            return base_path, False
        except (ValueError, OSError):
            return base_path, True
    return root / base_path, False


def describe_install(root):
    """
    Check whether a folder looks like a Mneme install and describe it.

    Returns None if it doesn't. Otherwise a dict:
        {
            "path": str, "has_config": bool, "has_api_key": bool,
            "data_external": bool, "data_dir": str,
            "profiles": [{"name", "db_bytes", "message_count"}],
            "total_bytes": int,
        }
    message_count is -1 when the database can't be read.
    """
    root = Path(root)
    if not root.is_dir():
        return None
    # Never treat the resolved home's own app folder confusion cases as imports
    cfg = _read_config_file(root)
    data_dir, data_external = _data_dir_for(root, cfg)

    profiles = []
    total_bytes = 0
    if data_dir.is_dir():
        for entry in sorted(data_dir.iterdir()):
            db_file = entry / LIVE_DB_NAME
            if not entry.is_dir() or not db_file.exists():
                continue
            db_bytes = db_file.stat().st_size
            message_count = -1
            try:
                conn = sqlite3.connect(f"file:{db_file.as_posix()}?mode=ro", uri=True, timeout=5)
                message_count = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
                conn.close()
            except Exception:
                pass
            profiles.append({
                "name": entry.name,
                "db_bytes": db_bytes,
                "message_count": message_count,
            })
        if not data_external:
            for f in data_dir.rglob("*"):
                if f.is_file():
                    try:
                        total_bytes += f.stat().st_size
                    except OSError:
                        pass

    if cfg is None and not profiles:
        return None

    has_key = bool(cfg and cfg.get("api_keys", {}).get("anthropic", "").strip()
                   and cfg.get("api_keys", {}).get("anthropic") != "YOUR_ANTHROPIC_API_KEY_HERE")

    return {
        "path": str(root),
        "has_config": cfg is not None,
        "has_api_key": has_key,
        "data_external": data_external,
        "data_dir": str(data_dir),
        "profiles": profiles,
        "total_bytes": total_bytes,
    }


def _backup_sqlite(src_db, dst_db):
    """Consistent snapshot of a (possibly live, WAL-mode) SQLite database."""
    src_conn = sqlite3.connect(f"file:{Path(src_db).as_posix()}?mode=ro", uri=True, timeout=30)
    try:
        dst_conn = sqlite3.connect(str(dst_db))
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
    finally:
        src_conn.close()


def _verify_copied_db(src_db, dst_db):
    """quick_check the copy and compare message counts against the source."""
    conn = sqlite3.connect(f"file:{Path(dst_db).as_posix()}?mode=ro", uri=True, timeout=30)
    try:
        result = conn.execute("PRAGMA quick_check").fetchone()[0]
        if result != "ok":
            raise MigrationError(f"Copied database failed integrity check: {dst_db} ({result})")
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        dst_count = None
        if "messages" in tables:
            dst_count = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    finally:
        conn.close()

    if dst_count is not None:
        src_conn = sqlite3.connect(f"file:{Path(src_db).as_posix()}?mode=ro", uri=True, timeout=30)
        try:
            src_count = src_conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        finally:
            src_conn.close()
        # The source may have gained messages while we copied (server live);
        # the copy must never have FEWER than the source had at snapshot
        # time, but a small forward drift on the source is not data loss.
        if dst_count < src_count - 50:
            raise MigrationError(
                f"Copied database looks incomplete: {dst_db} "
                f"({dst_count} messages vs {src_count} at source)"
            )


def copy_install(src_root, dst_home, allow_nonempty=False, on_progress=None,
                 leave_note=False):
    """
    Copy a Mneme install's user state (data/, config.json,
    system_instructions.txt) from src_root into dst_home.

    Args:
        src_root: existing install folder (validated via describe_install)
        dst_home: target home folder (created if missing)
        allow_nonempty: proceed even if dst_home already holds data
        on_progress: optional callable(done_bytes, total_bytes, label)
        leave_note: drop WHERE-IS-MY-DATA.txt in src_root on success
                    (relocation flow only — requires src_root writable)

    Returns a report dict. Raises MigrationError on any failure, after
    removing everything this call created. The source is never touched.
    """
    src_root = Path(src_root)
    dst_home = Path(dst_home)

    info = describe_install(src_root)
    if info is None:
        raise MigrationError(
            f"'{src_root}' doesn't look like a Mneme install "
            f"(no config.json or data/<profile>/memory.db found)."
        )

    try:
        if src_root.resolve() == dst_home.resolve():
            raise MigrationError("Source and destination are the same folder.")
    except OSError:
        pass

    # Refuse to clobber an existing home unless explicitly confirmed
    dst_config = dst_home / "config.json"
    dst_data = dst_home / "data"
    if not allow_nonempty:
        if dst_config.exists():
            raise MigrationError(
                f"'{dst_home}' already has a config.json — refusing to overwrite. "
                f"Move it aside first if you really want to replace it."
            )
        if dst_data.is_dir() and any(
            not (entry.is_file() and entry.name in DESTINATION_RUNTIME_NAMES)
            for entry in dst_data.iterdir()
        ):
            raise MigrationError(
                f"'{dst_home}\\data' already contains files — refusing to overwrite."
            )

    src_data = Path(info["data_dir"])
    data_external = info["data_external"]
    total_bytes = info["total_bytes"]

    created = []          # every path this call creates, newest last
    done_bytes = 0

    def _progress(label):
        if on_progress:
            on_progress(done_bytes, total_bytes, label)

    def _copy_tree(src_dir, dst_dir):
        nonlocal done_bytes
        for src_file in sorted(src_dir.rglob("*")):
            if not src_file.is_file():
                continue
            if src_file.name in SKIP_NAMES:
                continue
            relative = src_file.relative_to(src_dir)
            target = dst_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            created.append(target)   # registered first so a partial file still rolls back
            if src_file.name == LIVE_DB_NAME:
                _backup_sqlite(src_file, target)
            else:
                shutil.copy2(src_file, target)
            try:
                done_bytes += src_file.stat().st_size
            except OSError:
                pass
            _progress(str(relative))

    def _rollback():
        for path in reversed(created):
            try:
                path.unlink()
            except OSError:
                pass
        # Prune now-empty directories we may have introduced
        if dst_data.is_dir():
            for directory in sorted(dst_data.rglob("*"), reverse=True):
                if directory.is_dir():
                    try:
                        directory.rmdir()   # only succeeds when empty
                    except OSError:
                        pass
            try:
                dst_data.rmdir()
            except OSError:
                pass

    try:
        dst_home.mkdir(parents=True, exist_ok=True)

        # 1. Data tree (skipped when the config points at external storage —
        #    the copied config keeps pointing there and nothing needs to move)
        copied_profiles = 0
        if not data_external and src_data.is_dir():
            _copy_tree(src_data, dst_data)
            copied_profiles = len(info["profiles"])

            # 2. Verify every copied live database before committing
            for profile in info["profiles"]:
                src_db = src_data / profile["name"] / LIVE_DB_NAME
                dst_db = dst_data / profile["name"] / LIVE_DB_NAME
                _verify_copied_db(src_db, dst_db)

        # 3. Root-level live system instructions
        src_instructions = src_root / "system_instructions.txt"
        if src_instructions.is_file():
            target = dst_home / "system_instructions.txt"
            created.append(target)
            shutil.copy2(src_instructions, target)

        # 4. config.json LAST — the commit point that flips the resolver.
        #    Copied as raw bytes: the on-disk file is the source of truth
        #    (never json.dump a live config dict — profile overlays and
        #    resolved absolute paths would leak in).
        src_config = src_root / "config.json"
        if src_config.is_file():
            created.append(dst_config)
            shutil.copy2(src_config, dst_config)

        _progress("done")

    except MigrationError:
        _rollback()
        raise
    except Exception as e:
        _rollback()
        raise MigrationError(f"Copy failed ({e}) — nothing was changed at the destination.") from e

    if leave_note:
        # Best-effort breadcrumb in the old install; never fail the
        # migration over it (the source may be read-only).
        try:
            note = src_root / "WHERE-IS-MY-DATA.txt"
            note.write_text(
                "Your Mneme data was copied to its new home:\n"
                f"    {dst_home}\n\n"
                "Mneme now reads and writes there. The data/ folder, config.json\n"
                "and system_instructions.txt in THIS folder are an untouched\n"
                "backup from the moment of the move. Once you've confirmed\n"
                "everything works, you can delete them.\n",
                encoding="utf-8",
            )
        except OSError:
            pass

    return {
        "src": str(src_root),
        "dst": str(dst_home),
        "copied_profiles": copied_profiles,
        "data_external": data_external,
        "bytes_copied": done_bytes,
        "has_config": info["has_config"],
    }


def find_candidate_installs(exclude=None):
    """
    Scan common locations for previous Mneme installs (import bridge).

    Returns a list of describe_install() dicts, deduplicated. `exclude`
    is an optional path (the current home) to omit from results.
    """
    home = Path.home()
    app_root = get_project_root()
    candidates = []
    for pattern_root, glob in [
        (home / "Documents" / "GitHub", "Mneme*"),
        (home / "Documents", "Mneme*"),
        (home / "Desktop", "Mneme*"),
        (home / "Downloads", "Mneme*"),
        (app_root.parent, "Mneme*"),
    ]:
        if not pattern_root.is_dir():
            continue
        try:
            candidates.extend(pattern_root.glob(glob))
        except OSError:
            continue

    exclude_resolved = set()
    for path in (exclude, app_root):
        if path:
            try:
                exclude_resolved.add(Path(path).resolve())
            except OSError:
                pass

    seen = set()
    results = []
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved in seen or resolved in exclude_resolved:
            continue
        seen.add(resolved)
        info = describe_install(candidate)
        if info and info["profiles"]:
            results.append(info)
    return results
