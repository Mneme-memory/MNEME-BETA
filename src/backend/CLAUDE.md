# Backend — Developer Notes

## Request Flow: User Message → Response

1. User message arrives at `/api/chat/stream`
2. `ConversationManager` stores message, retrieves relevant memories via semantic search
3. `ContextAssembler` assembles: memories → entity summaries → concepts → notes → timeline
4. `PromptBuilder` constructs prompt with cached (static) and uncached (dynamic) sections
5. `AIClient` calls Anthropic API (streaming or non-streaming, with optional extended thinking)
6. `InstanceExecutor` checks response for @commands
7. If retrieval command found → execute, inject results, call AI again (continuation)
8. Response streams back via SSE
9. Background queue: generate embeddings, assign entities, update summaries on tier transition
10. `ProvenanceLogger` records what memories/concepts/summaries were surfaced this turn

---

## File Reference: What to Modify

| Task | File(s) |
|------|---------|
| API endpoints | `server.py` |
| Profile management (create, switch, list) | `server.py`, `config.py` |
| Per-profile config overlay | `config.py` (`load_profile_config`, `update_active_profile`) |
| Main orchestration loop | `conversation.py` |
| AI command execution (@commands from AI) | `instance_executor.py` |
| User command execution (@commands from user) | `commands.py` |
| Context assembly (memories, concepts, notes, timeline) | `context.py` |
| Prompt construction and caching structure | `prompt_builder.py` |
| Caching decisions (TTL, gap detection) | `prompt_cache.py` |
| Anthropic API calls (streaming, thinking) | `ai_client.py` |
| Memory tier transitions | `tier_manager.py` |
| Memory retrieval scoring | `retrieval.py` |
| Background processing (embeddings, entity assignment) | `background.py` |
| OpenAI embeddings | `embeddings.py` |
| Entity summary generation (Phase 8) | `entity_summaries.py` |
| Entity assignment to messages | `entity_assignment.py` |
| Graph DB (entities used for summaries only) | `graph_database.py` |
| File attachments (Phase 7) | `file_processor.py`, `file_storage.py` |
| Artifact storage (filesystem, @artifact) | `artifact_storage.py` |
| Code execution (@run, read-only subprocess) | `commands.py` (`cmd_run`) |
| Daily timeline summaries (Phase 9b) | `daily_summaries.py` |
| Provenance tracking | `provenance.py` |
| Error handling and retry logic | `error_handling.py` |
| Database CRUD operations | `database.py` |
| Database schema | `schema.py` |
| System prompt (no code change needed) | `system_instructions.txt` |
| CLI interface | `cli.py` |

---

## Critical: Command System

Commands can come from the user OR from the AI's own response.

### Command Types

**Non-retrieval** (execute immediately, no continuation):
- `@remember` / `@remember self` — Mark messages as important
- `@forget {topic}` — Archive memories
- `@note {section}` / `@endnote` — Create/update persistent note section
- `@config` — Adjust settings

**Retrieval** (execute, then call AI again with results):
- `@recall {topic}` — Semantic search
- `@recall --deep {topic}` — Search deep archive (6+ months)
- `@concept list/view` — Show narrative concepts

### The Continuation Flow (CRITICAL)

```
AI Response: "Let me check that.\n@recall memory systems"
    │
    ▼
InstanceExecutor parses and executes ALL commands first
    │
    ▼
Builds continuation prompt:
    "Let me check that.

    [Command Result: @recall memory systems]
    Memory 1: ...

    IMPORTANT: Continue naturally from your previous message."
    │
    ▼
Calls AI AGAIN with full context preserved (cache-safe)
    │
    ▼
AI continues: "Found it! We discussed..."
```

### Past Bugs (Don't Reintroduce)

**Multi-command execution**: OLD code returned early on first retrieval command, skipping remaining commands. FIX: Execute ALL commands first, THEN handle retrieval continuation.

**Cache breaking in continuations**: OLD code used `_call_ai(prompt=continuation_prompt)` which broke the cache. FIX: Use `_call_ai(context=context, current_input=continuation_prompt)` to preserve cached sections.

**Double-printing**: Intermediate responses were printed twice. The deduplication logic in `app.js` handles this, but be careful when modifying response flow.

---

## Memory Tiers

- **Active**: Recent context (~75k tokens), always in prompt
- **Standard**: Older messages, searchable via semantic retrieval
- **Deep Archive**: 6+ months old, low importance, requires `--deep` flag

Transitions happen automatically when active window exceeds budget or on conversation gaps. Tier transitions trigger entity summary updates — if modifying `tier_manager.py`, ensure that hook still fires.

---

## Prompt Caching

**CACHED** (static across turns — system instructions + conversation history):
- System instructions
- Timeline (daily summaries — changes once per day, so cacheable)
- Conversation history

**UNCACHED** (changes every turn):
- Retrieved memories
- Entity summaries
- Concepts
- AI Notes
- File attachments
- Current user input

Gap detection: If >60 minutes since last message, skip caching (cache likely expired).

---

## Configuration Keys

Config lives in `config.json` (gitignored). All options are in `config.example.json` with inline comments. Per-profile overrides live in `data/{profile}/config.json` — only profile-scoped keys (`identity`, `model`, `thinking`, `context`, `features`) are merged; everything else stays global.

| Section | Controls |
|---------|----------|
| `api_keys` | API keys (anthropic, openai, elevenlabs) |
| `storage` | Database profile and paths |
| `identity` | User name, instance name |
| `model` | Model selection, temperature, max_tokens, streaming |
| `thinking` | Extended thinking budget and display |
| `context` | Recent message and memory token budgets |
| `retrieval` | Embeddings, search weights, thresholds, archive age |
| `caching` | Prompt cache enable/disable, TTL, rebalancing |
| `features.concepts` | Narrative concept settings |
| `features.attachments` | File attachment settings |
| `features.entity_summaries` | Entity extraction + summary settings |
| `features.tts` | Text-to-speech (ElevenLabs) |
| `features.timeline` | Daily summary / timeline settings |
| `features.notes` | AI Notes token budget and cleanup |
| `commands` | Max iterations, instance autonomy |
| `costs` | Budget tracking |
| `system` | Log level, backups, timezone, server port |

