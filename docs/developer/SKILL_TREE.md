# Skill Tree — Non-Obvious Flows & Institutional Knowledge

Cross-cutting behaviors that span multiple files and aren't obvious from reading any single one. Each entry documents **what** the flow does, **which files** are involved, **what can go wrong**, and **past fixes**.

---

## Table of Contents

- [SSE Event Protocol](#sse-event-protocol)
- [Message Lifecycle: Storage, Cleanup & Interruption](#message-lifecycle-storage-cleanup--interruption)
- [Command Continuation Flow](#command-continuation-flow)
- [Prompt Caching Architecture](#prompt-caching-architecture)
- [Background Processing Pipeline](#background-processing-pipeline)
- [Entity Summary Pipeline](#entity-summary-pipeline)
- [Day Rollover & Timeline](#day-rollover--timeline)
- [Artifact Storage Flow](#artifact-storage-flow)
- [Code Execution Flow (@run)](#code-execution-flow-run)
- [Profile System & Config Overlay](#profile-system--config-overlay)
- [Abandoned: Graph Relationship Extraction](#abandoned-graph-relationship-extraction)

---

## SSE Event Protocol

**Files**: `conversation.py`, `server.py` (backend), `app.js` (frontend)

The streaming API (`POST /api/chat/stream` and `POST /api/chat/continue`) communicates via Server-Sent Events. Each event is a JSON line: `data: {"type": "...", "data": ...}\n\n`. This is the contract — both sides must agree on event types.

### Event types

| Type | `data` value | Backend source | Frontend effect |
|------|-------------|----------------|-----------------|
| `notification` | string (human-readable status) | `conversation.py` yield during context assembly and command execution | Routed to `handleNotificationAsLog()` → status log line. Special trigger: `"Cache"` in text → `activateWave()`. `"💭 Calling AI again"` → sets `inContinuationPhase = true` |
| `thinking_start` | `null` or empty | `ai_client.py` on first thinking block | `activateWave()` (fallback), creates thinking block in message bubble |
| `thinking` | chunk string | `ai_client.py` thinking delta | Appended to current thinking block |
| `chunk` | text string | `ai_client.py` text delta | `activateWave()` (fallback), appended to streaming message bubble |
| `done` | `{is_command, context_info}` | `conversation.py` after turn finalizes | Finalizes bubble (cursor off, timestamp, action row). Hides wave pill if `inContinuationPhase`. |
| `error` | error string | Any except block | Logged as error line, re-thrown — reaches `sendMessage` catch block for cleanup |

### Critical: inner SSE try/catch must only swallow `SyntaxError`

`app.js:sendMessageStreaming` has an inner try/catch around each event parse. It must re-throw anything that isn't a `SyntaxError`. If error events are swallowed here, the outer catch in `sendMessage` never fires — no cleanup, no orphan removal, no text restoration. See past bug in Message Lifecycle section.

### Notification string conventions

Backend uses emoji prefixes to signal severity: `✅` success, `⚠️` warning, `❌` error, `💭` AI/continuation. Frontend strips these in `stripNotificationEmoji()` and infers log type via `getNotificationType()`. Do not rely on exact emoji placement for routing logic — use the `type` field instead.

> Frontend streaming state machine driven by these events is documented in `src/frontend/CLAUDE.md § Turn Lifecycle` and `§ Streaming Wave`.

---

## Message Lifecycle: Storage, Cleanup & Interruption

**Files**: `conversation.py`, `database.py`, `server.py`, `app.js`, `schema.py`

### How user messages are stored

User messages are stored in the DB **immediately** when `_process_conversation_stream` begins (conversation.py ~line 872), before context assembly or the API call. This means if anything fails downstream, the message is already persisted as an orphan.

### Orphan cleanup system

`database.py:cleanup_orphan_messages()` scans ALL messages in order and applies two rules:

1. **Consecutive user runs**: If 2+ user messages appear in a row with no assistant message between them, delete all but the last (the newest retry).
2. **Trailing user message**: If the last surviving message is from a user (no AI response after it), delete it and return its text as `restored_text`.

The endpoint is `POST /api/messages/cleanup-orphans` (server.py).

### When cleanup is triggered

| Trigger | Location | Behavior |
|---------|----------|----------|
| Page load | `app.js:loadHistory()` | Runs cleanup before loading history. If `restored_text` is returned, populates the input field. |
| Send error | `app.js:sendMessage()` catch block | Runs cleanup, restores text to input, removes the optimistic user bubble from DOM. |
| Abort before AI text | `app.js:handleStreamAbort()` | Runs cleanup, restores text, removes user bubble. |

### Interruption: two distinct cases

**Abort BEFORE any AI text** (stop button pressed during context assembly / before first chunk):
- User bubble is removed from DOM
- DB orphan is cleaned via cleanup endpoint
- Text is restored to input field

**Abort DURING AI streaming** (stop button pressed after chunks arrived):
- User bubble stays (message is valid — AI was responding)
- Partial AI response is saved to DB via `/api/messages/save-partial`
- `[interrupted]` suffix is appended
- Continue toast appears offering to resume

### FK constraint gotcha

`delete_message()` must manually clean `retrieval_log` entries before deleting, because `retrieval_log.message_id` references `messages(id)` **without** `ON DELETE CASCADE` (schema.py ~line 574). All other FK references either cascade or use `SET NULL`.

If you add new tables that reference `messages(id)`, either add `ON DELETE CASCADE` in the schema or add a cleanup line in `delete_message()`.

### SSE error propagation

Backend errors during streaming are yielded as `{"type": "error", "data": "..."}` events. The frontend SSE reader has an inner try/catch — it must only swallow `SyntaxError` (JSON parse failures), not re-thrown error events. If error events are swallowed, the outer `sendMessage` catch block never fires, and no cleanup/bubble-removal/text-restoration happens.

### Past bugs (don't reintroduce)

| Bug | Root cause | Fix |
|-----|-----------|-----|
| Cleanup never worked at all | `retrieval_log` FK without CASCADE caused `delete_message` to throw on every attempt | `delete_message` now deletes `retrieval_log` rows first |
| API errors silently swallowed | Inner SSE catch checked `!startsWith('Server error')` — backend errors start with `"Error calling AI:"` so they were logged, not re-thrown | Changed to only swallow `SyntaxError` |
| User bubble persisted after pre-API abort | `handleStreamAbort` had no reference to the bubble element | Now receives `userBubbleEl` param, removes it in pre-text branch |

> Frontend UI for the interrupt state (wave contraction, interrupted pill, YES/× buttons, `showContinueToast`) is documented in `src/frontend/CLAUDE.md § Interrupt & Continue Flow`.

---

## Command Continuation Flow

**Files**: `instance_executor.py`, `conversation.py`, `ai_client.py`, `prompt_builder.py`

### What it is

When the AI's response contains a retrieval command (`@recall`, `@file view`), the system executes the command and calls the AI **again** with the results injected. The second AI response is what the user sees. This "continuation" must preserve the prompt cache or costs spike.

### Step by step

```
AI Response: "Let me check that.\n@recall memory systems"
    │
    ▼
InstanceExecutor.execute_commands()
    ├── Parses ALL commands from the response first
    ├── Executes non-retrieval commands immediately (no continuation)
    └── Queues retrieval commands for continuation
    │
    ▼
For each retrieval command:
    - Execute (semantic search, graph query, etc.)
    - Build continuation prompt:
        "Let me check that.
         [Command Result: @recall memory systems]
         Memory 1: ...
         IMPORTANT: Continue naturally from your previous message."
    │
    ▼
_call_ai(context=context, current_input=continuation_prompt)
    └── context= preserves cached sections (system + history)
    └── current_input= goes into the uncached dynamic section
    │
    ▼
AI continues: "Found it! We discussed..."
```

### Critical: how multi-command execution works

OLD code returned early on the first retrieval command, skipping the rest. **All commands must be parsed and executed before any continuation fires.** Non-retrieval commands run inline; retrieval commands accumulate, then trigger one continuation call with all results.

### Critical: cache preservation in continuations

`_call_ai(prompt=string)` breaks the cache — it replaces the structured context with a flat string. `_call_ai(context=context, current_input=string)` preserves cached sections. Continuations must always use the second form.

### Iteration limit

`max_iterations` (from system instructions) caps how many continuation loops can happen per message. Guards against infinite recall chains.

### Frontend side of continuation

When the backend executes a retrieval command and is about to call the AI again, it emits a `notification` SSE event starting with `"💭 Calling AI again"`. The frontend (`app.js`) uses this to set `inContinuationPhase = true`, which:
- Resets `currentAssistantMessage` so the continuation response appends to a new bubble
- Keeps the wave pill visible during the second API call (showing the latest status line)
- On `done`, hides the wave pill and clears `inContinuationPhase`

If you add a new retrieval command type that triggers a continuation, make sure the backend emits that notification string — the frontend relies on it to track which "turn" within a message it's on.

### Past bugs (don't reintroduce)

| Bug | Root cause | Fix |
|-----|-----------|-----|
| Multi-command skipped after first retrieval | Early return on first retrieval command | Execute ALL commands first, then do continuation |
| Cache broken on continuation | `_call_ai(prompt=...)` instead of `_call_ai(context=..., current_input=...)` | Use structured form to preserve cached sections |
| Intermediate response printed twice | Dedup logic missing | `app.js` deduplication handles this, but be careful modifying response flow |

---

## Prompt Caching Architecture

**Files**: `prompt_builder.py`, `prompt_cache.py`, `ai_client.py`, `conversation.py`

### What's cached vs uncached

The Anthropic prompt cache works by marking message blocks with `cache_control: {"type": "ephemeral"}`. Blocks marked this way are cached for up to 1 hour (TTL resets on use).

**CACHED** (static or near-static across turns):
| Block | Why |
|-------|-----|
| System instructions | Never changes mid-conversation |
| Timeline (daily summaries) | Changes once per day — cacheable for the whole day |
| Conversation history | Grows by one turn each message; old turns stay cached |

**UNCACHED** (changes every turn):
| Block | Why |
|-------|-----|
| Retrieved memories | Different every turn (semantic search result varies) |
| Entity summaries | Selected based on current message content |
| Narrative concepts | Keyword-triggered — changes with topic |
| AI Notes | User could update them via command |
| File attachments | Attached per-message |
| Current user input | Always new |

### Gap detection

`prompt_cache.py` tracks the last message timestamp. If >60 minutes have elapsed since the last message, the cache has likely expired — the system skips attempting to use it and builds a fresh cached prompt. This avoids paying input token costs for a cache that's already gone.

### Cache growth

Each turn adds ~300–400 tokens to the cached conversation history block. Total cache size grows linearly with conversation length. No cache pruning needed until the context window limit is approached (rare in practice).

### What breaks the cache

- Passing a flat string to `_call_ai(prompt=...)` instead of a structured context — the cached blocks are discarded
- Modifying system instructions mid-conversation
- Any gap >60 minutes (triggers gap detection → fresh cache build)

---

## Background Processing Pipeline

**Files**: `background.py`, `embeddings.py`, `entity_assignment.py`, `entity_summaries.py`, `tier_manager.py`, `conversation.py`

### After every message

When an AI response is finalized, `BackgroundQueue` enqueues async work:

```
Response finalized
    │
    ├── generate_embedding(user_message)     ← OpenAI API call
    ├── generate_embedding(assistant_message) ← OpenAI API call
    └── assign_entities(batch)               ← Anthropic Haiku (tool use, guaranteed JSON)
```

These run in a background thread and do not block the response. Do not assume embeddings or entity links are available immediately after a message.

### On tier transition (active → standard)

When `TierManager` moves messages from active to standard tier (happens when active window exceeds token budget), it fires a hook:

```
transition_tiers(background_summaries=True)
    │
    └── For each entity linked to transitioning messages:
            entity_summaries.update_entity_summary(entity_id)
                ├── If no existing summary: generate from scratch (Haiku call)
                ├── If <10 incremental updates: incremental update (Haiku call)
                └── If ≥10 incremental updates: full regeneration (drift prevention)
```

**Critical**: `background_summaries=True` must be passed or summary generation blocks synchronously on cold start. Both streaming and non-streaming paths must pass this flag.

### Entity assignment pipeline details

- Uses Anthropic tool use with `tool_choice` — guarantees valid JSON at token level
- Batch size: 30 messages (reduced from 250 after Haiku attention degradation at large scale)
- Combined assignment + discovery mode in live pipeline (assigns existing entities + proposes new ones)
- Known limit: Haiku's safety filter blocks batches containing violence/weapons/ethics discussions — those messages (~34) will have 0 entities

### Past bugs (don't reintroduce)

| Bug | Root cause | Fix |
|-----|-----------|-----|
| Cold start takes minutes | `transition_tiers()` without `background_summaries=True` caused synchronous Haiku API calls | Both streaming and non-streaming paths now pass `background_summaries=True` |
| JSON parse failures in entity assignment | Direct JSON string output from Haiku was malformed ~5% of the time | Switched to Anthropic tool use — token-level JSON guarantee |
| 0-link entities in backfill | 170k-token mega-batches caused Haiku attention degradation | Batch size reduced to 30–50 messages |

---

## Entity Summary Pipeline

**Files**: `entity_summaries.py`, `entity_assignment.py`, `context.py`, `database.py`

### What entity summaries are

When a memory is retrieved that mentions entity X, the system also injects a *summary* of who/what X is — built from all messages ever tagged to X, organized as monthly snapshots + an all-time synthesis. This gives the AI historical depth ("3 years of AE experience") without having to retrieve hundreds of individual messages.

### Summary structure

```
entity_summaries table:
  - entity_id
  - period_type: "monthly" | "all_time"
  - period_start: ISO date (for monthly) or NULL (for all_time)
  - frozen: bool (monthly summaries freeze at month-end, never regenerate)
  - content: generated text
  - incremental_count: how many updates since last full regeneration
```

### Injection into context

`context.py:_get_entity_summaries_context()`:
1. Scores each entity by how many retrieved memories mention it
2. Direct string match: if user's message contains an entity name/alias, that entity gets a boosted baseline score
3. Selects top-N entities within token budget (~5k tokens)
4. Returns formatted summaries alongside retrieved memories

### Lazy generation

Summaries are only generated when an entity is first retrieved. Entities the user never asks about cost $0.

### Past bugs (don't reintroduce)

| Bug | Root cause | Fix |
|-----|-----------|-----|
| `@remember` marked AI's own message | AI response stored in DB before `@remember` executed; LIKE search matched AI's just-stored text | When `marked_by="instance"`, keyword search filters to `sender="user"` only |
| Entities with 0 links after backfill | Haiku attention degradation at 170k-token batches | Reduced batch size; gap-fill script re-processes 0-link messages |

---

## Day Rollover & Timeline

**Files**: `daily_summaries.py`, `conversation.py`, `context.py`, `prompt_builder.py`

### What timeline awareness is

A 7-day rolling window of daily summaries injected into the **cached** section of the prompt. This gives the AI grounding in recent days without loading hundreds of individual messages.

### Day rollover check

At the start of each `_process_conversation_stream`:
1. `_check_day_rollover()` compares today's date to the last stored daily summary date
2. If a new day has started: generates yesterday's summary from all messages in that date range (Haiku call)
3. Runs in a **background thread** — does not block the current message

**Critical**: The background thread call must stay in place. If it's accidentally made synchronous (no `threading.Thread`), first-message-of-day will block for several seconds waiting for summary generation.

### Injection position

Daily summaries go in the **CACHED** section (they're stable for the whole day). Retrieved memories and dynamic context go in the UNCACHED section. This distinction matters for cost — putting stable data in the uncached section wastes tokens on every turn.

### Past bugs (don't reintroduce)

| Bug | Root cause | Fix |
|-----|-----------|-----|
| Cold start blocks on day rollover | `_check_day_rollover()` called synchronously | Wrapped in `threading.Thread` |

---

## Artifact Storage Flow

**Files**: `artifact_storage.py`, `instance_executor.py`, `server.py`, `conversation.py`

### What artifacts are

Persistent markdown files for creative and technical work — poems, stories, design notes, technical docs. Unlike memories (in SQLite), artifacts are pure filesystem: browsable, editable, and version-controllable outside the app.

### Directory structure

```
data/{profile}/artifacts/
    poetry/
        2026-03-06_first-snow/
            ARTIFACT.md
    technical/
        api-design-notes/
            ARTIFACT.md
```

### The @artifact command

```
@artifact poetry/2026-03-06_first-snow | First Snow | nature, poetry | Haiku sequence
# First Snow

[content lines...]
@endartifact
```

`InstanceExecutor` parses `@artifact...@endartifact` blocks (multi-line, like `@note...@endnote`). Calls `ArtifactStorage.save(category, slug, title, summary, tags, content)`. The AI can also browse existing artifacts via `@run` (os.walk on `ARTIFACTS_PATH`).

### ARTIFACT.md format

Each file has a YAML-like frontmatter header followed by the content:
```markdown
# {title}

**Date**: {date}
**Tags**: {tag1}, {tag2}
**Summary**: {summary}

---

{content}
```

### No database involvement

Artifacts are filesystem-only. There is no `artifacts` table in the database. This is intentional — the files are meant to be human-readable and independently portable.

### Save semantics

`ArtifactStorage.save()` overwrites any existing `ARTIFACT.md` at the same category/slug path. This allows the AI to update artifacts by reissuing the same slug.

---

## Code Execution Flow (@run)

**Files**: `commands.py` (`cmd_run`), `instance_executor.py`, `conversation.py`, `app.js` (`parseMarkdown`)

### How it works

AI writes `@run\n<python>\n@endrun`. `InstanceExecutor` extracts the block in a pre-pass (same pattern as `@note`/`@artifact`). `cmd_run` writes the code to a temp file, runs it in a subprocess with env vars (`DB_PATH`, `DB_FILE`, `ARTIFACTS_PATH`, `ATTACHMENTS_PATH`, `SRC_PATH`), captures stdout/stderr, returns as a retrieval result triggering continuation.

### Read-only enforcement

`DB_PATH` is a `file:///...?mode=ro` SQLite URI. The subprocess cannot write to the database — SQLite enforces this at the engine level.

### Code stripping

After the executor loop completes, `conversation.py` strips `@run...@endrun` blocks from the response text via regex, replacing with `[ran python]`. This happens before DB storage, so code never enters the prompt cache.

### Frontend rendering

`parseMarkdown` extracts `@run...@endrun` blocks at Step 0 (before HTML escaping, before any markdown processing) into a `<details class="cmd-run-block">` with the code in a `<pre><code>` block. This prevents Python `# comments` from becoming headers and `**text**` from becoming bold.

### Transient failure handling

The subprocess retries once with a 0.5s delay on failure (covers OneDrive file locks). Even if both attempts fail, the result is returned as a retrieval (success=True, is_retrieval=True) so the AI always gets feedback via continuation — no silent failures.

### What can go wrong

- **OneDrive file locks**: Intermittent "unable to open database file" errors. The auto-retry handles this. If both attempts fail, the AI sees the error in continuation and can retry at the instruction level.
- **AI hallucinating results**: If the AI writes text after `@endrun`, it invents results it hasn't received yet. System instructions explicitly forbid this: "After writing @endrun, STOP."
- **Column name assumptions**: The AI may guess wrong column names (e.g., `role` vs `sender`). System instructions document key `messages` columns. For other tables, the AI should use `PRAGMA table_info()`.
- **Iteration budget**: Multi-step queries (search → fetch → save) can use 3-4 iterations. Max is 6. Complex workflows can exhaust the budget.

---

## Profile System & Config Overlay

**Files**: `config.py` (`load_profile_config`, `update_active_profile`, `save_config`), `server.py` (`list_profiles`, `create_profile`, `switch_profile`, `reinit_system`, `_build_system`), `app.js` (three-screen navigation, profile rendering), `prompt_builder.py` (per-profile system instructions)

### Config overlay mechanism

Each profile can have a `data/{profile}/config.json` containing profile-scoped overrides. On load, `load_profile_config()` snapshots the base values into `config["_base_config"]`, then deep-merges profile overrides for keys in `PROFILE_SCOPED_KEYS` (`identity`, `model`, `thinking`, `context`, `features`). Global keys (API keys, storage, system) are never overridden.

### Critical: overlay leakage prevention

The in-memory `config` dict has profile overrides applied. If written directly to disk, profile values corrupt the root config.json. Two safeguards:
- **`save_config()`** pops `_base_config` and restores base values before writing
- **`update_active_profile()`** strips the old overlay (restores from `_base_config`) before applying the new profile's overlay

**Past bug**: `save_config` didn't restore base values → creating a profile with Opus 4.6 made ALL profiles show Opus 4.6 in the root config. Fixed by adding `_base_config` snapshot/restore.

### Profile switching (`reinit_system`)

1. Close existing graph DB connection (`manager.background_queue.graph_db.conn.close()`)
2. `update_active_profile()` — strips old overlay, sets new profile, re-resolves paths, applies new overlay
3. `save_config()` — persists `active_profile` change (with base values restored)
4. `_build_system()` — rebuilds Database, EmbeddingGenerator, GraphDatabase, ConversationManager, FileStorage

**What can go wrong**: if `_build_system` fails mid-way (e.g. schema mismatch in new DB), the config has already been saved pointing to the new profile. Next server restart will hit the same error. Fix: ensure `graph_schema.sql` has all columns the code queries, and `_migrate_schema()` adds missing columns to existing databases.

### Per-profile system instructions

`prompt_builder.py` checks `data/{profile}/system_instructions.txt` first, falls back to global `system_instructions.txt`. Created automatically from `system_instructions.example.txt` during profile creation.

### Frontend three-screen navigation

Starting screen (new profile creation) ↔ Profile selector (list + switch) ↔ Chat view. Back button from chat → profile selector. "New instance" → starting screen. Profile creation flow: model pick → typewriter headline → name input → loading animation → chat view.

---

## Abandoned: Graph Relationship Extraction

**Files**: `background.py` (`_process_graph_batch`), `graph_extraction.py`, `graph_database.py` (`relations` table), `config.example.json` (`phase5_graph.auto_extract`)

### What was abandoned and why

Phase 5 built a knowledge graph of entity *relationships* extracted from messages via Haiku ("Alice relates to anxiety", "Mneme relates to memory systems"). The extraction ran but produced shallow, low-signal output — the AI got "X is related to Y" with no further substance useful for retrieval or context. The feature was abandoned before it was ever wired into the live pipeline.

**What was kept**: entities themselves (names, aliases, mention counts) and the `message_entities` junction table. These power entity summaries (Phase 8), which *are* active and valuable. The `relations` table exists in the schema but is empty in practice.

### Dead code left in place

- `background.py`: `_process_graph_batch()`, `graph_enabled`, `graph_auto_extract`, `graph_batches_processed`/`graph_relationships_extracted`/`graph_new_entities_found` stats — all defined but never called from `add_message()`
- `config.example.json`: `phase5_graph.auto_extract` key
- `graph_extraction.py`: relationship extraction logic, unused in live pipeline
- `graph_database.py`: `add_relation()`, `get_relations()` — unused in live pipeline

None of this causes errors — it's inert. But don't spend time debugging why graph relationship stats are always 0.

### If redesigning

Start from scratch. The entity summary approach (aggregate AI-written summaries per entity, updated on tier transition) proved far more useful than relationship edges. Any new graph layer should be designed around what context it actually adds to retrieval, not just what's extractable.
