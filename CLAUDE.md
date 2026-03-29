# CLAUDE.md — Mneme Developer Guide

**Version**: 14.0.0 | **Updated**: March 2026

Mneme is a local-first AI memory system. All data stays on-device in SQLite. It gives AI assistants long-term context across conversations via semantic search, narrative concepts, entity summaries, daily timeline awareness, and a persistent notes layer.

---

## Directory Map

```
Mneme/
├── src/backend/        ← Python backend (Flask + AI logic)
├── src/frontend/       ← Vanilla JS/CSS/HTML frontend
├── scripts/            ← Utilities, migrations, backfills
├── data/               ← SQLite databases, TTS cache (gitignored)
├── docs/               ← ROADMAP, design docs, user guides
├── config.json         ← Active config (gitignored)
└── config.example.json ← Config template with all options and comments
```

---

## Architecture at a Glance

```
Browser (app.js)
    │ HTTP + Server-Sent Events
    ▼
Flask Server (server.py)
    │
    ▼
ConversationManager (conversation.py) ◄── Main orchestrator
    ├── ContextAssembler   ← Retrieves memories, concepts, summaries, notes, timeline
    ├── PromptBuilder      ← Constructs cached prompt structure
    ├── AIClient           ← Anthropic API wrapper (streaming + extended thinking)
    ├── InstanceExecutor   ← Handles @commands from AI responses
    ├── TierManager        ← Memory tier transitions
    ├── ProvenanceLogger   ← Logs what context was surfaced each turn
    └── BackgroundQueue    ← Async embeddings/entity assignment
```

---

## Phase History

| Phase | Feature | Key files |
|-------|---------|-----------|
| 1–2 | Core DB, embeddings, semantic search | `database.py`, `embeddings.py`, `retrieval.py` |
| 3 | Command system, web UI, interaction loop | `commands.py`, `instance_executor.py` |
| 4 | Prompt caching, streaming, error handling | `prompt_cache.py`, `prompt_builder.py`, `ai_client.py` |
| 5 | Graph system (relationships abandoned; entity infrastructure in `graph_database.py` is actively used) | `graph_database.py` |
| 6 | Narrative concepts (keyword-triggered) | `commands.py` (`@concept`), `context.py` |
| 7 | File attachments (images, PDF, text, JSON) | `file_processor.py`, `file_storage.py` |
| 8 | Entity summaries (hierarchical context) | `entity_summaries.py`, `entity_assignment.py` |
| 9a | Text-to-speech (ElevenLabs) | `server.py` |
| 9b | Timeline awareness (7-day daily summaries) | `daily_summaries.py` |
| 10 | Extended thinking (chain-of-thought) | `ai_client.py`, `conversation.py` |
| 11 | AI Notes (persistent, AI-managed sections) | `context.py`, `database.py` |
| 12 | Artifact storage (filesystem, @artifact command) | `artifact_storage.py`, `instance_executor.py` |
| 13 | Code execution (@run, read-only Python subprocess) | `commands.py`, `instance_executor.py` |
| 14 | Profile system (multi-instance, per-profile config) | `config.py`, `server.py`, `app.js` |

The command continuation flow (Phase 3), caching structure (Phase 4), and profile config overlay (Phase 14) are the trickiest parts architecturally.

---

## Quick Start

```bash
python scripts/verify_setup.py    # Check setup
python scripts/chat.py             # CLI chat (quick testing)
python src/backend/server.py       # Web server → http://localhost:8080
sqlite3 data/main/memory.db        # Inspect database
```

---

## Backlog

Feature backlog and UI polish queue: `docs/TODO_SOMEDAY.md` (gitignored — private).
Code quality issues and known minor bugs live in the relevant sub-guide under **§ Known Issues — Fix When Touching Nearby Code**.

---

## Agent usage

Solo dev project. Prefer direct file reading (Read, Grep, Glob) over spawning Explore or Plan agents. Only use agents when the task genuinely requires broad multi-area exploration that can't be done with a few targeted reads. Never spawn agents just because a workflow skill or plan mode instructs it by default.

---

## Repositories

Changes are committed to **two remotes**:

- **Personal repo** (`origin`, current): commit here always. `git push origin MNEME-MAIN`
- **Production repo** (`Mneme-memory/MNEME-BETA`): push periodically when a meaningful set of changes is ready. **Never** use `git push production` directly — always use the script: `bash scripts/push-production.sh`. The script creates a clean orphan commit (no personal history), verifies no sensitive files are staged, and force-pushes safely. Optional custom message: `bash scripts/push-production.sh "v14.1.0 — description"`

---

## System Instructions

Both `system_instructions.txt` (live prompt) and `system_instructions.example.txt` (template for new users) can be edited. Keep them in sync when adding new commands or features.

---

## Detailed Documentation

**Before working on any area, read the relevant sub-guide:**

| Working on... | Read this first |
|---------------|----------------|
| Backend Python files (`src/backend/`) | `src/backend/CLAUDE.md` |
| Frontend JS/CSS/HTML (`src/frontend/`) | `src/frontend/CLAUDE.md` |
| Scripts (`scripts/`) | `scripts/CLAUDE.md` |
| Config options | `config.example.json` |
| Database schema | `src/backend/schema.py` |
| Cross-cutting flows & gotchas | `docs/developer/SKILL_TREE.md` |
| Changelog | `docs/developer/CHANGELOG.md` |
| Roadmap | `docs/ROADMAP.md` |
