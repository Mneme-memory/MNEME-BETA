"""
Provenance Tracking for Mneme Context Assembly

Logs what memories, concepts, and entity summaries are surfaced each turn,
with full score breakdowns. Append-only, read-only after write.

TABLES (defined in schema.py):
- turn_log: Parent table, one row per context assembly
- retrieval_log: Per-memory scores and inclusion status
- concept_trigger_log: Concept keyword matches
- entity_summary_log: Entity summary selection

USAGE:
    provenance = ProvenanceLogger(db)
    turn_id = provenance.start_turn()
    provenance.log_retrievals(turn_id, results, query, "standard", included_ids)
    provenance.log_concepts(turn_id, concept_data)
    provenance.log_entity_summaries(turn_id, entity_data)
    provenance.finalize_turn(turn_id, memories_considered, memories_included, total_tokens)
    report = provenance.get_turn_report(turn_id)
"""

import uuid
import json
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set


class ProvenanceLogger:
    """
    Append-only logger for context assembly provenance.

    Records what was retrieved, what was included, and why things
    were cut — per turn, with full score breakdowns.
    """

    def __init__(self, database):
        """
        Initialize provenance logger.

        Args:
            database: Database instance (shared with other components)
        """
        self.db = database
        self._ensure_tables()

    def _ensure_tables(self):
        """
        Ensure provenance tables exist (for existing databases).

        New databases get tables from schema.py. Existing databases
        need this migration path.
        """
        try:
            # Check if turn_log exists
            result = self.db.execute_query(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='turn_log'"
            )
            if not result:
                # Tables don't exist yet — create them
                from .schema import create_database_schema
                # Can't re-run full schema (would fail on existing tables),
                # so create just the provenance tables
                self._create_provenance_tables()
        except Exception as e:
            print(f"Warning: Provenance table check failed: {e}")

    def _create_provenance_tables(self):
        """Create provenance tables on an existing database."""
        import sqlite3

        conn = None
        try:
            conn = self.db._get_connection()
            cursor = conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS turn_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    turn_id TEXT NOT NULL UNIQUE,
                    query_text TEXT,
                    tier_filter TEXT,
                    memories_considered INTEGER DEFAULT 0,
                    memories_included INTEGER DEFAULT 0,
                    total_tokens_used INTEGER DEFAULT 0,
                    timestamp TEXT NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS retrieval_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    turn_id TEXT NOT NULL,
                    message_id INTEGER,
                    similarity_score REAL,
                    importance_raw REAL,
                    importance_effective REAL,
                    recency_multiplier REAL,
                    composite_score REAL,
                    rank INTEGER,
                    was_included INTEGER DEFAULT 1,
                    exclusion_reason TEXT,
                    timestamp TEXT NOT NULL,
                    FOREIGN KEY (turn_id) REFERENCES turn_log(turn_id),
                    FOREIGN KEY (message_id) REFERENCES messages(id)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS concept_trigger_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    turn_id TEXT NOT NULL,
                    concept_id INTEGER,
                    concept_name TEXT,
                    matched_keywords TEXT,
                    match_count INTEGER DEFAULT 0,
                    was_included INTEGER DEFAULT 1,
                    timestamp TEXT NOT NULL,
                    FOREIGN KEY (turn_id) REFERENCES turn_log(turn_id)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS entity_summary_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    turn_id TEXT NOT NULL,
                    entity_id INTEGER,
                    entity_name TEXT,
                    relevance_score REAL,
                    rank INTEGER,
                    was_included INTEGER DEFAULT 1,
                    timestamp TEXT NOT NULL,
                    FOREIGN KEY (turn_id) REFERENCES turn_log(turn_id)
                )
            """)

            # Indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_turn_log_turn_id ON turn_log(turn_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_turn_log_timestamp ON turn_log(timestamp DESC)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_retrieval_log_turn ON retrieval_log(turn_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_retrieval_log_message ON retrieval_log(message_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_concept_trigger_log_turn ON concept_trigger_log(turn_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_entity_summary_log_turn ON entity_summary_log(turn_id)")

            conn.commit()
            print("  Provenance tables created (migration)")
        except sqlite3.Error as e:
            print(f"Warning: Failed to create provenance tables: {e}")
        finally:
            if conn:
                conn.close()

    # =========================================================================
    # Write Methods
    # =========================================================================

    def start_turn(self) -> str:
        """
        Start a new provenance turn. Returns a UUID turn_id.

        Call this at the beginning of assemble_context().
        """
        turn_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        self.db.execute_write(
            """INSERT INTO turn_log (turn_id, timestamp)
               VALUES (?, ?)""",
            (turn_id, now)
        )

        return turn_id

    def log_retrievals(
        self,
        turn_id: str,
        all_results: List[Dict],
        included_ids: Set[int],
        excluded_reasons: Optional[Dict[int, str]] = None
    ):
        """
        Log all retrieval candidates for a turn.

        Args:
            turn_id: UUID from start_turn()
            all_results: Full list from semantic_search() (before dedup/budget)
            included_ids: Set of message IDs that made it into the prompt
            excluded_reasons: Optional dict mapping excluded msg_id -> reason
                            ('duplicate', 'budget', 'recent_context')
        """
        if not all_results:
            return

        excluded_reasons = excluded_reasons or {}
        now = datetime.now(timezone.utc).isoformat()

        rows = []
        for rank, r in enumerate(all_results, 1):
            msg_id = r.get("id")
            included = 1 if msg_id in included_ids else 0
            reason = None if included else excluded_reasons.get(msg_id, "budget")

            rows.append((
                turn_id,
                msg_id,
                r.get("semantic_similarity"),
                r.get("importance"),
                r.get("effective_importance"),
                r.get("recency_multiplier"),
                r.get("final_score"),
                rank,
                included,
                reason,
                now
            ))

        self.db.execute_many(
            """INSERT INTO retrieval_log
               (turn_id, message_id, similarity_score, importance_raw,
                importance_effective, recency_multiplier, composite_score,
                rank, was_included, exclusion_reason, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows
        )

    def log_concepts(
        self,
        turn_id: str,
        triggered_concepts: List[Dict],
        included_ids: Optional[Set[int]] = None
    ):
        """
        Log concept triggers for a turn.

        Args:
            turn_id: UUID from start_turn()
            triggered_concepts: List of dicts with keys:
                id, name, matched_keywords, match_count
            included_ids: Set of concept IDs that made budget cut.
                         If None, all assumed included.
        """
        if not triggered_concepts:
            return

        now = datetime.now(timezone.utc).isoformat()

        rows = []
        for c in triggered_concepts:
            cid = c.get("id")
            included = 1 if (included_ids is None or cid in included_ids) else 0

            rows.append((
                turn_id,
                cid,
                c.get("name", ""),
                json.dumps(c.get("matched_keywords", [])),
                c.get("match_count", 0),
                included,
                now
            ))

        self.db.execute_many(
            """INSERT INTO concept_trigger_log
               (turn_id, concept_id, concept_name, matched_keywords,
                match_count, was_included, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            rows
        )

    def log_entity_summaries(
        self,
        turn_id: str,
        scored_entities: List[Dict],
        included_ids: Optional[Set[int]] = None
    ):
        """
        Log entity summary selection for a turn.

        Args:
            turn_id: UUID from start_turn()
            scored_entities: List of dicts with keys:
                entity_id, entity_name, relevance_score
            included_ids: Set of entity IDs that got summaries included.
                         If None, all assumed included.
        """
        if not scored_entities:
            return

        now = datetime.now(timezone.utc).isoformat()

        rows = []
        for rank, e in enumerate(scored_entities, 1):
            eid = e.get("entity_id")
            included = 1 if (included_ids is None or eid in included_ids) else 0

            rows.append((
                turn_id,
                eid,
                e.get("entity_name", ""),
                e.get("relevance_score"),
                rank,
                included,
                now
            ))

        self.db.execute_many(
            """INSERT INTO entity_summary_log
               (turn_id, entity_id, entity_name, relevance_score,
                rank, was_included, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            rows
        )

    def finalize_turn(
        self,
        turn_id: str,
        query_text: Optional[str] = None,
        tier_filter: Optional[str] = None,
        memories_considered: int = 0,
        memories_included: int = 0,
        total_tokens_used: int = 0
    ):
        """
        Update the turn_log row with final counts.

        Call this at the end of assemble_context() after all logging is done.
        """
        self.db.execute_write(
            """UPDATE turn_log
               SET query_text = ?,
                   tier_filter = ?,
                   memories_considered = ?,
                   memories_included = ?,
                   total_tokens_used = ?
               WHERE turn_id = ?""",
            (query_text, tier_filter, memories_considered,
             memories_included, total_tokens_used, turn_id)
        )

    # =========================================================================
    # Read Methods
    # =========================================================================

    def get_turn_report(self, turn_id: str) -> Dict:
        """
        Retrieve full provenance for a turn.

        Args:
            turn_id: UUID of the turn

        Returns:
            dict: Complete provenance data for the turn
        """
        # Turn metadata
        turn_rows = self.db.execute_query(
            "SELECT * FROM turn_log WHERE turn_id = ?",
            (turn_id,)
        )
        if not turn_rows:
            return {"error": f"Turn {turn_id} not found"}

        turn = dict(turn_rows[0])

        # Retrievals
        retrieval_rows = self.db.execute_query(
            """SELECT message_id, similarity_score, importance_raw,
                      importance_effective, recency_multiplier,
                      composite_score, rank, was_included, exclusion_reason
               FROM retrieval_log
               WHERE turn_id = ?
               ORDER BY rank""",
            (turn_id,)
        )
        retrievals = [
            {
                "message_id": r["message_id"],
                "similarity": round(r["similarity_score"], 4) if r["similarity_score"] else None,
                "importance_raw": round(r["importance_raw"], 2) if r["importance_raw"] else None,
                "importance_effective": round(r["importance_effective"], 2) if r["importance_effective"] else None,
                "recency": round(r["recency_multiplier"], 2) if r["recency_multiplier"] else None,
                "composite": round(r["composite_score"], 4) if r["composite_score"] else None,
                "rank": r["rank"],
                "included": bool(r["was_included"]),
                "exclusion_reason": r["exclusion_reason"]
            }
            for r in retrieval_rows
        ]

        # Concepts
        concept_rows = self.db.execute_query(
            """SELECT concept_name, matched_keywords, match_count, was_included
               FROM concept_trigger_log
               WHERE turn_id = ?
               ORDER BY match_count DESC""",
            (turn_id,)
        )
        concepts = [
            {
                "name": c["concept_name"],
                "keywords": json.loads(c["matched_keywords"]) if c["matched_keywords"] else [],
                "match_count": c["match_count"],
                "included": bool(c["was_included"])
            }
            for c in concept_rows
        ]

        # Entity summaries
        entity_rows = self.db.execute_query(
            """SELECT entity_name, relevance_score, rank, was_included
               FROM entity_summary_log
               WHERE turn_id = ?
               ORDER BY rank""",
            (turn_id,)
        )
        entities = [
            {
                "name": e["entity_name"],
                "relevance": round(e["relevance_score"], 4) if e["relevance_score"] else None,
                "rank": e["rank"],
                "included": bool(e["was_included"])
            }
            for e in entity_rows
        ]

        return {
            "turn_id": turn_id,
            "query": turn.get("query_text"),
            "tier_filter": turn.get("tier_filter"),
            "timestamp": turn.get("timestamp"),
            "total_tokens": turn.get("total_tokens_used", 0),
            "memories_considered": len(retrievals),
            "memories_included": sum(1 for r in retrievals if r["included"]),
            "memories_cut": sum(1 for r in retrievals if not r["included"]),
            "concepts_triggered": len(concepts),
            "concepts_included": sum(1 for c in concepts if c["included"]),
            "entities_considered": len(entities),
            "entities_included": sum(1 for e in entities if e["included"]),
            "retrievals": retrievals,
            "concepts": concepts,
            "entity_summaries": entities
        }

    def get_recent_turns(self, limit: int = 20) -> List[Dict]:
        """
        Get recent turn summaries (without full retrieval details).

        Args:
            limit: Maximum turns to return

        Returns:
            List of turn summary dicts
        """
        rows = self.db.execute_query(
            """SELECT turn_id, query_text, memories_considered,
                      memories_included, total_tokens_used, timestamp
               FROM turn_log
               ORDER BY timestamp DESC
               LIMIT ?""",
            (limit,)
        )
        return [dict(r) for r in rows]
