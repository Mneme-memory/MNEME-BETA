"""
Database Schema for Mneme Memory System

This file defines the structure of the SQLite database that stores all conversation
memories, embeddings, and metadata.

TABLES:
1. messages - Core conversation messages with importance and tier information
2. embeddings - Vector embeddings for semantic search
3. importance_scores - Historical record of importance changes over time
4. metadata - System-wide settings and configuration
5. tiers - Tier definitions (active, standard, deep_archive)
6. concepts - Narrative concepts for contextual interpretation (Phase 6)
7. attachments - File attachments for messages (Phase 7)
8. message_entities - Links messages to entities (Phase 8)
9. entity_summaries - Hierarchical summaries for entities (Phase 8)
10. daily_summaries - Daily conversation summaries for timeline awareness (Phase 9)
11. notes - AI-managed persistent notes organized in named sections (Phase 11)
12. turn_log - Parent table for provenance tracking per turn (Phase 12)
13. retrieval_log - Per-memory retrieval scores and inclusion status (Phase 12)
14. concept_trigger_log - Concept keyword matches per turn (Phase 12)
15. entity_summary_log - Entity summary selection per turn (Phase 12)

WHY SQLITE?
- Single file database (easy backup)
- No separate server needed
- Fast for read-heavy workloads
- Perfect for local applications
- Built into Python (no installation needed)
"""

import sqlite3
from datetime import datetime, timezone
import json


def get_schema_version():
    """
    Returns the current schema version.
    This helps track database migrations if we need to update the structure later.

    Version history:
    - 1.0.0: Initial schema (messages, embeddings, importance_scores, metadata, tiers)
    - 1.1.0: Added concepts table (Phase 6)
    - 1.2.0: Added attachments table (Phase 7)
    - 1.3.0: Added message_entities and entity_summaries tables (Phase 8)
    - 1.4.0: Added daily_summaries table (Phase 9)
    - 1.5.0: Added notes table (Phase 11)
    - 1.6.0: Added provenance tables: turn_log, retrieval_log, concept_trigger_log, entity_summary_log (Phase 12)
    """
    return "1.6.0"


