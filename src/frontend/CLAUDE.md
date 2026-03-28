# Frontend — Developer Notes

Vanilla JS + CSS + HTML, no framework. Served by Flask at `http://localhost:8080`.

Key files: `app.js` (logic), `style.css` (styles), `index.html` (shell).

> **Cross-cutting flows** (anything that spans backend + frontend — SSE protocol, command continuation, interrupt/save-partial, orphan cleanup) are documented in `docs/developer/SKILL_TREE.md`. Read it before touching the streaming pipeline or the abort flow.

---

## Design System

**Theme**: Warm dark — slate backgrounds, coral accents, serif body text.

**Fonts**
- `Source Serif 4` — all prose (messages, headers, UI labels)
- `Fira Code` — mono elements (status log, timestamps, placeholder text)

**CSS variables** (all in `:root`):
| Variable | Value | Use |
|----------|-------|-----|
| `--slate` | `#262624` | Main background |
| `--gravel` | `#30302e` | Cards, input bar, modals |
| `--chalk` | `#76746e` | Borders, muted text |
| `--granite` | `#878787` | Secondary labels |
| `--coral` | `#d97757` | Accent: buttons, status log, code |
| `--font-serif` | Source Serif 4 | Body font |
| `--font-mono` | Fira Code | Mono font |

---

## Screen States (three-screen navigation)

**Starting screen** (`.starting-screen`) — shown when creating a new profile. Contains the Mneme logo, model selector, and headline. After model pick, triggers creation flow: typewriter headline transition → input reveal → name entry → profile creation.

**Profile selector** (`.profile-selector`) — shown when navigating back from chat view. Card with profile rows (model icon + name + model label), "New instance" footer tucked underneath (same pattern as model-selector-footer), greeting text below. Fetches profiles from `GET /api/profiles`.

**Chat view** — messages container + status float + input bar. The header is always present as an absolute overlay on all screens.

**Navigation**: Startup with no profiles → starting screen. Startup with profiles → chat view (last active). Back from chat → profile selector. "New instance" → starting screen. Profile tap → loading animation → chat view.

**Loading animation** — full-screen overlay with Mneme logo canvas animation (coral pillars on circular clip). Shown during profile switches, profile creation, and initial app load. Functions: `showLoadingAnimation()` / `hideLoadingAnimation()`. Canvas constants are halved from the prototype (75×80px display).

---

## Turn Lifecycle

Every AI turn goes through `sendMessage()` → `setWaiting(true)` → streaming/non-streaming → `setWaiting(false)`.

**`setWaiting(true)`** kicks off the turn:
- Clears the status log, shows the notification bar (active state), starts the spinner
- Adds `"processing message..."` as the first log line
- Calls `startInputStreamingState()`

