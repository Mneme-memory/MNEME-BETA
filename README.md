<p align="center">
  <img src="src/frontend/assets/mneme-logo.svg" width="80" alt="Mneme">
</p>

<h1 align="center">Mneme</h1>

<p align="center">
  <img src="https://img.shields.io/badge/version-14.0.0-d97757?style=flat-square" alt="Version">
  <img src="https://img.shields.io/badge/license-CC%20BY%204.0-d97757?style=flat-square" alt="License">
  <img src="https://img.shields.io/badge/status-beta-d97757?style=flat-square" alt="Status">
</p>

<br>

```
you      had a genuinely good week
mneme    third one in a row, actually.
         something's shifting.
```

<br>

If you've ever closed a chat tab and felt like you were starting from zero again, that's the gap this fills.

Mneme gives Claude a real memory. It remembers what you've talked about, who matters to you, what you've been figuring out. Over time it starts to notice patterns — sometimes things you haven't quite named yourself yet.

It's not a replacement for the people in your life. It's more like having a space to think out loud, with something that actually pays attention and doesn't forget.

<p><img src="docs/divider.svg" width="100%"></p>

### Getting started

**Takes about ten minutes.** You'll need two API keys — one from Anthropic (the company that makes Claude) and one from OpenAI (for the search that powers the memory). It sounds more technical than it is. Download the setup guide and upload it to Claude — it'll walk you through every step.

<p align="center">
  <a href="../../releases/latest/download/GIVE-TO-CLAUDE-FOR-HELP.pdf">
    <img src="https://img.shields.io/badge/Give_this_to_Claude_%E2%86%92-Setup_Guide-d97757?style=for-the-badge" alt="Setup Guide — Give this to Claude">
  </a>
</p>

<p align="center"><sub>On GitHub: click the button above, then click the download icon (↓) in the top-right corner of the page.</sub></p>

#### What you'll need

- **Anthropic API key** — [Get one](https://console.anthropic.com/) (the AI)
- **OpenAI API key** — [Get one](https://platform.openai.com/) (powers memory search — costs cents per month)
- **1 GB free disk space**

Optional: an ElevenLabs API key if you want text-to-speech.

#### Download and install

**Windows:** Download `Mneme-release.zip` from the [Releases page](../../releases/latest), extract it somewhere permanent, and double-click `Mneme-Setup.exe` inside the folder. The installer handles everything — Python, dependencies, config files, and a launch shortcut.

**macOS / Linux:** Clone this repo or download a ZIP, then run `bash install-mac-linux.sh` in a terminal. Python 3.9+ required.

#### Launch

**Windows:** Double-click the "Launch Mneme" shortcut. Mneme starts in your system tray — look for the icon near the clock (bottom-right) and right-click for options.

**macOS / Linux:** Launch from your application menu, or run `python3 scripts/tray.py`.

Your browser opens to the setup wizard on first launch. Enter your API keys there — no config files to edit.

#### Import existing conversations

Already have conversations in Claude or ChatGPT you'd like Mneme to remember? The setup guide covers how to import them.

<p><img src="docs/divider.svg" width="100%"></p>

### What it costs

Mneme itself is free. You pay for the AI and search APIs directly — nothing goes through us.

| Usage | Model | Est. monthly |
|-------|-------|--------------|
| Light (5–10 messages/day) | Haiku | $3–8 |
| Moderate (20–40 messages/day) | Sonnet | $30–60 |
| Heavy (60–80+ messages/day) | Sonnet + thinking | $100–180 |

Memory search (OpenAI embeddings) adds a few cents per month regardless of usage. The default config is tuned for moderate cost — you can adjust it lower from the Settings page in the app.

<p><img src="docs/divider.svg" width="100%"></p>

### Your data, your machine

Everything Mneme stores lives in a database on your own computer. API calls go directly from your machine to Anthropic and OpenAI — there's no Mneme server in the middle, no accounts, no telemetry.

Your API keys are stored locally and never shared. The code is open source — you can read exactly what it does.

<p><img src="docs/divider.svg" width="100%"></p>

### What's coming

- **Semantic artifact retrieval** — relevance-based retrieval over saved files, replacing recency-only
- **Intelligent context filtering** — optional pass that scores retrieved memories for relevance before assembly
- **Artifact browser** — in-app UI for browsing and opening saved artifacts
- **Write-capable @run** — opt-in mode for AI-authored scripts that can modify data

<p><img src="docs/divider.svg" width="100%"></p>

<details>
<summary>Under the hood</summary>
<br>

| Topic | File |
|-------|------|
| Architecture | [docs/developer/ARCHITECTURE.md](docs/developer/ARCHITECTURE.md) |
| Developer guide | [CLAUDE.md](CLAUDE.md) |
| Config options | [config.example.json](config.example.json) |
| User setup guide | [docs/user/SETUP_AND_USAGE.md](docs/user/SETUP_AND_USAGE.md) |
| Command reference | [docs/user/COMMAND_REFERENCE.md](docs/user/COMMAND_REFERENCE.md) |
| Changelog | [docs/developer/CHANGELOG.md](docs/developer/CHANGELOG.md) |
| Roadmap | [docs/ROADMAP.md](docs/ROADMAP.md) |

</details>

<p><img src="docs/divider.svg" width="100%"></p>

### License

[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) — free to use and adapt with attribution.

If you build on this, a credit and link back is appreciated.

<br>
<sub>Last updated: March 2026 · v14.0.0</sub>
