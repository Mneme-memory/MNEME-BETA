# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [15.1.0] - 2026-07-12

### Added
- **Mneme home** — user data (config, databases, live system instructions) now lives outside the app folder, at `%LOCALAPPDATA%\Mneme` (override with the `MNEME_HOME` environment variable). The app folder becomes pure, replaceable code: updating or re-installing Mneme can no longer endanger memories. Existing installs keep their current layout untouched and get a one-time in-app offer to move; the move copies (never deletes), verifies every database, and leaves the original behind as a backup with a `WHERE-IS-MY-DATA.txt` breadcrumb. Explicit absolute paths in `config.json` are always respected.
- Setup wizard "Import from a previous Mneme": first-run installs can adopt the memories, settings, and API keys of an older install — auto-detected in common locations or pointed at by folder path. The old install is never modified.
- Windows AppContainer execution backend for `@run`: read-only repository/profile access, redacted credentials, disposable scratch storage, denied network/registry/child processes, job-based time and memory limits, and fail-closed behavior. A statically linked x64 runner is bundled; ARM64 prefers a future native build and can use Windows 11 x64 emulation meanwhile.
- Tailnet identity gate for every Flask route: loopback remains local, direct Tailscale-IP phone access remains unchanged, and ordinary LAN clients are rejected.
- Claude Fable / newer Claude model support, including model picker entries, pricing metadata, newer model ID handling, and per-model request parameter allowlisting.
- Local embedding support using BGE small ONNX embeddings, with provider selection through `retrieval.embedding_provider`.
- One-click in-app embedding migration with backup-first behavior, resumable progress, verification, and migration status UI.
- Existing-user migration now switches the live app from legacy/OpenAI embeddings to local embeddings before starting the re-index job.
- Transcript export from the app, with Markdown and import-compatible JSON output options.
- Model-aware context budgeting with prompt-size preflight, near-limit warnings, over-budget context refresh, and one context-length retry.
- Per-turn dynamic budget for elastic context blocks (memories, entity summaries, concepts, files) sized from the model's remaining input window — items are dropped whole rather than excerpted, and forced entities surface a visible status note when omitted.
- Anchored active prompt-history window to preserve Anthropic prompt-cache prefix stability across long sessions.
- Model-aware conversation-window settings, including 1M-only context choices for supported models.
- "Keep this PC awake while Mneme is running" setting (`system.keep_pc_awake`, Windows-only for now) — suppresses system sleep via `SetThreadExecutionState` so mobile clients stay connected, while still allowing the display to turn off. Toggle applies immediately from Settings, no restart required.
- In-app system instructions editor: Settings → Profile settings → System instructions lets you edit a profile's system instructions directly from the app — changes apply on the next message, no restart required. Includes a reset-to-template button and a 100 KB cap.

- `src/frontend/DESIGN.md` — the visual identity law: closed named-rock palette
  (`--alabaster` as THE text white, `--wash`, named coral washes), four type
  voices (Wordmark/Mneme/AI/Machine), three planes (room/structure/glass),
  glass tokenized as `--glass-*` + `--scrim`. Full token sweep across the app;
  modals and bottom drawers now wear the glass material.
- Startup screen restyled per the law, with `startup.html?preview` mode that
  cycles real boot states without a running server.
- Wave progress bar (`createWaveProgress`): determinate squiggle with the
  thinking-wave DNA — traveled portion is a living coral wave, remainder a
  flat chalk track with an end dot; exhales flat at 100%. Used by the
  migration modal and the startup screen (backend now reports boot
  `step`/`steps` in `/api/startup/status`).
- Command console: the commands drawer executes query commands in place via
  new `POST /api/command` (zero conversation storage — no temporary messages
  or cache-pollution cleanup). Browse topics/concepts as tappable glass cards
  with drill-down detail; files render as a squircle thumbnail grid with an
  editable description form. Action forms: archive-a-topic (preview →
  tap-select → confirm), concept create/edit (prefilled); typed bare
  `@concept create` / `@concept edit <name>` summons the form.
- `@entity merge a | b | c` (human-only) + tap-to-select merge mode in the
  console: Haiku picks the surviving name and merged description, message
  links repoint, summaries rebuild lazily from combined history, absorbed
  names become aliases so future assignment redirects.
