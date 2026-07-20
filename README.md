<p align="center">
  <img src="src/frontend/assets/mneme-logo.svg" width="80" alt="Mneme">
</p>

<p align="center">
  <img src="src/frontend/assets/mneme-wordmark.svg" width="240" alt="Mneme">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-15.1.0-d97757?style=flat-square" alt="Version">
  <img src="https://img.shields.io/badge/license-CC%20BY%204.0-d97757?style=flat-square" alt="License">
  <img src="https://img.shields.io/badge/status-beta-d97757?style=flat-square" alt="Status">
</p>

<details>
<summary><b>✨ What's new in 15.1</b></summary>

- **A command console** — run things with buttons and ready-made suggestions instead of remembering commands.
- **Tidy up your memory** — merge duplicate people or topics into one.
- **Memory search now runs on your own machine** — faster, more private, and one less key to set up.
- **Shape your AI right in Settings** — change how it behaves in the app, no files to hunt down.
- **Replies that don't drop** — lose your connection or close the tab, and Mneme keeps going.

→ **[See the full changelog](docs/developer/CHANGELOG.md)**
</details>

<br>

```
you      had a genuinely good week
mneme    third one in a row, actually.
```

<br>

> 🟧 **If Fable is no longer included in your Claude plan, it isn't gone for good.** Mneme connects to Fable through Anthropic's API directly — no Max subscription required. You pay only for the API usage you choose, and Mneme's adaptive prompt caching typically cuts input costs by 50–70% in active conversations. With moderate, cached use, Fable can stay below $100/month; the calculation is [below](#what-it-costs).
>
> Fable costs $10/$50 per million input/output tokens and requires 30-day API data retention. It will return an error in a zero-data-retention workspace, and heavy use can still be expensive.

<br>

This is for you, if you have closed a chat tab and felt like you were starting from zero with the new one.

Mneme gives Claude a conversational memory. It remembers what you've talked about, who matters to you, what you've been figuring out. Over time it starts to notice patterns, including things you haven't named.

Instead of being a replacement for the people in your life, think of Mneme as having a space to think out loud together with something that pays attention and doesn't forget.

<p align="center"><img src="src/frontend/assets/mneme-divider-anim.webp" width="369" alt="Mneme"></p>

### Getting started

**Takes about ten minutes.** You'll need one API key, from Anthropic (the company that makes Claude). Download the setup guide and upload it to Claude — it'll walk you through every step.

<p align="center">
  <a href="https://github.com/Mneme-memory/MNEME-BETA/releases/latest/download/GIVE-TO-CLAUDE-FOR-HELP.pdf">
    <img src="https://img.shields.io/badge/Give_this_to_Claude_%E2%86%92-Setup_Guide-d97757?style=for-the-badge" alt="Setup Guide — Give this to Claude">
  </a>
</p>

<p align="center"><sub>The setup guide is a release download, separate from the code ZIP.</sub></p>

#### What you'll need

- **Anthropic API key** — [Get one](https://console.anthropic.com/) (the AI)
- **1 GB free disk space** (memory search runs on a small local model, downloaded automatically on first use — about 33MB, no account or key needed)

Optional: an ElevenLabs API key if you want text-to-speech.

(If you're an existing user still on OpenAI embeddings, Mneme will offer a one-click "Migrate to new embeddings" prompt. It backs up your database first, migrates, and verifies before finishing. See the setup guide for details.)

#### Download and install

**Windows:** Download `Mneme-release.zip` from the [Releases page](https://github.com/Mneme-memory/MNEME-BETA/releases/latest), extract it somewhere permanent, and double-click `Mneme-Setup.exe` inside the folder. The installer handles everything — Python, dependencies, config files, and a launch shortcut.

(Windows may warn that it "protected your PC" because Mneme is not signed with a paid publisher certificate yet. Click **More info** / **Read more**, then **Run anyway**.)

#### Launch

Double-click the "Launch Mneme" shortcut. Mneme starts in your system tray, look for the icon near the clock (bottom-right) and right-click for options.

Your browser opens to the setup wizard on first launch. Enter your API keys there. No config files to edit.

#### Platform notes

Mneme currently supports **Windows only**. It's developed and tested on Windows, with mobile browser use tested on Android against the local server. iPhone should most likely work fine too — it is still just a browser talking to a local server — but it has not been tested yet.

Linux and macOS are not supported yet — the installer, tray integration, and the code-execution sandbox are all Windows-specific right now. If you want to help port Mneme to your platform, get it working with Claude on your machine and send the changes back so they can be folded in. :D

#### Import existing conversations

Already have conversations in Claude or ChatGPT you'd like Mneme to remember? The setup guide covers how to import them.

#### Updating

One-click updates are coming — a future version will update Mneme from the tray, nothing to download. **For now, updating is a short guided process.** v15.1+ keeps personal data in `%LOCALAPPDATA%\Mneme`, outside the replaceable app folder, and the first-run wizard can safely import and verify an older Mneme install. You still cannot update by *pulling* this repo in git or GitHub Desktop; download the release ZIP and follow the [update guide](docs/user/UPDATING.md).

→ **[How to update Mneme](docs/user/UPDATING.md)** · a few minutes

<p><img src="docs/divider.svg" width="100%"></p>

### What it costs

Mneme itself is free. You pay Anthropic directly for the AI — nothing goes through us. API billing is based on the tokens you use, so using Fable here does not require a $100+ monthly Claude plan.

| Usage | Model | Est. monthly |
|-------|-------|--------------|
| Light (5–10 messages/day) | Haiku | $3–8 |
| Moderate (20–40 messages/day) | Sonnet | $30–60 |
| Heavy (60–80+ messages/day) | Sonnet + thinking | $100–180 |
| Selective Fable (5 messages/day, cached session) | Fable | ~$32 |
| Regular Fable (10 messages/day, cached session) | Fable | ~$53 |
| Daily Fable (20 messages/day, cached session) | Fable | ~$95 |
| Heavy, on Fable | Fable ($10/$50 per MTok — ~2× Opus) | $200–350+ |

**How the Fable examples are calculated:** one active conversation session per day, averaging 20,000 cached input tokens, 7,000 new input tokens, and 1,000 output tokens per message. Fable bills those at $1, $10, and $50 per million tokens respectively. Mneme uses Anthropic's one-hour cache, whose first write costs $20 per million tokens. That works out to about $1.08/day at 5 messages, $1.78/day at 10, and $3.18/day at 20 — approximately $32, $53, and $95 over 30 days.

These are examples, not a spending guarantee. Longer replies, more thinking, larger retrieved context, or messages spread across separate sessions will cost more. Keeping messages in an active conversation lets Mneme reuse the cached prompt; after a long gap, a new cache has to be written. Very heavy Fable users may still spend less on a subscription plan that includes it.

Memory search runs on a local model on your machine, with no ongoing cost. The default config is tuned for moderate cost, and you can adjust it lower from the Settings page in the app.
<p><img src="docs/divider.svg" width="100%"></p>

### Your data, your machine

Everything Mneme stores lives in a database on your own computer. API calls go directly from your machine to Anthropic, there's no Mneme server in the middle.

Your API keys are stored locally and never shared. The code is open source, you can read exactly what it does.

<p><img src="docs/divider.svg" width="100%"></p>

### Next stages

Mneme is in active development. **The first architectural priority is replacing its text-parsed `@command` protocol with native AI tool use:** typed, structured calls for memory, files, artifacts, and execution, with clearer permissions and fewer fragile continuation round trips. For that and the other directions being explored, see the [Roadmap](docs/ROADMAP.md).

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
<sub>Last updated: July 2026 · v15.1.0</sub>
