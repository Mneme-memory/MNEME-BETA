# Mneme — AI Memory System

**Version 14.0.0 · Beta**

Mneme is a local-first memory system for Claude AI. All data stays on-device in SQLite. It gives AI long-term context across conversations via semantic search, narrative concepts, entity summaries, daily timeline awareness, and a persistent notes layer.

> **Not technical?** Upload [`GIVE-TO-CLAUDE-FOR-HELP.txt`](GIVE-TO-CLAUDE-FOR-HELP.txt) to [Claude](https://claude.ai) and it will walk you through setup step by step.

---

## Features

- **Semantic memory** — Retrieval scored on four configurable factors: semantic similarity, recency, importance, and entity/keyword match
- **Narrative concepts** — High-level interpretive meta-memories triggered by keyword matching
- **Entity summaries** — Hierarchical summaries providing historical context for people, places, and topics
- **Timeline awareness** — 7-day rolling daily summaries keep the AI grounded in recent events
- **AI Notes** — Persistent notes the AI can create and update across sessions
- **Artifact storage** — Save creative and technical work as markdown files on disk
- **Code execution** — AI can run read-only Python scripts to query its own database
- **Multi-profile** — Run multiple independent AI instances from one installation
- **Extended thinking** — Optional chain-of-thought reasoning for complex responses
- **Text-to-speech** — ElevenLabs integration with local audio cache
- **Prompt caching** — 50–70% API cost reduction via adaptive cache structure
- **Streaming UI** — Real-time Server-Sent Events with <500ms to first token
- **AI command system** — `@remember`, `@recall`, `@forget`, `@concept`, `@run`, and more
- **Local-first** — No cloud storage, no telemetry, no accounts. Your data never leaves your machine.

---

## Quick Start

### Prerequisites

- **Python 3.9+** — [Download](https://www.python.org/downloads/) (check "Add to PATH" during install)
- **Anthropic API key** — [Get one](https://console.anthropic.com/)
- **OpenAI API key** — [Get one](https://platform.openai.com/) (for embeddings)

### Install

**Windows:** Double-click `install-windows.bat`

**macOS / Linux:** Run `bash install-mac-linux.sh`

The installer handles dependencies, config files, and creates a launch shortcut.

### Launch

**Windows:** Double-click the "Launch Mneme" shortcut (on your desktop or in the project folder)

**macOS / Linux:** Launch from your application menu, or run `python3 scripts/tray.py`

Mneme starts in your system tray. The setup wizard opens in your browser on first launch — enter your API keys there, no config files to edit.

### Import Existing Conversations

Already have conversations in Claude or ChatGPT? You can import them:

1. Export your conversation as JSON (browser extensions can do this)
2. Run the import script:

```bash
python scripts/import_conversation.py your-export.json
```

The script auto-detects the format. Supported input structures:

```jsonc
// Simple array (recommended for manual exports):
[
  {"role": "user", "content": "Hello!", "timestamp": "2025-01-15T10:30:00Z"},
  {"role": "assistant", "content": "Hi there!", "timestamp": "2025-01-15T10:30:05Z"}
]

// Or wrapped: {"messages": [...]}
// Claude.ai export: {"chat_messages": [{"sender": "human", "text": "...", ...}]}
// ChatGPT export: {"mapping": {"id": {"message": {"author": {"role": "user"}, "content": {"parts": ["..."]}}}}}
```

The role field accepts `user`/`human` and `assistant`/`ai`/`bot`. Timestamps can be ISO 8601 strings or Unix timestamps. See `scripts/import_conversation.py` for full format details.

The script inserts your messages, then runs the full enrichment pipeline — embeddings, entity discovery, importance scoring, entity summaries, and daily summaries. It shows a cost estimate and asks for confirmation before the API-heavy steps.

For large conversations (1000+ messages), expect $2–5 in API costs and 15–60 minutes of processing time. You can interrupt and `--resume` at any time.

---

## Documentation

| Topic | File |
|-------|------|
| Architecture deep dive | [docs/developer/ARCHITECTURE.md](docs/developer/ARCHITECTURE.md) |
| Developer guide | [CLAUDE.md](CLAUDE.md) |
| Backend internals | [src/backend/CLAUDE.md](src/backend/CLAUDE.md) |
| Frontend internals | [src/frontend/CLAUDE.md](src/frontend/CLAUDE.md) |
| Database schema | [src/backend/schema.py](src/backend/schema.py) |
| Config options | [config.example.json](config.example.json) |
| User setup guide | [docs/user/SETUP_AND_USAGE.md](docs/user/SETUP_AND_USAGE.md) |
| Command reference | [docs/user/COMMAND_REFERENCE.md](docs/user/COMMAND_REFERENCE.md) |
| Changelog | [docs/developer/CHANGELOG.md](docs/developer/CHANGELOG.md) |
| Roadmap | [docs/ROADMAP.md](docs/ROADMAP.md) |

---

## System Requirements

- **Python** 3.9+
- **Anthropic API key** — AI conversation, entity summaries, and daily timelines
- **OpenAI API key** — Embeddings (`text-embedding-3-small`)
- **ElevenLabs API key** — Optional, for text-to-speech
- **Tailscale** — For mobile access (free, installer offers to set this up)
- **Storage** — 1GB+ free space recommended

---

## Cost Estimates

With adaptive prompt caching enabled:

| Usage level | Model | Est. monthly cost |
|-------------|-------|-------------------|
| Light (5–10 msgs/day) | Haiku | $3–8 |
| Moderate (20–40 msgs/day) | Sonnet | $30–60 |
| Heavy (60–80+ msgs/day) | Sonnet + thinking | $100–180 |

Costs depend heavily on model choice, context window size, and extended thinking budget. Prompt caching reduces input costs by 50–90% but output tokens (the expensive part on Sonnet) are unaffected. OpenAI embeddings add negligible cost (cents/month).

**Tuning costs**: The default config is set for moderate cost. To reduce costs, lower `context.recent_messages_tokens` (conversation history size), `retrieval.max_results` (memories per query), `thinking.budget_tokens` (reasoning depth), and `model.max_tokens` (output cap). To improve retrieval quality at higher cost, increase these values. Most of these are adjustable from the Settings page; for values not exposed there, edit `config.json` directly. See `config.example.json` for all options.

---

## Security & Privacy

- **100% local** — all data stored in SQLite on your device
- **No telemetry, no accounts, no cloud** — API keys go directly to Anthropic/OpenAI/ElevenLabs
- **Open source** — don't trust us, read the code
- API keys stored in gitignored `config.json`
- CORS restricted to localhost
- Input validation (50KB message limit)
- XSS protection on external links

---

## Troubleshooting

If the installer fails or you prefer manual setup:

```bash
pip install -r requirements.txt
cp config.example.json config.json       # then edit with your API keys
cp system_instructions.example.txt system_instructions.txt
python scripts/verify_setup.py           # check everything is in order
python src/backend/server.py             # start server → http://localhost:8080
```

---

## License

[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) — free to use and adapt with attribution.

If you build on this, a credit and link back to the original repo is appreciated.

---

## Roadmap

Mneme is in active development. Features currently in progress or planned:

- **Semantic artifact retrieval** — relevance-based retrieval over saved artifacts and attachments, replacing the current recency-only file block
- **Intelligent context filtering** — optional Haiku pass that scores retrieved memories for relevance before assembly, improving signal quality at the cost of added latency
- **Frontend artifact browser** — in-app UI for browsing and opening saved artifacts
- **Write-capable @run** — opt-in mode for AI-authored scripts that can modify data, not just read it

See [`docs/ROADMAP.md`](docs/ROADMAP.md) for the full picture.

---

## License

[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) — free to use and adapt with attribution.

If you build on this, a credit and link back to the original repo is appreciated.

---

**Last updated**: March 2026 (v14.0.0)
