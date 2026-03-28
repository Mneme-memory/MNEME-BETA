# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [14.0.0] - 2026-03-20

### Added — Profile System
- Multi-instance support: each profile gets its own database, config overlay, and conversation history
- Profile selector screen with model icon, instance name, and model label per profile
- "New instance" creation flow with typewriter headline, model picker, and name entry
- Per-profile config overlay — `identity`, `model`, `thinking`, `context`, `features` keys scoped per profile; everything else stays global
- Mneme logo loading animation (canvas-based coral pillars) during profile switches and creation
- Three-screen navigation: starting screen → profile selector → chat view
- `GET /api/profiles`, `POST /api/profiles`, `POST /api/profiles/switch` endpoints
- Graph database schema migration to support per-profile entity databases

### Changed
- `config.py` now manages base config snapshot and profile overlay merging
- `server.py` startup flow initializes last-active profile automatically
- Header back button navigates to profile selector instead of reloading

---

## [13.0.0] - 2026-03-18

### Added — Code Execution (`@run`)
- `@run...@endrun` command: AI executes read-only Python in a sandboxed subprocess
- Environment variables: `DB_PATH` (read-only SQLite URI), `DB_FILE` (plain path), `ARTIFACTS_PATH`, `ATTACHMENTS_PATH`, `SRC_PATH`
- 10-second timeout, 4000-char output truncation
- Auto-retry on transient failures (OneDrive file locks)
- Errors always trigger continuation (no silent failures)
- Code blocks stripped to `[ran python]` in stored messages to save cache tokens
- Collapsible `<details>` rendering in frontend with coral "ran python" summary

### Added — Artifact System Instructions
- System instructions entry for `@artifact` — syntax, naming conventions, proactive saving guidance
- AI now knows when and how to save artifacts without being told

### Changed
- Max instance command iterations: 5 → 6 (needed for multi-step @run workflows)
- Files context block reduced from 20 → 5 recent files (AI can query attachments table via @run for older files)
- Files block header updated: "RECENT FILES" with hint about @run for older files
- System instructions: added messages table key columns, artifact filesystem hint, code execution anti-hallucination rules

### Fixed
- Block command highlighting (`@run`, `@note`, `@artifact`) — extracted at Step 0 of markdown parser before any processing; `# comments` in code no longer parsed as headers, `**text**` no longer parsed as bold
- `@artifact` blocks with multi-line content now render correctly in frontend

### Removed
- `collaborators` field from `artifact_storage.py` (unnecessary complexity)

---

## [12.1.0] - 2026-03-08

### Added
- Model selector wired to backend — clicking Opus/Sonnet/Haiku in the starting screen now switches the active model at runtime without restarting the server (`POST /api/set-model`)
- `scripts/migrate_drop_tags.py` — drops the deprecated `tags` table from existing databases

### Removed
- Ghost button (profiles placeholder) removed from header — served no purpose
- Dead `tags` schema removed from `schema.py` (table, indexes, ANALYZE call)

### Fixed
- `GET /api/stats` now returns the live `manager.model` instead of re-reading config, so the badge reflects runtime model changes correctly

---

## [12.0.0] - 2026-03-07

### Added — Artifact Storage
- Filesystem storage for creative and technical work (poems, stories, docs, design notes)
- `@artifact {category}/{slug} | title | tags | summary` ... `@endartifact` command
- Files stored as human-readable `ARTIFACT.md` under `data/{profile}/artifacts/{category}/{slug}/`
- No database tables — pure filesystem, directly browsable and editable outside the app
- `ArtifactStorage` module with lazy directory creation

### Added — Stop Button & Interrupted Response Recovery
- Square stop button during streaming; aborts via AbortController
- Partial AI response saved to DB with `[message interrupted]` suffix
- Continue toast offers to resume; continuation merges into same DB record
- Multiple re-interruptions supported
- Abort before any AI text: orphan cleanup runs, text restored to input

### Added — Orphan Message Cleanup
- `POST /api/messages/cleanup-orphans` endpoint
- Consecutive user messages deduped; trailing unanswered user message removed and text restored
- Runs on page load (silent) and on send error (shows status line)

