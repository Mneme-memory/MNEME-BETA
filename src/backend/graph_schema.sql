-- Entity Schema for Mneme
-- Entity store with FTS5 for name search
-- Relationships were removed; only entities remain

-- ============================================================================
-- Entities Table
-- ============================================================================
CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,  -- Canonical name (from consolidation)
    description TEXT NOT NULL DEFAULT '',  -- Human-readable description
    aliases TEXT,               -- JSON array of alternative names
    mention_count INTEGER DEFAULT 0,
    first_mentioned TEXT,       -- ISO timestamp
    last_mentioned TEXT,        -- ISO timestamp
    metadata TEXT               -- JSON for extensibility
);

-- ============================================================================
-- Full-Text Search for Entities (FTS5)
-- ============================================================================
CREATE VIRTUAL TABLE IF NOT EXISTS entities_fts USING fts5(
    name,
    content='entities',
    content_rowid='id'
);

-- Triggers to keep FTS5 in sync
CREATE TRIGGER IF NOT EXISTS entities_ai AFTER INSERT ON entities BEGIN
    INSERT INTO entities_fts(rowid, name) VALUES (new.rowid, new.name);
END;

CREATE TRIGGER IF NOT EXISTS entities_ad AFTER DELETE ON entities BEGIN
    DELETE FROM entities_fts WHERE rowid = old.rowid;
END;

CREATE TRIGGER IF NOT EXISTS entities_au AFTER UPDATE ON entities BEGIN
    UPDATE entities_fts SET name = new.name WHERE rowid = new.rowid;
END;

-- ============================================================================
-- Performance Indexes
-- ============================================================================

-- Entity indexes
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name);
CREATE INDEX IF NOT EXISTS idx_entities_mentions ON entities(mention_count DESC);
CREATE INDEX IF NOT EXISTS idx_entities_last_mentioned ON entities(last_mentioned DESC);

-- ============================================================================
-- Statistics Update
-- ============================================================================
ANALYZE;
