# Mneme Visual Identity — the law

One page. If a style choice isn't derivable from this file, it's a violation.
Agreed 2026-07-08 (Mikael + Fable). Change the law here first, then the CSS.

---

## Palette — named rocks only

Every color in the UI is one of these tokens. A raw hex or `rgba()` in a rule
is a violation — if a new color is needed, it gets designed, named, and added
here first.

| Token | Value | Job |
|-------|-------|-----|
| `--slate` | `#262624` | The room. Main background. |
| `--gravel` | `#30302e` | Cards, input bar, modal bodies. |
| `--chalk` | `#76746e` | Secondary text, hints, inactive states; borders. |
| `--granite` | `#878787` | Structural edges (e.g. writing-area frame). Structure, not text. |
| `--andesite` | `#a2a2a2` | Structural accents. Structure, not text. |
| `--coral` | `#d97757` | Accent: interactive, emphasis, machine voice, chunky lines. |
| `--coral-50/-30/-20/-15/-10` | coral alphas | Named background washes only. Never text. |
| `--alabaster` | `#ece9e2` (starting point — pixel-push live) | THE text white. Warm. Replaces `--white`/`#ffffff` everywhere. |
| `--wash` | `rgba(255, 255, 255, 0.05)` | The one sanctioned neutral hover/active background wash. |
| `--error` | `#ff4444` | Errors only. |

**Translucency ban:** no opacity on text, no unnamed `rgba()` fills.
The single sanctioned translucency is the glass material (below).

## Type — four voices, closed set

| Voice | Face | Weight | Color | Used for |
|-------|------|--------|-------|----------|
| **Wordmark** | hand-drawn asset | — | coral | Logo moments. It's a face, not a heading style. Small (icon rule), except deliberate hero moments. |
| **Mneme** | Source Serif 4 | light (~350) | alabaster | Titles, product copy, onboarding — Mneme explaining itself. Quiet, editorial; contrasts the wordmark, never competes. |
| **AI** | Source Serif 4 | regular | alabaster (chalk for its secondary lines) | Conversation prose. |
| **Machine** | Fira Code | regular | coral | All transient system state: status log, loading substatus, timestamps, progress labels, token counts, model IDs, setting *values*. |

The test for settings and mixed surfaces: **who is speaking?**
Machine reporting state → Fira coral. Mneme explaining an option → serif alabaster/chalk.

No font sizes or weights outside the roles above without adding them here.
Chalk is never body prose (contrast ~3.2:1 on slate — labels only).

## Planes — the material system

1. **The room** — the conversation. Slate, serif, opaque.
2. **Structure** — drawn on the room: chunky coral/chalk strokes, granite/andesite
   edges, outline-no-fill.
3. **The glass** — the meta layer. Orange frosted glass for UI that sits *above or
   between* the conversation doing meta work: status float, status bar, modals.

**Glass rules:**
- Layers only, never in-flow. If it scrolls with the page, it's not glass.
- One recipe, tokenized: `--glass-tint` (coral 0.12) layered over `--glass-base`
  (slate 0.8), `--glass-blur` (8px), `--glass-radius` (26px). A sanctioned
  denser variant may exist for text-heavy layers (e.g. settings) — one
  variant, not per-surface improvisation.
- Cards standing ON glass fill with `--glass-card` (slate 0.5) so the
  material shows through.
- Behind a glass layer that demands focus, dim the room with `--scrim`
  (slate 0.6) + `--scrim-blur` (2px).
- What stands on glass usually speaks machine voice (Fira + coral).

## Shape

- Pills and soft squircles first. Rounded squares tolerated where content
  demands. Sharp corners banned.
- Chunky strokes, majority coral and chalk. Outline over fill (glass is the
  exception).

## Icons

Small, always. If an icon feels like it wants to be big, it's trying to be
the wordmark — don't let it.
