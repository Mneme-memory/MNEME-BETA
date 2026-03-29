"""
Entity Database for Mneme

Manages the entity store (canonical names, aliases, mention tracking) used by
entity summaries and entity assignment. Built on SQLite + FTS5.

Relationships were removed — only entity CRUD and lookup remain.

USAGE:
    from graph_database import GraphDatabase

    graph_db = GraphDatabase(config)
    graph_db.add_entity("consciousness", aliases=["sapience", "awareness"])
    entity = graph_db.get_entity_by_name("consciousness")
"""

import sqlite3
import json
from pathlib import Path
from typing import List, Dict, Optional, Any
from datetime import datetime, timezone


class GraphDatabase:
    """
    Database interface for the knowledge graph layer.

    Provides entity and relationship management with:
    - Entity normalization (canonical names + aliases)
    - Relationship tracking with evidence
    - Multi-hop graph traversal
    - FTS5 full-text search
    - Entity proposal tracking (for Pass 2)
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize graph database connection.

        Args:
            config: Configuration dictionary with database path
        """
        self.config = config
        self.db_path = config["storage"]["database_path"]
        self.conn = None
        self.connect()

    def connect(self):
        """Establish database connection."""
        # check_same_thread=False allows use across Flask request threads
        # This is safe because each request is isolated
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row  # Access columns by name

    def initialize_schema(self):
        """
        Initialize graph database schema.

        Applies the graph_schema.sql file to create tables.
        Safe to call multiple times (uses IF NOT EXISTS).
        """
        schema_path = Path(__file__).parent / "graph_schema.sql"

        with open(schema_path, 'r', encoding='utf-8') as f:
            schema_sql = f.read()

        cursor = self.conn.cursor()
        cursor.executescript(schema_sql)
        self.conn.commit()

        # Migrations: add columns that may be missing from older databases
        self._migrate_schema()

    def _migrate_schema(self):
        """Apply column migrations for databases created before schema updates."""
        cursor = self.conn.cursor()
        # Check existing columns on entities table
        cols = {row[1] for row in cursor.execute("PRAGMA table_info(entities)").fetchall()}
        if "description" not in cols:
            cursor.execute('ALTER TABLE entities ADD COLUMN description TEXT NOT NULL DEFAULT ""')
            self.conn.commit()

    # ========================================================================
    # Entity Operations
    # ========================================================================

    def add_entity(
        self,
        name: str,
        aliases: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> int:
        """
        Add or update an entity.

        Args:
            name: Canonical entity name
            aliases: List of alternative names
            metadata: Optional metadata dictionary

        Returns:
            int: Entity ID

        BEHAVIOR:
        - If entity exists, updates mention count and last_mentioned
        - If new, creates with mention_count=1
        - Aliases stored as JSON array
        """
        cursor = self.conn.cursor()
        now = datetime.now(timezone.utc).isoformat() + "Z"

        # Check if entity exists
        existing = self.get_entity_by_name(name)

        if existing:
            # Update existing entity
            entity_id = existing["id"]
            cursor.execute("""
                UPDATE entities
                SET mention_count = mention_count + 1,
                    last_mentioned = ?,
                    aliases = ?,
                    metadata = ?
                WHERE id = ?
            """, (
                now,
                json.dumps(aliases) if aliases else None,
                json.dumps(metadata) if metadata else None,
                entity_id
            ))
        else:
            # Create new entity
            cursor.execute("""
                INSERT INTO entities (
                    name, aliases, mention_count,
                    first_mentioned, last_mentioned, metadata
                )
                VALUES (?, ?, 1, ?, ?, ?)
            """, (
                name,
                json.dumps(aliases) if aliases else None,
                now,
                now,
                json.dumps(metadata) if metadata else None
            ))
            entity_id = cursor.lastrowid

        self.conn.commit()
        return entity_id

    def get_entity_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Get entity by canonical name.

        Args:
            name: Canonical entity name (case-insensitive)

        Returns:
            Dictionary with entity data or None if not found
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM entities
            WHERE LOWER(name) = LOWER(?)
        """, (name,))

        row = cursor.fetchone()
        if not row:
            return None

        return self._row_to_dict(row)

    def get_entity_by_id(self, entity_id: int) -> Optional[Dict[str, Any]]:
        """
        Get entity by ID.

        Args:
            entity_id: Entity ID

        Returns:
            Dictionary with entity data or None if not found
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM entities
            WHERE id = ?
        """, (entity_id,))

        row = cursor.fetchone()
        if not row:
            return None

        return self._row_to_dict(row)

    def get_entity_by_alias(self, alias: str) -> Optional[Dict[str, Any]]:
        """
        Search for entity by alias.

        Args:
            alias: Alias to search for

        Returns:
            Dictionary with entity data or None if not found

        NOTES:
        - Searches JSON aliases field
        - Case-insensitive
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM entities WHERE aliases IS NOT NULL")

        for row in cursor.fetchall():
            entity = self._row_to_dict(row)
            aliases = json.loads(entity["aliases"]) if entity["aliases"] else []

            if any(alias.lower() == a.lower() for a in aliases):
                return entity

        return None

    def search_entities(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Full-text search for entities using FTS5.

        Args:
            query: Search query
            limit: Maximum results

        Returns:
            List of matching entities, sorted by relevance
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT e.*
            FROM entities e
            JOIN entities_fts fts ON e.id = fts.rowid
            WHERE entities_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """, (query, limit))

        return [self._row_to_dict(row) for row in cursor.fetchall()]

    def update_entity(
        self,
        entity_id: int,
        description: Optional[str] = None,
        aliases: Optional[List[str]] = None
    ) -> bool:
        """
        Update an entity's description and/or aliases.

        Args:
            entity_id: ID of the entity to update
            description: New description (None to keep existing)
            aliases: New aliases list (None to keep existing)

        Returns:
            True if update succeeded
        """
        # Build update query dynamically based on what's provided
        updates = []
        params = []

        if description is not None:
            updates.append("description = ?")
            params.append(description)

        if aliases is not None:
            updates.append("aliases = ?")
            params.append(json.dumps(aliases) if aliases else None)

        if not updates:
            return True  # Nothing to update

        params.append(entity_id)
        query = f"UPDATE entities SET {', '.join(updates)} WHERE id = ?"

        cursor = self.conn.cursor()
        cursor.execute(query, params)
        self.conn.commit()

        return cursor.rowcount > 0 or True  # rowcount may be 0 if value unchanged

    def get_entity_stats(self, min_mentions: int = 1) -> List[Dict[str, Any]]:
        """
        Get entity statistics for consolidation.

        Args:
            min_mentions: Minimum mention count to include

        Returns:
            List of entities with stats, sorted by mention count

        USED FOR:
        - Manual consolidation helper script
        - Finding duplicate/similar entities
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT id, name, description, mention_count, aliases,
                   first_mentioned, last_mentioned
            FROM entities
            WHERE mention_count >= ?
            ORDER BY mention_count DESC, name ASC
        """, (min_mentions,))

        return [self._row_to_dict(row) for row in cursor.fetchall()]

    # ========================================================================
    # Utility Methods
    # ========================================================================

    def get_entity_by_name_or_alias(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Get entity by canonical name or alias.

        Args:
            name: Name or alias to search

        Returns:
            Entity dictionary or None
        """
        # Try canonical name first
        entity = self.get_entity_by_name(name)
        if entity:
            return entity

        # Try alias
        return self.get_entity_by_alias(name)

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        """Convert SQLite Row to dictionary."""
        return dict(row)

    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()


