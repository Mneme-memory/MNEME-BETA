# Mneme Development Roadmap

**Current Status**: Phase 14 Complete — **Alpha**
**Version**: 14.0.0 | **Updated**: March 2026

---

## Completed Phases

### Phases 1–4: Core System
- **Phase 1** — SQLite storage, message tiers, keyword search, CLI
- **Phase 2** — OpenAI embeddings, semantic search, importance scoring, time decay
- **Phase 3** — Web UI, @command system, streaming SSE, background processing
- **Phase 4** — Adaptive prompt caching (50–70% cost savings), compound DB indexes, error handling + retry

### Phase 5: Entity System (Graph Abandoned)
Entity extraction and canonical name management. The relationship graph was abandoned and will be reworked. Entities are now used as the basis for Phase 8 summaries. Note: `graph_database.py` is still actively used — the entity infrastructure is load-bearing; only the relationship extraction output is unused.

### Phase 6: Narrative Concepts
Keyword-triggered interpretive meta-memories. Zero API cost (local string matching). `@concept` CRUD commands.

### Phase 7: File Attachments
Images, PDFs, text files, JSON. Vision API for images. Stored in `data/{profile}/attachments/`. `@file` and `@describe` commands.

### Phase 8: Entity Summaries
On-demand hierarchical summaries (monthly frozen + all-time synthesis). Lazy generation ($0 for entities never retrieved). Triggered on tier transitions.

### Phases 9a/9b: TTS & Timeline
- **9a** — ElevenLabs TTS integration, streaming audio, local cache
- **9b** — 7-day rolling daily summaries, injected into prompt context

### Phase 10: Extended Thinking
Chain-of-thought reasoning via Claude's extended thinking API. Configurable budget. Collapsible thinking display in web UI.

### Phase 11: AI Notes
Persistent AI-managed note sections in SQLite. Survives tier transitions. `@note`/`@endnote` commands. Token-budgeted injection.

### Phase 12: Artifact Storage
Filesystem storage for creative and technical work. `@artifact`/`@endartifact` commands. Human-readable `ARTIFACT.md` files under `data/{profile}/artifacts/{category}/{slug}/`. No database tables.

### Phase 13: Code Execution
`@run` command — read-only Python subprocess for AI self-directed introspection. Sandboxed environment with access to the database via a read-only `db` helper.

### Phase 14: Profile System
Per-instance configuration, in-app profile selector UI, loading animation (canvas-based Mneme logo), settings page with live controls. Profile config overlay system (`data/{profile}/config.json`).

---

## Verified Metrics

| Metric | Value |
|--------|-------|
| Cache hit rate | 50–70% cost savings on active conversations |
| Cache growth | Linear (+300–400 tokens/turn) |
| Cost vs uncached | $26 vs $94 per 1000 messages (72% savings) |
| Streaming latency | <500ms to first token |
| DB query speed | 2–5x faster with compound indexes |

---

## Future Directions

Possibilities, not commitments.

### Retrieval Improvements
- **Dedicated search UI** — Semantic/keyword search panel replacing `@recall`/`@file search` for visual memory browsing; shows results as cards with relevance scores and timestamps
- Cross-conversation search (multiple profiles)
- Import from ChatGPT/Claude exports

### Graph Enhancements
- Visual graph explorer in the web UI
- Entity clustering and community detection
- Temporal relationship tracking

### Infrastructure
- MCP server exposing Mneme as a memory tool for other AI systems
- Docker containerization
- Automated test suite

---

## Design Principles

1. **Local-first** — All data stays on the user's machine
2. **Cost-optimized** — Adaptive caching, batch processing, local operations where possible
3. **Privacy-focused** — No cloud storage
4. **Additive** — Each phase extends without breaking existing functionality
5. **Production-ready** — Robust error handling, security hardening, graceful degradation
