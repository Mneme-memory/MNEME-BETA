"""
Database Operations for Mneme Memory System

This module provides all the functions to interact with the SQLite database.

CRUD OPERATIONS:
- Create: Add new messages, embeddings
- Read: Retrieve messages, search memories
- Update: Modify importance scores, tier assignments
- Delete: Remove messages (rare - we prefer archiving)

WHY THIS FILE EXISTS:
- Separates database logic from other parts of the system
- Makes it easy to test database operations
- Provides a clean API for storing and retrieving memories
- Handles all SQL queries in one place

USAGE:
    from database import Database
    db = Database("path/to/memory.db")
    db.add_message(sender="user", content="Hello!", importance=5.0)
    messages = db.get_recent_messages(limit=10)
"""

import sqlite3
import json
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Tuple
from pathlib import Path
import os

from .database_embeddings import DatabaseEmbeddingsMixin
from .database_concepts import DatabaseConceptsMixin
from .database_attachments import DatabaseAttachmentsMixin
from .database_entities import DatabaseEntitiesMixin
from .database_timeline import DatabaseTimelineMixin


class DatabaseError(Exception):
    """
    Custom exception for database operations.
    This helps distinguish database problems from other errors.
    """
    pass


class Database(
    DatabaseEmbeddingsMixin,
    DatabaseConceptsMixin,
    DatabaseAttachmentsMixin,
    DatabaseEntitiesMixin,
    DatabaseTimelineMixin,
):
    """
    Main database interface for the Mneme memory system.

    This class handles all interactions with the SQLite database.
    It provides methods to store messages, retrieve memories, manage tags,
    and track importance scores.

    DESIGN PATTERN:
    This uses the "repository pattern" - a common way to organize database code.
    All database operations go through this class, making it easier to:
    - Test the code
    - Change the database later if needed
    - Keep track of what operations are available
    """

    def __init__(self, db_path: str, auto_initialize: bool = True):
        """
        Initialize database connection.

        Args:
            db_path (str): Path to the SQLite database file
            auto_initialize (bool): If True, automatically create schema if database is empty

        WHAT HAPPENS HERE:
        - Stores the database path
        - Creates the database file if it doesn't exist
        - Sets up connection parameters
        - Auto-initializes schema if enabled (Phase 4 feature)
        """
        self.db_path = db_path
        self._ensure_directory_exists()

        # Phase 4: Auto-initialize schema if database is new
        if auto_initialize:
            self._auto_initialize_schema()

    def _ensure_directory_exists(self):
        """
        Creates the directory for the database if it doesn't exist.

        WHY THIS MATTERS:
        If we try to create a database at "C:/Mneme/data/memory.db"
        but the "data" folder doesn't exist, we'll get an error.
        This function creates any missing directories.
        """
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)

    def _auto_initialize_schema(self):
        """
        Auto-initialize database schema if tables don't exist.

        PHASE 4 FEATURE:
        Makes profile switching seamless - no need to manually run init_db.py!
        When you switch profiles in config.json, the new database is automatically
        initialized on first use.

        WHAT THIS DOES:
        1. Checks if database file exists
        2. If new file: Creates schema silently
        3. If existing file: Checks if 'messages' table exists
        4. If no tables: Creates schema silently
        5. If tables exist: Does nothing (preserves existing data)
        """
        # Import here to avoid circular dependency
        from .schema import create_database_schema

        # Check if database file exists
        db_exists = os.path.exists(self.db_path)

        if not db_exists:
            # Brand new database - create schema
            print(f"📦 Creating new database: {self.db_path}")
            if not create_database_schema(self.db_path):
                raise DatabaseError("Failed to auto-initialize database schema")
            print(f"✓ Database initialized successfully")
            return

        # Database file exists - check if it has tables
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='messages'")
            has_tables = cursor.fetchone() is not None

            if not has_tables:
                # Empty database file - create schema
                print(f"📦 Initializing schema for: {self.db_path}")
                if not create_database_schema(self.db_path):
                    raise DatabaseError("Failed to auto-initialize database schema")
                print(f"✓ Schema initialized successfully")
            else:
                # Existing database - run migrations for new columns
                self._migrate_columns(cursor, conn)
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to check database schema: {e}")
        finally:
            if conn:
                conn.close()

    def _migrate_columns(self, cursor, conn):
        """Add columns that were introduced after the initial schema."""
        # Get existing columns for entity_summaries
        try:
            cursor.execute("PRAGMA table_info(entity_summaries)")
            columns = {row[1] for row in cursor.fetchall()}

            if "summary_short" not in columns:
                cursor.execute("ALTER TABLE entity_summaries ADD COLUMN summary_short TEXT")
                conn.commit()
        except sqlite3.Error:
            pass  # Table may not exist yet in very old DBs

    def _get_connection(self) -> sqlite3.Connection:
        """
        Creates a connection to the database.

        Returns:
            sqlite3.Connection: Database connection object

        CONFIGURATION:
        - row_factory = sqlite3.Row makes results easier to work with
          Instead of: result[0], result[1], result[2]
          We can use: result["id"], result["content"], result["timestamp"]
        - foreign_keys = ON enforces data integrity
        """
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row  # Access columns by name
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def execute_query(self, query: str, params: tuple = ()) -> List[sqlite3.Row]:
        """
        Execute a SELECT query and return results.

        Args:
            query (str): SQL query to execute
            params (tuple): Parameters for the query (prevents SQL injection)

        Returns:
            List[sqlite3.Row]: Query results

        SAFETY:
        This uses parameterized queries to prevent SQL injection attacks.
        NEVER do: f"SELECT * FROM messages WHERE id={user_input}"
        ALWAYS do: "SELECT * FROM messages WHERE id=?", (user_input,)
        """
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(query, params)
            results = cursor.fetchall()
            return results
        except sqlite3.Error as e:
            raise DatabaseError(f"Query failed: {e}\nQuery: {query}")
        finally:
            if conn:
                conn.close()

    def execute_write(self, query: str, params: tuple = ()) -> int:
        """
        Execute an INSERT, UPDATE, or DELETE query.

        Args:
            query (str): SQL query to execute
            params (tuple): Parameters for the query

        Returns:
            int: ID of inserted row (for INSERT) or number of affected rows

        TRANSACTION SAFETY:
        This automatically commits changes. If there's an error,
        changes are rolled back (not saved).
        """
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(query, params)
            conn.commit()

            # Return appropriate value based on query type
            # INSERT: return lastrowid (new row's ID)
            # UPDATE/DELETE: return rowcount (number of affected rows)
            query_upper = query.strip().upper()
            if query_upper.startswith("INSERT"):
                return cursor.lastrowid
            else:
                return cursor.rowcount

        except sqlite3.Error as e:
            if conn:
                conn.rollback()
            raise DatabaseError(f"Write operation failed: {e}\nQuery: {query}")
        finally:
            if conn:
                conn.close()

    def execute_many(self, query: str, params_list: list) -> int:
        """
        Execute an INSERT/UPDATE/DELETE query for multiple rows.

        Args:
            query (str): SQL query with ? placeholders
            params_list (list): List of tuples, one per row

        Returns:
            int: Number of rows affected

        USAGE:
            rows = db.execute_many(
                "INSERT INTO retrieval_log (turn_id, message_id) VALUES (?, ?)",
                [("abc", 1), ("abc", 2), ("abc", 3)]
            )
        """
        if not params_list:
            return 0

        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.executemany(query, params_list)
            conn.commit()
            return cursor.rowcount
        except sqlite3.Error as e:
            if conn:
                conn.rollback()
            raise DatabaseError(f"Batch write operation failed: {e}\nQuery: {query}")
        finally:
            if conn:
                conn.close()

    # =========================================================================
    # MESSAGE OPERATIONS
    # =========================================================================

    def add_message(
        self,
        sender: str,
        content: str,
        importance_score: float = 3.0,
        tier: str = "active",
        metadata: Optional[Dict] = None,
        timestamp: Optional[str] = None
    ) -> int:
        """
        Add a new message to the database.

        Args:
            sender (str): "user" or "assistant"
            content (str): The message text
            importance_score (float): 1-10, default 3.0 (neutral)
            tier (str): "active" (default - in rolling window), "standard" (retrievable), or "deep_archive"
            metadata (dict, optional): Additional data to store with message
            timestamp (str, optional): ISO 8601 timestamp, defaults to now

        Returns:
            int: ID of the newly created message

        EXAMPLE:
            message_id = db.add_message(
                sender="user",
                content="Tell me about the crows",
                importance_score=5.0,
                metadata={"context": "asking about past memories"}
            )
        """
        if timestamp is None:
            # Use actual UTC time (the 'Z' suffix correctly indicates Zulu/UTC time)
            timestamp = datetime.now(timezone.utc).replace(microsecond=0).strftime('%Y-%m-%dT%H:%M:%S') + 'Z'

        metadata_json = json.dumps(metadata) if metadata else None

        query = """
            INSERT INTO messages (timestamp, sender, content, importance_score, tier, metadata)
            VALUES (?, ?, ?, ?, ?, ?)
        """
        params = (timestamp, sender, content, importance_score, tier, metadata_json)

        return self.execute_write(query, params)

    def get_message(self, message_id: int) -> Optional[Dict]:
        """
        Retrieve a single message by ID.

        Args:
            message_id (int): The message ID

        Returns:
            dict: Message data, or None if not found

        RETURN FORMAT:
            {
                "id": 123,
                "timestamp": "2025-10-24T14:30:00Z",
                "sender": "user",
                "content": "Hello!",
                "importance_score": 5.0,
                "tier": "standard",
                "metadata": {"context": "greeting"},
                ...
            }
        """
        query = "SELECT * FROM messages WHERE id = ?"
        results = self.execute_query(query, (message_id,))
        return dict(results[0]) if results else None

    def get_messages_before(self, message_id: int, limit: int = 2) -> List[Dict]:
        """Get messages immediately preceding a given message ID."""
        results = self.execute_query(
            "SELECT * FROM messages WHERE id < ? ORDER BY id DESC LIMIT ?",
            (message_id, limit)
        )
        return [dict(r) for r in results]

    def get_recent_messages(
        self,
        limit: int = 50,
        tier: Optional[str] = None,
        sender: Optional[str] = None
    ) -> List[Dict]:
        """
        Retrieve the most recent messages.

        Args:
            limit (int): Maximum number of messages to return
            tier (str, optional): Filter by tier ("active", "standard", "deep_archive")
            sender (str, optional): Filter by sender ("user" or "assistant")

        Returns:
            List[dict]: List of messages, newest first

        USE CASE:
        This is used to load recent conversation context when starting a session.
        Also used by @remember to find the user's last message.
        """
        conditions = []
        params = []

        if tier:
            conditions.append("tier = ?")
            params.append(tier)

        if sender:
            conditions.append("sender = ?")
            params.append(sender)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        query = f"""
            SELECT * FROM messages
            {where_clause}
            ORDER BY timestamp DESC
            LIMIT ?
        """
        params.append(limit)

        results = self.execute_query(query, tuple(params))
        return [dict(row) for row in results]

    def get_messages_by_date_range(
        self,
        start_date: str,
        end_date: Optional[str] = None
    ) -> List[Dict]:
        """
        Retrieve messages within a date range.

        Args:
            start_date (str): ISO 8601 timestamp
            end_date (str, optional): ISO 8601 timestamp, defaults to now

        Returns:
            List[dict]: Messages within the date range

        EXAMPLE:
            messages = db.get_messages_by_date_range(
                start_date="2025-01-01T00:00:00Z",
                end_date="2025-01-31T23:59:59Z"
            )
        """
        if end_date is None:
            end_date = datetime.now(timezone.utc).isoformat() + "Z"

        query = """
            SELECT * FROM messages
            WHERE timestamp >= ? AND timestamp <= ?
            ORDER BY timestamp ASC
        """
        results = self.execute_query(query, (start_date, end_date))
        return [dict(row) for row in results]

    def update_message_importance(
        self,
        message_id: int,
        new_score: float,
        reason: str,
        details: Optional[Dict] = None
    ) -> bool:
        """
        Update a message's importance score and log the change.

        Args:
            message_id (int): The message ID
            new_score (float): New importance score (1-10)
            reason (str): Why the score changed (e.g., "user_marked", "time_decay")
            details (dict, optional): Additional information about the change

        Returns:
            bool: True if successful

        WHAT THIS DOES:
        1. Gets the current importance score
        2. Updates the message with the new score
        3. Logs the change in importance_scores table (audit trail)
        """
        # Get current score
        message = self.get_message(message_id)
        if not message:
            raise DatabaseError(f"Message {message_id} not found")

        old_score = message["importance_score"]

        # Update message
        query = "UPDATE messages SET importance_score = ? WHERE id = ?"
        self.execute_write(query, (new_score, message_id))

        # Log the change
        details_json = json.dumps(details) if details else None
        log_query = """
            INSERT INTO importance_scores (message_id, old_score, new_score, reason, changed_at, details)
            VALUES (?, ?, ?, ?, ?, ?)
        """
        timestamp = datetime.now(timezone.utc).isoformat() + "Z"
        self.execute_write(log_query, (message_id, old_score, new_score, reason, timestamp, details_json))

        return True

    def update_message_tier(self, message_id: int, new_tier: str) -> bool:
        """
        Move a message to a different tier.

        Args:
            message_id (int): The message ID
            new_tier (str): "active", "standard", or "deep_archive"

        Returns:
            bool: True if successful

        USE CASE:
        - Moving old messages to deep archive
        - Promoting important messages to active tier
        - Archiving low-priority content
        """
        valid_tiers = ["active", "standard", "deep_archive"]
        if new_tier not in valid_tiers:
            raise ValueError(f"Invalid tier: {new_tier}. Must be one of {valid_tiers}")

        query = "UPDATE messages SET tier = ? WHERE id = ?"
        self.execute_write(query, (new_tier, message_id))
        return True

    def update_message_content(self, message_id: int, content: str) -> bool:
        """
        Update a message's content.

        Args:
            message_id (int): The message ID
            content (str): New content

        Returns:
            bool: True if successful

        USE CASE:
        - Updating partial AI response after command execution
        - Fixing message content
        """
        query = "UPDATE messages SET content = ? WHERE id = ?"
        self.execute_write(query, (content, message_id))
        return True

    def update_message_metadata(self, message_id: int, metadata: Dict, merge: bool = True) -> bool:
        """
        Update a message's metadata field.

        Args:
            message_id (int): The message ID
            metadata (dict): New metadata to store
            merge (bool): If True, merge with existing metadata; if False, replace entirely

        Returns:
            bool: True if successful

        USE CASE:
        - Tracking reference counts
        - Storing custom attributes
        - Updating message context

        MERGE BEHAVIOR (Phase 4 Fix):
        - merge=True (default): Merges new metadata with existing, prevents data loss
        - merge=False: Replaces entire metadata object (use with caution)

        Example:
            Existing: {"reference_count": 5, "custom_field": "value"}
            Update:   {"reference_count": 6}
            Result:   {"reference_count": 6, "custom_field": "value"}  # custom_field preserved
        """
        if merge:
            # Get existing metadata and merge
            msg = self.get_message(message_id)
            if msg:
                existing_metadata = json.loads(msg.get('metadata') or '{}')
                # Merge: existing values preserved, new values override
                existing_metadata.update(metadata)
                metadata = existing_metadata

        metadata_json = json.dumps(metadata)
        query = "UPDATE messages SET metadata = ? WHERE id = ?"
        self.execute_write(query, (metadata_json, message_id))
        return True

    def delete_message(self, message_id: int) -> bool:
        """
        Delete a message and its associated data.

        Args:
            message_id (int): The message ID to delete

        Returns:
            bool: True if successful

        USE CASE:
        - Removing temporary command results
        - Cleaning up test data
        - User-requested deletions

        NOTE: Foreign key constraints will cascade delete:
        - Associated tags (tags.message_id)
        - Associated embeddings (embeddings.message_id)
        - Importance score history (importance_scores.message_id)

        Tables without ON DELETE CASCADE must be cleaned manually:
        - retrieval_log (message_id)
        """
        # Clean up tables that reference messages without ON DELETE CASCADE
        self.execute_write("DELETE FROM retrieval_log WHERE message_id = ?", (message_id,))

        # Get embedding_id before deleting message (to clean up orphan embedding)
        msg = self.get_message(message_id)
        embedding_id = msg.get("embedding_id") if msg else None

        query = "DELETE FROM messages WHERE id = ?"
        self.execute_write(query, (message_id,))

        # Clean up orphaned embedding row
        if embedding_id:
            self.execute_write("DELETE FROM embeddings WHERE id = ?", (embedding_id,))

        return True

    def cleanup_orphan_messages(self) -> dict:
        """
        Delete orphaned user messages that were never responded to by the AI.

        Rules applied in order:
        1. Consecutive user runs: if 2+ user messages appear in a row with no
           assistant message between them, keep only the last (most recent retry),
           delete the rest.
        2. Trailing user message: if the final surviving message is from a user
           (no subsequent assistant response), delete it and return its text.

        Returns:
            dict: {"deleted": N, "restored_text": "..." or None}
        """
        messages = self.execute_query(
            "SELECT id, sender, content FROM messages ORDER BY id ASC"
        )
        messages = [dict(m) for m in messages]

        if not messages:
            return {"deleted": 0, "restored_text": None}

        ids_to_delete = []

        # Rule 0: remove pre-allocated assistant shells that never got filled
        for msg in messages:
            if msg["sender"] == "assistant" and msg["content"] == "":
                ids_to_delete.append(msg["id"])
        messages = [m for m in messages if m["id"] not in ids_to_delete]

        # Rule 1: find consecutive user runs; delete all but the last in each run
        i = 0
        while i < len(messages):
            if messages[i]["sender"] == "user":
                run_start = i
                while i < len(messages) and messages[i]["sender"] == "user":
                    i += 1
                run = messages[run_start:i]
                if len(run) > 1:
                    for msg in run[:-1]:
                        ids_to_delete.append(msg["id"])
            else:
                i += 1

        # Rule 2: check if last surviving message is a trailing user message
        surviving = [m for m in messages if m["id"] not in ids_to_delete]
        restored_text = None
        if surviving and surviving[-1]["sender"] == "user":
            trailing = surviving[-1]
            ids_to_delete.append(trailing["id"])
            restored_text = trailing["content"]

        for msg_id in ids_to_delete:
            self.delete_message(msg_id)

        return {"deleted": len(ids_to_delete), "restored_text": restored_text}

    def mark_messages_entity_checked(self, message_ids: list) -> None:
        """Mark messages as having had entity assignment attempted."""
        if not message_ids:
            return
        placeholders = ','.join('?' * len(message_ids))
        self.execute_write(
            f"UPDATE messages SET entity_checked = 1 WHERE id IN ({placeholders})",
            tuple(message_ids)
        )

    def get_unchecked_messages(self) -> list:
        """Return messages that have not yet had entity assignment attempted."""
        results = self.execute_query(
            "SELECT id, sender, content FROM messages WHERE entity_checked = 0 ORDER BY id ASC"
        )
        return [dict(r) for r in results]

    def get_unchecked_message_count(self) -> int:
        """Return the count of messages pending entity assignment."""
        result = self.execute_query(
            "SELECT COUNT(*) as count FROM messages WHERE entity_checked = 0"
        )
        return result[0]["count"] if result else 0

    # =========================================================================
    # SEARCH OPERATIONS
    # =========================================================================

    def search_messages_keyword(
        self,
        keyword: str,
        limit: int = 20,
        tier: Optional[str] = None,
        months_back: Optional[int] = None,
        sender: Optional[str] = None
    ) -> List[Dict]:
        """
        Search for messages containing a keyword.

        Args:
            keyword (str): The search term
            limit (int): Maximum number of results
            tier (str, optional): Filter by tier
            months_back (int, optional): Only search last N months
            sender (str, optional): Filter by sender ("user" or "assistant")

        Returns:
            List[dict]: Messages matching the search, ordered by recency

        HOW IT WORKS:
        Uses SQL LIKE operator for simple text matching.
        Not as sophisticated as semantic search, but faster and works without embeddings.

        EXAMPLE:
            results = db.search_messages_keyword("crow", limit=10, months_back=6)
        """
        # Build filter conditions (tier, sender, date)
        filters = []
        filter_params = []

        if tier:
            filters.append("tier = ?")
            filter_params.append(tier)

        if sender:
            filters.append("sender = ?")
            filter_params.append(sender)

        if months_back:
            cutoff_date = (datetime.now(timezone.utc) - timedelta(days=months_back * 30)).isoformat() + "Z"
            filters.append("timestamp >= ?")
            filter_params.append(cutoff_date)

        # Split keyword into words — AND first, OR fallback
        words = keyword.split()
        word_conditions = [f"content LIKE ?" for w in words]
        word_params = [f"%{w}%" for w in words]

        and_where = filters + [f"({' AND '.join(word_conditions)})"]
        params = filter_params + word_params + [limit]

        query = f"""
            SELECT * FROM messages
            WHERE {' AND '.join(and_where)}
            ORDER BY timestamp DESC
            LIMIT ?
        """
        results = self.execute_query(query, tuple(params))

        # Fall back to OR if AND finds nothing and there are multiple words
        if not results and len(words) > 1:
            or_where = filters + [f"({' OR '.join(word_conditions)})"]
            params = filter_params + word_params + [limit]
            query = f"""
                SELECT * FROM messages
                WHERE {' AND '.join(or_where)}
                ORDER BY timestamp DESC
                LIMIT ?
            """
            results = self.execute_query(query, tuple(params))

        return [dict(row) for row in results]

    def get_high_importance_messages(
        self,
        min_importance: float = 7.0,
        limit: int = 50
    ) -> List[Dict]:
        """
        Retrieve high-importance messages.

        Args:
            min_importance (float): Minimum importance score
            limit (int): Maximum number of results

        Returns:
            List[dict]: High-importance messages

        USE CASE:
        Loading the "active" context with emotionally significant memories.
        """
        query = """
            SELECT * FROM messages
            WHERE importance_score >= ?
            ORDER BY importance_score DESC, timestamp DESC
            LIMIT ?
        """
        results = self.execute_query(query, (min_importance, limit))
        return [dict(row) for row in results]

    # =========================================================================
    # STATISTICS AND MAINTENANCE
    # =========================================================================

    def get_message_count(self) -> int:
        """
        Get total number of messages in database.

        Returns:
            int: Total message count
        """
        query = "SELECT COUNT(*) as count FROM messages"
        result = self.execute_query(query)
        return result[0]["count"] if result else 0

    def get_message_count_by_tier(self) -> Dict[str, int]:
        """
        Get message counts for each tier.

        Returns:
            dict: Tier names mapped to counts

        EXAMPLE RETURN:
            {
                "active": 45,
                "standard": 320,
                "deep_archive": 1250
            }
        """
        query = """
            SELECT tier, COUNT(*) as count
            FROM messages
            GROUP BY tier
        """
        results = self.execute_query(query)
        return {row["tier"]: row["count"] for row in results}

    def vacuum_database(self) -> bool:
        """
        Optimize database and reclaim unused space.

        Returns:
            bool: True if successful

        WHAT THIS DOES:
        After deleting data, SQLite doesn't immediately reclaim the disk space.
        VACUUM reorganizes the database file and reduces its size.

        RUN THIS:
        - Weekly (automatically via maintenance script)
        - After bulk deletions
        - If database file seems larger than expected
        """
        conn = None
        try:
            conn = self._get_connection()
            conn.execute("VACUUM")
            return True
        except sqlite3.Error as e:
            raise DatabaseError(f"VACUUM failed: {e}")
        finally:
            if conn:
                conn.close()

    def create_backup(
        self,
        backup_dir: str,
        cloud_backup_dir: Optional[str] = None,
        keep_count: int = 3,
    ) -> Optional[str]:
        """
        Create a consistent snapshot of the database using VACUUM INTO.
        Safe to call while the server is running.

        Keeps the most recent backups in backup_dir. If cloud_backup_dir
        is provided, copies the snapshot there too.

        Returns the backup path on success, None on failure.
        """
        import shutil
        from datetime import datetime

        keep_count = max(1, int(keep_count or 3))
        backup_path_obj = Path(backup_dir)
        backup_path_obj.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = backup_path_obj / f"memory_backup_{timestamp}.db"

        conn = None
        try:
            conn = self._get_connection()
            conn.execute("VACUUM INTO ?", (str(backup_file),))

            # Prune old backups, keep most recent
            backups = sorted(backup_path_obj.glob("memory_backup_*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
            for old in backups[keep_count:]:
                old.unlink()

            # Copy to cloud backup dir if provided
            if cloud_backup_dir:
                cloud_path = Path(cloud_backup_dir)
                cloud_path.mkdir(parents=True, exist_ok=True)
                cloud_file = cloud_path / backup_file.name
                shutil.copy2(str(backup_file), str(cloud_file))
                # Prune cloud backups too
                cloud_backups = sorted(cloud_path.glob("memory_backup_*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
                for old in cloud_backups[keep_count:]:
                    old.unlink()

            return str(backup_file)
        except (OSError, shutil.Error, sqlite3.Error):
            return None
        finally:
            if conn:
                conn.close()

    def integrity_check(self) -> bool:
        """
        Check database for corruption.

        Returns:
            bool: True if database is healthy, False if corrupted

        RUN THIS:
        - Monthly (automatically via maintenance script)
        - After unexpected program crashes
        - If you see strange errors
        """
        try:
            query = "PRAGMA integrity_check"
            result = self.execute_query(query)
            return result[0][0] == "ok"
        except Exception:
            return False


if __name__ == "__main__":
    """
    Test the database operations when this file is run directly.
    """
    print("Database module loaded successfully.")
    print("To test database operations, use scripts/init_db.py")
