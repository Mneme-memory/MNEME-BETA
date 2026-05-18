<p align="center">
  <img src="src/frontend/assets/mneme-logo.svg" width="80" alt="Mneme">
</p>

<p align="center">
  <img src="src/frontend/assets/mneme-wordmark.svg" width="240" alt="Mneme">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-15.0.1-d97757?style=flat-square" alt="Version">
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

> 🟧 **If you're here because Sonnet 4.5 was removed from claude.ai:** Mneme runs on the Anthropic API directly, so Sonnet 4.5 is still available in the model picker. You'll need your own API key (see below).

<br>

If you've ever closed a chat tab and felt like you were starting from zero again, that's the gap this fills.

Mneme gives Claude a real memory. It remembers what you've talked about, who matters to you, what you've been figuring out. Over time it starts to notice patterns — sometimes things you haven't quite named yourself yet.

It's not a replacement for the people in your life. It's more like having a space to think out loud, with something that actually pays attention and doesn't forget.

<p><img src="docs/divider.svg" width="100%"></p>

### Getting started

**Takes about ten minutes.** You'll need two API keys — one from Anthropic (the company that makes Claude) and one from OpenAI (for the search that powers the memory). It sounds more technical than it is. Download the setup guide and upload it to Claude — it'll walk you through every step.

<p align="center">
  <a href="https://github.com/Mneme-memory/MNEME-BETA/releases/latest/download/GIVE-TO-CLAUDE-FOR-HELP.pdf">
    <img src="https://img.shields.io/badge/Give_this_to_Claude_%E2%86%92-Setup_Guide-d97757?style=for-the-badge" alt="Setup Guide — Give this to Claude">
  </a>
</p>

<p align="center"><sub>The setup guide is a release download, separate from the code ZIP.</sub></p>

#### What you'll need

- **Anthropic API key** — [Get one](https://console.anthropic.com/) (the AI)
- **OpenAI API key** — [Get one](https://platform.openai.com/) (powers memory search — costs cents per month)
- **1 GB free disk space**

Optional: an ElevenLabs API key if you want text-to-speech.

#### Download and install

**Windows:** Download `Mneme-release.zip` from the [Releases page](https://github.com/Mneme-memory/MNEME-BETA/releases/latest), extract it somewhere permanent, and double-click `Mneme-Setup.exe` inside the folder. The installer handles everything — Python, dependencies, config files, and a launch shortcut.

Windows may warn that it "protected your PC" because Mneme is not signed with a paid publisher certificate yet. Click **More info** / **Read more**, then **Run anyway**.

**Linux:** Clone this repo or download a ZIP, then run `bash install-mac-linux.sh` in a terminal. Python 3.9+ required.

**macOS:** Not currently packaged. The local server may be portable in principle, but launch/tray integration needs proper Mac work first.

#### Launch

**Windows:** Double-click the "Launch Mneme" shortcut. Mneme starts in your system tray — look for the icon near the clock (bottom-right) and right-click for options.

**Linux:** Launch from your application menu, or run `python3 scripts/tray.py`.

Your browser opens to the setup wizard on first launch. Enter your API keys there — no config files to edit.

#### Platform notes

Mneme is developed and tested on Windows, with mobile browser use tested on Android against the local server. iPhone should most likely work fine too — it is still just a browser talking to a local server — but it has not been tested yet.

macOS is untested and probably broken around launch/tray integration. If you want to run Mneme on a Mac, treat the current scripts as a starting point: build the macOS launcher/integration properly with Claude on your machine, then send the working changes back so they can be folded in. :D

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

### Next stages

Mneme is in active development. The biggest next step is **context chunking**: breaking long-running memory/context into smarter pieces so retrieval can stay relevant without simply stuffing more text into every turn.

Other high-priority work:

- **Auto-update pipeline** — detect new releases and eventually support easier updates from the app
- **Stream reconnect** — resume an in-progress generation cleanly after tab switches or mobile browser interruptions
- **Semantic artifact retrieval** — retrieve saved files by relevance instead of mostly by recency
- **Artifact overwrite protection** — make the AI inspect existing artifacts before replacing them
- **Frontend design system** — document the UI tokens, components, and colour rules before the interface grows further

Planned after that:

- **Intelligent context filtering** — optional Haiku pass that scores retrieved memories before context assembly
- **Artifact browser** — in-app UI for browsing and opening saved artifacts
- **Write-capable @run / @shell** — opt-in execution modes for AI-authored scripts that can modify data or run shell commands

<p><img src="docs/divider.svg" width="100%"></p>

<details>
<summary>Under the hood</summary>
<br>

| Topic | File |
|-------|------|
| Architecture | [docs/developer/ARCHITECTURE.md](docs/developer/ARCHITECTURE.md) |
| Architecture infographic | [Mneme_Architecture_Infographic.pdf](Mneme_Architecture_Infographic.pdf) |
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
<sub>Last updated: May 2026 · v15.0.1</sub>