### Added — UI Improvements
- Copy button (hover-visible) on AI messages with coral flash on success
- User messages: single left-click copies on desktop, long-press on touch
- Paste image from clipboard to attach directly (no file picker required)
- `@command` text highlighted coral in both user and AI messages
- Markdown rendering in user messages (bold, italic, code, lists, headers)
- "Entity assembled" notification per bootstrapped entity summary
- Attachment chips below user bubble (thumbnail for images, `◎` glyph + filename for others)

### Fixed — SSE Error Propagation
- Inner SSE catch now only swallows `SyntaxError`; backend errors re-thrown to outer handler
- Ensures orphan cleanup and bubble removal fire correctly on API errors

### Fixed — Non-cached Path Missing Attachments
- Cold-start branch in `_call_ai()` now passes `attachment_blocks` when present

---

## [11.0.0] - 2026-03-01

### Added — AI Notes Layer
- Persistent, AI-managed note sections stored in SQLite
- AI can create, update, and read notes across conversations
- Notes injected into context alongside memories and graph data
- Notes persist independently of conversation tier transitions

### Added — Extended Thinking (Phase 10)
- Chain-of-thought reasoning via Claude's extended thinking API
- Configurable thinking budget per conversation
- Thinking tokens excluded from display, used only for reasoning quality
- Opt-in via config: `extended_thinking.enabled`

### Added — Timeline Awareness (Phase 9b)
- 7-day rolling daily summaries generated automatically
- Injected into context to give the AI awareness of recent days
- Summaries generated on-demand and cached in SQLite
- Configurable via `timeline.enabled` and `timeline.days`

### Added — Text-to-Speech (Phase 9a)
- ElevenLabs TTS integration for AI responses
- Streaming audio playback in the web UI
- Voice selection and speed configurable in settings
- TTS cache stored locally to avoid repeated API calls

### Changed — Database Refactor
- Split monolithic `database.py` into 6 domain-specific mixin modules
- Improves maintainability; no functional changes to external behavior

### Changed — Batch Processing
- Background tagging/graph extraction batch size increased from 10 → 30 messages
- Reduces API call frequency 3× at the same total cost

### Fixed — Configurable Streaming
- Added `enable_streaming` option in `phase3.conversation` config section
- Frontend auto-detects streaming capability from `/api/config` endpoint
- Fixes compatibility issues with certain proxy/network configurations

### Fixed — API Timeout
- Increased request timeout from 60s → 180s
- Prevents spurious timeouts on large context windows

### Fixed — Streaming Continuation
- Recursive AI calls during command execution (e.g. `@recall`) now stream properly
- Eliminates UI freezing during multi-turn command flows

---

## [8.0.0] - 2026-01-31

### Added — Entity Summaries
- On-demand hierarchical summaries for graph entities
- Monthly summaries (frozen at month end) + all-time synthesis
- Lazy generation: $0 cost for entities never retrieved
- Summaries update automatically when messages transition tiers
- Provides historical context alongside retrieved memories (e.g. "3 years of AE experience")

### Schema
- `message_entities` junction table linking messages to entities
- `entity_summaries` table with period type, period start, frozen flag, incremental count

### Migration
```bash
python scripts/migrate_add_entity_summaries_tables.py
python scripts/backfill_message_entities.py
```

---

## [6.0.0] - 2025-11-19

### Added — Narrative Concepts
- Keyword-triggered interpretive meta-memories bridging raw memories and the graph
- Zero-cost local string matching (no embeddings)
- Commands: `@concept list/view/create/edit/delete`
- Positioned between memories and graph in prompt structure

### Fixed
- Continuation cache fix: retrieval commands now preserve prompt cache (50-70% savings)
- Intermediate message double-printing in command continuation flow
- `@graph` results not passed to continuation call
- 200-character truncation removed from `@recall`/`@review` output

### Migration
```bash
python scripts/migrate_add_concepts_table.py
```

---

## [5.0.0] and earlier

See git history for Phase 5 (Knowledge Graph), Phase 4 (Optimization), Phase 3 (Web UI & Commands), and earlier changes.