- Typed query commands (`@recall`/`@review`, `@entity list/view`,
  `@concept list/view`, `@file list/search`) now get AI commentary: the raw
  result surfaces as an expandable status-log detail, then the AI replies
  with the substance plus its own take (result rides the uncached dynamic
  input — cache-safe). A command's first line can be followed by prose,
  which the AI answers using the result. Action commands stay instant.
- Command autocomplete in the chat input: commands, subcommands, and live
  entity/concept names from the DB; glass popup, tap/Tab/arrows.
- Command drafts render in machine voice: pure single-line commands go
  Fira+coral; multi-line drafts paint the command line coral through a
  mirror layer with caret-safe identical metrics.

- Durable stream reconnect (v1): turn generation now runs in a background worker
  thread decoupled from the SSE response, so a client disconnect (mobile tab
  switch, screen lock, network blip) no longer kills the response. The full turn
  — including command-continuation iterations — runs to completion and persists
  normally even with no listener. New files: `src/backend/stream_worker.py`
  (`TurnWorker`, `GenerationRegistry`).
- `GET /api/chat/generation-status` reports whether a turn is in flight for the
  active profile. On page load / after a mid-stream socket death the frontend
  shows a "Mneme is still writing…" indicator and polls until the turn lands,
  then reloads it (no live token replay in v1).
- Per-profile in-flight guard: sending a new message while one is generating is
  rejected with HTTP 409 and a clear notice (no double-generation). Applies to
  `/api/chat/stream` and `/api/chat/continue`.
- `POST /api/chat/cancel`: cooperative cancellation for the stop button. The
  worker closes the turn generator from the worker thread (raising
  `GeneratorExit` inside `process_message_stream` — the pre-v1 kill semantics)
  and the in-flight guard clears, so the follow-up save-partial /
  cleanup-orphans calls keep their exact pre-v1 behavior.
- Incremental "load older messages" scrolling: `GET /api/history` now accepts
  `before_id` for keyset pagination (`db.get_message_page()`, ordered by `id`
  so an 8,000+ message import stays fast — no `OFFSET` scan) and returns
  `has_more`. The frontend fetches the previous page when the user scrolls
  near the top of the message list (`scrollTop < 200`, tolerant of mobile
  touch-momentum overscroll), prepends it via a detached `DocumentFragment`
  built with the existing `addMessage()` bubble renderer (no second renderer),
  and restores scroll position by compensating `scrollTop` for the exact
  `scrollHeight` delta so there's no visible jump. A small top-of-list
  indicator shows "loading earlier messages…" while fetching and "beginning
  of conversation" once `has_more` is false. Initial-page load behavior is
  unchanged. Duplicate concurrent fetches are guarded by
  `isLoadingOlderMessages`.

### Changed
- The update guide and downloadable AI-assistance guide now make the setup wizard's verified previous-install importer the recommended legacy upgrade path; v15.1+ updates explicitly reuse `%LOCALAPPDATA%\Mneme` without copying personal files back into the app folder.
- The Windows installer no longer creates a live `system_instructions.txt` in the replaceable app folder; fresh setup and import write live instructions to the Mneme home/profile instead.
- Entity merge UX rebuilt: long-press selects (tap toggles, long-press peeks at a detail mid-selection), merge/cancel live in a glass bar pinned to the drawer bottom, all console views restore scroll position on back-navigation, and merging shows a staged progress view (Mneme logo animation, per-month rebuild narration) that lands on the merged topic with its fresh summary.
- Merging entities now rebuilds the survivor's combined summary immediately in the background instead of waiting for the next retrieval.
- `@entity view` falls back to the newest monthly summary when no all-time summary exists, labeled with its month.
- `@forget confirm` now enforces the preview: IDs the preview did not show are rejected (mixed lists archive nothing), and confirming without a preceding preview is refused.
- Settings: single-line controls (model dropdown, text inputs) are pills; the model dropdown's border and chevron are coral to match its value. Machine values (dropdown, slider bubbles, stats) render in the mono/coral machine voice.
- Console scrollers (home pills, query views) fade content at clipped edges like the expanded status log; the back-button header stays pinned while lists scroll.
- `@run` now receives `REPO_PATH`, redacted `CONFIG_PATH`, read-only `DB_PATH`, and disposable `SCRATCH_PATH`; the writable `DB_FILE` escape hatch was removed.
- Debug message deletion now uses the canonical database deletion lifecycle instead of issuing a raw SQL delete.
- New installs now use a single Anthropic key path; OpenAI is no longer part of first-time setup unless users manually opt into OpenAI embeddings.
- Retrieval entry points now honor the shared embedding provider factory instead of assuming OpenAI.
- Embedding migration copy and user docs now explain local embeddings, migration, transcript export, and single-key setup.
- Migration status now reports the local target count/model even when the current provider is still OpenAI.
- Settings page visual language was normalized: pill selectors, retrieval-weight controls, transcript-format selector, text hierarchy, color usage, and accessibility pass.
- Chat input now locks with a status indicator while embedding migration is actively running, and reopens the migration status modal if dismissed mid-run.