---

## Database Tables

Schema in `schema.py`. Key tables:

| Table | Purpose |
|-------|---------|
| `messages` | Core conversation storage |
| `embeddings` | OpenAI vectors (1536 dimensions) |
| `entities` | Entity store (names, aliases, mention tracking) |
| `concepts` | Narrative layer |
| `message_entities` | Links messages to entities |
| `entity_summaries` | Hierarchical entity context (monthly + all-time) |
| `daily_summaries` | 7-day rolling timeline summaries |
| `notes` | AI-managed persistent notes |
| `turn_log`, `retrieval_log`, etc. | Provenance tracking |

All queries use parameterized statements.

---

## Common Gotchas

1. **Commands must be at line start** — `@recall` works, `Maybe @recall` doesn't

2. **Check for string errors before dict access**:
   ```python
   result = handler.handle_command(cmd)
   if isinstance(result, str):  # Error case
       continue
   if result.get("success"):  # Safe now
   ```

3. **Streaming vs non-streaming paths**: Many methods have both variants. Changes often need to be made in both.

4. **Metadata is JSON**: Always `json.loads()` / `json.dumps()` when reading/writing message metadata.

5. **Context limits**: Active window ~50k tokens (configurable). Retrieved memories, entities, concepts, and files are count-limited (not token-budgeted). Notes ~5k tokens, timeline ~2.8k tokens.

6. **Background processing is async**: Embeddings and entity assignment happen after response. Don't expect them immediately.

7. **Profile config overlay**: In-memory `config` has profile overrides applied. `save_config()` restores base values via `_base_config` snapshot before writing to prevent overlay leakage into root config.json. When switching profiles, `update_active_profile()` strips the old overlay before applying the new one. Don't bypass these — writing `config` directly to disk will corrupt the root config.

---

## Quick Checklist

Before modifying code:
- [ ] Read the relevant file(s) first
- [ ] Check if change affects both streaming and non-streaming paths
- [ ] Check if change affects caching (cached vs uncached sections)
- [ ] Check if change affects command continuation flow
- [ ] Test with `python scripts/chat.py` before committing

---

## Known Issues — Fix When Touching Nearby Code

No need to fix proactively — address when already in the area.

**server.py**
- Thumbnail served with original file's mimetype, not actual thumbnail format
- `filter_output` emoji detection: `ord > 127` matches all non-ASCII, not just emoji

**retrieval.py**
- `cosine_similarity` clamped to [0,1], loses negative signal (deliberate design choice?)

**embeddings.py**
- `generate_embeddings_batch` has no `@retry_with_backoff` unlike the single version

**artifact_storage.py**
- YAML frontmatter title/summary not escaped for quotes

**instance_executor.py**
- `_print_result` and `_format_result_notification` are near-identical (~100 lines duplication)
- Non-streaming `execute_loop` never called from `conversation.py` (may be intentional fallback)

**database.py**
- N+1 pattern in `cleanup_orphan_messages` (one query per delete)

**database_concepts.py, database_embeddings.py**
- f-string LIMIT interpolation (should be parameterized)

**schema.py**
- `tiers` table populated on creation but never queried
- `importance_scores` table is write-only (audit trail never read)

**database_timeline.py**
- `INSERT OR REPLACE` changes rowid on notes (subtle footgun if notes ever referenced by ID)

**graph_database.py**
- `get_entity_by_alias` does full table scan
- `check_same_thread=False` shared connection, no write serialization

**graph_extraction.py**
- Creates new Anthropic client per call instead of reusing

**entity_summaries.py**
- Confusing merge of all_time into monthly list then immediate filter-out

**daily_summaries.py**
- `generate_summary()` temporarily mutates `ai_client.model` directly — not thread-safe if another thread uses the same client concurrently. Fix: add optional `model` parameter to `AIClient.call()`.

**context.py**
- Same "trim items until under token budget" loop in `_get_concept_context`, `_get_files_context`, `_get_notes_context`. A `_trim_to_budget(items, rebuild_fn, budget)` helper saves ~3-5 lines per site — only worth doing if a clean signature emerges naturally.

**Dead database functions** — defined but never called externally, safe to remove when touching these files:

| Function | File |
|----------|------|
| `get_messages_by_date_range` | `database.py` |
| `vacuum_database` | `database.py` |
| `get_attachment` (by int ID) | `database_attachments.py` |
| `delete_attachment` | `database_attachments.py` |
| `get_attachment_stats` | `database_attachments.py` |
| `get_message_entity_stats` | `database_entities.py` |
| `get_entity_summary_stats` | `database_entities.py` |
| `get_unlinked_messages` | `database_entities.py` |
| `get_stale_summaries` | `database_entities.py` |
| `get_unfrozen_summaries` | `database_entities.py` |
| `get_messages_for_entity` | `database_entities.py` |
| `delete_daily_summary` | `database_timeline.py` |
| `get_messages_without_embeddings` | `database_embeddings.py` |
| `generate_embeddings_batch` | `embeddings.py` |
| `clear_queue` | `background.py` |

**Redundant indexes** — duplicate indexes already created by UNIQUE constraints:
- `idx_turn_log_turn_id` (turn_id is already UNIQUE)
- `idx_concept_name` (name is already UNIQUE)
- `idx_attachments_uuid` (uuid is already UNIQUE)
