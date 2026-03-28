# Mneme — Architecture Deep Dive

**Version**: 14.0.0 | For people building memory systems

This document covers the mechanics: how context is assembled, how retrieval scoring works, what happens in the background, and how caching interacts with all of it.

---

## Table of Contents

- [Per-turn flow](#per-turn-flow)
- [Memory tiers](#memory-tiers)
- [Context assembly — sequential, not parallel](#context-assembly--sequential-not-parallel)
- [Retrieval scoring formula](#retrieval-scoring-formula)
- [Entity summaries — the hybrid selection](#entity-summaries--the-hybrid-selection)
- [Narrative concepts — keyword layer](#narrative-concepts--keyword-layer)
- [Prompt caching structure](#prompt-caching-structure)
- [Background pipeline](#background-pipeline)
- [Command continuation flow](#command-continuation-flow)
- [Code execution (@run)](#code-execution-run)
- [Profile system](#profile-system)

---

## Per-turn flow

One complete message, start to finish:

```
User message arrives
    │
    ▼
1. Store user message in SQLite (immediately, before anything else)
    │
    ▼
2. Check day rollover (background thread — does not block)
   └── If new day: generate yesterday's daily summary via Haiku
    │
    ▼
3. Check for cold start (gap > 60 min since last message)
   └── If cold: rebalance memory tiers, rebuild prompt cache
    │
    ▼
4. Assemble context (sequential — see below)
    │
    ▼
5. Build prompt (cached + uncached sections)
    │
    ▼
6. Call Anthropic API (streaming)
    │
    ▼
7. Stream response to frontend via SSE
    │
    ▼
8. Parse AI response for @commands
   ├── Non-retrieval commands (@remember, @note, @forget, @artifact): execute inline
   └── Retrieval commands (@recall, @run, @file view): execute → inject results → call AI again
    │
    ▼
9. Store AI response in SQLite
    │
    ▼
10. Background queue (does not block the response):
    ├── generate_embedding(user_message)     ← OpenAI text-embedding-3-small
    ├── generate_embedding(assistant_message)
    └── assign_entities(batch)               ← Haiku with tool_use (guaranteed JSON)
```

Step 1 happens before any API call. If anything downstream fails, the user message is already in the database as an orphan. The cleanup system (`/api/messages/cleanup-orphans`) handles this on page load and on error.

---

## Memory tiers

Messages age through three tiers:

| Tier | Contents | How retrieved |
|------|----------|---------------|
| **Active** | Recent messages within ~75k token budget | Loaded verbatim into conversation history — always in context |
| **Standard** | Messages that have aged out of the active window | Semantic search only |
| **Deep archive** | Standard messages ≥6 months old, low importance | Semantic search with `@recall --deep` flag only |

Tier transitions happen on cold starts (conversation gap >60 minutes). When messages move from active to standard, entity summary generation is triggered for all entities linked to those messages.

The active window is conversation history the AI sees directly. Semantic retrieval is only run against standard tier — there's no point retrieving something already in the active window.

---

## Context assembly — sequential, not parallel

The infographic shows five context layers in parallel cards. In practice, assembly is sequential with a hard token budget waterfall. Each layer has a cap, and later layers only run if budget remains.

```
assemble_context(recent_messages, user_query)
    │
    ├─ 1. RECENT HISTORY         ~75,000 tokens (active tier, verbatim)
    │       Always included. This is the conversation window.
    │
    ├─ 2. SEMANTIC MEMORY        ~10,000 tokens budget
    │       Semantic search against standard tier only.
    │       Returns up to memory_limit results, deduplicated against
    │       active window and previously loaded memories this session.
    │       Referenced memories get an importance boost.
    │
    ├─ 3. ENTITY SUMMARIES       ~5,000 tokens budget
    │       Derived from step 2 — runs after retrieval, not independently.
    │       (See: Entity summaries section below)
    │
    ├─ 4. NARRATIVE CONCEPTS     ~500 tokens budget
    │       Keyword scan of last N messages (default: 5).
    │       Independent of retrieval results.
    │
    ├─ 5. AI NOTES               ~5,000 tokens budget
    │       All notes loaded verbatim from database.
    │       No filtering or ranking — all-or-nothing.
    │
    └─ 6. TIMELINE               ~2,800 tokens budget
            7-day daily summary block, loaded verbatim.
            Changes once per day. No filtering.
```

**The key structural point**: Entity summaries (step 3) are computed from the retrieved memories (step 2). They are not an independent retrieval — they are a secondary layer that enriches whatever semantic search found. If no memories are retrieved, no entity summaries appear.

**What goes in the cached vs uncached sections** is covered under [Prompt caching structure](#prompt-caching-structure).

---

## Retrieval scoring formula

`MemoryRetriever.semantic_search()` in `retrieval.py`:

```
Final_Score = (semantic_similarity × 0.4) + (importance_norm × 0.4) + (recency_norm × 0.2)
```

Each component:

**Semantic similarity** — cosine similarity between query embedding and message embedding (OpenAI `text-embedding-3-small`, 1536 dimensions). Threshold: 0.25 (configurable). Messages below threshold are dropped entirely.

**Importance (normalized)** — importance scores (1–10, assigned by Haiku at tagging time) are normalized relative to the *current candidate pool*, not against a fixed 0–10 scale. This prevents score collapse when most candidates cluster near the same importance (e.g. all at 10.0 in a small database).

**Recency** — a time-decay multiplier is computed per message and normalized to 0–1:

| Age | Multiplier |
|-----|-----------|
| 0–30 days | ×1.5 (recency bonus) |
| 31–90 days | ×1.2 |
| 91–180 days | ×1.0 (baseline) |
| 181–365 days | ×0.95 |
| >1 year | ×0.9 |
| High-importance (≥8) | never decays below 7.0 effective score |

After scoring, retrieved memories that appear in the active window or were already retrieved earlier this session are deduplicated and skipped. The dedup check is important — without it, the same memory can appear in both conversation history and the retrieved memories block, wasting context and confusing the model.

---

## Importance assignment

Every message starts with an importance score of **3.0** and is scored by Haiku in the same background call that assigns entities. Importance changes through four mechanisms:

**1. Haiku scoring — automatic baseline**

Every message batch processed by the entity assignment pipeline is also scored 1–9:
- 1–2: Greetings, small talk, acknowledgments
- 3–4: Casual conversation, everyday topics
- 5–6: Substantive discussion, meaningful ideas
- 7–8: Key insights, decisions, significant personal moments
- 9: Major breakthroughs, critical turning points

This runs in the background after each response. The 3.0 default is overwritten for every processed message.

**2. `@remember` — manual marking**

Either the user or the AI can mark a message via `@remember {id}`. The multiplier depends on who has marked it:

| Marked by | Multiplier |
|-----------|-----------|
| User only | ×2.0 |
| AI only | ×2.0 |
| Both | ×3.0 |

The multipliers stack correctly: marking a 3.0 message once gives 6.0; marking it again (by the other party) gives `3.0 × 3.0 = 9.0`, capped at 10.0.

**3. Retrieval boost — diminishing returns**

Every time a memory is included in retrieved context, its stored importance is boosted:

```
boost = 1.5 / (1 + log10(reference_count))
```

Progression: 1st retrieval +1.50, 2nd +1.16, 3rd +1.01, 5th +0.88. Memories that keep proving useful stay surfaced; rarely-retrieved ones don't inflate.

**4. Daily decay — exponential toward floor**

Once per calendar day, all messages above the floor are decayed:

```
new = 3.0 + (current - 3.0) × 0.995^days_elapsed
```

Floor: 3.0 (new-message default — never decays below it). Rate: 0.995/day.

Practical effect:
- Message at 10.0, never retrieved: ~4.1 after 1 year
- Message at 10.0, retrieved monthly: ~9.0 after 1 year

The retrieval boost deliberately counteracts decay for memories that stay relevant. Messages the AI stops surfacing gradually return toward the baseline floor.

**5. Retrieval scoring modifier (not stored)**

During retrieval, the recency time-decay table (×0.9–×1.5) adjusts effective importance for ranking purposes only. It does not write back to the database. High-importance messages (≥8.0) are additionally protected: their effective score in the ranking formula never falls below 7.0 regardless of age.

---

## Entity summaries — the hybrid selection

Entity summaries give the AI historical depth about a person or topic without loading every message that mentions them. Instead of "here are 300 messages that mention Alice", the model sees "here is a monthly synthesis of Alice-related messages, updated as they age out of the active window."

**Selection happens in two stages:**

**Stage 1 — String matching on the current query.**
All entity names and aliases are checked against the user's current message using substring matching. This catches proper nouns that embed poorly. A message like "what did we say about Alice?" will surface Alice's summary even if Alice wasn't in the top semantic matches. Matched entities get a boosted baseline score of 1.5 (vs 0.0 for unmatched).

**Stage 2 — Entity links from retrieved memories.**
Each retrieved memory has entity links (assigned by Haiku during background processing). All linked entities are collected and their scores are accumulated: `avg_confidence × log(link_count + 1) × recency_factor × memory_count`.

Both stages feed the same scoring pool. The top N entities (default: 3, configurable) within the token budget are selected.

**Lazy generation**: summaries are only generated the first time an entity is retrieved. Entities the user never asks about cost nothing.

**Summary structure**: monthly snapshots (frozen at month-end, never regenerated) + an all-time synthesis. When messages age from active to standard tier, incremental updates are applied. After 10 incremental updates, a full regeneration runs to prevent drift.

---

## Narrative concepts — keyword layer

Concepts are AI-created meta-memories: named patterns with a definition and a list of trigger keywords. Examples: a concept called `learned_helplessness` with keywords `["can't", "pointless", "won't work", "tried before"]`.

**Retrieval**: pure local string matching against the last N messages (default: 5). No embeddings, no API calls. The combined text of the window is scanned for each concept's keyword list. Concepts are ranked by match count and the top results are injected (up to the token budget).

This layer is intentionally cheap — it adds interpretive context without any API cost. The tradeoff is lower precision than semantic search: a concept triggers whenever its keywords appear, regardless of context.

Concepts are created autonomously by the AI via `@concept create` during conversation, or manually via the command interface.

---

## Prompt caching structure

Anthropic's prompt caching caches blocks marked with `cache_control: {"type": "ephemeral"}` for up to 1 hour (TTL resets on use). The prompt is divided into cached and uncached sections to maximize hit rate.

**CACHED** (stable across turns):

| Block | Rationale |
|-------|-----------|
| System instructions | Never changes mid-conversation |
| Timeline (daily summaries) | Changes once per day — cacheable for the full day |
| Conversation history | Grows by one turn per message; older turns stay cached |

**UNCACHED** (changes every turn):

| Block | Rationale |
|-------|-----------|
| Retrieved memories | Semantic search result differs every turn |
| Entity summaries | Selected based on current retrieval results |
| Narrative concepts | Keyword-triggered — changes with topic |
| AI Notes | Can be modified by `@note` command |
| File attachments | Per-message |
| Current user input | Always new |

**Gap detection**: if >60 minutes have elapsed since the last message, the cache has expired. The system rebuilds from scratch rather than attempting to use a dead cache.

**Typical savings**: 50–70% reduction in input token costs vs uncached.

The distinction between cached/uncached sections matters architecturally. Timeline goes in the cached block because it's stable; retrieved memories cannot go there because they change every turn. Putting dynamic content in the cached section would break the cache on every message and provide zero savings.

---

## Background pipeline

After every AI response, a background queue processes work that doesn't need to block the response:

```
Response finalized
    │
    ├── generate_embedding(user_message)      ← OpenAI API
    ├── generate_embedding(assistant_message) ← OpenAI API
    └── assign_entities(batch of 30 messages) ← Haiku (tool_use, guaranteed JSON)
         ├── Assigns existing entities to messages
         └── Proposes new entities for discovery
```

Entity assignment uses Anthropic tool use with `tool_choice` to guarantee valid JSON at the token level (raw JSON string output from Haiku was malformed ~5% of the time). Batch size is 30 messages — larger batches (tested up to 170k tokens) caused Haiku attention degradation with near-zero entity link rates.

**On tier transition (active → standard)**: when messages age out of the active window, entity summary generation fires for all entities linked to those messages. This runs in a background thread to avoid blocking the first message after a long gap.

Embeddings and entity links are not available immediately after a message is stored. Any code that reads from `embeddings` or `message_entities` right after a message is saved will see stale results.

---

## Command continuation flow

When the AI's response contains a retrieval command (`@recall`, `@run`, `@file view`), the system executes the command and calls the AI again with the results. This is the "continuation" pattern.

```
AI response: "Let me check that.\n@recall memory systems"
    │
    ▼
InstanceExecutor parses ALL commands first (non-retrieval run inline)
    │
    ▼
Retrieval command executed → results collected
    │
    ▼
Continuation prompt built:
    "Let me check that.

    [Command Result: @recall memory systems]
    Memory 1: ...
    Memory 2: ...

    IMPORTANT: Continue naturally from your previous message."
    │
    ▼
_call_ai(context=context, current_input=continuation_prompt)
    └── context= preserves the cached sections (system + history)
    └── current_input= goes into uncached section only
    │
    ▼
AI continues: "Found it — we discussed..."
```

The continuation call must use the structured `context=` form, not a flat `prompt=` string. Passing a flat string discards the cached sections and breaks the cache for that turn.

Multiple retrieval commands in one response are all executed before any continuation fires. The continuation receives all results combined.

---

## Code execution (@run)

The AI can execute read-only Python code via `@run...@endrun` blocks. This is a retrieval command — results trigger a continuation.

```
AI response: "Let me check the database.\n@run\nimport sqlite3, os\n...\n@endrun"
    │
    ▼
InstanceExecutor extracts @run block in pre-pass (same as @note/@artifact)
    │
    ▼
cmd_run() writes code to temp file, runs in subprocess with env vars:
    - DB_PATH (read-only SQLite URI)
    - DB_FILE, ARTIFACTS_PATH, ATTACHMENTS_PATH, SRC_PATH
    │
    ▼
stdout/stderr captured → returned as retrieval result → continuation
    │
    ▼
@run...@endrun block stripped from stored response (replaced with [ran python])
```

The subprocess enforces read-only database access at the SQLite engine level via `?mode=ro` URI. 10-second timeout, 4000-char output truncation. Auto-retry on transient failures (OneDrive file locks).

Code blocks are stripped from the stored response before it enters the prompt cache, keeping cached content lean.

---

## Profile system

Mneme supports multiple AI instances, each with its own database, conversation history, and configuration overlay.

**Config overlay**: each profile can have a `data/{profile}/config.json` with overrides for profile-scoped keys (`identity`, `model`, `thinking`, `context`, `features`). Global keys (API keys, storage, system) are never overridden. On load, `load_profile_config()` snapshots base values into `config["_base_config"]`, then deep-merges profile overrides.

**Profile switching**: `reinit_system()` in `server.py` closes the current graph DB, strips the old overlay, applies the new profile's overlay, saves the config, and rebuilds all system components (Database, EmbeddingGenerator, GraphDatabase, ConversationManager, FileStorage).

**Per-profile system instructions**: `prompt_builder.py` checks `data/{profile}/system_instructions.txt` first, falls back to global `system_instructions.txt`.

**Frontend**: three-screen navigation — starting screen (new profile) ↔ profile selector (list + switch) ↔ chat view. Profile creation flow: model pick → typewriter headline → name input → loading animation → chat view.

---

## Source file map

| Area | File |
|------|------|
| Turn orchestration | `src/backend/conversation.py` |
| Context assembly | `src/backend/context.py` |
| Retrieval scoring | `src/backend/retrieval.py` |
| Entity summaries (generation) | `src/backend/entity_summaries.py` |
| Entity assignment (background) | `src/backend/entity_assignment.py` |
| Narrative concepts | `src/backend/commands.py` (`@concept`) |
| Daily summaries / timeline | `src/backend/daily_summaries.py` |
| AI Notes | `src/backend/context.py` (`_get_notes_context`) |
| Prompt caching | `src/backend/prompt_builder.py`, `prompt_cache.py` |
| Command execution | `src/backend/instance_executor.py` |
| Code execution (@run) | `src/backend/commands.py` (`cmd_run`) |
| Artifact storage | `src/backend/artifact_storage.py` |
| Memory tier transitions | `src/backend/tier_manager.py` |
| Background processing | `src/backend/background.py` |
| Profile config overlay | `src/backend/config.py` |
| Database schema | `src/backend/schema.py` |

Cross-cutting flows (SSE protocol, interruption handling, past bugs): [`SKILL_TREE.md`](SKILL_TREE.md)