def create_database_schema(db_path):
    """
    Creates all tables and indexes for the Mneme memory system.

    Args:
        db_path (str): Path where the SQLite database file should be created

    Returns:
        bool: True if successful, False otherwise

    WHAT THIS DOES:
    1. Connects to SQLite database (creates file if it doesn't exist)
    2. Creates all necessary tables
    3. Creates indexes for fast searching
    4. Inserts default tier definitions
    5. Stores schema version in metadata
    """

    try:
        # Connect to database (creates file if it doesn't exist)
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Enable foreign key constraints
        # This ensures data integrity (e.g., can't tag a message that doesn't exist)
        cursor.execute("PRAGMA foreign_keys = ON")

        # =================================================================
        # TABLE: messages
        # =================================================================
        # This is the main table storing all conversation messages
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                -- Unique identifier for each message
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                -- When the message was sent (stored as ISO 8601 UTC timestamp)
                -- Example: "2025-10-24T14:30:00Z"
                timestamp TEXT NOT NULL,

                -- Who sent the message: "user" or "assistant"
                sender TEXT NOT NULL,

                -- The actual message content
                content TEXT NOT NULL,

                -- Importance score (1-10, where 3=neutral, 7-10=emotional)
                -- This affects whether memories stay active or get archived
                importance_score REAL DEFAULT 3.0,

                -- Memory tier: "active", "standard", or "deep_archive"
                -- Active = always loaded, Standard = default pool, Deep = requires --deep flag
                tier TEXT DEFAULT 'standard',

                -- ID of the embedding vector (links to embeddings table)
                -- NULL if embedding not yet generated
                embedding_id INTEGER,

                -- Additional metadata stored as JSON
                -- Example: {"device": "mobile", "location": "home", "mood": "reflective"}
                metadata TEXT,

                -- Tracks if this message has been modified after initial storage
                modified INTEGER DEFAULT 0,

                -- When the message was last modified (NULL if never modified)
                last_modified TEXT,

                -- Whether entity assignment has been attempted for this message
                -- 0 = pending (not yet attempted, or failed and needs retry)
                -- 1 = done (attempted; may or may not have produced links)
                entity_checked INTEGER NOT NULL DEFAULT 0,

                -- Foreign key linking to embeddings table
                FOREIGN KEY (embedding_id) REFERENCES embeddings(id)
            )
        """)

        # =================================================================
        # TABLE: embeddings
        # =================================================================
        # Stores vector embeddings for semantic search
        # Embeddings are mathematical representations of text meaning
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS embeddings (
                -- Unique identifier for each embedding
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                -- The embedding vector stored as JSON array
                -- Example: [0.123, -0.456, 0.789, ...]
                -- Typical size: 1024-1536 dimensions depending on model
                vector TEXT NOT NULL,

                -- Which model generated this embedding
                -- Example: "anthropic-embed-v1" or "openai-ada-002"
                model TEXT NOT NULL,

                -- When this embedding was generated
                created_at TEXT NOT NULL,

                -- Cost to generate this embedding (in USD)
                -- Helps track API spending
                cost REAL DEFAULT 0.0
            )
        """)

        # =================================================================
        # TABLE: importance_scores
        # =================================================================
        # Historical record of importance changes (audit trail)
        # This lets us track WHY a message's importance changed over time
        # NOTE: Currently write-only - data is logged but not displayed in UI yet
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS importance_scores (
                -- Unique identifier for each score change
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                -- Which message's score changed
                message_id INTEGER NOT NULL,

                -- The old score before this change
                old_score REAL NOT NULL,

                -- The new score after this change
                new_score REAL NOT NULL,

                -- Why the score changed
                -- Examples: "time_decay", "user_marked", "referenced_again"
                reason TEXT NOT NULL,

                -- When the score was changed
                changed_at TEXT NOT NULL,

                -- Additional details stored as JSON
                details TEXT,

                -- Foreign key linking to messages table
                FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE
            )
        """)

        # =================================================================
        # TABLE: metadata
        # =================================================================
        # System-wide settings and configuration
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS metadata (
                -- Setting name (unique identifier)
                key TEXT PRIMARY KEY,

                -- Setting value (stored as JSON for flexibility)
                value TEXT NOT NULL,

                -- When this setting was last updated
                updated_at TEXT NOT NULL
            )
        """)

        # =================================================================
        # TABLE: tiers
        # =================================================================
        # Defines the memory tier system
        # NOTE: Currently populated but not queried - tier logic uses
        # hardcoded tier names in tier_manager.py. This table exists
        # for potential future configurable tier system.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tiers (
                -- Tier name (unique identifier)
                name TEXT PRIMARY KEY,

                -- Human-readable description
                description TEXT NOT NULL,

                -- Minimum importance score required for this tier
                min_importance REAL NOT NULL,

                -- Configuration for this tier (stored as JSON)
                -- Example: {"auto_load": true, "max_age_days": 90}
                config TEXT NOT NULL
            )
        """)

        # =================================================================
        # TABLE: concepts (Phase 6)
        # =================================================================
        # Narrative concepts that provide interpretive context between memories and graph
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS concepts (
                -- Unique identifier for each concept
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                -- Concept name/identifier (unique, lowercase for consistency)
                -- Example: "token_rationing", "glitchmob_energy"
                name TEXT NOT NULL UNIQUE,

                -- Full narrative definition/explanation
                definition TEXT NOT NULL,

                -- Trigger keywords for matching (stored as JSON array)
                -- Example: ["context_limits", "saving_tokens", "silence_for_survival"]
                trigger_keywords TEXT NOT NULL,

                -- Who created the concept: "user" or "instance"
                created_by TEXT DEFAULT 'user',

                -- When the concept was created (ISO 8601 UTC)
                created_at TEXT NOT NULL,

                -- When the concept was last updated (ISO 8601 UTC)
                updated_at TEXT NOT NULL,

                -- Additional metadata (stored as JSON)
                -- Example: {"category": "relational", "importance": "high"}
                metadata TEXT
            )
        """)

        # =================================================================
        # TABLE: attachments (Phase 7)
        # =================================================================
        # File attachments for messages (images, text, JSON, PDFs)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS attachments (
                -- Unique identifier for each attachment
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                -- UUID for external reference (used in commands, URLs)
                -- Example: "a1b2c3d4-5678-90ab-cdef-ghij12345678"
                uuid TEXT NOT NULL UNIQUE,

                -- Original filename (for display purposes)
                filename TEXT NOT NULL,

                -- MIME type of the file
                -- Example: "image/jpeg", "text/plain", "application/pdf"
                mime_type TEXT NOT NULL,

                -- File size in bytes (of stored version, after any resizing)
                size_bytes INTEGER NOT NULL,

                -- SHA-256 hash for deduplication
                file_hash TEXT,

                -- Path to file directory (relative to attachments dir)
                -- Example: "a1b2c3d4-5678-90ab-cdef-ghij12345678"
                storage_path TEXT NOT NULL,

                -- AI-generated description (created by instance via @describe)
                -- Example: "Black crow perched on fence, morning light..."
                ai_description TEXT,

                -- AI-generated summary (for large text/PDF files)
                ai_summary TEXT,

                -- Content preview (first ~2000 chars for text/JSON)
                content_preview TEXT,

                -- ID of the embedding vector for semantic search
                -- Embedding is generated from ai_description
                embedding_id INTEGER,

                -- Message this attachment is associated with
                -- NULL if uploaded but not yet sent in a message
                message_id INTEGER,

                -- Processing status: 'pending', 'ready', 'failed'
                processing_status TEXT DEFAULT 'pending',

                -- When processing completed
                processed_at TEXT,

                -- When the attachment was created (ISO 8601 UTC)
                created_at TEXT NOT NULL,

                -- Additional metadata stored as JSON
                -- Images: {"width": 1920, "height": 1080, "original_size": 5242880}
                -- Text: {"word_count": 1500, "line_count": 45, "encoding": "utf-8"}
                -- PDF: {"page_count": 12, "has_images": true}
                metadata TEXT,

                -- Foreign keys
                FOREIGN KEY (embedding_id) REFERENCES embeddings(id),
                FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE SET NULL
            )
        """)

        # =================================================================
        # TABLE: message_entities (Phase 8)
        # =================================================================
        # Links messages to entities for entity summaries feature
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS message_entities (
                -- Unique identifier for each link
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                -- Which message this entity appears in
                message_id INTEGER NOT NULL,

                -- Which entity is mentioned
                entity_id INTEGER NOT NULL,

                -- Confidence of the assignment (0.0-1.0)
                confidence REAL DEFAULT 1.0,

                -- How the assignment was made: 'haiku', 'string_match', 'manual'
                source TEXT NOT NULL,

                -- When this link was created (ISO 8601 UTC)
                created_at TEXT NOT NULL,

                -- Foreign keys
                FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE,
                FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE CASCADE,

                -- Each message-entity pair should be unique
                UNIQUE(message_id, entity_id)
            )
        """)

        # =================================================================
        # TABLE: entity_summaries (Phase 8)
        # =================================================================
        # Stores hierarchical summaries for entities (monthly + all-time)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS entity_summaries (
                -- Unique identifier for each summary
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                -- Which entity this summary is for
                entity_id INTEGER NOT NULL,

                -- Type of summary: 'month' or 'all_time'
                period_type TEXT NOT NULL,

                -- Period identifier (e.g., '2024-01' for monthly, NULL for all_time)
                period_start TEXT,

                -- The summary text (full version, used for all-time synthesis)
                summary TEXT NOT NULL,

                -- Condensed summary (max ~100 words, used for context injection)
                summary_short TEXT,

                -- Number of messages that contributed
                message_count INTEGER DEFAULT 0,

                -- Approximate token count
                token_count INTEGER DEFAULT 0,

                -- Last message ID included
                last_message_id INTEGER,

                -- Whether this summary is frozen (completed months)
                is_frozen INTEGER DEFAULT 0,

                -- Incremental updates since last full regen
                incremental_update_count INTEGER DEFAULT 0,

                -- Timestamps
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,

                -- Foreign keys
                FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE CASCADE,
                FOREIGN KEY (last_message_id) REFERENCES messages(id) ON DELETE SET NULL,

                -- Unique constraint
                UNIQUE(entity_id, period_type, period_start)
            )
        """)

        # =================================================================
        # TABLE: daily_summaries (Phase 9)
        # =================================================================
        # Stores daily conversation summaries for timeline awareness
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_summaries (
                -- Date in YYYY-MM-DD format (unique identifier)
                date TEXT PRIMARY KEY,

                -- AI-generated summary of the day's conversation
                summary_text TEXT NOT NULL,

                -- Approximate token count of the summary
                token_count INTEGER DEFAULT 0,

                -- Number of messages included in the summary
                message_count INTEGER DEFAULT 0,

                -- When the summary was generated (ISO 8601 UTC)
                generated_at TEXT NOT NULL
            )
        """)

        # =================================================================
        # TABLE: notes (Phase 11)
        # =================================================================
        # AI-managed persistent notes organized in named sections
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS notes (
                -- Unique identifier for each note section
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                -- Section name (unique, case-preserved)
                -- Example: "Preferences", "Current Projects"
                section TEXT NOT NULL UNIQUE,

                -- Section content (markdown-style text)
                content TEXT NOT NULL,

                -- When this section was first created (ISO 8601 UTC)
                created_at TEXT NOT NULL,

                -- When this section was last updated (ISO 8601 UTC)
                updated_at TEXT NOT NULL
            )
        """)

        # =================================================================
        # TABLE: turn_log (Phase 12 - Provenance)
        # =================================================================
        # Parent table for provenance tracking — one row per context assembly turn
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS turn_log (
                -- Unique identifier
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                -- UUID grouping key for all logs in this turn
                turn_id TEXT NOT NULL UNIQUE,

                -- The query text used for semantic search
                query_text TEXT,

                -- Tier filter applied to search
                tier_filter TEXT,

                -- How many candidate memories semantic_search returned
                memories_considered INTEGER DEFAULT 0,

                -- How many survived dedup + budget trimming
                memories_included INTEGER DEFAULT 0,

                -- Total tokens used by all context sections this turn
                total_tokens_used INTEGER DEFAULT 0,

                -- When this turn was assembled (ISO 8601 UTC)
                timestamp TEXT NOT NULL
            )
        """)

        # =================================================================
        # TABLE: retrieval_log (Phase 12 - Provenance)
        # =================================================================
        # Per-memory retrieval scores — all candidates, not just included ones
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS retrieval_log (
                -- Unique identifier
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                -- Links to turn_log.turn_id
                turn_id TEXT NOT NULL,

                -- Which memory was considered
                message_id INTEGER,

                -- Raw cosine similarity against query
                similarity_score REAL,

                -- Base importance_score from messages table
                importance_raw REAL,

                -- After time decay applied
                importance_effective REAL,

                -- Time decay multiplier (0.9-1.5)
                recency_multiplier REAL,

                -- Final ranked score (weighted composite)
                composite_score REAL,

                -- Rank position in results (1 = best)
                rank INTEGER,

                -- 1 if included in prompt, 0 if cut by dedup/budget
                was_included INTEGER DEFAULT 1,

                -- Why excluded: 'duplicate', 'budget', 'recent_context', or NULL if included
                exclusion_reason TEXT,

                -- When this was logged (ISO 8601 UTC)
                timestamp TEXT NOT NULL,

                -- Foreign keys
                FOREIGN KEY (turn_id) REFERENCES turn_log(turn_id),
                FOREIGN KEY (message_id) REFERENCES messages(id)
            )
        """)

        # =================================================================
        # TABLE: concept_trigger_log (Phase 12 - Provenance)
        # =================================================================
        # Which concepts matched keywords and whether they fit in budget
        # NOTE: concept_id has no FK constraint because concepts may be
        # deleted while provenance logs are retained (append-only)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS concept_trigger_log (
                -- Unique identifier
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                -- Links to turn_log.turn_id
                turn_id TEXT NOT NULL,

                -- Which concept was triggered (no FK — concepts may be deleted)
                concept_id INTEGER,

                -- Concept name (denormalized for quick reads)
                concept_name TEXT,

                -- Which keywords matched (JSON array)
                matched_keywords TEXT,

                -- How many keywords matched
                match_count INTEGER DEFAULT 0,

                -- 1 if included in prompt, 0 if cut by budget
                was_included INTEGER DEFAULT 1,

                -- When this was logged (ISO 8601 UTC)
                timestamp TEXT NOT NULL,

                -- Foreign keys (only turn_id — provenance is append-only)
                FOREIGN KEY (turn_id) REFERENCES turn_log(turn_id)
            )
        """)

        # =================================================================
        # TABLE: entity_summary_log (Phase 12 - Provenance)
        # =================================================================
        # Which entities were selected for summary injection
        # NOTE: entity_id has no FK constraint because entities live in
        # the graph database (separate file) and may be reorganized
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS entity_summary_log (
                -- Unique identifier
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                -- Links to turn_log.turn_id
                turn_id TEXT NOT NULL,

                -- Which entity was considered (no FK — entities in separate DB)
                entity_id INTEGER,

                -- Entity name (denormalized for quick reads)
                entity_name TEXT,

                -- Relevance score from selection algorithm
                relevance_score REAL,

                -- Rank position (1 = most relevant)
                rank INTEGER,

                -- 1 if summary was included in prompt, 0 if cut
                was_included INTEGER DEFAULT 1,

                -- When this was logged (ISO 8601 UTC)
                timestamp TEXT NOT NULL,

                -- Foreign keys (only turn_id — provenance is append-only)
                FOREIGN KEY (turn_id) REFERENCES turn_log(turn_id)
            )
        """)

        # =================================================================
        # INDEXES FOR PERFORMANCE
        # =================================================================
        # Indexes make searches faster by creating efficient lookup structures

        # Index for searching messages by timestamp (recent messages first)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_timestamp
            ON messages(timestamp)
        """)

        # Index for filtering by importance score
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_importance
            ON messages(importance_score)
        """)

        # Index for filtering messages by tier
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_tier
            ON messages(tier)
        """)

        # Index for looking up embeddings
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_embedding_id
            ON messages(embedding_id)
        """)

        # Index for concept name lookups (Phase 6)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_concept_name
            ON concepts(name)
        """)

        # Index for attachment UUID lookups (Phase 7)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_attachments_uuid
            ON attachments(uuid)
        """)

        # Index for finding attachments by message (Phase 7)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_attachments_message
            ON attachments(message_id)
        """)

        # Index for attachment creation time (Phase 7)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_attachments_created
            ON attachments(created_at DESC)
        """)

        # Index for attachment processing status (Phase 7)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_attachments_status
            ON attachments(processing_status)
        """)

        # Indexes for message_entities (Phase 8)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_message_entities_message
            ON message_entities(message_id)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_message_entities_entity
            ON message_entities(entity_id)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_message_entities_created
            ON message_entities(created_at)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_message_entities_entity_conf
            ON message_entities(entity_id, confidence DESC)
        """)

        # Indexes for entity_summaries (Phase 8)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_entity_summaries_entity
            ON entity_summaries(entity_id)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_entity_summaries_period
            ON entity_summaries(period_type, period_start)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_entity_summaries_frozen
            ON entity_summaries(is_frozen)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_entity_summaries_entity_type
            ON entity_summaries(entity_id, period_type)
        """)

        # Indexes for provenance tables (Phase 12)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_turn_log_turn_id
            ON turn_log(turn_id)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_turn_log_timestamp
            ON turn_log(timestamp DESC)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_retrieval_log_turn
            ON retrieval_log(turn_id)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_retrieval_log_message
            ON retrieval_log(message_id)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_concept_trigger_log_turn
            ON concept_trigger_log(turn_id)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_entity_summary_log_turn
            ON entity_summary_log(turn_id)
        """)

        # =================================================================
        # PHASE 4.2: PERFORMANCE OPTIMIZATION - COMPOUND INDEXES
        # =================================================================
        # These compound indexes significantly improve query performance for
        # the most common retrieval patterns

        # Compound index for tier + timestamp queries
        # Optimizes: get_recent_messages(), get_messages_with_embeddings()
        # Impact: Runs on every turn - significant performance gain
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_tier_timestamp
            ON messages(tier, timestamp DESC)
        """)

        # Compound index for importance + timestamp queries
        # Optimizes: get_high_importance_messages()
        # Impact: Faster active tier queries and memory retrieval
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_importance_timestamp
            ON messages(importance_score DESC, timestamp DESC)
        """)

        # Partial index for entity assignment queue
        # Only indexes unchecked rows — shrinks as messages get processed
        # Optimizes: get_unchecked_messages(), get_unchecked_message_count()
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_entity_unchecked
            ON messages(entity_checked) WHERE entity_checked = 0
        """)

        # Phase 4.2: Update query planner statistics after index creation
        # This ensures SQLite knows about the new indexes for optimal query planning
        cursor.execute("ANALYZE messages")
        cursor.execute("ANALYZE attachments")
        cursor.execute("ANALYZE message_entities")
        cursor.execute("ANALYZE entity_summaries")
        cursor.execute("ANALYZE daily_summaries")
        cursor.execute("ANALYZE turn_log")
        cursor.execute("ANALYZE retrieval_log")
        cursor.execute("ANALYZE concept_trigger_log")
        cursor.execute("ANALYZE entity_summary_log")

        # =================================================================
        # INSERT DEFAULT DATA
        # =================================================================

        # Insert tier definitions
        tiers_data = [
            (
                "active",
                "Recent and high-importance memories, always loaded in context",
                7.0,
                json.dumps({"auto_load": True, "max_age_days": 30})
            ),
            (
                "standard",
                "Normal priority memories, default retrieval pool",
                3.0,
                json.dumps({"auto_load": False, "max_age_days": 180})
            ),
            (
                "deep_archive",
                "Old or low-priority memories, requires explicit --deep flag",
                0.0,
                json.dumps({"auto_load": False, "max_age_days": None})
            )
        ]

        cursor.executemany("""
            INSERT OR IGNORE INTO tiers (name, description, min_importance, config)
            VALUES (?, ?, ?, ?)
        """, tiers_data)

        # Store schema version
        cursor.execute("""
            INSERT OR REPLACE INTO metadata (key, value, updated_at)
            VALUES (?, ?, ?)
        """, ("schema_version", json.dumps(get_schema_version()), datetime.now(timezone.utc).isoformat() + "Z"))

        # Store database creation timestamp
        cursor.execute("""
            INSERT OR REPLACE INTO metadata (key, value, updated_at)
            VALUES (?, ?, ?)
        """, ("created_at", json.dumps(datetime.now(timezone.utc).isoformat() + "Z"), datetime.now(timezone.utc).isoformat() + "Z"))

        # Commit all changes
        conn.commit()
        conn.close()

        return True

    except Exception as e:
        print(f"Error creating database schema: {e}")
        return False