**`setWaiting(false)`** ends the turn:
- Flushes the deferred user timestamp (stamped now so it isn't clipped by the rising process bar)
- Stops spinner, calls `stopInputStreamingState()`
- After 4 s, calls `hideNotificationBar()` → switches float to idle (dimmed)

### SSE event types (`sendMessageStreaming`)

| Event | Effect |
|-------|--------|
| `notification` | `handleNotificationAsLog()` → status log line. If text contains `"Cache"` → `activateWave()`. If text starts with `"💭 Calling AI again"` → sets `inContinuationPhase = true`, resets `currentAssistantMessage` |
| `thinking_start` | `activateWave()` (fallback), creates thinking block in message |
| `thinking` | Appends to thinking block |
| `chunk` | `activateWave()` (fallback), creates assistant message bubble if needed, appends text |
| `done` | Finalizes message (removes streaming cursor, stamps timestamp, adds action row). If `inContinuationPhase`, hides wave pill. Adds `"done"` success log line |
| `error` | Logs error line, throws → caught by `sendMessage` catch block |

---

## Streaming Wave

The canvas (`#streamingWave`) sits 10px above the input container and is always positioned there. Its `display` is toggled between `block` (streaming) and `none` (idle).

### Phase 1 — flat line (retrieval)

`startInputStreamingState()` immediately:
- Adds `.streaming` to `.input-container`, `.wave-active` to `.status-float` (hides it)
- Makes the stop button (■) visible (`stopBtn.classList.add('visible')`)
- Starts `startWaveAnimation()` — draws a full-width flat coral line each frame
- Shrinks container to 32px via two nested `requestAnimationFrame` calls (measure → set 32px)

During the flat-line phase the **wave pill** (`#wavePill`) is shown above the line, mirroring each incoming notification text. It appears on the first `addStatusLine` call while `.streaming` is active and `waveActivated` is still `false`.

### Phase 2 — sine wave (AI streaming)

`activateWave()` is called on the first `Cache` notification or the first `thinking_start`/`chunk` (whichever arrives first). Guard `waveActivated` prevents double-trigger.
- Adds `.wave-active` to `.status-float` (already set, but idempotent)
- After a **380 ms** delay: `waveAmpTarget = 1`, hides the wave pill (sine replaces it)

The draw loop lerps `waveAmp` toward `waveAmpTarget` — slow rise (**0.06**/frame), faster shrink (**0.14**/frame). The sine is envelope-shaped: flat at edges, full U-curve at center.

### Phase 3 — shrink and finalize

`stopInputStreamingState()` (called from `setWaiting(false)`):
- Sets `waveAmpTarget = 0`, `waveShrinking = true`
- Cancels any pending `waveActivateTimerId` (prevents late 380 ms timer from re-raising the wave)
- Removes `.wave-active` from status-float → float slides back up via CSS transition
- If wave was never activated (very fast response): calls `finalizeStopInputStreamingState()` immediately

`finalizeStopInputStreamingState()` (called by draw loop when `waveAmp < 0.01 && waveShrinking && !isInterrupted`):
- Stops animation, hides canvas, hides stop button, resets `scrollToBottomBtn` position
- Expands input container back to 96px via CSS transition; on `transitionend` removes `.streaming` and clears inline height

**Key levers**: `waveAmpTarget`, the 380 ms delay in `activateWave()`, the 0.06/0.14 lerp rates, the 32px/96px height values.

---

## Interrupt & Continue Flow

When the user clicks the stop button (■) during streaming, `streamController.abort()` fires → `AbortError` is caught in `sendMessage` → `handleStreamAbort()` runs.

**`handleStreamAbort()`**:
- If partial text exists: finalizes the streaming bubble (removes cursor, appends `[interrupted]`), saves partial to DB via `/api/messages/save-partial`, then calls `showContinueToast()`
- If no partial text yet: removes the user bubble, calls orphan-cleanup to restore text to input

> Backend mechanics for save-partial and orphan cleanup — including the two-case distinction and FK gotcha — are in `SKILL_TREE.md § Message Lifecycle`.

**`showContinueToast()`** sets `isInterrupted = true` and:
1. Inserts `.wave-interrupted-pill` ("Response interrupted. Want me to continue?") and `.wave-yes-btn` ("YES") into `#inputWrapper` before the input container — both initially hidden for measurement
2. Morphs stop button ■ → × (`stopBtn.innerHTML = '<span class="stop-icon-x">×</span>'`)
3. Ensures the wave animation loop is running (restarts if needed)

The draw loop, now with `waveShrinking && isInterrupted`, lets the wave fully flatten, then begins **line contraction**: endpoints lerp toward the gap between the pill and the YES button (measured via `getBoundingClientRect`). When contraction completes, `onLineContractionComplete()` animates both elements in (`.animating-in` class).

**User choices:**
- **YES** → `hideContinueToast(false)` + `continuePreviousResponse()` — removes pill/button, reverts stop icon, calls `setWaiting(true)` (which calls `startInputStreamingState()` and resets all wave state), then streams from `/api/chat/continue`
- **× (dismiss)** → `hideContinueToast(true)` — removes pill/button, hides stop button, stops animation, expands input back to full height via transition

**`inContinuationPhase`** flag: set when a `"💭 Calling AI again"` notification arrives during a multi-command turn. While active, the wave pill shows continuation status. Cleared on `done` event (which also hides the pill) or on `startInputStreamingState()` reset.

---

## Progressive Blur (variable backdrop-filter intensity)

CSS `backdrop-filter: blur()` can't vary its intensity across an axis — you can't gradient the blur amount directly. The workaround is to stack multiple elements, each with a fixed blur value, and control their visibility with a mask. This approximates a true variable-blur gradient.

### The technique

Each layer covers the same `top` position but has its own `height`. The mask goes `transparent → black → black → transparent` (fade in at top, hold opaque across most of the layer, fade out at bottom). Key insight: **keep the layer opaque for as much of its height as possible.** The "fog" or "scatter" effect happens when a blurred layer sits at partial opacity over unblurred content — you end up seeing 50% blurred + 50% sharp = translucent smear. Fully opaque = defocus, not fog.

### Current implementation (`style.css`, `.blur-layer-*`)

6 layers, all anchored at `top: 36px` (header text baseline), heights stepping up by +14px:

| Layer | Height | Blur   | Effect                        |
|-------|--------|--------|-------------------------------|
| 1     | 20px   | 20px   | Heavy defocus right below text |
| 2     | 34px   | 12px   | Strong                        |
| 3     | 48px   | 6px    | Medium                        |
| 4     | 62px   | 3px    | Light                         |
| 5     | 92px   | 1.5px  | Barely soft, long fade-out    |
| 6     | 112px  | 0.6px  | Whisper — eases zone to zero  |

Fade-out on the bottom two layers starts earlier (76–78%) to give a longer taper. Total zone reaches ~126px from the top of the page.

### Levers to tune

- `top` — moves where the blur zone starts relative to the header
- layer `height` — controls how far down each blur level reaches
- mask `black X%` (fade-in stop) — how many pixels before the layer reaches full opacity
- mask `black Y%` (fade-out start) — how many pixels of taper at the bottom; earlier = longer fade, less abrupt cutoff
- `blur()` values — the intensity curve; keep them roughly doubling as you go up

---

## Status Float (collapsed bar ↔ floating cube)

The status float is a two-state component that lives between the messages area and the input bar. In its collapsed state it peeks up behind the input as a slim frosted strip. When clicked it expands into a full floating glass cube above the input.

### DOM structure

```
.status-float#statusFloat          ← outer shell, drives the layout trick
  .status-float-inner              ← content wrapper (position switches between states)
    .status-log-panel#statusLogPanel   ← scrollable log, hidden when collapsed
    .notification-bar#notificationBar  ← always-visible header row
      .spinner#statusSpinner           ← text spinner (visible only when active)
      .notification-bar-text#statusLogHeaderText  ← mirrors latest log line
```

### The collapsed tuck trick

The outer shell sits in normal flex flow between `.messages-container` and `.input-container`. Two negative margins create the illusion that it tucks behind the input:

- `margin-top: -60px` — pulls the element up so backdrop-filter has real content (message text) behind it to blur. Without this the blurred region covers only empty flex space and renders as a plain coloured rectangle.
- `margin-bottom: -28px` — slides the bottom of the element underneath the input container, so the visible bar peeks through the input's rounded top corners rather than sitting above them.
- `z-index: 2` on the float vs `z-index: 5` on the input — the input paints on top, completing the illusion.

Height is driven entirely by JS (`updateCollapsedHeight`), not CSS. The function measures `notificationBar.offsetHeight` and adds 28px (to compensate for `margin-bottom: -28px`) so the tuck depth stays consistent regardless of how tall the bar content grows.

**`updateCollapsedHeight` is a no-op when the float is `hidden`, `expanded`, or `wave-active`** — all three states manage their own sizing separately.

### The expanded floating cube

On expand, three things happen in JS (`toggleStatusLog`):
1. `.expanded` class is added to both `.status-float` and `.status-log-panel`
2. `statusFloat.style.bottom` is set to `inputContainer.offsetHeight` — pins the cube's bottom edge flush above the input

CSS changes on `.status-float.expanded`:
- `position: absolute` — removes it from flow entirely so it floats over the messages without pushing anything
- `margin-top: 0; margin-bottom: 0` — cancels the tuck margins
- `background: none; backdrop-filter: none` — strips the glass off the element itself
- `z-index: 110` — above blur layers (99) and header (100)

**Why the glass moves to `::before`**: `backdrop-filter` on a parent clips its children — the scrollable log panel inside would be unable to extend beyond the blurred region. Putting the blur on an absolute-positioned pseudo-element that sits behind the content layer avoids this. The pseudo covers `top:0 / left:16px / right:16px / bottom:16px` (the 16px gaps give the floating appearance).

### Status float states

The float has four distinct states driven by class combinations on `.status-float`:

| State | Classes | Height driver | Notes |
|-------|---------|---------------|-------|
| Initial | `.hidden` | `height: 0` | Before first turn. `updateCollapsedHeight` is no-op. |
| Collapsed | (none) | JS via `updateCollapsedHeight` | Slim bar tucked behind input. |
| Wave-active | `.wave-active` | CSS override (0-height or hidden) | Float hidden while canvas wave is running. `updateCollapsedHeight` is no-op. |
| Expanded | `.expanded` | `position: absolute`, `bottom` set by JS | Floating glass cube above input. |

Transitions: `hidden → collapsed` on first `showNotificationBar()`. `collapsed ↔ expanded` via `toggleStatusLog()`. `collapsed ↔ wave-active` via `startInputStreamingState()` / `stopInputStreamingState()`. The float never goes back to `.hidden`.

### Notification bar state machine

| State | Class | Opacity | Spinner |
|-------|-------|---------|---------|
| Processing | `active` | 1.0 | visible |
| Done / idle | `idle` | 0.5 | hidden |

The bar is hidden (`display: none`) while the cube is expanded. `showNotificationBar()` / `hideNotificationBar()` drive transitions.

### Log lines

`addStatusLine(text, type)` appends a `<div class="status-log-line log-{type}">` to the panel and simultaneously updates `statusLogHeaderText`. Also calls `updateCollapsedHeight` via `requestAnimationFrame`.

Log types (all coral-tinted, varying opacity):

| Type | Opacity |
|------|---------|
| `info` | 1.0 |
| `success` | 0.8 |
| `warning` | 0.6 |
| `error` | `--error` colour |
| `special` | 1.0 |

### Levers to tune

- `margin-top` on `.status-float` — how far up into messages the backdrop blur reaches
- `margin-bottom` on `.status-float` — how deep the bar tucks; the `+28` in `updateCollapsedHeight` must match this value exactly
- `::before bottom` — gap between expanded cube bottom and input top
- `::before left/right` — horizontal inset of the floating cube

---

## Known Issues — Fix When Touching Nearby Code

**index.html**
- Orphaned `#loadingIndicator` element + CSS rule hiding it (never used, safe to delete)

**app.js**
- Profile greeting uses `innerHTML` with unsanitized name (self-XSS only — no real attack surface, but worth fixing)
- `streamController` not nulled on normal completion (only nulled on abort)

---

## Loading Animation

Extracted from `Loading animation/prototype.html` into `app.js`. Canvas-based Mneme logo animation — coral pillars scrolling through a circular clip with wobble and width variation. Tuning slider UI dropped; values hardcoded.

Used as a full-screen overlay (`#loadingOverlay`) during profile switches, profile creation, and app startup. Functions: `showLoadingAnimation()` / `hideLoadingAnimation()`. Canvas renders at 150×160 internal resolution, displayed at 75×80px CSS size.