- `cleanup_orphan_messages()` accepts `protect_trailing_turn`; the
  `/api/messages/cleanup-orphans` endpoint passes it when a generation is active
  so page-load cleanup can no longer delete the in-flight user row or its
  pre-allocated empty assistant shell.
- Disconnect vs interrupt is now explicit: an interrupt is the stop-button flow
  (`/api/chat/cancel` first, then `save-partial`/`cleanup-orphans`). A silent
  socket death makes no cancel call, touches nothing, and the turn keeps
  generating.

### Fixed
- First-run import no longer mistakes Mneme's own `.server.pid` and `.launched`
  runtime markers for existing user data and refuses to import. All other
  destination content still triggers the overwrite guard.
- Setup import now rejects database-only folders that lack a root `config.json`, preventing a failed initialization from stranding copied data behind a disabled setup wizard.
- Entity merge crashed with an IntegrityError when a message was linked to two of the merged entities (the co-mention case merges exist for); source links are now deduplicated before repointing, and a graph-DB failure after main-DB commits reports a clear run-it-again recovery message.
- `@entity view` read a summary column that never existed, so every entity showed "No summary generated yet" since the view was written; it now reads the real column.
- Failed query commands typed in chat now persist as temporary messages instead of vanishing from history on reload.
- Console buttons ("Bring into next reply", concept Delete) no longer announce business failures as success; cancelling merge selection clears stale card highlights.
- Double-tapping send on a bare `@concept edit` no longer fires the form lookup twice or falls through to a raw send.
- `messages.modified`/`last_modified` are now stamped when message content is updated (were never written).
- Recovered user messages now pass through the HTML-escaping Markdown renderer, closing a stored-XSS path during stream recovery.
- Duplicate retrieval counts are now included in the retrieval status summary instead of being computed and discarded.
- Temperature/API parameter failures on newer Claude models by omitting unsupported parameters.
- Clipboard copy failures on phone/LAN/non-secure contexts via fallback behavior.
- `@run` capability confusion by clarifying it cannot save files, plus artifact write verification so file results come from actual writes rather than model narration.
- Migration prompt now defers the mobile notification overlay instead of stacking modals.
- Over-budget context refresh now reloads persisted post-tier-transition history safely, excluding the in-flight user row and empty preallocated assistant row.
- `@run` output stripping no longer depends on entity summaries being enabled.
- Graph/entity schema now initializes for standard installs too, preventing missing-entity-table failures when summaries are disabled.
- `Database` now ensures the entity/graph schema exists on every construction (not just server startup), fixing `DELETE FROM messages` failures (`delete_message`, `cleanup_orphan_messages`, tier transitions) on any entry point — scripts, importers, diagnostics — that never explicitly builds a `GraphDatabase`.
- `@recall` was structurally blind to active-tier (recent) messages: `semantic_search(..., tier="standard")` compiled to an exact-match `WHERE tier = 'standard'`, so a highly relevant memory from the last few days (still in the active tier) could never be returned by an explicit recall. `get_messages_with_embeddings` now accepts a list of tiers (`WHERE tier IN (...)`), and `@recall`'s standard search now queries `["active", "standard"]`. Automatic per-turn retrieval (`context.py`) intentionally stays standard-tier-only — see `context-assembly.md`.
- `@run` sandbox now falls back correctly on ownership-less / non-NTFS volumes: a git "dubious ownership" error no longer fails the sandbox.
- `init_db.py` no longer crashes with a `UnicodeEncodeError` on Windows' default cp1252 console.