def verify_schema(db_path):
    """
    Verifies that all tables and indexes exist in the database.

    Args:
        db_path (str): Path to the SQLite database file

    Returns:
        dict: Status information about each table

    WHAT THIS DOES:
    Checks that the database was created correctly by verifying:
    - All expected tables exist
    - All expected indexes exist
    - Schema version is stored
    """

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Get list of all tables
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table'
            ORDER BY name
        """)
        tables = [row[0] for row in cursor.fetchall()]

        # Get list of all indexes
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='index'
            ORDER BY name
        """)
        indexes = [row[0] for row in cursor.fetchall()]

        # Get schema version
        cursor.execute("""
            SELECT value FROM metadata WHERE key='schema_version'
        """)
        result = cursor.fetchone()
        schema_version = json.loads(result[0]) if result else None

        conn.close()

        expected = ["messages", "embeddings", "importance_scores", "metadata", "tiers", "concepts", "attachments", "message_entities", "entity_summaries", "daily_summaries", "notes", "turn_log", "retrieval_log", "concept_trigger_log", "entity_summary_log"]
        return {
            "tables": tables,
            "indexes": indexes,
            "schema_version": schema_version,
            "expected_tables": expected,
            "all_tables_exist": all(t in tables for t in expected)
        }

    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    """
    This runs when the script is executed directly (for testing).
    """
    print("This is the schema definition file.")
    print("To create a database, use scripts/init_db.py")
    print(f"Current schema version: {get_schema_version()}")
