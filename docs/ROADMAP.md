# Mneme Development Roadmap

**Current Status**: v15.1 public beta — Windows installer, command console, local embeddings, sandboxed `@run`
**Version**: 15.1.0 | **Updated**: July 2026

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
`@run` command — Python execution for AI self-directed introspection, now run in a Windows AppContainer sandbox (read-only repository/profile access, redacted credentials, disposable scratch storage, no network/registry/child processes, job-based time and memory limits, fail-closed startup). Database access via a read-only SQLite URI in `DB_PATH`.

### Phase 14: Profile System
Per-instance configuration, in-app profile selector UI, loading animation (canvas-based Mneme logo), settings page with live controls. Profile config overlay system (`data/{profile}/config.json`).

### v15: Windows Installer and Release Packaging
Inno Setup-based Windows installer, bundled setup flow, Tailscale prompt, release ZIP packaging, and production snapshot tooling for the public `Mneme-memory/MNEME-BETA` repo.

### v15.1: Command Console, Entity Merge, Design System
A command console for running queries and actions in place, entity merge for cleaning up duplicates, local embeddings as the default, durable stream reconnect, and a codified visual design system.

→ full release notes in the [CHANGELOG](developer/CHANGELOG.md).

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

## Committed: OpenAI Embedding Deprecation

Decided July 2026 (solo-maintainer simplification). Embeddings move to the bundled local model (bge-small-en-v1.5, on-device, no key required); chat continues to use the Anthropic API key.

- **Current release** — Local embeddings ship as the default. One-click "Migrate to new embeddings" (automatic DB backup first, verified completion, resumable). The OpenAI embedding path still works as a safety net for failed migrations.
- **A later release** — OpenAI embedding support removed entirely (`EmbeddingGenerator`, the setup-flow key requirement, the provider config branch). The migration machinery stays: late updaters get the same one-tap migration popup on first launch.

Rationale: one embedding provider means one similarity threshold, no dimension guards, no OpenAI key in the setup funnel, and less surface for a single maintainer.

---

## Future Directions

Possibilities, not commitments — roughly in the order they're likely to happen.

### Onboarding and First-Run Experience
- **Interactive onboarding** — a guided first conversation that teaches Mneme's mental model (system instructions, commands, where your data lives, what `@run` can and can't touch) instead of leaving its most important powers hidden. Lightweight, skippable, reopenable from Settings.
- **Import your history** — bring existing Claude/ChatGPT conversations in through the app itself (upload in the browser, not a CLI script), so Mneme remembers you from day one.

### Entity Quality
- **Entity consolidation** — AI-proposed merge/cleanup of duplicate and near-duplicate entities with a human approval queue, plus short generated descriptions so entities are self-explanatory.
- **Naming cleanup** — one consistent name for the entity/topic/concept triangle across UI and docs.

### Retrieval
- **Chunked retrieval** — split long memories into semantically coherent pieces at embed time so one rambling memory stops diluting relevance and hogging context budget.
- **Semantic artifact retrieval** — embed artifact summaries and retrieve saved files by relevance, while still keeping the most recent uploads available.
- **Intelligent context filtering** (experimental, opt-in) — a small-model scoring pass over retrieved memories before assembly.
- **Dedicated search UI** — a visual semantic/keyword search panel to browse memory directly, complementing `@recall`.

### Connectors and Integration
- **MCP / external tools** — let Mneme-powered assistants reach outward (web search first, then a broader connector story), and potentially expose Mneme itself as a memory tool for other AI systems.
- **`@run` extensions** — an explicit opt-in write-capable mode, and delegation of heavy analysis to a cheaper model.

### Reliability and Distribution
- **Auto-update checks** — in-app notice when a new release is out on GitHub, so installer users don't silently run old versions forever.
- **Artifact overwrite protection** — require viewing an existing artifact before it can be overwritten.
- **Linux/macOS support** — currently Windows-only (installer, tray, and the `@run` sandbox are all Windows-specific). Porting help is welcome.

---

## Design Principles

1. **Local-first** — All data stays on the user's machine
2. **Cost-optimized** — Adaptive caching, batch processing, local operations where possible
3. **Privacy-focused** — No cloud storage
4. **Additive** — Each phase extends without breaking existing functionality
5. **Production-ready** — Robust error handling, security hardening, graceful degradation
