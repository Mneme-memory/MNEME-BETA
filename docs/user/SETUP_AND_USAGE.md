# Mneme Setup and Usage Guide

**v15.1.0** — Updated July 2026

---

## Table of Contents

1. [What You'll Need](#what-youll-need)
2. [Installation](#installation)
3. [Configuration](#configuration)
4. [Starting Mneme](#starting-mneme)
5. [Using the Web Interface](#using-the-web-interface)
6. [Command Reference](#command-reference)
7. [Troubleshooting](#troubleshooting)
8. [Profiles](#profiles)

---

## What You'll Need

### Required

- **Computer**: Windows 10/11 tested. Android browser access is tested over the local server. iPhone should most likely work as a browser client, but is untested.
- **Python**: Version 3.9 or higher (Windows: installed automatically by `Mneme-Setup.exe`)
- **Storage**: At least 1GB free space
- **Anthropic API Key**: For AI chat ([get here](https://console.anthropic.com/))

Semantic search runs on a bundled local model (BAAI/bge-small-en-v1.5, via ONNX) — it downloads automatically (~33MB) on first use and needs no account or key. This is the default for new installs.

If you're using Claude Fable, your Anthropic API tier needs Fable access and 30-day data retention enabled; organizations on zero-data-retention terms will get a 400 error from the API when Fable is selected.

### Optional

- **ElevenLabs API Key**: For text-to-speech
- **Tailscale**: For secure mobile access (free)

---

## Installation

### Option A: Run the Installer (Recommended)

**Windows:** Download `Mneme-release.zip` from the [Releases page](https://github.com/Mneme-memory/MNEME-BETA/releases/latest), extract it somewhere permanent, and double-click `Mneme-Setup.exe` inside the extracted folder. The installer must be run from inside the Mneme folder — it uses its own location to find the app files.

Windows may show a "Windows protected your PC" warning because Mneme is not code-signed with a paid publisher certificate. Click **More info** (or **Read more**) and then **Run anyway**. This warning is Windows saying the publisher is unknown, not that it detected malware.

**Linux / macOS:** Not currently supported — the installer, tray integration, and the code-execution sandbox are Windows-specific. Treat any attempt to run Mneme there as porting work.

The installer handles everything: Python installation if needed, dependencies, config file creation, and shortcut setup. It also offers to install Tailscale for mobile access.

### Option B: Manual Setup

#### Step 1: Install Python

1. Download Python 3.11+ from https://www.python.org/downloads/
2. Run installer
3. **CRITICAL**: Check "Add Python to PATH"
4. Click "Install Now"

#### Step 2: Get Mneme

Download `Mneme-release.zip` from the [Releases page](https://github.com/Mneme-memory/MNEME-BETA/releases/latest) and extract it, or clone:

```bash
git clone https://github.com/Mneme-memory/MNEME-BETA.git
cd MNEME-BETA
```

#### Step 3: Install Dependencies

```cmd
pip install -r requirements.txt
```

#### Step 4: Create Config Files

```powershell
$mnemeDataHome = Join-Path $env:LOCALAPPDATA "Mneme"
New-Item -ItemType Directory -Force $mnemeDataHome
Copy-Item .\config.example.json "$mnemeDataHome\config.json"
Copy-Item .\system_instructions.example.txt "$mnemeDataHome\system_instructions.txt"
```

#### Step 5: Verify Setup

```bash
python scripts/verify_setup.py
```

All checks should pass with checkmarks.

---

## Importing Existing Conversations

If you have existing conversations in Claude or ChatGPT, you can import them so Mneme remembers your history from day one.

1. Export your conversation as a JSON file (browser extensions can do this)
2. Run the import script:

```bash
python scripts/import_conversation.py your-export.json
```

The script auto-detects the format (Claude.ai, ChatGPT, or generic JSON), inserts all messages, and then offers to run the full enrichment pipeline — embeddings, entity assignment, importance scoring, entity summaries, and daily summaries.

**Cost warning:** Enrichment uses API calls. For 1000 messages, expect ~$2–5 in costs and 15–60 minutes. The script shows an estimate and asks for confirmation. You can interrupt with Ctrl+C and `--resume` later.

**Options:**
- `--dry-run` — Parse and show stats without importing
- `--skip-enrichment` — Insert messages only (free, instant)
- `--resume` — Skip insertion, run enrichment on existing unprocessed messages
- `--profile NAME` — Import into a specific profile

**What's not backfilled:** Narrative concepts and AI Notes are created organically during live conversation — they'll build up naturally as you continue chatting.

---

## Configuration

### Setup Wizard (First Launch)

On first launch, Mneme opens a setup wizard in the browser. Choose **Start fresh** to walk through:
- Entering your API key(s) (Anthropic, optionally ElevenLabs)
- Setting your name
- Choosing a model and naming your AI instance

No need to manually edit config files — the wizard handles everything. New installs use the bundled local embedding model by default, so there's no OpenAI key to enter.

If you already have an older Mneme install, choose **Import from a previous Mneme** instead. Select the old app folder (the one containing `config.json` and `data`); Mneme copies and verifies every profile into `%LOCALAPPDATA%\Mneme` and leaves the old install untouched. See [UPDATING.md](UPDATING.md) for the complete upgrade walkthrough.

### Manual Configuration

If you prefer, edit `%LOCALAPPDATA%\Mneme\config.json` directly (never share or commit this file — it contains API keys):

```json
{
  "api_keys": {
    "anthropic": "sk-ant-api03-..."
  }
}
```

See `config.example.json` for all options with inline comments, including `retrieval.embedding_provider` (`"local"` by default — no key needed; `"openai"` if you're keeping the legacy path for now).

Key sections: `api_keys`, `storage`, `identity`, `model`, `thinking`, `context`, `retrieval`, `caching`, `features`, `commands`, `costs`, `system`.

### Editing System Instructions

You can edit your AI's system instructions directly in the app now: **Settings → Profile settings → System instructions**. It's per-profile, changes take effect on your next message (no restart needed), and there's a "Reset to template" button if you want to start over. Hand-editing `%LOCALAPPDATA%\Mneme\data\{profile}\system_instructions.txt` still works too, if you'd rather work in a text editor.

The Settings page also has a **Conversation window** control — how much recent chat history gets kept in context. Models that support very large context (1M tokens) show extra options here; other models are capped at 200k. Larger windows mean more history but can cost more per message, since more tokens get sent each turn.

### Get API Keys

- **Anthropic** (required): https://console.anthropic.com/ → API Keys
- **ElevenLabs** (optional): https://elevenlabs.io/ → for text-to-speech

### Existing users: migrating off OpenAI embeddings

OpenAI embeddings are deprecated (the provider will be removed entirely in a future release). If your config still uses `embedding_provider: "openai"`, Mneme shows a one-click **"Migrate to new embeddings"** popup on launch:

- It backs up your database automatically before touching anything
- Migration runs in the background with a visible progress bar
- Completion is verified before your config is switched over
- If interrupted, it resumes from where it left off
- You can snooze the prompt for a few days if you're not ready

The OpenAI path still works this release as a fallback if a migration fails, but plan to migrate — it will be removed in the next release.

---

## Starting Mneme

### System Tray (Recommended)

Double-click the "Launch Mneme" shortcut (desktop or Mneme folder). Mneme starts in the system tray — look for the icon near the clock. Right-click for options.

### Direct Server Start

```bash
python src/backend/server.py
```

You should see:
```
Initializing Mneme Memory System...
✓ Configuration loaded
✓ Database connected

======================================================================
  MNEME WEB SERVER
======================================================================

  Local:     http://localhost:8080
  Press Ctrl+C to stop
======================================================================
```

### Access the Interface

**On your computer:** Open browser → **http://localhost:8080**

**On your phone (via Tailscale):**
1. Install Tailscale on both devices (free)
2. Sign in with the same account on both
3. Find your computer's Tailscale IP (looks like `100.x.y.z`)
4. Open: **http://[tailscale-ip]:8080**

If your computer goes to sleep, phone access stops working until you wake it. On Windows, turn on **Keep this PC awake while Mneme is running** in Settings (gear icon → System) to stop sleep while Mneme runs — the screen can still turn off, and the toggle applies immediately with no restart. Windows-only for now.

---

## Using the Web Interface

### First Launch

On first launch (or with no profiles), you'll see the **starting screen** with the Mneme logo and a model selector. Pick a model, enter a name for your AI instance, and you're in.

### Interface Layout

- **Header**: Instance name on the left, settings gear and back button on the right
- **Messages area**: Scrollable conversation — your messages on the right, AI responses on the left
- **Status float**: Slim bar above the input showing real-time processing status. Click to expand into a full log panel
- **Input bar**: Multiline text input with send button. Attach files by pasting images from clipboard
- **Streaming wave**: Animated coral wave above the input while the AI is responding. A stop button (■) appears to interrupt
- **Settings page**: Gear icon in the header — adjust model, API keys, and feature toggles without editing config files

### Sending Messages

1. Type your message in the input bar
2. Press **Enter** for new lines
3. Click the **send button** to send
4. The streaming wave animates while the AI responds
5. Click the **stop button** (■) to interrupt — you'll be offered to continue

### Features

- Auto-scroll to latest message
- Full conversation history loads on page reload
- Messages stored automatically in local SQLite database
- Background embeddings and entity assignment after each message
- Copy button on AI messages (hover to reveal)
- Click user messages to copy
- Paste images from clipboard to attach
- Collapsible extended thinking blocks
- Mobile-responsive design

### Transcript Export

From Settings, export your conversation as a transcript:
- **Markdown** — formatted for reading or sharing
- **JSON** — structured for reinstall or migration via `scripts/import_conversation.py`

Pick the format toggle in the Settings export section, then download.

---

## Command Reference

The AI uses these commands proactively during conversation. For complete details, see [COMMAND_REFERENCE.md](COMMAND_REFERENCE.md).

### Core Commands

- **@remember {id}** — Mark a message as high-importance
- **@recall [topic]** — Retrieve memories about a topic (triggers continuation)
- **@recall --deep [topic]** — Search deep archive (6+ months)
- **@forget [topic]** — Archive memories about a topic
- **@note {section}** / **@endnote** — Create/update a persistent note section
- **@note remove {section}** — Remove a note section
- **@concept list** — List narrative concepts
- **@concept view [name]** — View concept details
- **@file list** — List attached files
- **@file view {uuid}** — Load a file in detail (triggers continuation)
- **@describe {uuid}** — View or write an AI description for an attached file
- **@entity list/view/name** — Browse entity summaries or force-include one in retrieval
- **@artifact** / **@endartifact** — Save creative or technical work to disk as markdown
- **@run** / **@endrun** — Execute read-only Python to query the database or inspect files
- **@config [param] [value]** — Adjust system settings

---

## Troubleshooting

### "python is not recognized" (Windows)

Reinstall Python and check "Add Python to PATH". Restart your terminal.

### "No module named 'flask'"

```bash
pip install -r requirements.txt
```

### "Configuration file not found"

```powershell
$mnemeHome = Join-Path $env:LOCALAPPDATA "Mneme"
New-Item -ItemType Directory -Force $mnemeHome | Out-Null
Copy-Item .\config.example.json (Join-Path $mnemeHome "config.json")
# Then add your API keys, or let the setup wizard handle it
```

### Server won't start

1. Check port 8080 is not already in use
2. Verify API keys in `%LOCALAPPDATA%\Mneme\config.json` or the Settings page
3. Run `python scripts/verify_setup.py`

### Can't connect from phone

1. Server is running (tray icon is colored, not gray)
2. Tailscale connected on both devices with the same account
3. Using correct Tailscale IP
4. Firewall not blocking port 8080

### Tray icon missing

Look for hidden icons — click the `^` arrow near the clock (Windows). The icon may be in the overflow area.

---

## Profiles

Mneme supports multiple AI instances, each with its own database, conversation history, and configuration.

### Creating Profiles

Click the back button in the header to reach the **profile selector**. Click "New instance" to create a new profile — pick a model, enter a name, and you're set.

### Switching Profiles

From the profile selector, tap any profile to switch. A loading animation plays while the system reinitializes with the new profile's database and settings.

### Per-Profile Settings

Each profile can override `identity`, `model`, `thinking`, `context`, and `features` settings independently. Global settings (API keys, storage, system) stay shared. Per-profile overrides are stored in `%LOCALAPPDATA%\Mneme\data\{profile}\config.json`.

### Profile Data

```text
%LOCALAPPDATA%\Mneme\data\
├── main/              ← Profile: "main"
│   ├── memory.db
│   ├── config.json    ← profile overrides (optional)
│   ├── attachments/
│   └── artifacts/
├── testing/           ← Profile: "testing"
│   ├── memory.db
│   └── ...
```

Each profile's data is fully independent. Back up `%LOCALAPPDATA%\Mneme` to preserve every profile as well as your global configuration and system instructions.

---

## Tips

### Security

- **Keep API keys secret** — never share them
- **Monitor costs** — check your Anthropic console dashboard
- **Local-first** — all data stays on your computer

### Performance

- **Database size**: ~1MB per 1000 messages
- **Streaming latency**: <500ms to first token
- **API costs**: Depends on model and usage. Haiku at 5–10 msgs/day: ~$3–8/month. Sonnet at 20–40 msgs/day: ~$30–60/month. Heavy Sonnet use (60–80+ msgs/day with thinking): ~$100–180/month. Fable bills at $10/$50 per million tokens (input/output) — roughly 2× Opus — so heavy use on Fable can run $200–350+/month

### Backups

Fresh v15.1 installs keep all user state under `%LOCALAPPDATA%\Mneme`. Close Mneme before copying that folder so its SQLite databases are not being written during the backup. This preserves every profile, attachment, artifact, setting, and system-instructions file. Mneme can also create safe SQLite startup snapshots when `system.enable_auto_backup` is enabled; snapshots use `storage.backup_path`, and can optionally copy to `storage.cloud_backup_path`.

```powershell
$mnemeHome = Join-Path $env:LOCALAPPDATA "Mneme"
$backupRoot = Join-Path $PWD "backups"
$backupPath = Join-Path $backupRoot ("Mneme-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
New-Item -ItemType Directory -Force $backupRoot | Out-Null
Copy-Item -Recurse -LiteralPath $mnemeHome -Destination $backupPath
```

---

**Last Updated**: July 2026 (v15.1.0)