- Pagination scroll restore jumped/animated (CSS `scroll-behavior: smooth`
  animating programmatic `scrollTop`; native scroll anchoring suspended only
  during prepends now).
- FTS5 syntax errors from punctuation in `@entity view` names (tokens now
  quoted before MATCH).
- Settings title/description spacing unified at 6px.
- Dead `.notification-bar.idle` dim state removed.
- Sticky mobile `:hover` made merge selection unreadable; hover styles now
  gated behind `(hover: hover)` and selection made unambiguous.

### Docs
- OpenAI embedding deprecation / local embedding migration plan documented.
- User setup/help docs refreshed for single-key setup, local embeddings, migration, transcript export, and troubleshooting.

### Verification
- Added a regression covering the packaged startup lifecycle where runtime
  markers exist before the setup wizard submits an import; 106 backend tests
  pass.
- AppContainer adversarial tests verified repository/profile write denial, credential blocking and output scrubbing, unrelated-file denial, network/registry/child-process denial, database reads, timeout termination, output caps, scratch quota termination, and fail-closed startup behavior.
- Live Tailscale verification accepted this machine's authenticated tailnet identity and rejected an ordinary LAN source; Flask smoke checks returned 200 for loopback and 403 for LAN.
- Backend verification: 49 standard tests plus 5 AppContainer integration/adversarial tests passed (54 total). JavaScript syntax, Python compileall, targeted Ruff checks, native `/W4 /WX` compilation, and `git diff --check` passed.
- Backend `py_compile` checks were run across the changed context-budgeting, migration, embedding, server, and tier-transition modules.
- Frontend `node --check src/frontend/app.js` passed for the JavaScript changes.
- Isolated SQLite integration test verified context trim reload, `@run` output stripping, and in-flight row exclusion.
- Isolated Haiku `/api/chat/stream` smoke test returned `MNEME_TEST_OK`.
- Standard-install tier transition test verified `@run` stripping with entity summaries disabled.

---

## [15.0.1] - 2026-05-18

### Added
- Windows installer/release refresh for the public beta
- Configurable startup database backups using SQLite snapshots, local retention, and optional cloud/off-device copy
- Startup readiness page and `/api/startup/status` flow for tray/browser launch feedback
- `scripts/check-production-sync.sh` for comparing local state against the orphan-snapshot production repo
- `src/frontend/startup.html`, `startup.css`, and `startup.js` loading screen files
- Root-level `Mneme_Architecture_Infographic.pdf` for release visibility

### Fixed
- Cold-start image attachment payload handling
- Profile creation model normalization for newer dated Claude model IDs
- Windows launch path now records the exact installer Python in `scripts/.python-path` and reuses it from `launch.bat` / `tray.py`
- Production push now fails when required release files or release assets are missing/stale
- Release pruning now excludes private/dev files from the orphan production snapshot and release ZIP
- Linux installer exits clearly on macOS instead of pretending Mac launcher support is packaged

### Docs
- README wordmark, platform support notes, next-stage roadmap, and under-the-hood document refresh
- Setup guide PDF refreshed for the release, including Windows SmartScreen / unsigned publisher instructions
- Command reference refreshed for current `@remember`, `@forget`, `@describe`, `@entity`, `@artifact`, and `@run` behavior
- Architecture docs updated with startup/release maintenance notes
- Production release links now point to `Mneme-memory/MNEME-BETA` release assets

---

## [15.0.0] - 2026-03-29

### Changed
- Status copy rewritten toward shorter, more casual in-app language
- Profile selector and starting screen polish
- Release ZIP workflow and install flow refinements

---

## [14.1.0] - 2026-03-29

### Added — Windows Installer
- `Mneme-Setup.exe`: Inno Setup-based Windows installer with a graphical wizard
- Automatic Python 3.12 installation if no compatible Python is detected — no manual Python setup required
- ARM64 Windows support: detects ARM64-native Python directories; forces x64 Python install via `winget` to avoid native wheel build failures
- Tailscale installation page in the wizard with opt-out checkbox
- Dark-themed wizard UI with custom banner and icon

### Changed
- `install-windows.bat` moved to `scripts/installer/` — the GUI installer (`Mneme-Setup.exe`) is now the recommended Windows install path

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
