# Mneme Command Reference

**v14.0.0** — Updated March 2026

Quick reference for all AI commands and system operations.

---

## AI Commands (Instance Commands)

These commands are used by the AI proactively during conversation. They appear at the start of a line in the AI's response and execute automatically.

### @remember {id}

Mark a specific message as high-importance (×2.0 importance multiplier). Every message shows its ID as `[ID:N]` in the context the AI sees. The AI uses this to flag important memories for stronger retrieval.

```
@remember 1234
```

---

### @recall {topic}

Retrieve memories semantically similar to a topic. Triggers a continuation — AI receives the results and continues responding.

```
@recall [topic]
@recall --deep [topic]    ← search deep archive (6+ months old)
```

---

### @forget {topic}

Archive memories about a topic (moves to deep archive, reduces importance).

```
@forget [topic]
```

---

### @note {section} / @endnote

Create or replace a persistent note section. Notes survive across conversations.

```
@note Preferences
- Dark themes, minimal UI
- Direct communication style
@endnote
```

```
@note remove Preferences     ← remove a specific section
@note clear                  ← clear all notes
```

---

### @concept

Read and manage narrative concepts (keyword-triggered interpretive context).

```
@concept list
@concept view [name]
@concept create [name] | [keyword1, keyword2] | [definition]
@concept edit [name] | [keywords] | [definition]
@concept delete [name]
```

`@concept list` and `@concept view` trigger continuations.

---

### @file

Manage and view file attachments.

```
@file list
@file view [uuid]           ← triggers continuation
@file search [query]
```

---

### @describe {uuid} {description}

Write a description for an attached file so it can be found by semantic search later.

```
@describe abc12345 Golden sunset over calm water — shared when discussing favorite moments
```

---

### @artifact / @endartifact

Save creative or technical work as a persistent markdown file on disk. Files are stored as human-readable `ARTIFACT.md` under `data/{profile}/artifacts/{category}/{slug}/`.

```
@artifact poetry/2026-03-06_first-snow | First Snow | nature, poetry | Haiku sequence
# First Snow

[content lines...]
@endartifact
```

The AI uses this proactively to save poems, stories, design notes, technical docs, and other work worth preserving.

---

### @run / @endrun

Execute read-only Python code in a sandboxed subprocess. The AI uses this to query the database, browse artifacts, or inspect source code. Triggers a continuation with stdout/stderr results.

```
@run
import sqlite3, os
db = sqlite3.connect(os.environ["DB_PATH"], uri=True)
cursor = db.execute("SELECT COUNT(*) FROM messages")
print(cursor.fetchone()[0])
@endrun
```

10-second timeout. Database access is read-only. Output truncated at 4000 characters.

---

### @config

Adjust a setting for the current session.

```
@config [parameter] [value]
```

---

## Command Behavior

### Non-retrieval commands (execute inline, no continuation)
`@remember {id}`, `@forget`, `@note`, `@describe`, `@artifact`, `@config`

Multiple non-retrieval commands can be combined in one message.

### Retrieval commands (trigger continuation)
`@recall`, `@run`, `@file view`, `@concept list`, `@concept view`

The AI pauses, executes the command, receives results, then continues responding. Only one retrieval command should be used per message (multiple use up the iteration budget quickly).

### Iteration limit

Maximum iterations per message is configurable (`max_iterations` in system instructions). Default is 6. Guards against infinite recall chains.

---

## System Operations

### Server

```bash
python src/backend/server.py       # Start server → http://localhost:8080
python scripts/tray.py             # Start via system tray (recommended)
# Ctrl+C to stop (server mode)
```

### Database

```bash
python scripts/init_db.py          # Initialize database
python scripts/verify_setup.py     # Check setup
python scripts/chat.py             # CLI chat (quick testing without browser)
```

```bash
sqlite3 data/main/memory.db        # Direct database access
```

Useful SQLite queries:
```sql
SELECT COUNT(*) FROM messages;
SELECT id, sender, importance_score, content FROM messages ORDER BY id DESC LIMIT 20;
SELECT name, mention_count FROM entities ORDER BY mention_count DESC LIMIT 20;
SELECT name, trigger_keywords FROM concepts ORDER BY name;
```

### Artifacts

Stored as plain markdown files at `data/{profile}/artifacts/{category}/{slug}/ARTIFACT.md`. Browsable and editable outside the app — no database tables involved.

### Debug Endpoints

```
GET  http://localhost:8080/api/debug/messages     ← all messages
GET  http://localhost:8080/api/debug/context      ← what AI sees this turn
DELETE http://localhost:8080/api/debug/delete/{id} ← delete a message
```

### Configuration

Edit `config.json` (never commit this file — it contains API keys). Most settings are also adjustable from the in-app settings page.

See `config.example.json` for all options with inline comments.

Key sections: `api_keys`, `storage`, `identity`, `model`, `thinking`, `context`, `retrieval`, `caching`, `features` (concepts, attachments, entity_summaries, tts, timeline, notes), `commands`, `system`.

### Maintenance

```bash
python scripts/diagnose_database.py                # Check database health
python scripts/manage_entities.py                  # View/edit/merge entities
python scripts/regenerate_entity_summaries.py      # Fix botched entity summaries
sqlite3 data/main/memory.db "VACUUM;"              # Optimize database
```
