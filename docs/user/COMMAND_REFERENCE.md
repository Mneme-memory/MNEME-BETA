# Mneme Command Reference

**v15.0.1** — Updated May 2026

Quick reference for all AI commands and system operations.

---

## AI Commands (Instance Commands)

These commands are used by the AI proactively during conversation. They appear at the start of a line in the AI's response and execute automatically.

### @remember {id}

Mark a specific message as high-importance. Explicitly remembered messages are set to importance `10.0`. Every message shows its ID as `[ID:N]` in the context the AI sees. The AI uses this to flag important memories for stronger retrieval.

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

Preview memories about a topic, then archive selected matches in a confirmation step.

```
@forget [topic]
@forget confirm [id1] [id2] ...
@forget confirm all
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

View or write a description for an attached file so it can be found by search later.

```
@describe
@describe abc12345
@describe abc12345 Golden sunset over calm water — shared when discussing favorite moments
@describe abc12345 | Golden sunset over calm water — shared when discussing favorite moments
```

---

### @entity

Browse entity summaries or force-include an entity in the next retrieval.

```
@entity list
@entity view [name]
@entity [name]
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

### @help

Show the full command menu or detailed help for one command.

```
@help
@help recall
```

---

## Command Behavior

### Non-retrieval commands (execute inline, no continuation)
`@remember {id}`, `@forget confirm`, `@note`, `@describe {uuid} | {description}`, `@artifact`, `@config`

Multiple non-retrieval commands can be combined in one message.

### Retrieval commands (trigger continuation)
`@recall`, `@run`, `@file list`, `@file view`, `@file search`, `@describe`, `@describe {uuid}`, `@concept list`, `@concept view`, `@entity list`, `@entity view`

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
sqlite3 data/main/memory.db "VACUUM;"              # Optimize database
```

Startup backups are controlled by `system.enable_auto_backup`, `system.backup_keep_count`, `storage.backup_path`, and optional `storage.cloud_backup_path`.
