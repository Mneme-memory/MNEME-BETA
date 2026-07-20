/**
 * Mneme Memory System - Frontend Application
 * Warm dark theme with coral accents
 */

// API endpoint
const API_BASE = window.location.origin;

// DOM Elements
const messagesContainer = document.getElementById('messagesContainer');
const messageInput = document.getElementById('messageInput');
const sendBtn = document.getElementById('sendBtn');
const stopBtn = document.getElementById('stopBtn');
const wavePillEl = document.getElementById('wavePill');
const wavePillTextEl = document.getElementById('wavePillText');
const inputWrapper = document.getElementById('inputWrapper');
const errorBanner = document.getElementById('errorBanner');
const errorMessage = document.getElementById('errorMessage');
const errorClose = document.getElementById('errorClose');
const settingsBtnHeader = document.getElementById('settingsBtnHeader');
const settingsPage = document.getElementById('settingsPage');
const settingsBackBtn = document.getElementById('settingsBackBtn');
const bottomDrawer = document.getElementById('bottomDrawer');
const bottomDrawerOverlay = document.getElementById('bottomDrawerOverlay');
const commandsDrawer = document.getElementById('commandsDrawer');
const drawerAttachOption = document.getElementById('drawerAttachOption');
const drawerCommandOption = document.getElementById('drawerCommandOption');
const settingsSaveBtn = document.getElementById('settingsSaveBtn');
const profileName = document.getElementById('profileName');
const headerModelLabel = document.getElementById('headerModelLabel');
const scrollToBottomBtn = document.getElementById('scrollToBottom');
const inputContainer = document.getElementById('inputContainer');
const attachBtn = document.getElementById('attachBtn');
const fileInput = document.getElementById('fileInput');
const pendingAttachments = document.getElementById('pendingAttachments');
const statusFloat = document.getElementById('statusFloat');
const notificationBar = document.getElementById('notificationBar');
const statusLogPanel = document.getElementById('statusLogPanel');
const statusSpinner = document.getElementById('statusSpinner');
const statusLogHeaderText = document.getElementById('statusLogHeaderText');
const startingScreen = document.getElementById('startingScreen');
const chatHeader = document.getElementById('chatHeader');
const modelBadge = document.getElementById('modelBadge');
const modelBadgeText = document.getElementById('modelBadgeText');
const modelBadgeVersion = document.getElementById('modelBadgeVersion');
const modelBadgeIcon = document.getElementById('modelBadgeIcon');
const modelSelector = document.getElementById('modelSelector');
const modelSelectorWrap = document.getElementById('modelSelectorWrap');
const modelOthersBtn = document.getElementById('modelOthersBtn');
const profileSelector = document.getElementById('profileSelector');
const profileSelectorWrap = document.getElementById('profileSelectorWrap');
const profileBadge = document.getElementById('profileBadge');
const profileBadgeIcon = document.getElementById('profileBadgeIcon');
const profileBadgeText = document.getElementById('profileBadgeText');
const profileBadgeModel = document.getElementById('profileBadgeModel');
const profileBadgeVersion = document.getElementById('profileBadgeVersion');
const profileCard = document.getElementById('profileCard');
const profileNewInstance = document.getElementById('profileNewInstance');
const profileGreeting = document.getElementById('profileGreeting');
const startingHeadline = document.getElementById('startingHeadline');
const loadingOverlay = document.getElementById('loadingOverlay');
const loadingCanvas = document.getElementById('loadingCanvas');
const migrationChatLock = document.getElementById('migrationChatLock');
const migrationLockCanvas = document.getElementById('migrationLockCanvas');
const backBtn = document.getElementById('backBtn');
const forwardBtn = document.getElementById('forwardBtn');
const headerCenter = document.getElementById('headerCenter');
const headerWordmark = document.getElementById('headerWordmark');
const inputMirror = document.getElementById('inputMirror');
const cmdAutocomplete = document.getElementById('cmdAutocomplete');

// State
let isWaiting = false;
let waveAnimId = null;
let wavePhase = 0;
let waveAmp = 0;              // current amplitude (0–1), lerped each frame
let waveAmpTarget = 0;        // 0 = shrink to flat, 1 = grow to full
let waveActivated = false;    // guard: only trigger activateWave() once per session
let waveShrinking = false;    // set only by stopInputStreamingState — enables cleanup
let waveActivateTimerId = null; // pending setTimeout in activateWave()
let streamingEnabled = false;
let isInterrupted = false;         // interrupted state — pill visible, input stays at 32px
let inContinuationPhase = false;   // between "Calling AI again" notification and turn end
let waveLineContracting = false;   // line contraction animation active
let waveLineL = 0;                 // current left endpoint of flat line (px)
let waveLineR = null;              // current right endpoint (null = full width)
let waveLineLTarget = 0;           // contraction target — left
let waveLineRTarget = null;        // contraction target — right (null = full width)
let waveInterruptedPillEl = null;  // interrupted pill DOM element
let waveYesBtnEl = null;           // YES button DOM element
let pendingFiles = [];
let streamController = null;        // AbortController for active stream
let notifDisplayQueue = [];         // rAF-paced notification display queue
let notifQueueActive = false;       // whether drainNotifQueue rAF loop is running
let partialResponse = '';           // text accumulated during current stream
let currentStreamThinking = '';     // thinking text accumulated during current stream
let interruptedMessageId = null;    // DB id set after save-partial succeeds
let currentAssistantMessage = null; // active streaming message element (module-level)
let continueToastVisible = false;
let ttsEnabled = false;
let thinkingEnabled = false;
let showThinking = true;
let currentAudio = null;
let currentTTSButton = null;
let statusLogExpanded = false;
let spinnerInterval = null;
let statusViewsWrapper = null;
let statusProcessList = null;
let statusDetailPanel = null;
let processDetailContent = null;
let processBackBtn = null;
let statusDetailVisible = false;

// Incremental "load older messages" scrolling
let oldestLoadedMessageId = null;  // id of the oldest message currently rendered
let hasMoreOlderMessages = true;   // false once the start of history is reached
let isLoadingOlderMessages = false; // guards against duplicate concurrent fetches
let olderMessagesIndicatorEl = null; // top-of-list loading / "beginning" marker
let chatActive = false;
let loadingAnimId = null;          // rAF id for loading animation
let migrationLockAnimId = null;    // rAF id for in-chat migration lock animation
let creationFlowModel = null;      // model selected during profile creation flow
let hasProfiles = false;           // whether any profiles exist (for navigation)
let lastPinnedActions = null;
let streamingAutoScroll = true;
let pendingUserTimestamp = null;   // { div, time } — deferred until AI responds
let sendMessageTimestamp = null;   // ms since epoch when user sent last message (for tab-switch recovery)
let lastChunkTimestamp = null;     // ms since epoch of last received chunk
let skipAbortHandler = false;      // set by stream recovery to silence the abort catch
let migrationInputLocked = false;  // true while embedding migration is actively running

// Spinner frames
const SPINNER_FRAMES = ['\u2819', '\u2839', '\u2838', '\u283C', '\u2834', '\u2826', '\u2827', '\u2807', '\u280F'];
let spinnerIndex = 0;

// =============================================================================
// MODEL SELECTOR STATE
// =============================================================================

// Alt model definitions for "Others" swap
const MODEL_SELECTOR_MAIN_HTML = null; // set on DOMContentLoaded
const MODEL_SELECTOR_ALT = [
    { id: 'claude-opus-4-7', icon: 'assets/model-opus.svg', name: 'Opus', version: '4.7' },
    { id: 'claude-opus-4-6', icon: 'assets/model-opus.svg', name: 'Opus', version: '4.6' },
    { id: 'claude-sonnet-4-6', icon: 'assets/model-sonnet.svg', name: 'Sonnet', version: '4.6' },
];
let modelSelectorShowingOthers = false;
const FABLE_DOT_SRC = 'data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 22 22%22%3E%3Ccircle cx=%2211%22 cy=%2211%22 r=%2211%22 fill=%22%23d97757%22/%3E%3C/svg%3E';

function modelFamilyFromId(modelId) {
    const match = (modelId || '').match(/claude-([a-z]+)/i);
    const family = match ? match[1].toLowerCase() : 'sonnet';
    return ['fable', 'opus', 'sonnet', 'haiku'].includes(family) ? family : 'sonnet';
}

function parseModelDisplay(modelId) {
    const id = modelId || '';
    const newFmt = id.match(/^claude-([a-z]+)-(\d+)-(\d+)/i);
    const singleFmt = !newFmt && id.match(/^claude-([a-z]+)-(\d+)$/i);

    if (newFmt) {
        return {
            name: newFmt[1].charAt(0).toUpperCase() + newFmt[1].slice(1),
            version: `${newFmt[2]}.${newFmt[3]}`
        };
    }
    if (singleFmt) {
        return {
            name: singleFmt[1].charAt(0).toUpperCase() + singleFmt[1].slice(1),
            version: singleFmt[2]
        };
    }
    return { name: '', version: '' };
}

function setModelIconImage(img, family) {
    if (!img) return;
    if (family === 'fable') {
        img.src = FABLE_DOT_SRC;
        img.classList.add('model-icon-dot');
        return;
    }
    img.classList.remove('model-icon-dot');
    img.src = `assets/model-${family}.svg`;
}

function createModelIconElement(family, size = 18) {
    if (family === 'fable') {
        const dot = document.createElement('span');
        dot.className = 'model-icon-dot';
        dot.setAttribute('aria-hidden', 'true');
        dot.style.width = `${size}px`;
        dot.style.height = `${size}px`;
        return dot;
    }

    const icon = document.createElement('img');
    icon.src = `assets/model-${family}.svg`;
    icon.alt = '';
    icon.width = size;
    icon.height = size;
    return icon;
}

async function copyTextToClipboard(text) {
    const value = String(text ?? '');

    if (navigator.clipboard && navigator.clipboard.writeText) {
        try {
            await navigator.clipboard.writeText(value);
            return true;
        } catch (err) {
            console.warn('Navigator clipboard failed, trying fallback:', err);
        }
    }

    const textArea = document.createElement('textarea');
    textArea.value = value;
    textArea.setAttribute('readonly', '');
    textArea.style.position = 'fixed';
    textArea.style.top = '-9999px';
    textArea.style.left = '-9999px';
    textArea.style.opacity = '0';
    document.body.appendChild(textArea);

    const selection = document.getSelection();
    const previousRanges = [];
    if (selection) {
        for (let i = 0; i < selection.rangeCount; i++) {
            previousRanges.push(selection.getRangeAt(i));
        }
    }

    textArea.focus();
    textArea.select();
    textArea.setSelectionRange(0, textArea.value.length);

    let copied = false;
    try {
        copied = document.execCommand('copy');
    } finally {
        document.body.removeChild(textArea);
        if (selection) {
            selection.removeAllRanges();
            previousRanges.forEach(range => selection.addRange(range));
        }
    }

    if (!copied) {
        throw new Error('Browser copy command failed');
    }

    return true;
}

function openModelSelector() {
    modelSelectorWrap.classList.add('active');
    modelBadge.style.display = 'none';
    bindModelSelectorHover();
}

function closeModelSelectors() {
    modelSelectorWrap.classList.remove('active');
    modelBadge.style.display = '';
    // Reset to main models if showing others
    if (modelSelectorShowingOthers) {
        modelSelectorShowingOthers = false;
        modelSelector.innerHTML = modelSelector._mainHTML;
        modelOthersBtn.textContent = 'Others';
        bindModelSelectorHover();
    }
}

function openProfileSelectorWrap() {
    profileSelectorWrap.classList.add('active');
    profileBadge.style.display = 'none';
}

function closeProfileSelectorWrap() {
    profileSelectorWrap.classList.remove('active');
    profileBadge.style.display = '';
}

function bindModelSelectorHover() {
    const items = modelSelector.querySelectorAll('.model-selector-item');
    items.forEach(item => {
        item.addEventListener('mouseenter', () => {
            items.forEach(i => i.classList.remove('model-hover'));
            item.classList.add('model-hover');
        });
    });
}

async function selectModel(modelId) {
    closeModelSelectors();
    try {
        const res = await fetch('/api/set-model', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model_id: modelId })
        });
        if (!res.ok) {
            const data = await res.json().catch(() => ({}));
            throw new Error(data.error || 'Failed to switch model');
        }
        const data = await res.json();
        updateModelBadge(data.model || modelId);
        await loadSettingsValues();
        return;
    } catch (e) {
        showError(e.message || 'Failed to switch model');
    }
}

function updateModelBadge(modelId) {
    // New format (two version segments): claude-{family}-{major}-{minor}[-{date}]  e.g. claude-sonnet-4-6, claude-haiku-4-5-20251001
    // Single-segment format: claude-{family}-{version}  e.g. claude-fable-5
    // Old format: claude-{major}-{family}-{date}            e.g. claude-3-opus-20240229
    let name = '', version = '';

    const newFmt = modelId.match(/^claude-([a-z]+)-(\d+)-(\d+)/i);
    const singleFmt = !newFmt && modelId.match(/^claude-([a-z]+)-(\d+)$/i);
    const oldFmt = !newFmt && !singleFmt && modelId.match(/^claude-(\d+)-([a-z]+)/i);

    if (newFmt) {
        name = newFmt[1];
        version = `${newFmt[2]}.${newFmt[3]}`;
    } else if (singleFmt) {
        name = singleFmt[1];
        version = singleFmt[2];
    } else if (oldFmt) {
        name = oldFmt[2];
        version = oldFmt[1];
    } else {
        // Fallback: show raw string
        modelBadgeText.textContent = modelId;
        modelBadgeVersion.textContent = '';
        headerModelLabel.textContent = modelId;
        return;
    }

    const displayName = name.charAt(0).toUpperCase() + name.slice(1);
    modelBadgeText.textContent = displayName;
    modelBadgeVersion.textContent = version;
    setModelIconImage(modelBadgeIcon, modelFamilyFromId(modelId));
    headerModelLabel.textContent = `${displayName} ${version}`;
}

// =============================================================================
// LOADING ANIMATION (Mneme logo)
// =============================================================================

const LOAD_W = 150, LOAD_H = 160;
const LOAD_CX = 75, LOAD_CY = 80;
const LOAD_PATH_R = 59, LOAD_CLIP_R = 74;
const LOAD_BASE_WIDTH = 14;
const LOAD_NOTCH_MIN = 0.55;
const LOAD_TAU = Math.PI * 2;

// Hardcoded tuned values (from prototype sliders)
const LOAD_CFG = {
    spacing: 22, scrollSpeed: 50, wobbleAmp: 0.5,
    widthAmp: 0.75, subs: 20, connSubs: 4, cornerDip: 0.22
};

function loadCircleY(x) {
    const dx = x - LOAD_CX;
    if (Math.abs(dx) >= LOAD_PATH_R) return null;
    const h = Math.sqrt(LOAD_PATH_R * LOAD_PATH_R - dx * dx);
    return { top: LOAD_CY - h, bottom: LOAD_CY + h };
}

function loadPosWobble(px, py, t, amp) {
    return [
        px + Math.sin(t * 0.0020 + py * 0.08 + px * 0.03) * amp,
        py + Math.cos(t * 0.0025 + px * 0.06 + py * 0.02) * amp * 0.6,
    ];
}

function loadWidthWobble(px, py, t, amp) {
    return LOAD_BASE_WIDTH + Math.sin(t * 0.0015 + px * 0.045 + py * 0.065) * amp;
}

function loadSubdivide(x1, y1, x2, y2, n, t, wAmp, pAmp, skipFirst, mode) {
    const pts = [];
    const start = skipFirst ? 1 : 0;
    for (let i = start; i <= n; i++) {
        const f = i / n;
        const bx = x1 + (x2 - x1) * f;
        const by = y1 + (y2 - y1) * f;
        const [wx, wy] = loadPosWobble(bx, by, t, pAmp);
        let w = loadWidthWobble(bx, by, t, wAmp);
        if (mode === 'pillar') w *= LOAD_NOTCH_MIN + (1 - LOAD_NOTCH_MIN) * Math.sin(f * Math.PI);
        else if (mode === 'conn') w *= LOAD_NOTCH_MIN;
        pts.push({ x: wx, y: wy, w });
    }
    return pts;
}

function loadConnectorCurve(x0, y0, x1, y1, n, t, wAmp, pAmp, dip) {
    const sy0 = y0 + (LOAD_CY - y0) * dip;
    const sy1 = y1 + (LOAD_CY - y1) * dip;
    const midX = (x0 + x1) / 2, midY = (y0 + y1) / 2;
    const ctrlY = midY - dip * (LOAD_CY - midY);
    const pts = [];
    for (let i = 0; i <= n; i++) {
        const f = i / n;
        const bx = (1 - f) * (1 - f) * x0 + 2 * f * (1 - f) * midX + f * f * x1;
        const by = (1 - f) * (1 - f) * sy0 + 2 * f * (1 - f) * ctrlY + f * f * sy1;
        const [wx, wy] = loadPosWobble(bx, by, t, pAmp);
        pts.push({ x: wx, y: wy, w: loadWidthWobble(bx, by, t, wAmp) * LOAD_NOTCH_MIN });
    }
    return pts;
}

let loadStartTime = null;

function drawLoadingIcon(canvas, time) {
    if (!canvas) return;
    const { spacing, scrollSpeed, wobbleAmp, widthAmp, subs, connSubs, cornerDip } = LOAD_CFG;

    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    if (canvas.width !== LOAD_W * dpr || canvas.height !== LOAD_H * dpr) {
        canvas.width = LOAD_W * dpr;
        canvas.height = LOAD_H * dpr;
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const offset = (time / 1000 * scrollSpeed) % (spacing * 2);
    const firstGrid = Math.floor((LOAD_CX - LOAD_PATH_R - offset) / spacing) - 1;
    const lastGrid = Math.ceil((LOAD_CX + LOAD_PATH_R - offset) / spacing) + 1;

    const columns = [];
    for (let gi = firstGrid; gi <= lastGrid; gi++) {
        const x = gi * spacing + offset;
        const cy = loadCircleY(x);
        if (!cy) continue;
        const goesUp = ((gi % 2) + 2) % 2 === 0;
        columns.push({ x, yTop: cy.top, yBottom: cy.bottom, goesUp, gi });
    }

    let points = [];

    // Left phantom connector
    if (columns.length >= 1) {
        const first = columns[0];
        const prevGi = first.gi - 1;
        const prevX = prevGi * spacing + offset;
        if (!loadCircleY(prevX)) {
            const edgeX = LOAD_CX - LOAD_PATH_R;
            const edgeDist = edgeX - prevX;
            if (edgeDist > 0 && edgeDist < spacing) {
                const phantomGoesUp = ((prevGi % 2) + 2) % 2 === 0;
                const toY = phantomGoesUp ? first.yTop : first.yBottom;
                for (let i = 0; i < connSubs; i++) {
                    const f = i / connSubs;
                    const bx = edgeX + (first.x - edgeX) * f;
                    const by = LOAD_CY + (toY - LOAD_CY) * f;
                    const [wx, wy] = loadPosWobble(bx, by, time, wobbleAmp);
                    points.push({ x: wx, y: wy, w: loadWidthWobble(bx, by, time, widthAmp) * LOAD_NOTCH_MIN });
                }
            }
        }
    }

    for (let i = 0; i < columns.length; i++) {
        const col = columns[i];
        const sy = col.goesUp ? col.yBottom : col.yTop;
        const ey = col.goesUp ? col.yTop : col.yBottom;
        points = points.concat(loadSubdivide(col.x, sy, col.x, ey, subs, time, widthAmp, wobbleAmp, i > 0, 'pillar'));
        if (i < columns.length - 1) {
            const next = columns[i + 1];
            const fromY = col.goesUp ? col.yTop : col.yBottom;
            const toY = col.goesUp ? next.yTop : next.yBottom;
            points = points.concat(loadSubdivide(col.x, fromY, next.x, toY, connSubs, time, widthAmp, wobbleAmp, true, 'conn'));
        }
    }

    // Right phantom connector
    if (columns.length >= 1) {
        const last = columns[columns.length - 1];
        const nextGi = last.gi + 1;
        const nextX = nextGi * spacing + offset;
        if (!loadCircleY(nextX)) {
            const edgeX = LOAD_CX + LOAD_PATH_R;
            const edgeDist = nextX - edgeX;
            if (edgeDist > 0 && edgeDist < spacing) {
                const endY = last.goesUp ? last.yTop : last.yBottom;
                for (let i = 1; i <= connSubs; i++) {
                    const f = i / connSubs;
                    const bx = last.x + (edgeX - last.x) * f;
                    const by = endY + (LOAD_CY - endY) * f;
                    const [wx, wy] = loadPosWobble(bx, by, time, wobbleAmp);
                    points.push({ x: wx, y: wy, w: loadWidthWobble(bx, by, time, widthAmp) * LOAD_NOTCH_MIN });
                }
            }
        }
    }

    // Edge fade
    const fadeZone = spacing * 0.7;
    for (const p of points) {
        const dist = Math.min(p.x - (LOAD_CX - LOAD_PATH_R), (LOAD_CX + LOAD_PATH_R) - p.x);
        p.w *= 0.8 + 0.2 * Math.max(Math.min(dist / fadeZone, 1), 0);
    }

    // Draw
    ctx.clearRect(0, 0, LOAD_W, LOAD_H);
    ctx.save();
    ctx.beginPath();
    ctx.arc(LOAD_CX, LOAD_CY, LOAD_CLIP_R, 0, LOAD_TAU);
    ctx.clip();
    ctx.strokeStyle = '#d97757';
    ctx.lineCap = 'round';

    for (let i = 0; i < points.length - 1; i++) {
        const p = points[i], q = points[i + 1];
        ctx.lineWidth = (p.w + q.w) / 2;
        ctx.beginPath();
        ctx.moveTo(p.x, p.y);
        ctx.lineTo(q.x, q.y);
        ctx.stroke();
    }

    // Curved connector overlay
    for (let i = 0; i < columns.length - 1; i++) {
        const col = columns[i], next = columns[i + 1];
        const fromY = col.goesUp ? col.yTop : col.yBottom;
        const toY = col.goesUp ? next.yTop : next.yBottom;
        const cPts = loadConnectorCurve(col.x, fromY, next.x, toY, connSubs, time, widthAmp, wobbleAmp, cornerDip);
        for (const p of cPts) {
            const dist = Math.min(p.x - (LOAD_CX - LOAD_PATH_R), (LOAD_CX + LOAD_PATH_R) - p.x);
            p.w *= 0.8 + 0.2 * Math.max(Math.min(dist / fadeZone, 1), 0);
        }
        for (let j = 0; j < cPts.length - 1; j++) {
            const p = cPts[j], q = cPts[j + 1];
            ctx.lineWidth = (p.w + q.w) / 2;
            ctx.beginPath();
            ctx.moveTo(p.x, p.y);
            ctx.lineTo(q.x, q.y);
            ctx.stroke();
        }
    }

    ctx.restore();
}

function drawLoadingFrame(timestamp) {
    if (!loadStartTime) loadStartTime = timestamp;
    drawLoadingIcon(loadingCanvas, timestamp - loadStartTime);
    loadingAnimId = requestAnimationFrame(drawLoadingFrame);
}

function showLoadingAnimation() {
    loadingOverlay.classList.remove('hidden');
    loadStartTime = null;
    loadingAnimId = requestAnimationFrame(drawLoadingFrame);
}

function hideLoadingAnimation() {
    loadingOverlay.classList.add('hidden');
    if (loadingAnimId) {
        cancelAnimationFrame(loadingAnimId);
        loadingAnimId = null;
    }
}

let migrationLockStartTime = null;

function drawMigrationLockFrame(timestamp) {
    if (!migrationLockStartTime) migrationLockStartTime = timestamp;
    drawLoadingIcon(migrationLockCanvas, timestamp - migrationLockStartTime);
    migrationLockAnimId = requestAnimationFrame(drawMigrationLockFrame);
}

function startMigrationLockAnimation() {
    if (migrationLockAnimId || !migrationLockCanvas) return;
    migrationLockStartTime = null;
    migrationLockAnimId = requestAnimationFrame(drawMigrationLockFrame);
}

function stopMigrationLockAnimation() {
    if (migrationLockAnimId) {
        cancelAnimationFrame(migrationLockAnimId);
        migrationLockAnimId = null;
    }
}

function setMigrationInputLocked(locked) {
    if (migrationInputLocked === locked) return;
    migrationInputLocked = locked;
    inputWrapper.classList.toggle('migration-locked', locked);
    if (migrationChatLock) migrationChatLock.hidden = !locked;
    messageInput.disabled = isWaiting || locked;
    sendBtn.disabled = isWaiting || locked;
    attachBtn.disabled = locked;
    fileInput.disabled = locked;

    if (locked) {
        closeBottomDrawer();
        closeCommandsDrawer();
        messageInput.dataset.preMigrationPlaceholder = messageInput.placeholder;
        messageInput.placeholder = 'Migrating memories...';
        startMigrationLockAnimation();
    } else {
        messageInput.placeholder = messageInput.dataset.preMigrationPlaceholder || messageInput.placeholder;
        delete messageInput.dataset.preMigrationPlaceholder;
        stopMigrationLockAnimation();
        if (!isWaiting && chatActive) messageInput.focus();
    }
}

// =============================================================================
// PROFILE MANAGEMENT
// =============================================================================

async function fetchProfiles() {
    try {
        const res = await fetch(`${API_BASE}/api/profiles`);
        if (!res.ok) return null;
        return await res.json();
    } catch (e) {
        console.error('Failed to fetch profiles:', e);
        return null;
    }
}

function renderProfiles(profiles, active) {
    profileCard.innerHTML = '';
    for (const p of profiles) {
        const row = document.createElement('div');
        row.className = 'profile-row' + (p.name === active ? ' active' : '');
        row.dataset.profile = p.name;

        const modelFamily = modelFamilyFromId(p.model);
        const { name: modelName, version: modelVersion } = parseModelDisplay(p.model);

        // Populate badge with active profile
        if (p.name === active) {
            setModelIconImage(profileBadgeIcon, modelFamily);
            profileBadgeText.textContent = p.display_name || p.name;
            profileBadgeModel.textContent = modelName;
            profileBadgeVersion.textContent = modelVersion ? ` ${modelVersion}` : '';
        }

        const icon = createModelIconElement(modelFamily, 18);
        row.appendChild(icon);

        const nameSpan = document.createElement('span');
        nameSpan.className = 'profile-row-name';
        nameSpan.textContent = p.display_name || p.name;
        row.appendChild(nameSpan);

        if (modelName) {
            const modelSpan = document.createElement('span');
            modelSpan.className = 'profile-row-model';
            modelSpan.textContent = modelName;
            row.appendChild(modelSpan);
        }
        if (modelVersion) {
            const verSpan = document.createElement('span');
            verSpan.className = 'profile-row-version';
            verSpan.textContent = modelVersion;
            row.appendChild(verSpan);
        }

        row.addEventListener('click', () => switchProfile(p.name));
        row.addEventListener('mouseenter', () => {
            profileCard.querySelectorAll('.profile-row').forEach(r => r.classList.remove('profile-hover'));
            row.classList.add('profile-hover');
        });
        profileCard.appendChild(row);
    }
}

async function switchProfile(name) {
    showLoadingAnimation();
    try {
        const res = await fetch(`${API_BASE}/api/profiles/switch`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ profile: name })
        });
        if (!res.ok) {
            const data = await res.json();
            throw new Error(data.error || 'Switch failed');
        }

        // Reload everything for the new profile
        messagesContainer.innerHTML = '';
        await loadHistory();
        await loadStats();
        transitionToChatView();
    } catch (e) {
        console.error('Profile switch failed:', e);
        showError('Failed to switch profile: ' + e.message);
    } finally {
        hideLoadingAnimation();
    }
}

async function createProfile(displayName, modelId) {
    showLoadingAnimation();
    try {
        const res = await fetch(`${API_BASE}/api/profiles/create`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: displayName, model: modelId })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Create failed');

        // Reload for new profile
        messagesContainer.innerHTML = '';
        await loadHistory();
        await loadStats();
        hasProfiles = true;
        transitionToChatView();
    } catch (e) {
        console.error('Profile creation failed:', e);
        showError('Failed to create profile: ' + e.message);
    } finally {
        hideLoadingAnimation();
    }
}

function showProfileSelector() {
    startingScreen.classList.add('hidden');
    messagesContainer.classList.add('hidden');
    profileSelector.classList.remove('hidden');
    inputContainer.style.display = 'none';
    statusFloat.classList.add('hidden');
    creationFlowModel = null;
    chatActive = false;
    closeProfileSelectorWrap();
    headerWordmark.style.display = '';
    profileName.style.display = 'none';
    headerModelLabel.style.display = 'none';
    backBtn.style.display = 'none';
    settingsBtnHeader.style.display = 'none';
    forwardBtn.style.display = messagesContainer.children.length > 0 ? '' : 'none';

    // Show greeting immediately (may update with name after fetch)
    profileGreeting.innerHTML = 'Nice to see you!<br>Who will it be?';

    // Fetch and render profiles
    fetchProfiles().then(data => {
        if (!data || !data.profiles) return;
        renderProfiles(data.profiles, data.active);
        const name = data.user_name;
        if (name) {
            profileGreeting.innerHTML = `Nice to see you, ${name}!<br>Who will it be?`;
        }
    }).catch(e => {
        console.error('Profile fetch failed:', e);
    });
}

// Typewriter effect for headline text changes
function typewriterTransition(el, newText, onComplete) {
    const currentText = el.textContent;
    // Add cursor
    let cursor = el.querySelector('.typewriter-cursor');
    if (!cursor) {
        cursor = document.createElement('span');
        cursor.className = 'typewriter-cursor';
        el.appendChild(cursor);
    }

    let i = currentText.length;
    // Phase 1: Backspace
    const backspace = setInterval(() => {
        if (i <= 0) {
            clearInterval(backspace);
            el.textContent = '';
            el.appendChild(cursor);
            let j = 0;
            // Phase 2: Type new text
            const typeIn = setInterval(() => {
                if (j >= newText.length) {
                    clearInterval(typeIn);
                    // Remove cursor after a beat
                    setTimeout(() => { if (cursor.parentNode) cursor.remove(); }, 400);
                    if (onComplete) onComplete();
                    return;
                }
                el.textContent = newText.slice(0, j + 1);
                el.appendChild(cursor);
                j++;
            }, 55);
            return;
        }
        i--;
        el.textContent = currentText.slice(0, i);
        el.appendChild(cursor);
    }, 35);
}

// =============================================================================
// INITIALIZATION
// =============================================================================

async function init() {
    showLoadingAnimation();
    await loadConfig();

    // Check for existing profiles
    const profileData = await fetchProfiles();
    hasProfiles = profileData && profileData.profiles && profileData.profiles.length > 0;

    // Load history first to determine starting view
    const hasHistory = await loadHistory();

    hideLoadingAnimation();

    if (hasHistory) {
        transitionToChatView();
    } else if (!hasProfiles) {
        // Fresh install — show model selector (starting screen)
        showStartingScreen();
    } else {
        // Profiles exist but no history for active one — still go to chat
        transitionToChatView();
    }

    loadStats();
    // Mutual exclusion: if the migration overlay is about to show, defer the
    // mobile notify overlay until migration is dismissed/completed (avoids both
    // overlays stacking on desktop first launch).
    maybeShowMigrationPrompt().then((migrationShown) => {
        if (migrationShown) {
            mobileNotifyPendingAfterMigration = true;
            relocationPendingAfterMigration = true;
        } else {
            showMobileNotifyIfNeeded();
            maybeShowRelocationOffer();
        }
    });
    wireMigrationModal();
    wireRelocationModal();

    // Event listeners
    sendBtn.addEventListener('click', sendMessage);
    errorClose.addEventListener('click', hideError);
    settingsBtnHeader.addEventListener('click', showSettings);
    settingsBackBtn.addEventListener('click', () => {
        if (isSysInstructionsDirty()) {
            showConfirm('You have unsaved changes to the system instructions. Leave without saving?', {
                okLabel: 'Leave',
                onOk: () => hideSettings()
            });
        } else {
            hideSettings();
        }
    });
    const sysInstructionsSaveBtn = document.getElementById('sysInstructionsSaveBtn');
    if (sysInstructionsSaveBtn) sysInstructionsSaveBtn.addEventListener('click', saveSystemInstructions);
    const sysInstructionsResetBtn = document.getElementById('sysInstructionsResetBtn');
    if (sysInstructionsResetBtn) sysInstructionsResetBtn.addEventListener('click', resetSystemInstructionsToTemplate);
    const exportTranscriptBtn = document.getElementById('exportTranscriptBtn');
    if (exportTranscriptBtn) {
        exportTranscriptBtn.addEventListener('click', exportTranscript);
    }
    document.querySelectorAll('#exportTranscriptFormat .transcript-format-option').forEach(btn => {
        btn.addEventListener('click', () => {
            const selector = document.getElementById('exportTranscriptFormat');
            selector?.classList.toggle('markdown-active', btn.dataset.format === 'markdown');
            selector?.classList.toggle('json-active', btn.dataset.format === 'json');
            selector?.querySelectorAll('.transcript-format-option').forEach(option => {
                option.classList.remove('active');
            });
            btn.classList.add('active');
        });
    });

    // Wire slider oninput — show value bubble while adjusting
    const allSliders = [
        'settingRetrieval', 'settingMaxRetrieval',
        'settingMaxEntities', 'settingMaxConcepts', 'settingMaxFiles',
        'settingTemperature', 'settingArchiveAge'
    ];

    // Snap selector click handlers
    document.querySelectorAll('.snap-selector').forEach(container => {
        container.querySelectorAll('.snap-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                container.querySelectorAll('.snap-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
            });
        });
    });
    allSliders.forEach(id => {
        const slider = document.getElementById(id);
        const bubble = document.getElementById(id + 'Value');
        if (!slider || !bubble) return;
        let hideTimer;
        slider.addEventListener('input', () => {
            updateSliderBubble(id, id + 'Value');
            bubble.classList.add('visible');
            clearTimeout(hideTimer);
        });
        slider.addEventListener('pointerup', () => {
            hideTimer = setTimeout(() => bubble.classList.remove('visible'), 1200);
        });
        slider.addEventListener('touchend', () => {
            hideTimer = setTimeout(() => bubble.classList.remove('visible'), 1200);
        });
    });

    // Thinking toggle → hide/show temperature section and thinking budget
    document.getElementById('settingThinkingEnabled').addEventListener('change', (e) => {
        document.getElementById('settingTemperatureSection').style.display = e.target.checked ? 'none' : '';
        document.getElementById('settingThinkingBudgetSection').style.display = e.target.checked ? '' : 'none';
    });

    document.getElementById('settingTestingModel').addEventListener('change', () => {
        updateConversationWindowOptions(getSettingsActiveModel());
    });

    // TTS toggle → show/hide voice link
    document.getElementById('settingTTS').addEventListener('change', (e) => {
        document.getElementById('ttsVoiceLink').style.display = e.target.checked ? '' : 'none';
    });

    // Identity per-field edit buttons (pen icons)
    document.querySelectorAll('#identityFields .setting-field-edit-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const input = document.getElementById(btn.dataset.target);
            if (input.disabled) {
                input.disabled = false;
                input.focus();
            } else {
                input.disabled = true;
            }
        });
    });

    // API key edit button
    document.getElementById('apiKeyEditBtn').addEventListener('click', function() {
        const fields = document.querySelectorAll('#apiKeyFields .setting-text-input');
        const editing = this.classList.toggle('editing');
        this.textContent = editing ? 'Done' : 'Edit';
        fields.forEach(f => {
            f.disabled = !editing;
            if (editing) { f.value = ''; f.type = 'text'; }
            else { f.type = 'password'; }
        });
        if (editing) fields[0].focus();
    });

    // Generalized confirmation overlay — one-shot handlers, no listener stacking
    initSettingsConfirmOverlay();

    // Model default dropdown — confirmation popup
    let pendingModelValue = null;
    const modelDropdown = document.getElementById('settingModelDefault');

    modelDropdown.addEventListener('change', function() {
        const newModel = this.value;
        const label = this.options[this.selectedIndex].text;
        pendingModelValue = { value: newModel, previous: this._previousValue || this.value };
        updateConversationWindowOptions(getSettingsActiveModel());
        showConfirm(`Change default model to ${label}? This affects all new conversations.`, {
            okLabel: 'Change',
            onOk: () => { pendingModelValue = null; },
            onCancel: () => {
                if (pendingModelValue) modelDropdown.value = pendingModelValue.previous;
                updateConversationWindowOptions(getSettingsActiveModel());
                pendingModelValue = null;
            }
        });
    });
    modelDropdown.addEventListener('focus', function() { this._previousValue = this.value; });

    // Retrieval weights bar drag
    initWeightsBar();

    settingsSaveBtn.addEventListener('click', async () => {
        const status = document.getElementById('settingsSaveStatus');
        const thinkingEnabled = document.getElementById('settingThinkingEnabled').checked;
        const payload = {
            // Identity
            user_name: document.getElementById('settingUserName').value,
            instance_name: document.getElementById('settingInstanceName').value,
            // Model
            model_default: document.getElementById('settingModelDefault').value,
            use_testing_model: document.getElementById('settingTestingModel').checked,
            temperature: thinkingEnabled ? 1.0 : parseFloat(document.getElementById('settingTemperature').value),
            // Thinking
            thinking_enabled: thinkingEnabled,
            thinking_budget: getSnapValue('settingThinkingBudget'),
            // Context
            recent_messages_tokens: getSnapValue('settingRecentTokens'),
            // Retrieval
            retrieval_threshold: parseFloat(document.getElementById('settingRetrieval').value),
            max_retrieval_results: parseInt(document.getElementById('settingMaxRetrieval').value),
            max_entities_per_retrieval: parseInt(document.getElementById('settingMaxEntities').value),
            max_concepts_retrieved: parseInt(document.getElementById('settingMaxConcepts').value),
            max_files_displayed: parseInt(document.getElementById('settingMaxFiles').value),
            semantic_weight: parseFloat(document.getElementById('weightSemanticValue').textContent),
            importance_weight: parseFloat(document.getElementById('weightImportanceValue').textContent),
            recency_weight: parseFloat(document.getElementById('weightRecencyValue').textContent),
            entity_match_weight: parseFloat(document.getElementById('weightEntityMatchValue').textContent),
            deep_archive_age_days: parseInt(document.getElementById('settingArchiveAge').value),
            // API Keys (only sent if user edited them — backend ignores masked values)
            anthropic_key: document.getElementById('settingAnthropicKey').value,
            openai_key: document.getElementById('settingOpenaiKey').value,
            elevenlabs_key: document.getElementById('settingElevenlabsKey').value,
            // Features
            concepts_enabled: document.getElementById('settingConcepts').checked,
            entity_summaries_enabled: document.getElementById('settingEntities').checked,
            attachments_enabled: document.getElementById('settingAttachments').checked,
            tts_enabled: document.getElementById('settingTTS').checked,
            timeline_enabled: document.getElementById('settingTimeline').checked,
            notes_enabled: document.getElementById('settingNotes').checked,
            // System
            keep_pc_awake: document.getElementById('settingKeepAwake').checked,
        };
        try {
            const res = await fetch('/api/settings', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload)
            });
            const data = await res.json();
            status.textContent = data.success ? 'Saved.' : (data.error || 'Error saving.');
            setTimeout(() => { status.textContent = ''; }, 3000);
            if (data.success && payload.model_default) {
                const liveModel = payload.use_testing_model ? 'claude-haiku-4-5' : payload.model_default;
                updateModelBadge(liveModel);
                await loadStats();
            }
            // Lock identity fields after save
            document.querySelectorAll('#identityFields .setting-text-input').forEach(f => { f.disabled = true; });
            // Lock and re-mask API key fields after save
            document.querySelectorAll('#apiKeyFields .setting-text-input').forEach(f => { f.disabled = true; f.type = 'password'; });
            const apiEditBtn = document.getElementById('apiKeyEditBtn');
            apiEditBtn.classList.remove('editing');
            apiEditBtn.textContent = 'Edit';
            // Reload to show masked values
            await loadSettingsValues();
        } catch (e) { status.textContent = 'Error saving.'; }
    });

    messageInput.addEventListener('input', () => {
        autoResizeTextarea();
        if (continueToastVisible && messageInput.value.trim().length > 0) {
            hideContinueToast(true);
        }
    });
    autoResizeTextarea();

    stopBtn.addEventListener('click', () => {
        if (isInterrupted) return;  // X mode handled by once-listener in showContinueToast
        if (streamController) streamController.abort();
    });

    // Hide process bar while typing, restore on blur.
    // When the float collapses to height:0 its margins (-60px/-28px) remain, inflating the
    // messages container by 88px (flex:1 absorbs the -88px outer size). At max scroll this
    // pushes the footer bottom to Y ≈ clientHeight - 16 - paddingBottom, which lands right on
    // top of the input with the default 60px CSS padding. Bump to 100px while focused so the
    // footer stays 28px above the input edge regardless of conversation length.
    messageInput.addEventListener('focus', () => {
        if (!statusFloat.classList.contains('hidden') && !statusFloat.classList.contains('expanded')) {
            statusFloat.style.height = '0px';
            messagesContainer.style.paddingBottom = '100px';
        }
        requestAnimationFrame(() => scrollToBottom(true));
        // Fallback: re-scroll after keyboard animation completes (~300ms on iOS/Android).
        // visualViewport.resize fires mid-animation on first open so the RAF above may
        // land before the keyboard has fully settled and padding is final.
        setTimeout(() => scrollToBottom(true), 300);
    });
    messageInput.addEventListener('blur', () => {
        if (!statusFloat.classList.contains('hidden') && !statusFloat.classList.contains('expanded')) {
            updateCollapsedHeight();
            messagesContainer.style.paddingBottom = '';
        }
        requestAnimationFrame(() => scrollToBottom(true));
    });

    // Mobile keyboard: use visualViewport to detect when the keyboard actually opens/closes.
    // When keyboard opens, the float collapses to height:0 (focus listener above) but its
    // negative margins stay active: margin-top:-60px + margin-bottom:-28px = -88px outer size.
    // This inflates the messages container by 88px (flex:1 absorbs it), requiring 88px more
    // padding-bottom to keep the last message's action row scrollable above the input.
    // Float .hidden has margin:0 so no inflation — just the base 120px is enough.
    if (window.visualViewport) {
        window.visualViewport.addEventListener('resize', () => {
            const shrinkage = window.innerHeight - window.visualViewport.height;
            const keyboardOpen = shrinkage > 100;
            if (keyboardOpen) {
                const floatActive = !statusFloat.classList.contains('hidden');
                const extra = floatActive ? 88 : 0;  // abs(margin-top) + abs(margin-bottom)
                messagesContainer.style.paddingBottom = (120 + extra) + 'px';
                requestAnimationFrame(() => scrollToBottom(true));
            } else {
                // Restore focus-time padding if input is still focused with float active,
                // otherwise clear so CSS default (60px) takes over.
                const stillFocused = document.activeElement === messageInput &&
                    !statusFloat.classList.contains('hidden') &&
                    !statusFloat.classList.contains('expanded');
                messagesContainer.style.paddingBottom = stillFocused ? '100px' : '';
            }
        });
    }

    // Keyboard: Shift+Enter to send, Enter for newline
    messageInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    // Command mode: the command line renders coral while typing (mirror layer);
    // a pure single-line command additionally goes full machine voice (Fira)
    messageInput.addEventListener('input', updateInputMirror);
    messageInput.addEventListener('scroll', () => {
        if (!inputMirror.hidden) inputMirror.scrollTop = messageInput.scrollTop;
    });

    // Console scrollers: keep the edge fades tracking the scroll position
    for (const id of ['cmdHome', 'cmdConsoleView']) {
        const el = document.getElementById(id);
        if (el) el.addEventListener('scroll', () => updateEdgeFades(el));
    }

    // Command autocomplete
    messageInput.addEventListener('input', acUpdate);
    messageInput.addEventListener('click', acUpdate);
    messageInput.addEventListener('keydown', acHandleKeydown);
    messageInput.addEventListener('blur', () => setTimeout(acHide, 120));

    // File attachment — + button opens bottom drawer
    attachBtn.addEventListener('click', openBottomDrawer);
    drawerAttachOption.addEventListener('click', () => {
        if (migrationInputLocked) return;
        closeBottomDrawer();
        fileInput.click();
    });
    drawerCommandOption.addEventListener('click', () => {
        if (migrationInputLocked) return;
        closeBottomDrawer();
        openCommandsDrawer();
    });
    bottomDrawerOverlay.addEventListener('click', () => { closeBottomDrawer(); closeCommandsDrawer(); });
    commandsDrawer.addEventListener('click', (e) => {
        const pill = e.target.closest('.cmd-pill');
        if (pill) {
            if (pill.dataset.view === 'files') { runFilesView(); return; }          // structured files grid
            if (pill.dataset.form === 'forget') { renderForgetForm(); return; }     // console forms
            if (pill.dataset.form === 'concept-create') { renderConceptCreateForm(); return; }
            if (pill.dataset.exec) { runConsoleQuery(pill.dataset.exec); return; }  // console query — drawer stays open
            const cmd = pill.dataset.cmd;
            if (cmd) insertCommand(cmd);
            closeCommandsDrawer();
        }
    });
    document.getElementById('cmdBackBtn').addEventListener('click', consoleBack);
    fileInput.addEventListener('change', handleFileSelect);

    // Drag and drop
    inputContainer.addEventListener('dragover', handleDragOver);
    inputContainer.addEventListener('dragleave', handleDragLeave);
    inputContainer.addEventListener('drop', handleDrop);

    // Paste to attach image
    document.addEventListener('paste', handlePaste);

    // Scroll button
    scrollToBottomBtn.addEventListener('click', () => scrollToBottom());
    messagesContainer.addEventListener('scroll', handleScroll);

    // Detach auto-scroll the instant the user touches or wheels during streaming
    const detachAutoScroll = () => { if (isWaiting) streamingAutoScroll = false; };
    messagesContainer.addEventListener('wheel', detachAutoScroll, { passive: true });
    messagesContainer.addEventListener('touchstart', detachAutoScroll, { passive: true });

    // Status float toggle — on statusFloat itself so it works in both collapsed and expanded states
    // (notification-bar is hidden when expanded, so it can't receive clicks)
    statusFloat.addEventListener('click', toggleStatusLog);
    // Wave pill (visible during streaming) also opens the expanded log
    wavePillEl.addEventListener('click', toggleStatusLog);
    // Scroll-driven fade on expanded status log
    statusLogPanel.addEventListener('scroll', updatePanelFade);

    // Close model selectors on outside click
    document.addEventListener('click', (e) => {
        const inBadge = modelBadge.contains(e.target) || e.target === modelBadge;
        const inWrap  = modelSelectorWrap.contains(e.target);
        if (!inBadge && !inWrap) {
            closeModelSelectors();
        }

        const inProfileBadge = profileBadge.contains(e.target) || e.target === profileBadge;
        const inProfileWrap  = profileSelectorWrap.contains(e.target);
        if (!inProfileBadge && !inProfileWrap) {
            closeProfileSelectorWrap();
        }
    });

    // Model badge click -> open main selector
    modelBadge.addEventListener('click', (e) => {
        e.stopPropagation();
        openModelSelector();
    });

    // Profile badge click -> open profile list
    profileBadge.addEventListener('click', (e) => {
        e.stopPropagation();
        openProfileSelectorWrap();
    });

    // Store main HTML for swap-back, then bind hover
    modelSelector._mainHTML = modelSelector.innerHTML;
    bindModelSelectorHover();

    // Others/Back button — swap card contents
    modelOthersBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        if (modelSelectorShowingOthers) {
            // Back to main
            modelSelectorShowingOthers = false;
            modelSelector.innerHTML = modelSelector._mainHTML;
            modelOthersBtn.textContent = 'Others';
        } else {
            // Show alt models
            modelSelectorShowingOthers = true;
            modelSelector.innerHTML = MODEL_SELECTOR_ALT.map(m =>
                `<button class="model-selector-item" data-model-id="${m.id}">
                    <img src="${m.icon}" alt="" width="18" height="18">
                    <span class="model-name">${m.name}</span><span class="model-version"> ${m.version}</span>
                </button>`
            ).join('');
            modelOthersBtn.textContent = 'Back';
        }
        bindModelSelectorHover();
    });

    // Model item click -> select model (also triggers creation flow if on starting screen)
    document.addEventListener('click', (e) => {
        const item = e.target.closest('.model-selector-item[data-model-id]');
        if (!item) return;
        e.stopPropagation();
        const modelId = item.dataset.modelId;

        if (!startingScreen.classList.contains('hidden')) {
            // On starting screen: update badge UI only (don't persist to active profile),
            // then begin profile creation flow
            updateModelBadge(modelId);
            startProfileCreationFlow(modelId);
        } else {
            selectModel(modelId);
        }
    });

    // Back button — go to profile selector (or starting screen if no profiles)
    backBtn.addEventListener('click', () => {
        if (hasProfiles) {
            showProfileSelector();
        } else {
            showStartingScreen();
        }
    });

    forwardBtn.addEventListener('click', () => {
        transitionToChatView();
    });

    // Profile selector: "New instance" button
    profileNewInstance.addEventListener('click', () => {
        showStartingScreen();
    });

    // Profile creation: Enter key in input submits the name
    messageInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey && creationFlowModel) {
            e.preventDefault();
            const name = messageInput.value.trim();
            if (!name) return;
            messageInput.value = '';
            const model = creationFlowModel;
            creationFlowModel = null;
            createProfile(name, model);
        }
    });

    messageInput.focus();
}

// =============================================================================
// STARTING SCREEN / CHAT VIEW TRANSITION
// =============================================================================

function showStartingScreen() {
    startingScreen.classList.remove('hidden');
    profileSelector.classList.add('hidden');
    messagesContainer.classList.add('hidden');
    inputContainer.style.display = 'none';
    statusFloat.classList.add('hidden');
    chatActive = false;
    headerWordmark.style.display = 'none';
    profileName.style.display = '';
    headerModelLabel.style.display = '';
    creationFlowModel = null;
    // Reset headline
    startingHeadline.textContent = 'Pick a model and we can get started!';
    // Back button: go to profile selector if profiles exist
    backBtn.style.display = hasProfiles ? '' : 'none';
    settingsBtnHeader.style.display = 'none';
    forwardBtn.style.display = messagesContainer.children.length > 0 ? '' : 'none';
}

function transitionToChatView() {
    startingScreen.classList.add('hidden');
    profileSelector.classList.add('hidden');
    messagesContainer.classList.remove('hidden');
    inputContainer.style.display = '';
    chatActive = true;
    creationFlowModel = null;
    headerWordmark.style.display = 'none';
    profileName.style.display = '';
    headerModelLabel.style.display = '';
    backBtn.style.display = '';
    settingsBtnHeader.style.display = '';
    forwardBtn.style.display = 'none';
}

function startProfileCreationFlow(modelId) {
    creationFlowModel = modelId;
    closeModelSelectors();
    forwardBtn.style.display = 'none';
    backBtn.style.display = '';

    // Typewriter-transition the headline, then reveal input for naming
    typewriterTransition(startingHeadline, 'What should we call this instance?', () => {
        // Reveal input for name entry
        inputContainer.style.display = '';
        inputContainer.style.height = '32px';
        requestAnimationFrame(() => {
            requestAnimationFrame(() => {
                inputContainer.style.height = '';  // restore natural height
            });
        });
        messageInput.placeholder = 'Name this instance...';
        messageInput.value = '';
        messageInput.focus();
    });
}

// =============================================================================
// STATUS LOG / NOTIFICATION BAR
// =============================================================================

function ensureViewsWrapper() {
    if (statusViewsWrapper) return;
    statusViewsWrapper = document.createElement('div');
    statusViewsWrapper.className = 'status-views-wrapper';
    statusViewsWrapper.id = 'statusViewsWrapper';

    statusProcessList = document.createElement('div');
    statusProcessList.className = 'status-process-list';
    statusProcessList.id = 'statusProcessList';

    statusDetailPanel = document.createElement('div');
    statusDetailPanel.className = 'status-detail-panel';
    statusDetailPanel.id = 'statusDetailPanel';

    processBackBtn = document.createElement('button');
    processBackBtn.className = 'process-back-btn';
    processBackBtn.id = 'processBackBtn';
    processBackBtn.setAttribute('aria-label', 'Back to process list');
    processBackBtn.addEventListener('click', (e) => { e.stopPropagation(); hideDetailView(); });

    processDetailContent = document.createElement('div');
    processDetailContent.className = 'process-detail-content';
    processDetailContent.id = 'processDetailContent';

    statusDetailPanel.appendChild(processBackBtn);
    statusDetailPanel.appendChild(processDetailContent);

    statusViewsWrapper.appendChild(statusProcessList);
    statusViewsWrapper.appendChild(statusDetailPanel);

    statusLogPanel.appendChild(statusViewsWrapper);
}

function toggleStatusLog() {
    statusLogExpanded = !statusLogExpanded;
    if (statusLogExpanded) {
        // Expand into floating cube — position absolutely above input
        statusFloat.classList.add('expanded');
        statusLogPanel.classList.add('expanded');
        const parentRect = statusFloat.offsetParent.getBoundingClientRect();
        const inputRect = inputContainer.getBoundingClientRect();
        statusFloat.style.bottom = Math.round(parentRect.bottom - inputRect.top) + 'px';
        // Cap panel height so the float doesn't overflow above viewport
        const headerHeight = 60;
        const floatChrome = 80; // notification bar + padding
        const available = inputRect.top - headerHeight - floatChrome;
        statusLogPanel.style.maxHeight = Math.max(200, available) + 'px';
        scrollToBottomBtn.style.bottom = '';  // float is absolute, no overlap
        // Re-check fade after max-height transition finishes (not mid-animation)
        statusLogPanel.addEventListener('transitionend', updatePanelFade, { once: true });
    } else {
        // Collapse back to slim bar
        hideDetailView();
        statusFloat.classList.remove('expanded');
        statusLogPanel.classList.remove('expanded');
        statusFloat.style.bottom = '';
        statusFloat.style.marginTop = '';
        statusLogPanel.style.maxHeight = '';
        // Re-measure and set collapsed height
        updateCollapsedHeight();
    }
}

function updatePanelFade() {
    const p = statusLogPanel;
    const scrollable = p.scrollHeight > p.clientHeight + 1;
    p.classList.toggle('fade-top', scrollable && p.scrollTop > 4);
    p.classList.toggle('fade-bottom', scrollable && p.scrollTop + p.clientHeight < p.scrollHeight - 4);
}

function showNotificationBar() {
    // Remove hidden class (first activation) and switch to active
    statusFloat.classList.remove('hidden');
    notificationBar.classList.add('active');
    // Measure and animate height from 0 → notification bar height
    requestAnimationFrame(() => {
        updateCollapsedHeight();
    });
}

function hideNotificationBar() {
    // Collapse expanded state if open
    if (statusLogExpanded) {
        hideDetailView();
        statusFloat.classList.remove('expanded');
        statusLogPanel.classList.remove('expanded');
        statusFloat.style.bottom = '';
        statusFloat.style.marginTop = '';
        statusLogPanel.style.maxHeight = '';
        statusLogExpanded = false;
    }
    // Deactivate (spinner off) — bar stays visible with last status
    notificationBar.classList.remove('active');
    updateCollapsedHeight();
}

/**
 * Measure notification bar height and apply to status-float for smooth transitions.
 * Adds 12px for the portion tucked behind input (margin-bottom: -12px in CSS).
 */
function updateCollapsedHeight() {
    if (statusFloat.classList.contains('hidden') ||
        statusFloat.classList.contains('expanded') ||
        statusFloat.classList.contains('wave-active')) return;
    const h = notificationBar.offsetHeight;
    statusFloat.style.height = (h + 28) + 'px';
    // Keep scroll button above the visible notification bar (not just above the input)
    scrollToBottomBtn.style.bottom = `calc(100% + ${h + 10}px)`;
}

/**
 * Add a line to the status log panel
 */
function addStatusLine(text, type = 'info', structuredData) {
    const line = document.createElement('div');
    line.className = `status-log-line log-${type}`;
    line.textContent = text;

    if (structuredData) {
        line.dataset.processId = structuredData.id;
        line._processData = structuredData;  // Store full object for Phase B
        if (structuredData.detail) {
            line.classList.add('has-detail');  // Phase B will add click handler
        }
    }

    ensureViewsWrapper();
    statusProcessList.appendChild(line);
    statusProcessList.scrollTop = statusProcessList.scrollHeight;

    // Update notification bar text with latest (no timestamp — keep it clean)
    statusLogHeaderText.textContent = text;

    // Mirror to wave pill during streaming pre-wave flat phase (hidden during sine animation)
    if (inputContainer.classList.contains('streaming') && !isInterrupted && !waveActivated) {
        const pillText = (structuredData && structuredData.pill) ? structuredData.pill : text;
        if (wavePillEl.style.display === 'none') {
            showWavePill(pillText);
        } else {
            wavePillTextEl.textContent = pillText;
        }
    }

    // Re-measure collapsed height for smooth row-count transitions
    requestAnimationFrame(() => {
        updateCollapsedHeight();
    });
}

function clearStatusLog() {
    if (statusProcessList) {
        statusProcessList.innerHTML = '';
    } else {
        statusLogPanel.innerHTML = '';
    }
    hideDetailView();
    statusLogHeaderText.textContent = 'pipeline';
}

function startSpinner() {
    spinnerIndex = 0;
    statusSpinner.textContent = SPINNER_FRAMES[0];
    spinnerInterval = setInterval(() => {
        spinnerIndex = (spinnerIndex + 1) % SPINNER_FRAMES.length;
        statusSpinner.textContent = SPINNER_FRAMES[spinnerIndex];
    }, 80);
}

function stopSpinner() {
    if (spinnerInterval) {
        clearInterval(spinnerInterval);
        spinnerInterval = null;
    }
    statusSpinner.textContent = '';
}

/**
 * Strip emoji from notification text
 */
function stripNotificationEmoji(text) {
    return text.replace(/^[🔄🧠💭🤖✅⚠️❌↳📎💬🔍📊🗃️⏳📝🔧]+\s*/u, '').trim();
}

/**
 * Determine log type from notification text
 */
function getNotificationType(text) {
    const lower = text.toLowerCase();
    // Check 'special' before 'error' — concept/entity notifications can contain
    // words like "failed" or "error" in their content without being errors
    if (lower.includes('concept') || lower.includes('notes cleanup') ||
        lower.includes('injection') || lower.includes('reminder') ||
        lower.includes('entity summar') || lower.includes('daily summary') ||
        lower.includes('background') || lower.includes('day rollover') ||
        lower.includes('new entities') || lower.includes('entity links')) {
        return 'special';
    }
    if (text.includes('❌') || lower.includes('error') || lower.includes('failed')) {
        return 'error';
    }
    if (text.includes('⚠️') || lower.includes('miss') || lower.includes('warning') ||
        lower.includes('skipped') || lower.includes('cleanup may trigger') ||
        lower.includes('disabled') || lower.includes('no relevant memories')) {
        return 'warning';
    }
    if (text.includes('✅') || lower.includes('found') || lower.includes('loaded') ||
        lower.includes('generated') || lower.includes('processed') ||
        lower.includes('complete') || lower.includes('queued') ||
        lower.includes('cache hit') || lower.includes('saved')) {
        return 'success';
    }
    return 'info';
}

/**
 * Map a notification from SSE to a status log line.
 * Accepts either a legacy string or a structured notification object (Phase A+).
 */
function handleNotificationAsLog(data) {
    // Handle structured notification object (Phase A+)
    if (data && typeof data === 'object' && data.id) {
        addStructuredStatusLine(data);
        return;
    }
    // Legacy string format
    const text = typeof data === 'string' ? data : String(data);
    const type = getNotificationType(text);
    const cleanText = stripNotificationEmoji(text);
    addStatusLine(cleanText.toLowerCase(), type);
}

/**
 * rAF-paced notification display — one notification per animation frame so each
 * gets its own browser repaint, preventing TCP-batched notifications from collapsing
 * into a single visible update.
 */
function drainNotifQueue() {
    if (notifDisplayQueue.length === 0) {
        notifQueueActive = false;
        return;
    }
    handleNotificationAsLog(notifDisplayQueue.shift());
    requestAnimationFrame(drainNotifQueue);
}

function queueNotifDisplay(text) {
    notifDisplayQueue.push(text);
    if (!notifQueueActive) {
        notifQueueActive = true;
        requestAnimationFrame(drainNotifQueue);
    }
}

function addStructuredStatusLine(data) {
    ensureViewsWrapper();

    // Update pill/header even for noLog items, but don't add a log line
    if (data.noLog) {
        statusLogHeaderText.textContent = data.pill || data.summary || '';
        if (inputContainer.classList.contains('streaming') && !isInterrupted && !waveActivated) {
            const pillText = data.pill || data.summary || '';
            if (wavePillEl.style.display === 'none') {
                showWavePill(pillText);
            } else {
                wavePillTextEl.textContent = pillText;
            }
        }
        return;
    }

    const line = document.createElement('div');
    line.className = 'status-process-line';
    if (data.detail) line.classList.add('has-detail');
    line.dataset.processId = data.id;
    line._processData = data;

    const summaryEl = document.createElement('span');
    summaryEl.className = 'process-summary';
    summaryEl.textContent = data.summary || data.pill || '';
    line.appendChild(summaryEl);

    if (data.detail) {
        const chevron = document.createElement('span');
        chevron.className = 'process-chevron';
        chevron.textContent = '\u203a';
        line.appendChild(chevron);
        line.addEventListener('click', (e) => { e.stopPropagation(); showDetailView(data); });
    }

    statusProcessList.appendChild(line);
    statusProcessList.scrollTop = statusProcessList.scrollHeight;

    // Update header text with pill (short)
    statusLogHeaderText.textContent = data.pill || data.summary || '';
    requestAnimationFrame(() => {
        updateCollapsedHeight();
    });

    // Update wave pill (when in flat-line phase)
    if (inputContainer.classList.contains('streaming') && !isInterrupted && !waveActivated) {
        const pillText = data.pill || data.summary || '';
        if (wavePillEl.style.display === 'none') {
            showWavePill(pillText);
        } else {
            wavePillTextEl.textContent = pillText;
        }
    }
}

function showDetailView(data) {
    ensureViewsWrapper();
    statusDetailVisible = true;

    // Populate detail content
    processDetailContent.innerHTML = '';

    // Explanation paragraph
    if (data.detail && data.detail.explanation) {
        const explanation = document.createElement('p');
        explanation.className = 'process-explanation';
        explanation.textContent = data.detail.explanation;
        processDetailContent.appendChild(explanation);
    }

    // Item cards
    if (data.detail && data.detail.items && data.detail.items.length > 0) {
        data.detail.items.forEach(item => {
            const card = document.createElement('div');
            card.className = 'process-item-card';
            if (item.sender) card.dataset.sender = item.sender;  // omit for info items → all-rounded corners

            const cardInner = document.createElement('div');
            cardInner.className = 'process-item-card-inner';

            // Sender label only for actual messages (items with sender field)
            if (item.sender) {
                const senderEl = document.createElement('p');
                senderEl.className = 'process-item-sender';
                senderEl.textContent = item.sender === 'user' ? 'You:' : (window._instanceName || 'Assistant') + ':';
                cardInner.appendChild(senderEl);
            }

            const contentEl = document.createElement('p');
            contentEl.className = 'process-item-content';
            let contentText = item.content || '';
            contentText = contentText.replace(/^(user|assistant):\s*/i, '');
            // Quotes only for message content (items with a sender)
            if (item.sender) {
                contentEl.textContent = '\u201c' + contentText + '\u201d';
            } else {
                contentEl.textContent = contentText;
            }
            cardInner.appendChild(contentEl);

            card.appendChild(cardInner);

            // Footer: only show when there's a timestamp (label alone is redundant)
            if (item.timestamp) {
                const footer = document.createElement('p');
                footer.className = 'process-item-footer';
                const footerParts = [];
                if (item.label) footerParts.push(item.label);
                footerParts.push(formatMemoryTimestamp(item.timestamp));
                footer.textContent = footerParts.join(' \u00b7 ');
                card.appendChild(footer);
            }

            processDetailContent.appendChild(card);
        });
    }

    // Slide to detail view
    statusViewsWrapper.classList.add('detail-visible');
    // Ensure detail panel scrolls from top
    processDetailContent.scrollTop = 0;
    statusDetailPanel.scrollTop = 0;

    // Resize wrapper to fit detail content (float hugs content)
    requestAnimationFrame(() => {
        requestAnimationFrame(() => {
            const h = statusDetailPanel.scrollHeight;
            if (h > 0) statusViewsWrapper.style.height = h + 'px';
        });
    });
}

function hideDetailView() {
    if (!statusViewsWrapper) return;
    statusDetailVisible = false;
    statusViewsWrapper.classList.remove('detail-visible');
    statusViewsWrapper.style.height = '';  // back to auto (driven by process list)
    statusLogPanel.addEventListener('transitionend', updatePanelFade, { once: true });
}

function formatMemoryTimestamp(iso) {
    if (!iso) return '';
    try {
        const d = new Date(iso);
        const hours = d.getHours();
        const timeOfDay = hours < 5 ? 'at night' :
            hours < 12 ? 'in the morning' :
            hours < 17 ? 'in the afternoon' :
            hours < 21 ? 'in the evening' : 'at night';
        const day = d.getDate();
        const suffix = day === 1 || day === 21 || day === 31 ? 'st' :
            day === 2 || day === 22 ? 'nd' :
            day === 3 || day === 23 ? 'rd' : 'th';
        const months = ['January', 'February', 'March', 'April', 'May', 'June',
            'July', 'August', 'September', 'October', 'November', 'December'];
        return `${timeOfDay} on the ${day}${suffix} of ${months[d.getMonth()]} ${d.getFullYear()}`;
    } catch (e) {
        return '';
    }
}

// =============================================================================
// TEXTAREA & INPUT
// =============================================================================

function autoResizeTextarea() {
    messageInput.style.height = '1px';
    messageInput.style.height = messageInput.scrollHeight + 'px';

    if (messageInput.value.trim().length > 0) {
        sendBtn.classList.add('has-text');
    } else {
        sendBtn.classList.remove('has-text');
    }
}

// =============================================================================
// CONFIG
// =============================================================================

async function loadConfig() {
    try {
        const response = await fetch(`${API_BASE}/api/config`);
        if (response.ok) {
            const config = await response.json();
            streamingEnabled = config.streaming_enabled || false;
            ttsEnabled = config.tts_enabled || false;
            thinkingEnabled = config.thinking_enabled || false;
            showThinking = config.show_thinking !== false;
        }
    } catch (error) {
        console.warn('Failed to load config, using defaults:', error);
        streamingEnabled = false;
        ttsEnabled = false;
    }
}

// =============================================================================
// SEND MESSAGE
// =============================================================================

let interceptInFlight = false;  // guards against a double-tap re-firing interceptFormCommand's await

async function sendMessage() {
    if (migrationInputLocked) return;
    const message = messageInput.value.trim();

    // Profile creation flow: send button creates the profile
    if (creationFlowModel && message) {
        messageInput.value = '';
        const model = creationFlowModel;
        creationFlowModel = null;
        createProfile(message, model);
        return;
    }

    if ((!message && pendingFiles.length === 0) || isWaiting) {
        return;
    }

    // Typed form-summoning commands: a bare "@concept create" or
    // "@concept edit <name>" (no | arguments) opens the console form
    // instead of sending a doomed usage-error round-trip.
    // interceptInFlight guards against a double-tap firing the network
    // lookup (and its form/console push) twice while the await is pending.
    if (pendingFiles.length === 0) {
        if (interceptInFlight) return;  // drop the duplicate tap outright
        interceptInFlight = true;
        try {
            if (await interceptFormCommand(message)) return;
        } finally {
            interceptInFlight = false;
        }
    }

    // Transition to chat view on first message
    if (!chatActive) {
        transitionToChatView();
    }

    streamingAutoScroll = true;
    sendMessageTimestamp = Date.now();
    lastChunkTimestamp = null;
    setWaiting(true);

    let sentMessageEl = null;
    let attachmentMeta = [];

    try {
        let uploadedUuids = [];
        let finalMessage = message;
        if (pendingFiles.length > 0) {
            // Capture metadata (including object URLs for thumbnails) BEFORE upload clears pendingFiles
            attachmentMeta = pendingFiles.map(f => ({
                name: f.name,
                type: f.type,
                objectUrl: f.type.startsWith('image/') ? URL.createObjectURL(f) : null
            }));
            addStatusLine(`uploading ${pendingFiles.length} ${pendingFiles.length === 1 ? 'file' : 'files'}`, 'info');
            uploadedUuids = await uploadPendingFiles();
        }

        // Show message bubble for text or file-only sends — no file-note injection
        if (message || uploadedUuids.length > 0) {
            sentMessageEl = addMessage('user', message, true, null, null, attachmentMeta);
        }

        messageInput.value = '';
        messageInput.style.height = 'auto';
        updateInputMirror();
        sendBtn.classList.remove('has-text');

        if (message || uploadedUuids.length > 0) {
            if (streamingEnabled) {
                await sendMessageStreaming(message || '', uploadedUuids);
            } else {
                await sendMessageNonStreaming(message || '', uploadedUuids);
            }
        }
    } catch (error) {
        // User aborted stream — save partial + continue toast, or remove bubble if pre-API
        if (error.name === 'AbortError') {
            if (skipAbortHandler) { skipAbortHandler = false; return; }
            await handleStreamAbort(null, sentMessageEl);
            return;
        }

        // Durable stream reconnect (v1): another turn is already generating for
        // this profile (backend returned 409). Roll back this send and tell the
        // user to wait — don't touch the in-flight turn.
        if (error.message === 'GENERATION_IN_PROGRESS') {
            if (sentMessageEl) {
                sentMessageEl.remove();
                pendingUserTimestamp = null;
            }
            attachmentMeta.forEach(att => {
                if (att.objectUrl) URL.revokeObjectURL(att.objectUrl);
            });
            messageInput.value = message;
            if (message) sendBtn.classList.add('has-text');
            addStatusLine('Mneme is still writing — please wait a moment', 'warning');
            return;
        }

        console.error('Error sending message:', error);

        // Durable stream reconnect (v1): a network error (socket death) may just
        // mean the client dropped while the backend keeps generating. If a turn
        // is still in flight for this profile, KEEP the user bubble, show the
        // "still writing" indicator and wait for the turn to land — do NOT run
        // the destructive orphan-cleanup/restore path.
        try {
            if (await isGenerationActive()) {
                addStatusLine('reconnecting — Mneme kept writing', 'info');
                await waitForGenerationThenReload();
                return;
            }
        } catch (statusErr) {
            console.warn('generation-status check failed:', statusErr);
        }

        // Roll back the optimistically added user bubble
        if (sentMessageEl) {
            sentMessageEl.remove();
            pendingUserTimestamp = null;   // clear stale reference
        }

        // Revoke any pending attachment objectUrls (in case addMessage was never reached)
        attachmentMeta.forEach(att => {
            if (att.objectUrl) URL.revokeObjectURL(att.objectUrl);
        });

        addStatusLine('send failed — message restored', 'warning');

        // Clean orphans from DB and restore the newest message text to input
        try {
            const cleanupResp = await fetch(`${API_BASE}/api/messages/cleanup-orphans`, { method: 'POST' });
            if (cleanupResp.ok) {
                const cleanup = await cleanupResp.json();
                const restored = cleanup.restored_text || message;
                messageInput.value = restored;
                if (restored) sendBtn.classList.add('has-text');
            } else {
                messageInput.value = message;
                if (message) sendBtn.classList.add('has-text');
            }
        } catch (cleanupErr) {
            console.error('Orphan cleanup failed:', cleanupErr);
            messageInput.value = message;
            if (message) sendBtn.classList.add('has-text');
        }
    } finally {
        setWaiting(false);
    }
}

// =============================================================================
// STREAMING
// =============================================================================

async function sendMessageStreaming(message, attachmentUuids = []) {
    streamController = new AbortController();
    partialResponse = '';
    currentStreamThinking = '';
    currentAssistantMessage = null;

    const response = await fetch(`${API_BASE}/api/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message, attachment_uuids: attachmentUuids }),
        signal: streamController.signal
    });

    if (response.status === 409) {
        // Durable stream reconnect (v1): a turn is already generating for this
        // profile (likely another tab/device). Don't double-generate.
        throw new Error('GENERATION_IN_PROGRESS');
    }

    if (!response.ok) {
        throw new Error(`Server error: ${response.status}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let thinkingStartTime = null;
    let currentThinkingBlock = null;

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\n\n');
        buffer = lines.pop();

        for (const line of lines) {
            if (!line.trim() || !line.startsWith('data: ')) continue;

            try {
                const jsonData = line.substring(6);
                const event = JSON.parse(jsonData);

                if (event.type === 'notification') {
                    // Parse structured notification objects (Phase A+); fall back to raw string
                    let notifData = event.data;
                    try {
                        const parsed = JSON.parse(event.data);
                        if (parsed && typeof parsed === 'object' && parsed.id) {
                            notifData = parsed;  // Use structured object
                        }
                    } catch (e) {
                        // Not JSON, use raw string
                    }
                    // Immediate side-effects (wave, continuation flag) must not be delayed
                    const notifStr = (notifData && typeof notifData === 'object') ? (notifData.summary || '') : notifData;
                    if (notifStr.startsWith('💭 Calling AI again')) {
                        inContinuationPhase = true;
                        // Keep currentAssistantMessage — continuation chunks append
                        // to the same bubble, matching the single combined message
                        // the backend stores in the DB. Resetting it here used to
                        // create a second bubble that disappeared on refresh.
                        // Add separator to match the "\n\n" the backend inserts
                        // between initial and continuation text when storing.
                        if (currentAssistantMessage) {
                            appendToStreamingMessage(currentAssistantMessage, '\n\n');
                            partialResponse += '\n\n';
                        }
                        currentThinkingBlock = null;
                    }
                    if (notifStr.includes('Cache')) activateWave();
                    // Display one-per-frame so each notification gets its own repaint
                    queueNotifDisplay(notifData);
                } else if (event.type === 'thinking_start') {
                    activateWave();  // fallback: API is responding
                    thinkingStartTime = Date.now();
                    if (!currentAssistantMessage) {
                        currentAssistantMessage = createStreamingMessage();
                    }
                    currentThinkingBlock = createThinkingBlock(currentAssistantMessage);
                } else if (event.type === 'thinking') {
                    currentStreamThinking += event.data;
                    if (currentThinkingBlock) {
                        appendToThinkingBlock(currentThinkingBlock, event.data);
                    }
                } else if (event.type === 'chunk') {
                    lastChunkTimestamp = Date.now();
                    activateWave();  // fallback: API is responding
                    if (currentThinkingBlock && thinkingStartTime) {
                        const elapsed = ((Date.now() - thinkingStartTime) / 1000).toFixed(1);
                        finalizeThinkingBlock(currentThinkingBlock, elapsed);
                        currentThinkingBlock = null;
                        thinkingStartTime = null;
                    }
                    if (!currentAssistantMessage) {
                        currentAssistantMessage = createStreamingMessage();
                    }
                    partialResponse += event.data;
                    appendToStreamingMessage(currentAssistantMessage, event.data);
                } else if (event.type === 'done') {
                    if (currentThinkingBlock && thinkingStartTime) {
                        const elapsed = ((Date.now() - thinkingStartTime) / 1000).toFixed(1);
                        finalizeThinkingBlock(currentThinkingBlock, elapsed);
                        currentThinkingBlock = null;
                        thinkingStartTime = null;
                    }

                    // Remove streaming cursor, stamp timestamp, add action row
                    if (currentAssistantMessage) {
                        const contentDiv = currentAssistantMessage.querySelector('.message-content');
                        if (contentDiv) contentDiv.classList.remove('streaming');
                        const footer = currentAssistantMessage.querySelector('.message-footer');
                        if (footer) {
                            const ts = document.createElement('span');
                            ts.className = 'message-timestamp';
                            ts.textContent = formatTimestamp(new Date());
                            footer.insertBefore(ts, footer.firstChild);
                        }
                        addActionRow(currentAssistantMessage, contentDiv);
                    }

                    // If this done closes a continuation, hide the wave pill
                    if (inContinuationPhase) {
                        hideWavePill();
                        inContinuationPhase = false;
                    }

                    addStatusLine((window._instanceName || 'assistant') + ' recalled and replied', 'success');
                } else if (event.type === 'error') {
                    addStatusLine(`error: ${event.data}`, 'error');
                    throw new Error(event.data);
                }
            } catch (e) {
                if (e instanceof SyntaxError) {
                    console.error('Failed to parse SSE event:', e, line);
                } else {
                    throw e;
                }
            }
        }
    }
}

// =============================================================================
// TAB-SWITCH STREAM RECOVERY
// =============================================================================

document.addEventListener('visibilitychange', async () => {
    if (document.visibilityState !== 'visible') return;
    if (!sendMessageTimestamp) return;

    // Give the stream 2 seconds to resume naturally (Android Chrome keeps streams alive)
    await new Promise(r => setTimeout(r, 2000));

    // Check how long since we last received data
    const staleSince = lastChunkTimestamp
        ? Date.now() - lastChunkTimestamp
        : Date.now() - sendMessageTimestamp;
    if (staleSince < 2000) return; // stream is still active, no recovery needed

    try {
        const resp = await fetch(`${API_BASE}/api/history?limit=2`);
        if (!resp.ok) return;
        const data = await resp.json();
        const msgs = data.messages || [];
        const last = msgs[0];

        if (!last || last.sender !== 'assistant') return;
        if (new Date(last.timestamp).getTime() <= sendMessageTimestamp) return;

        // Check if it's already fully rendered in the DOM
        const lastDomMsg = messagesContainer.lastElementChild;
        if (lastDomMsg?.classList.contains('assistant')) {
            const rendered = lastDomMsg.querySelector('.message-content')?.getAttribute('data-raw-content');
            if (rendered === last.content) return;
        }

        sendMessageTimestamp = null; // prevent double-recovery

        if (isWaiting) {
            // Stream is stalled — fill in the completed response and abort the dead stream
            if (!currentAssistantMessage) currentAssistantMessage = createStreamingMessage();
            const contentDiv = currentAssistantMessage.querySelector('.message-content');
            if (contentDiv) {
                contentDiv.setAttribute('data-raw-content', last.content);
                contentDiv.innerHTML = parseMarkdown(last.content);
                contentDiv.classList.remove('streaming');
            }
            const footer = currentAssistantMessage.querySelector('.message-footer');
            if (footer && !footer.querySelector('.message-timestamp')) {
                const ts = document.createElement('span');
                ts.className = 'message-timestamp';
                ts.textContent = formatTimestamp(new Date(last.timestamp));
                footer.insertBefore(ts, footer.firstChild);
            }
            addActionRow(currentAssistantMessage, contentDiv);
            currentAssistantMessage = null;
            skipAbortHandler = true;
            if (streamController) streamController.abort(); // finally block calls setWaiting(false)
        } else {
            // Stream already died — render missed messages independently
            const userMsg = msgs[1];
            if (userMsg?.sender === 'user') {
                const lastDomIsUser = lastDomMsg?.classList.contains('user');
                if (!lastDomIsUser) renderRecoveredMessage('user', userMsg.content, userMsg.timestamp);
            }
            renderRecoveredMessage('assistant', last.content, last.timestamp);
        }

        addStatusLine('response received', 'success');
    } catch (e) {
        console.warn('Stream recovery failed:', e);
    }
});

function renderRecoveredMessage(role, content, timestamp) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}`;

    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';
    contentDiv.setAttribute('data-raw-content', content);
    // Always use the escaping markdown renderer. Recovery content comes from
    // stored messages and must follow the same HTML-safety path as history.
    contentDiv.innerHTML = parseMarkdown(content);
    messageDiv.appendChild(contentDiv);

    const footerDiv = document.createElement('div');
    footerDiv.className = 'message-footer';
    const ts = document.createElement('span');
    ts.className = 'message-timestamp';
    ts.textContent = formatTimestamp(new Date(timestamp));
    footerDiv.appendChild(ts);
    messageDiv.appendChild(footerDiv);

    if (role === 'assistant') addActionRow(messageDiv, contentDiv);
    messagesContainer.appendChild(messageDiv);
    scrollToBottom(true);
}

// =============================================================================
// STREAM ABORT + CONTINUE FLOW
// =============================================================================

async function handleStreamAbort(originalMessageId, userBubbleEl) {
    // Durable stream reconnect (v1): the stop button is an explicit interrupt,
    // so cancel the backend worker FIRST. This closes the turn generator
    // (GeneratorExit — the pre-v1 kill semantics) and clears the in-flight
    // guard, so the save-partial / cleanup-orphans calls below behave exactly
    // as before. Silent disconnects and page loads never call this endpoint.
    try {
        await fetch(`${API_BASE}/api/chat/cancel`, { method: 'POST' });
    } catch (err) {
        console.warn('Cancel request failed:', err);
    }

    if ((partialResponse.trim().length > 0 || currentStreamThinking.trim().length > 0) && currentAssistantMessage) {
        // Finalize the partial message element (stop cursor)
        const contentDiv = currentAssistantMessage.querySelector('.message-content');
        if (contentDiv) contentDiv.classList.remove('streaming');

        // Append visual interrupted indicator
        if (contentDiv) {
            const indicator = document.createElement('span');
            indicator.className = 'interrupted-indicator';
            indicator.textContent = ' [interrupted]';
            contentDiv.appendChild(indicator);
        }

        // Finalize any unresolved thinking block (thinking-only interrupt)
        const pendingThinkingSummary = currentAssistantMessage.querySelector('.thinking-block .thinking-summary');
        if (pendingThinkingSummary && pendingThinkingSummary.textContent === 'Thinking...') {
            pendingThinkingSummary.textContent = 'Thinking interrupted';
        }

        // Save partial to DB
        try {
            const body = { partial_content: partialResponse };
            if (originalMessageId) body.original_message_id = originalMessageId;
            if (currentStreamThinking) body.thinking_text = currentStreamThinking;
            const res = await fetch(`${API_BASE}/api/messages/save-partial`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            });
            if (res.ok) {
                const data = await res.json();
                interruptedMessageId = data.message_id;
                showContinueToast();
            }
        } catch (err) {
            console.error('Failed to save partial response:', err);
        }
    } else {
        // Aborted before any text — remove user bubble, clean DB orphan, restore to input
        if (userBubbleEl) {
            userBubbleEl.remove();
            pendingUserTimestamp = null;
        }
        try {
            const cleanupResp = await fetch(`${API_BASE}/api/messages/cleanup-orphans`, { method: 'POST' });
            if (cleanupResp.ok) {
                const cleanup = await cleanupResp.json();
                if (cleanup.restored_text) {
                    messageInput.value = cleanup.restored_text;
                    sendBtn.classList.add('has-text');
                }
            }
        } catch (err) {
            console.error('Orphan cleanup failed:', err);
        }
    }
    addStatusLine('response interrupted', 'warning');
}

function showContinueToast() {
    if (continueToastVisible) return;
    continueToastVisible = true;
    isInterrupted = true;

    // Create interrupted pill (initially hidden for measurement)
    const pill = document.createElement('div');
    pill.id = 'waveInterruptedPill';
    pill.className = 'wave-interrupted-pill';
    pill.innerHTML = '<span>stopped mid-thought — want me to keep going?</span>';

    const yesBtn = document.createElement('button');
    yesBtn.id = 'waveYesBtn';
    yesBtn.className = 'wave-yes-btn';
    yesBtn.textContent = 'YES';

    // Insert before input container so they're positioned within input-wrapper
    inputWrapper.insertBefore(pill, inputContainer);
    inputWrapper.insertBefore(yesBtn, inputContainer);

    waveInterruptedPillEl = pill;
    waveYesBtnEl = yesBtn;

    // Morph stop button ■ → ×
    stopBtn.innerHTML = '<span class="stop-icon-x">&times;</span>';

    // Contraction is triggered by the draw loop after wave flattens.
    // If the animation loop isn't running (e.g. wave never activated), restart it.
    if (!waveAnimId) startWaveAnimation();

    yesBtn.addEventListener('click', () => {
        hideContinueToast(false);
        continuePreviousResponse();
    });
    // Stop/X button click → dismiss
    stopBtn.addEventListener('click', dismissInterruptedOnce, { once: true });

    function dismissInterruptedOnce() {
        if (isInterrupted) hideContinueToast(true);
    }
}

function hideContinueToast(clearId = true) {
    const pill = document.getElementById('waveInterruptedPill');
    const yesBtn = document.getElementById('waveYesBtn');
    if (pill) pill.remove();
    if (yesBtn) yesBtn.remove();
    waveInterruptedPillEl = null;
    waveYesBtnEl = null;
    continueToastVisible = false;
    if (clearId) interruptedMessageId = null;

    if (isInterrupted) {
        isInterrupted = false;
        // Revert stop button icon
        stopBtn.innerHTML = '<span class="stop-icon"></span>';

        if (clearId) {
            // Dismiss path: expand input container now
            stopBtn.classList.remove('visible');
            scrollToBottomBtn.style.bottom = '';
            stopWaveAnimation();
            document.getElementById('streamingWave').style.display = 'none';
            const c = inputContainer;
            c.style.height = '96px';
            c.addEventListener('transitionend', () => {
                c.classList.remove('streaming');
                c.style.height = '';
            }, { once: true });
            // Restore notification bar (was hidden while interrupted pill was showing)
            statusFloat.classList.remove('wave-active');
            updateCollapsedHeight();
        }
        // Continue path (clearId=false): setWaiting(true) → startInputStreamingState() handles the rest
    }
}

// Called by the wave draw loop after line contraction finishes
function onLineContractionComplete() {
    // Grow interrupted pill and YES button in from the line
    if (waveInterruptedPillEl) {
        waveInterruptedPillEl.classList.add('animating-in');
    }
    if (waveYesBtnEl) {
        waveYesBtnEl.classList.add('animating-in');
        // After animation, ensure pointer events are active
        setTimeout(() => {
            if (waveYesBtnEl) waveYesBtnEl.classList.add('visible');
        }, 340);
    }
}

// =============================================================================
// WAVE PILL (status pill on the line during streaming)
// =============================================================================

function showWavePill(text) {
    wavePillTextEl.textContent = text;
    wavePillEl.style.display = 'flex';
    wavePillEl.classList.remove('animating-in');
    void wavePillEl.offsetWidth;  // force reflow so animation restarts
    wavePillEl.classList.add('animating-in');
}

function hideWavePill() {
    wavePillEl.style.display = 'none';
    wavePillEl.classList.remove('animating-in');
}

async function continuePreviousResponse() {
    if (!interruptedMessageId || !currentAssistantMessage) return;

    const msgId = interruptedMessageId;
    interruptedMessageId = null;

    // Remove [interrupted] indicator, re-add streaming cursor
    const contentDiv = currentAssistantMessage.querySelector('.message-content');
    if (contentDiv) {
        const indicator = contentDiv.querySelector('.interrupted-indicator');
        if (indicator) indicator.remove();
        contentDiv.classList.add('streaming');
    }

    streamController = new AbortController();
    partialResponse = '';
    setWaiting(true);

    try {
        const response = await fetch(`${API_BASE}/api/chat/continue`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ interrupted_message_id: msgId }),
            signal: streamController.signal
        });

        if (!response.ok) {
            throw new Error(`Server error: ${response.status}`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n\n');
            buffer = lines.pop();

            for (const line of lines) {
                if (!line.trim() || !line.startsWith('data: ')) continue;

                try {
                    const event = JSON.parse(line.substring(6));

                    if (event.type === 'chunk') {
                        activateWave();
                        partialResponse += event.data;
                        appendToStreamingMessage(currentAssistantMessage, event.data);
                    } else if (event.type === 'notification') {
                        // Parse structured notification objects (Phase A+); fall back to raw string
                        let notifData = event.data;
                        try {
                            const parsed = JSON.parse(event.data);
                            if (parsed && typeof parsed === 'object' && parsed.id) {
                                notifData = parsed;  // Use structured object
                            }
                        } catch (e) {
                            // Not JSON, use raw string
                        }
                        const notifStr = (notifData && typeof notifData === 'object') ? (notifData.summary || '') : notifData;
                        if (notifStr.includes('Cache')) activateWave();
                        queueNotifDisplay(notifData);
                    } else if (event.type === 'done') {
                        if (currentAssistantMessage) {
                            const cd = currentAssistantMessage.querySelector('.message-content');
                            if (cd) cd.classList.remove('streaming');
                            const footer = currentAssistantMessage.querySelector('.message-footer');
                            if (footer) {
                                const ts = document.createElement('span');
                                ts.className = 'message-timestamp';
                                ts.textContent = formatTimestamp(new Date());
                                footer.insertBefore(ts, footer.firstChild);
                            }
                            addActionRow(currentAssistantMessage, cd);
                            // Scroll the top of the message into view so the thinking block is visible
                            requestAnimationFrame(() => {
                                currentAssistantMessage.scrollIntoView({ behavior: 'smooth', block: 'start' });
                            });
                        }
                        addStatusLine((window._instanceName || 'assistant') + ' recalled and replied', 'success');
                    } else if (event.type === 'error') {
                        addStatusLine(`error: ${event.data}`, 'error');
                        throw new Error(event.data);
                    }
                } catch (e) {
                    if (e.message && !e.message.startsWith('Server error')) {
                        console.error('Failed to parse SSE event:', e, line);
                    } else {
                        throw e;
                    }
                }
            }
        }
    } catch (error) {
        if (error.name === 'AbortError') {
            await handleStreamAbort(msgId);
            return;
        }
        console.error('Continuation error:', error);
        addStatusLine('continuation failed', 'error');
    } finally {
        setWaiting(false);
    }
}

// =============================================================================
// NON-STREAMING
// =============================================================================

async function sendMessageNonStreaming(message, attachmentUuids = []) {
    const response = await fetch(`${API_BASE}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message, attachment_uuids: attachmentUuids })
    });

    if (!response.ok) {
        throw new Error(`Server error: ${response.status}`);
    }

    const data = await response.json();

    if (data.notifications && data.notifications.length > 0) {
        for (const notification of data.notifications) {
            handleNotificationAsLog(notification);
        }
    }

    if (data.response) {
        if (data.thinking && showThinking) {
            addMessage('assistant', data.response, true, null, { thinking: data.thinking });
        } else {
            addMessage('assistant', data.response);
        }
    }

    addStatusLine((window._instanceName || 'assistant') + ' recalled and replied', 'success');
}

// =============================================================================
// STREAMING MESSAGE HELPERS
// =============================================================================

function createStreamingMessage() {
    const messageDiv = document.createElement('div');
    messageDiv.className = 'message assistant';

    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content streaming';
    contentDiv.setAttribute('data-raw-content', '');

    messageDiv.appendChild(contentDiv);

    const footerDiv = document.createElement('div');
    footerDiv.className = 'message-footer';
    // Timestamp added on completion (done event) — not while streaming
    messageDiv.appendChild(footerDiv);
    messagesContainer.appendChild(messageDiv);
    scrollToBottom(true);

    return messageDiv;
}

function appendToStreamingMessage(messageDiv, chunk) {
    const contentDiv = messageDiv.querySelector('.message-content');
    const rawContent = contentDiv.getAttribute('data-raw-content') + chunk;
    contentDiv.setAttribute('data-raw-content', rawContent);
    contentDiv.innerHTML = parseMarkdown(rawContent);

    if (streamingAutoScroll) {
        scrollToBottom(true);
    }
}

// =============================================================================
// ACTION BUTTONS (inline in message footer)
// =============================================================================

function buildFooterActions(contentDiv) {
    const actions = document.createElement('span');
    actions.className = 'message-actions';

    // Copy button
    const copyBtn = document.createElement('button');
    copyBtn.className = 'action-btn';
    copyBtn.title = 'Copy';
    copyBtn.innerHTML = `<img src="assets/icon-copy.svg" alt="Copy" width="10" height="10">`;
    copyBtn.addEventListener('click', async () => {
        const rawContent = contentDiv ? contentDiv.getAttribute('data-raw-content') || contentDiv.textContent : '';
        try {
            await copyTextToClipboard(rawContent);
            copyBtn.title = 'Copied!';
            copyBtn.classList.add('copy-active');
            copyBtn.classList.remove('copy-error');
            setTimeout(() => {
                copyBtn.title = 'Copy';
                copyBtn.classList.remove('copy-active');
            }, 1200);
        } catch (err) {
            console.warn('Copy failed:', err);
            copyBtn.title = 'Copy failed';
            copyBtn.classList.add('copy-error');
            setTimeout(() => {
                copyBtn.title = 'Copy';
                copyBtn.classList.remove('copy-error');
            }, 1200);
            showError('Copy failed. Select the text manually and copy from the browser menu.');
        }
    });
    actions.appendChild(copyBtn);

    // TTS play button (only if TTS enabled)
    if (ttsEnabled) {
        const ttsBtn = document.createElement('button');
        ttsBtn.className = 'tts-btn';
        ttsBtn.title = 'Play';
        ttsBtn.innerHTML = `<img src="assets/icon-play.svg" alt="Play" width="10" height="10">`;
        ttsBtn.addEventListener('click', () => {
            const content = contentDiv ? contentDiv.getAttribute('data-raw-content') || contentDiv.textContent : '';
            playTTSWithBtn(content, ttsBtn);
        });
        actions.appendChild(ttsBtn);
    }

    return actions;
}

function pinMessageActions(actionsEl) {
    if (lastPinnedActions && lastPinnedActions !== actionsEl) {
        lastPinnedActions.classList.remove('visible');
    }
    if (actionsEl) {
        actionsEl.classList.add('visible');
        lastPinnedActions = actionsEl;
    }
}

function addActionRow(messageDiv, contentDiv) {
    // Inject action buttons into the existing footer
    const footer = messageDiv.querySelector('.message-footer');
    if (footer) {
        const actions = buildFooterActions(contentDiv);
        footer.appendChild(actions);
        // Fade in and pin as last active message
        requestAnimationFrame(() => pinMessageActions(actions));
    }
}

// =============================================================================
// HISTORY
// =============================================================================

// Durable stream reconnect (v1): is a turn currently generating for this profile?
async function isGenerationActive() {
    try {
        const resp = await fetch(`${API_BASE}/api/chat/generation-status`);
        if (!resp.ok) return false;
        const data = await resp.json();
        return !!data.active;
    } catch (e) {
        return false;
    }
}

// Show a lightweight "Mneme is still writing…" placeholder in the message list.
function showGeneratingIndicator() {
    let el = document.getElementById('generatingIndicator');
    if (el) return el;
    el = document.createElement('div');
    el.id = 'generatingIndicator';
    el.className = 'message assistant';
    el.innerHTML = '<div class="message-content"><em>Mneme is still writing…</em></div>';
    messagesContainer.appendChild(el);
    requestAnimationFrame(() => scrollToBottom(true));
    return el;
}

function hideGeneratingIndicator() {
    const el = document.getElementById('generatingIndicator');
    if (el) el.remove();
}

// Poll generation-status until the in-flight turn completes, then reload history
// so the freshly-persisted assistant message appears. No live token replay in v1.
async function waitForGenerationThenReload({ maxWaitMs = 5 * 60 * 1000 } = {}) {
    showGeneratingIndicator();
    const started = Date.now();
    while (Date.now() - started < maxWaitMs) {
        await new Promise(r => setTimeout(r, 2000));
        if (!(await isGenerationActive())) break;
    }
    hideGeneratingIndicator();
    // Skip the in-flight guard on this reload to avoid re-entering the wait loop
    // (if the turn is somehow still active past the timeout, load what we have).
    await loadHistory(true);
}

async function loadHistory(skipGenerationCheck = false) {
    // Durable stream reconnect (v1): if a turn is generating for this profile
    // (e.g. we reloaded mid-response, or another device is driving the turn),
    // don't run orphan cleanup against it — wait for it to land instead.
    if (!skipGenerationCheck && await isGenerationActive()) {
        await waitForGenerationThenReload();
        return true;
    }

    // Clean up any orphaned user messages from a previous interrupted session.
    // If a trailing user message was deleted, its text is restored to the input
    // so the user can retry without retyping.
    try {
        const cleanupResp = await fetch(`${API_BASE}/api/messages/cleanup-orphans`, { method: 'POST' });
        if (cleanupResp.ok) {
            const cleanup = await cleanupResp.json();
            if (cleanup.restored_text) {
                messageInput.value = cleanup.restored_text;
                sendBtn.classList.add('has-text');
            }
        }
    } catch (e) {
        // Non-critical: if cleanup fails, continue loading history normally
        console.warn('Startup orphan cleanup failed:', e);
    }

    try {
        const response = await fetch(`${API_BASE}/api/history?limit=50`);

        if (!response.ok) {
            console.error('Failed to load history:', response.status);
            return false;
        }

        const data = await response.json();
        // Reset pagination state for this (re)load of the initial page.
        oldestLoadedMessageId = null;
        hasMoreOlderMessages = !!data.has_more;
        isLoadingOlderMessages = false;
        removeOlderMessagesIndicator();

        if (data.messages && data.messages.length > 0) {
            messagesContainer.innerHTML = '';

            const displayMessages = filterDisplayMessages(data.messages);

            displayMessages.reverse();

            displayMessages.forEach(msg => {
                addMessage(msg.sender, msg.content, false, msg.timestamp, msg.metadata, [], null, msg.id);
            });

            // Oldest message actually in the raw (unfiltered) page — used as the
            // before_id cursor for the next "load older" fetch.
            const oldestRaw = data.messages[data.messages.length - 1];
            oldestLoadedMessageId = oldestRaw ? oldestRaw.id : null;

            // Pin the last assistant message's action buttons immediately
            const allAssistantActions = messagesContainer.querySelectorAll('.message.assistant .message-actions, .message.intermediate .message-actions');
            if (allAssistantActions.length > 0) {
                pinMessageActions(allAssistantActions[allAssistantActions.length - 1]);
            }

            // Defer until painted; also re-scroll once fonts finish loading because
            // Google Fonts (Source Serif 4) may not be ready yet, making scrollHeight
            // shorter than the final value and leaving the view short of the true bottom.
            requestAnimationFrame(() => scrollToBottom(true));
            document.fonts?.ready.then(() => scrollToBottom(true));
            return true;
        }

        return false;

    } catch (error) {
        console.error('Error loading history:', error);
        return false;
    }
}

// Shared history-message filter — drops system messages and retrieved/temporary
// metadata-flagged messages. Used by both the initial load and older-page loads
// so the two paths can never drift apart.
function filterDisplayMessages(messages) {
    return messages.filter(msg => {
        if (msg.sender === 'system') return false;
        if (msg.metadata) {
            try {
                const metadata = typeof msg.metadata === 'string' ? JSON.parse(msg.metadata) : msg.metadata;
                if (metadata.retrieved || metadata.temporary) return false;
            } catch (e) {
                console.warn('Failed to parse metadata:', e);
            }
        }
        return true;
    });
}

// =============================================================================
// LOAD OLDER MESSAGES (incremental scroll pagination)
// =============================================================================

function removeOlderMessagesIndicator() {
    if (olderMessagesIndicatorEl && olderMessagesIndicatorEl.parentNode) {
        olderMessagesIndicatorEl.parentNode.removeChild(olderMessagesIndicatorEl);
    }
    olderMessagesIndicatorEl = null;
}

function showOlderMessagesLoading() {
    removeOlderMessagesIndicator();
    olderMessagesIndicatorEl = document.createElement('div');
    olderMessagesIndicatorEl.className = 'older-messages-indicator';
    olderMessagesIndicatorEl.textContent = 'loading earlier messages…';
    messagesContainer.insertBefore(olderMessagesIndicatorEl, messagesContainer.firstChild);
}

function showBeginningOfConversationMarker() {
    removeOlderMessagesIndicator();
    olderMessagesIndicatorEl = document.createElement('div');
    olderMessagesIndicatorEl.className = 'older-messages-indicator older-messages-indicator-end';
    olderMessagesIndicatorEl.textContent = 'beginning of conversation';
    messagesContainer.insertBefore(olderMessagesIndicatorEl, messagesContainer.firstChild);
}

// Called on scroll — near-top (not exactly 0, to tolerate touch momentum
// overscroll on mobile) triggers a fetch of the previous (older) page.
async function maybeLoadOlderMessages() {
    if (isLoadingOlderMessages || !hasMoreOlderMessages) return;
    if (oldestLoadedMessageId === null) return;
    if (messagesContainer.scrollTop >= 200) return;

    isLoadingOlderMessages = true;
    showOlderMessagesLoading();

    try {
        const response = await fetch(`${API_BASE}/api/history?limit=50&before_id=${oldestLoadedMessageId}`);
        if (!response.ok) {
            console.error('Failed to load older messages:', response.status);
            removeOlderMessagesIndicator();
            return;
        }

        const data = await response.json();
        hasMoreOlderMessages = !!data.has_more;

        if (!data.messages || data.messages.length === 0) {
            hasMoreOlderMessages = false;
            showBeginningOfConversationMarker();
            return;
        }

        const displayMessages = filterDisplayMessages(data.messages);
        // Raw (unfiltered) page is newest-first; the oldest raw id becomes the
        // cursor for the *next* older page regardless of what got filtered out.
        const oldestRaw = data.messages[data.messages.length - 1];
        oldestLoadedMessageId = oldestRaw ? oldestRaw.id : oldestLoadedMessageId;

        // Build oldest-first in a detached fragment, then splice the whole
        // fragment in above the previous first message in one DOM operation —
        // reuses addMessage's existing bubble-building/decoration logic exactly
        // as the initial load does, just targeting a fragment instead of the
        // live container.
        displayMessages.reverse();
        const fragment = document.createDocumentFragment();
        const previousFirstChild = messagesContainer.firstChild; // the loading indicator

        // Anchor-based scroll restore: remember the message that's currently
        // pinned at the top of the viewport (by element, not by height diff —
        // scrollHeight diffing fights the browser's own scroll anchoring and
        // can be corrupted by layout changes during the fetch) and pin it back
        // to the same on-screen position after all the DOM mutations below.
        const anchorEl = messagesContainer.querySelector('.message');
        const anchorTopBefore = anchorEl ? anchorEl.getBoundingClientRect().top : null;

        // Suspend the browser's native scroll anchoring for just this mutation
        // block so it can't double-correct against the manual restore below.
        // Scoped (not global CSS): native anchoring is load-bearing elsewhere —
        // it pins the view to bottom content during font-swap layout growth on
        // initial load.
        messagesContainer.style.overflowAnchor = 'none';

        displayMessages.forEach(msg => {
            addMessage(msg.sender, msg.content, false, msg.timestamp, msg.metadata, [], fragment, msg.id);
        });
        messagesContainer.insertBefore(fragment, previousFirstChild);

        removeOlderMessagesIndicator();
        if (!hasMoreOlderMessages) {
            showBeginningOfConversationMarker();
        }

        // Restore in the same synchronous task as the mutations above so the
        // browser never paints the jumped-to-top intermediate frame. Must go
        // through scrollTo with behavior:'instant' — the container has CSS
        // scroll-behavior:smooth, which turns plain scrollTop assignment into
        // an ANIMATED scroll (the visible "jump then glide back" jank).
        if (anchorEl) {
            const anchorTopAfter = anchorEl.getBoundingClientRect().top;
            messagesContainer.scrollTo({
                top: messagesContainer.scrollTop + (anchorTopAfter - anchorTopBefore),
                behavior: 'instant'
            });
        }

    } catch (error) {
        console.error('Error loading older messages:', error);
        removeOlderMessagesIndicator();
    } finally {
        messagesContainer.style.overflowAnchor = '';
        isLoadingOlderMessages = false;
    }
}

// =============================================================================
// MARKDOWN PARSER
// =============================================================================

// Highlight @commands in coral. Expects HTML-escaped text (no raw < > & chars).
// Block commands (@note...@endnote) are extracted first to avoid being split
// by paragraph processing; single-line commands are wrapped inline.
function highlightCommands(text) {
    // Single-line @commands only — block commands are handled in parseMarkdown
    text = text.replace(/^(@\w+[^\n]*)/gm, (_, cmd) => {
        return `<span class="cmd-highlight">${cmd}</span>`;
    });
    return text;
}

function parseMarkdown(text) {
    // Step 0: Extract @command blocks → placeholders (before any processing)
    // These contain raw code/content that must not be markdown-processed.
    const cmdBlocks = [];

    // @run...@endrun → collapsible code box
    text = text.replace(/@run\s*\n([\s\S]*?)@endrun/g, (_, code) => {
        const escaped = code.trim()
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
        const idx = cmdBlocks.length;
        cmdBlocks.push(
            `<details class="cmd-run-block"><summary class="cmd-highlight">looked it up</summary>` +
            `<pre class="code-block"><code>${escaped}</code></pre></details>`
        );
        return `\x00CMDBLK${idx}\x00`;
    });

    // Other block commands: @word...@endword (e.g. @note...@endnote, @artifact...@endartifact)
    text = text.replace(/@(\w+)\b([\s\S]*?)@end\1\b/g, (match) => {
        const escaped = match
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
        const idx = cmdBlocks.length;
        cmdBlocks.push(`<span class="cmd-highlight">${escaped}</span>`);
        return `\x00CMDBLK${idx}\x00`;
    });

    // Step 1: Extract fenced code blocks → placeholders (protect from all processing)
    const codeBlocks = [];
    text = text.replace(/```(\w*)\n?([\s\S]*?)```/g, (match, lang, code) => {
        const escaped = code
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/\n$/, '');
        const idx = codeBlocks.length;
        codeBlocks.push(`<pre class="code-block"><code>${escaped}</code></pre>`);
        return `\x00CODE${idx}\x00`;
    });

    // Step 2: Extract inline code spans → placeholders (before bold/italic runs)
    const inlineCodes = [];
    text = text.replace(/`([^`]+)`/g, (match, code) => {
        const escaped = code
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
        const idx = inlineCodes.length;
        inlineCodes.push(`<code>${escaped}</code>`);
        return `\x00ICODE${idx}\x00`;
    });

    // Step 3: HTML-escape remaining text
    text = text.replace(/&/g, '&amp;')
               .replace(/</g, '&lt;')
               .replace(/>/g, '&gt;');

    // Step 4: Highlight @commands in coral (unchanged helper)
    text = highlightCommands(text);

    // Step 5: Headers
    text = text.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    text = text.replace(/^## (.+)$/gm, '<h2>$1</h2>');
    text = text.replace(/^# (.+)$/gm, '<h1>$1</h1>');

    // Step 6: Horizontal rule
    text = text.replace(/^---$/gm, '<hr class="message-hr">');

    // Step 6.5: Normalize list spacing — AI sometimes puts blank lines between
    // list items, which would split them into separate lists. Collapse blank lines
    // between consecutive list items so they stay grouped.
    // Run multiple times to catch chains (item\n\n item\n\n item).
    for (let i = 0; i < 3; i++) {
        text = text.replace(/(^[-*] .+)\n\n+([-*] )/gm, '$1\n$2');
        text = text.replace(/(^\d+\. .+)\n\n+(\d+\. )/gm, '$1\n$2');
    }

    // Step 7 & 8: Lists — scan line by line, wrap consecutive runs in <ul>/<ol>
    const lines = text.split('\n');
    const listLines = [];
    let inUl = false, inOl = false;
    for (const line of lines) {
        const ulMatch = line.match(/^[-*] (.+)/);
        const olMatch = line.match(/^\d+\. (.+)/);
        if (ulMatch) {
            if (inOl) { listLines.push('</ol>'); inOl = false; }
            if (!inUl) { listLines.push('<ul>'); inUl = true; }
            listLines.push(`<li>${ulMatch[1]}</li>`);
        } else if (olMatch) {
            if (inUl) { listLines.push('</ul>'); inUl = false; }
            if (!inOl) { listLines.push('<ol>'); inOl = true; }
            listLines.push(`<li>${olMatch[1]}</li>`);
        } else {
            if (inUl) { listLines.push('</ul>'); inUl = false; }
            if (inOl) { listLines.push('</ol>'); inOl = false; }
            listLines.push(line);
        }
    }
    if (inUl) listLines.push('</ul>');
    if (inOl) listLines.push('</ol>');
    text = listLines.join('\n');

    // Step 9: Bold-italic combo (must come before bold/italic individually)
    text = text.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>');

    // Step 10: Bold
    text = text.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');

    // Step 11: Italic (* and _)
    text = text.replace(/\*(.+?)\*/g, '<em>$1</em>');
    text = text.replace(/_(.+?)_/g, '<em>$1</em>');

    // Step 12: Links (with protocol whitelist to prevent javascript: XSS)
    text = text.replace(/\[([^\]]+)\]\(([^\)]+)\)/g, (match, label, url) => {
        if (/^https?:\/\/|^mailto:/i.test(url)) {
            return `<a href="${url}" target="_blank" rel="noopener noreferrer">${label}</a>`;
        }
        return `${label} (${url})`;
    });

    // Step 13: Paragraph split / line breaks
    // Block-level elements must not be wrapped in <p>
    const blockStart = /^<(?:h[123]|hr|ul|ol|li|pre)/;
    const isPlaceholder = /^\x00(?:CODE|CMDBLK)\d+\x00$/;
    const paragraphs = text.split(/\n\n+/);
    text = paragraphs.map(p => {
        const trimmed = p.trim();
        if (!trimmed) return '';
        if (blockStart.test(trimmed)) return trimmed;
        if (isPlaceholder.test(trimmed)) return trimmed;
        return `<p>${trimmed.replace(/\n/g, '<br>')}</p>`;
    }).join('');

    // Step 14: Restore inline code placeholders
    text = text.replace(/\x00ICODE(\d+)\x00/g, (_, idx) => inlineCodes[parseInt(idx)]);

    // Step 15: Restore fenced code block placeholders
    text = text.replace(/\x00CODE(\d+)\x00/g, (_, idx) => codeBlocks[parseInt(idx)]);

    // Step 16: Restore @command block placeholders
    text = text.replace(/\x00CMDBLK(\d+)\x00/g, (_, idx) => cmdBlocks[parseInt(idx)]);

    return text;
}

// =============================================================================
// TIMESTAMPS
// =============================================================================

function formatTimestamp(time) {
    const date = time instanceof Date ? time : new Date(time);
    return date.toLocaleTimeString([], {
        hour: '2-digit',
        minute: '2-digit',
        hour12: false
    });
}

// =============================================================================
// ADD MESSAGE
// =============================================================================

function addMessage(sender, content, scroll = true, timestamp = null, metadata = null, attachments = [], targetContainer = null, messageId = null) {
    // Transition to chat view if not already
    if (!chatActive) {
        transitionToChatView();
    }

    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${sender}`;
    if (messageId !== null && messageId !== undefined) {
        messageDiv.dataset.messageId = String(messageId);
    }

    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';

    if (sender === 'assistant' || sender === 'intermediate') {
        contentDiv.innerHTML = parseMarkdown(content);
        contentDiv.setAttribute('data-raw-content', content);
    } else if (sender === 'notification') {
        contentDiv.innerHTML = content.replace(/\n/g, '<br>');
    } else {
        contentDiv.innerHTML = parseMarkdown(content);
        contentDiv.setAttribute('data-raw-content', content);
    }

    messageDiv.appendChild(contentDiv);

    // Attachment chips (new outgoing messages only — not history)
    if (sender === 'user' && attachments && attachments.length > 0) {
        const chipsDiv = document.createElement('div');
        chipsDiv.className = 'attachment-chips';

        attachments.forEach(att => {
            const chip = document.createElement('div');
            chip.className = 'attachment-chip';

            if (att.objectUrl) {
                const img = document.createElement('img');
                img.src = att.objectUrl;
                img.addEventListener('load', () => URL.revokeObjectURL(att.objectUrl), { once: true });
                img.addEventListener('error', () => URL.revokeObjectURL(att.objectUrl), { once: true });
                chip.appendChild(img);
            } else {
                const icon = document.createElement('span');
                icon.className = 'chip-icon';
                icon.textContent = '◎';
                chip.appendChild(icon);
            }

            const nameSpan = document.createElement('span');
            nameSpan.className = 'chip-name';
            const name = att.name || 'unnamed';
            const truncated = name.length > 16 ? name.substring(0, 13) + '…' : name;
            nameSpan.textContent = truncated;
            nameSpan.title = name;
            chip.appendChild(nameSpan);

            chipsDiv.appendChild(chip);
        });

        messageDiv.appendChild(chipsDiv);
    }

    // Thinking block from history
    if (sender === 'assistant' && showThinking && metadata) {
        const parsedMeta = typeof metadata === 'string' ? (() => { try { return JSON.parse(metadata); } catch(e) { return null; } })() : metadata;
        if (parsedMeta && parsedMeta.thinking) {
            createStaticThinkingBlock(messageDiv, parsedMeta.thinking);
        }
    }

    // Footer with timestamp and action buttons
    if (sender === 'user' || sender === 'assistant' || sender === 'intermediate') {
        if (sender === 'user' && scroll) {
            // New outgoing message — defer timestamp until AI responds so the
            // absolutely-positioned footer doesn't get clipped by the rising process bar
            pendingUserTimestamp = { div: messageDiv, time: timestamp ? new Date(timestamp) : new Date() };
        } else {
            const footerDiv = document.createElement('div');
            footerDiv.className = 'message-footer';

            const timestampDiv = document.createElement('span');
            timestampDiv.className = 'message-timestamp';
            timestampDiv.textContent = timestamp ? formatTimestamp(timestamp) : formatTimestamp(new Date());
            footerDiv.appendChild(timestampDiv);

            if (sender === 'assistant' || sender === 'intermediate') {
                footerDiv.appendChild(buildFooterActions(contentDiv));
            }

            messageDiv.appendChild(footerDiv);
        }
    }

    // Tap/click to pin action buttons for assistant messages
    if (sender === 'assistant' || sender === 'intermediate') {
        messageDiv.addEventListener('click', () => {
            const actionsEl = messageDiv.querySelector('.message-actions');
            if (actionsEl) pinMessageActions(actionsEl);
        });
    }

    // Skip notification messages - route to status log
    if (sender === 'notification') {
        handleNotificationAsLog(content);
        return;
    }

    (targetContainer || messagesContainer).appendChild(messageDiv);

    // Add extra vertical padding when a user bubble wraps to multiple lines
    if (sender === 'user') {
        requestAnimationFrame(() => {
            const lh = parseFloat(getComputedStyle(contentDiv).lineHeight) || 20;
            if (contentDiv.clientHeight > lh + 25) {
                contentDiv.classList.add('multi-line');
            }
        });
    }

    if (scroll) {
        scrollToBottom();
    }

    // Right-click / long-press copy for user messages
    if (sender === 'user') {
        let longPressTimer = null;
        let flashTimer = null;

        const triggerCopy = async () => {
            const raw = contentDiv.getAttribute('data-raw-content') || contentDiv.textContent;
            try {
                await copyTextToClipboard(raw);
                if (flashTimer !== null) clearTimeout(flashTimer);
                messageDiv.classList.add('copy-flash');
                flashTimer = setTimeout(() => {
                    messageDiv.classList.remove('copy-flash');
                    flashTimer = null;
                }, 800);
            } catch (err) {
                console.warn('Copy failed:', err);
                showError('Copy failed. Select the text manually and copy from the browser menu.');
            }
        };

        messageDiv.addEventListener('contextmenu', (e) => {
            if (e.target.closest('a')) return;  // let browser handle link right-clicks
            e.preventDefault();
            triggerCopy();
        });

        messageDiv.addEventListener('click', (e) => {
            if (e.target.closest('a')) return;  // let links work normally
            if (window.getSelection().toString().length > 0) return;  // user is selecting text
            triggerCopy();
        });

        messageDiv.addEventListener('pointerdown', (e) => {
            if (e.pointerType === 'touch' || e.pointerType === 'pen') {
                longPressTimer = setTimeout(triggerCopy, 500);
            }
        });

        const cancelLongPress = () => {
            if (longPressTimer !== null) {
                clearTimeout(longPressTimer);
                longPressTimer = null;
            }
        };

        messageDiv.addEventListener('pointerup', cancelLongPress);
        messageDiv.addEventListener('pointermove', cancelLongPress);
        messageDiv.addEventListener('pointercancel', cancelLongPress);
    }

    return messageDiv;
}

// =============================================================================
// SCROLL
// =============================================================================

function scrollToBottom(instant = false) {
    messagesContainer.scrollTo({
        top: messagesContainer.scrollHeight,
        behavior: instant ? 'instant' : 'smooth'
    });
}

function isUserAtBottom() {
    const scrollTop = messagesContainer.scrollTop;
    const scrollHeight = messagesContainer.scrollHeight;
    const clientHeight = messagesContainer.clientHeight;
    return scrollHeight - scrollTop - clientHeight < 100;
}

function handleScroll() {
    if (isUserAtBottom()) {
        scrollToBottomBtn.classList.remove('visible');
        streamingAutoScroll = true;
    } else {
        scrollToBottomBtn.classList.add('visible');
        if (isWaiting) streamingAutoScroll = false;
    }

    maybeLoadOlderMessages();
}

// =============================================================================
// STREAMING WAVE ANIMATION
// =============================================================================

function startWaveAnimation() {
    const canvas = document.getElementById('streamingWave');
    const ctx = canvas.getContext('2d');
    const coral = '#d97757';
    const dpr = window.devicePixelRatio || 1;
    let lastTimestamp = null;

    function draw(timestamp) {
        const dt = lastTimestamp === null ? 1 / 60 : Math.min((timestamp - lastTimestamp) / 1000, 0.1);
        lastTimestamp = timestamp;
        const cssW = canvas.offsetWidth;
        const cssH = canvas.offsetHeight;
        canvas.width = cssW * dpr;
        canvas.height = cssH * dpr;
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

        ctx.clearRect(0, 0, cssW, cssH);
        ctx.strokeStyle = coral;
        ctx.lineWidth = 1.5;
        ctx.lineCap = 'round';
        ctx.lineJoin = 'round';

        const lineY = cssH / 2;

        // Lerp amplitude toward target — smooth grow/shrink (time-normalised)
        const ampRate = 1 - Math.pow(waveShrinking ? 0.86 : 0.94, 60 * dt);
        waveAmp += (waveAmpTarget - waveAmp) * ampRate;

        // When flat: handle contraction animation or finalize
        if (waveAmp < 0.01) {
            waveAmp = 0;
            const lineL = waveLineL;
            const lineR = waveLineR ?? cssW;

            // Draw flat line segment (contracted or full)
            ctx.beginPath();
            ctx.moveTo(lineL, lineY);
            ctx.lineTo(lineR, lineY);
            ctx.stroke();

            if (waveLineContracting) {
                // Animate endpoints toward targets
                const contractRate = 1 - Math.pow(0.87, 60 * dt);
                waveLineL += (waveLineLTarget - waveLineL) * contractRate;
                const rTarget = waveLineRTarget ?? cssW;
                waveLineR = (waveLineR ?? cssW) + (rTarget - (waveLineR ?? cssW)) * contractRate;
                if (Math.abs(waveLineL - waveLineLTarget) < 1 &&
                    Math.abs(waveLineR - rTarget) < 1) {
                    waveLineL = waveLineLTarget;
                    waveLineR = rTarget;
                    waveLineContracting = false;
                    onLineContractionComplete();
                    return;
                }
                waveAnimId = requestAnimationFrame(draw);
                return;
            }

            if (waveShrinking && isInterrupted) {
                // Wave just finished flattening — begin line contraction
                const wrapperRect = inputWrapper.getBoundingClientRect();
                if (waveInterruptedPillEl && waveYesBtnEl) {
                    const pillRect = waveInterruptedPillEl.getBoundingClientRect();
                    const yesRect = waveYesBtnEl.getBoundingClientRect();
                    waveLineLTarget = pillRect.right - wrapperRect.left + 8;
                    waveLineRTarget = yesRect.left - wrapperRect.left - 8;
                } else {
                    // Fallback estimates
                    waveLineLTarget = cssW * 0.28;
                    waveLineRTarget = cssW * 0.72;
                }
                waveLineContracting = true;
                waveAnimId = requestAnimationFrame(draw);
                return;
            }

            if (waveShrinking) {
                finalizeStopInputStreamingState();
                return;
            }

            // Flat line before wave activates — keep animating
            waveAnimId = requestAnimationFrame(draw);
            return;
        }

        // Animated wave
        const zoneW = cssW * 0.34;
        const zoneX = (cssW - zoneW) / 2;
        const amp = cssH * 0.42 * waveAmp;
        const period = cssW * 0.05;
        const maxStretch = 2.2;
        const taper = 0.32;

        ctx.beginPath();
        ctx.moveTo(0, lineY);
        ctx.lineTo(zoneX, lineY);

        let spatialPhase = 0;
        for (let px = zoneX; px <= zoneX + zoneW; px++) {
            const t = (px - zoneX) / zoneW;
            let envelope;
            if (t < taper)          envelope = (1 - Math.cos(Math.PI * t / taper)) / 2;
            else if (t > 1 - taper) envelope = (1 - Math.cos(Math.PI * (1 - t) / taper)) / 2;
            else                    envelope = 1;
            const stretch = 1 + (1 - envelope) * (maxStretch - 1);
            spatialPhase += (2 * Math.PI / period) / stretch;
            const raw = Math.sin(spatialPhase - wavePhase * (2 * Math.PI / period));
            const shaped = Math.sign(raw) * Math.pow(Math.abs(raw), 0.3);
            const wave = raw * (1 - envelope) + shaped * envelope;
            const y = lineY - amp * envelope * wave;
            ctx.lineTo(px, y);
        }

        ctx.lineTo(cssW, lineY);
        ctx.stroke();

        wavePhase += 60 * dt;
        waveAnimId = requestAnimationFrame(draw);
    }

    requestAnimationFrame(draw);
}

// ── WAVE PROGRESS (determinate) ──────────────────────────────
// Reusable squiggle progress bar — same DNA as the thinking wave.
// Traveled portion: living coral wave. Remainder: flat chalk track
// ending in a coral dot. At 100% the wave exhales flat.
// Usage: const wp = createWaveProgress(canvas); wp.set(0.4); wp.stop();
function createWaveProgress(canvas) {
    const ctx = canvas.getContext('2d');
    const coral = '#d97757';
    const chalk = '#76746e';
    let shown = 0;        // displayed progress (lerped toward target)
    let target = 0;
    let phase = 0;        // wave travel
    let amp = 1;          // 1 = living, lerps to 0 once complete
    let animId = null;
    let lastTs = null;

    function draw(ts) {
        const dt = lastTs === null ? 1 / 60 : Math.min((ts - lastTs) / 1000, 0.1);
        lastTs = ts;
        const dpr = window.devicePixelRatio || 1;
        const cssW = canvas.offsetWidth;
        const cssH = canvas.offsetHeight;
        if (cssW === 0) {   // hidden — idle cheaply until visible again
            animId = requestAnimationFrame(draw);
            return;
        }
        canvas.width = cssW * dpr;
        canvas.height = cssH * dpr;
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, cssW, cssH);

        const midY = cssH / 2;
        shown += (target - shown) * (1 - Math.pow(0.92, 60 * dt));
        const ampTarget = target >= 1 ? 0 : 1;
        amp += (ampTarget - amp) * (1 - Math.pow(0.95, 60 * dt));

        const dotR = 2.25;
        const gap = 7;
        const trackEnd = cssW - dotR;          // dot center sits at the very end
        const waveEnd = Math.max(3, (trackEnd - gap) * shown);

        // Traveled portion — the living wave
        ctx.strokeStyle = coral;
        ctx.lineWidth = 2;
        ctx.lineCap = 'round';
        ctx.lineJoin = 'round';
        const period = 24;                                  // px per cycle
        const waveAmp = Math.min(cssH * 0.32, 5) * amp;
        ctx.beginPath();
        for (let px = 0; px <= waveEnd; px++) {
            // flatten gently at both ends of the squiggle
            const env = Math.max(0, Math.min(1, px / 14, (waveEnd - px) / 14));
            // soften crests into u-shaped hills/valleys (thinking-wave shaping,
            // slightly rounder); relax toward a pure sine as the wave exhales
            // so the flattening keeps natural peaks
            const raw = Math.sin((px / period) * 2 * Math.PI - phase);
            const shaped = Math.sign(raw) * Math.pow(Math.abs(raw), 0.45);
            const blend = env * amp;
            const wave = raw * (1 - blend) + shaped * blend;
            const y = midY - wave * waveAmp * env;
            if (px === 0) ctx.moveTo(px, y);
            else ctx.lineTo(px, y);
        }
        ctx.stroke();

        // Remaining track — flat chalk
        if (waveEnd + gap < trackEnd - gap) {
            ctx.strokeStyle = chalk;
            ctx.lineWidth = 1.5;
            ctx.beginPath();
            ctx.moveTo(waveEnd + gap, midY);
            ctx.lineTo(trackEnd - gap, midY);
            ctx.stroke();
        }

        // End dot — coral, always
        ctx.fillStyle = coral;
        ctx.beginPath();
        ctx.arc(trackEnd - dotR, midY, dotR, 0, Math.PI * 2);
        ctx.fill();

        phase += 4.5 * dt;   // travel speed (radians/s-ish)

        // Once complete and fully exhaled, rest (draw one final still frame)
        if (target >= 1 && shown > 0.995 && amp < 0.01) {
            animId = null;
            return;
        }
        animId = requestAnimationFrame(draw);
    }

    return {
        set(p) {
            target = Math.max(0, Math.min(1, p));
            if (target < 1) amp = Math.max(amp, 0.001);  // re-wake if it had rested
            if (animId === null) {
                lastTs = null;
                animId = requestAnimationFrame(draw);
            }
        },
        stop() {
            if (animId !== null) {
                cancelAnimationFrame(animId);
                animId = null;
            }
            lastTs = null;
        },
    };
}

function stopWaveAnimation() {
    if (waveAnimId !== null) {
        cancelAnimationFrame(waveAnimId);
        waveAnimId = null;
        wavePhase = 0;
    }
    waveLineL = 0;
    waveLineR = null;
    waveLineContracting = false;
    // Note: canvas display is managed by finalizeStopInputStreamingState / hideContinueToast
}

function activateWave() {
    if (waveActivated) return;
    waveActivated = true;
    statusFloat.classList.add('wave-active');
    waveActivateTimerId = setTimeout(() => {
        waveActivateTimerId = null;
        waveAmpTarget = 1;
        hideWavePill();  // hide pill during sine animation — visible before and after
    }, 380);
}

function startInputStreamingState() {
    const c = inputContainer;
    waveAmp = 0;
    waveAmpTarget = 0;
    waveActivated = false;
    waveShrinking = false;
    notifDisplayQueue = [];
    notifQueueActive = false;
    // Reset line state (also handles re-entry from interrupted → continue path)
    waveLineL = 0;
    waveLineR = null;
    waveLineLTarget = 0;
    waveLineRTarget = null;
    waveLineContracting = false;
    isInterrupted = false;
    inContinuationPhase = false;
    // Hide old status float immediately — wave pill replaces it during streaming
    statusFloat.classList.add('wave-active');
    c.classList.add('streaming');
    document.getElementById('streamingWave').style.display = 'block';
    stopBtn.classList.add('visible');
    // Position scroll button above the stop button (stop btn: bottom 12px, height 40px → top at 52px; add 6px gap)
    scrollToBottomBtn.style.bottom = '58px';
    startWaveAnimation();  // starts immediately — draws flat coral line replacing fading border
    requestAnimationFrame(() => {
        c.style.height = c.offsetHeight + 'px';
        requestAnimationFrame(() => { c.style.height = '32px'; });
    });
}

function finalizeStopInputStreamingState() {
    stopWaveAnimation();
    hideWavePill();
    inContinuationPhase = false;
    document.getElementById('streamingWave').style.display = 'none';
    stopBtn.classList.remove('visible');
    scrollToBottomBtn.style.bottom = '';
    updateCollapsedHeight();
    if (isInterrupted) {
        // Input stays small while interrupted pill is showing — expand deferred.
        // Show canvas again so the contracted line can animate.
        document.getElementById('streamingWave').style.display = 'block';
        startWaveAnimation();
        return;
    }
    const c = inputContainer;
    c.style.height = '96px';
    c.addEventListener('transitionend', () => {
        c.classList.remove('streaming');
        c.style.height = '';
    }, { once: true });
}

function stopInputStreamingState() {
    waveAmpTarget = 0;
    waveShrinking = true;
    if (waveActivateTimerId !== null) {
        clearTimeout(waveActivateTimerId);  // prevent late timer from re-setting target to 1
        waveActivateTimerId = null;
    }
    if (!isInterrupted) {
        statusFloat.classList.remove('wave-active');
        updateCollapsedHeight();  // restores JS-set height so CSS transition slides bar back up
        setTimeout(() => scrollToBottom(true), 340);  // scroll after float finishes sliding up (300ms transition)
    }
    // If wave was never activated (e.g. very fast response), finalize immediately
    if (!waveActivated) {
        finalizeStopInputStreamingState();
    }
}

// =============================================================================
// WAITING STATE
// =============================================================================

function setWaiting(waiting) {
    isWaiting = waiting;
    messageInput.disabled = waiting || migrationInputLocked;
    sendBtn.disabled = waiting || migrationInputLocked;

    if (waiting) {
        clearStatusLog();
        showNotificationBar();
        // Do NOT auto-expand — status updates appear in the collapsed 1-2 row bar
        startSpinner();
        addStatusLine('one sec', 'info');
        startInputStreamingState();
    } else {
        // Flush deferred user timestamp now that the process bar is going away
        if (pendingUserTimestamp) {
            const footerDiv = document.createElement('div');
            footerDiv.className = 'message-footer';
            const timestampDiv = document.createElement('span');
            timestampDiv.className = 'message-timestamp';
            timestampDiv.textContent = formatTimestamp(pendingUserTimestamp.time);
            footerDiv.appendChild(timestampDiv);
            pendingUserTimestamp.div.appendChild(footerDiv);
            pendingUserTimestamp = null;
        }
        stopSpinner();
        stopInputStreamingState();
        // After 4s: deactivate. Do NOT collapse — bar stays visible with "done"
        setTimeout(() => {
            if (!isWaiting) {
                hideNotificationBar();
            }
        }, 4000);
        if (!migrationInputLocked) messageInput.focus();
    }
}

// =============================================================================
// ERRORS
// =============================================================================

function showError(message) {
    errorMessage.textContent = message;
    errorBanner.classList.add('active');
    setTimeout(hideError, 5000);
}

function hideError() {
    errorBanner.classList.remove('active');
}

// =============================================================================
// MODALS
// =============================================================================

function insertCommand(cmd) {
    if (migrationInputLocked) return;
    const current = messageInput.value;
    const needsNewline = current.length > 0 && !current.endsWith('\n');
    messageInput.value = (needsNewline ? current + '\n' : current) + cmd;
    messageInput.focus();
    messageInput.setSelectionRange(messageInput.value.length, messageInput.value.length);
    messageInput.dispatchEvent(new Event('input'));
}

function openBottomDrawer() {
    if (migrationInputLocked) return;
    bottomDrawer.classList.add('active');
    bottomDrawerOverlay.classList.add('active');
}

function closeBottomDrawer() {
    bottomDrawer.classList.remove('active');
    bottomDrawerOverlay.classList.remove('active');
}

function openCommandsDrawer() {
    if (migrationInputLocked) return;
    commandsDrawer.classList.add('active');
    bottomDrawerOverlay.classList.add('active');
    requestAnimationFrame(() => updateEdgeFades(consoleScroller()));
}

function closeCommandsDrawer() {
    commandsDrawer.classList.remove('active');
    bottomDrawerOverlay.classList.remove('active');
    consoleShowHome();
}

// ── COMMAND CONSOLE ──────────────────────────────────────────
// The commands drawer doubles as a console: query pills (data-exec) run
// through POST /api/command — which stores NOTHING in conversation
// history — and render results as navigable views on the glass.
// Action pills (data-cmd) insert into the input as before.

let cmdConsoleStack = [];  // [{ title, node, scrollTop }] — home is the empty stack

// The drawer shell carries the glass and must not scroll (masks would fade
// the glass) — cmdConsoleView/cmdHome are the scrollers, whichever is
// visible. Scroll position and edge fades are tracked on them.
function consoleScroller() {
    const view = document.getElementById('cmdConsoleView');
    return (view && !view.hidden) ? view : document.getElementById('cmdHome');
}

// Scroll-edge fades: same treatment as the expanded status log — fade
// content near clipped edges so scrollable glass never cuts abruptly.
function updateEdgeFades(el) {
    const scrollable = el.scrollHeight > el.clientHeight + 4;
    el.classList.toggle('fade-top', scrollable && el.scrollTop > 4);
    el.classList.toggle('fade-bottom', scrollable && el.scrollTop + el.clientHeight < el.scrollHeight - 4);
}

function consoleShowHome() {
    cmdConsoleStack = [];
    const view = document.getElementById('cmdConsoleView');
    document.getElementById('cmdConsoleHeader').hidden = true;
    view.hidden = true;
    view.replaceChildren();
    const home = document.getElementById('cmdHome');
    home.hidden = false;
    requestAnimationFrame(() => updateEdgeFades(home));
}

function consoleRenderTop() {
    const top = cmdConsoleStack[cmdConsoleStack.length - 1];
    if (!top) { consoleShowHome(); return; }
    const view = document.getElementById('cmdConsoleView');
    document.getElementById('cmdConsoleHeader').hidden = false;
    document.getElementById('cmdConsoleTitle').textContent = top.title;
    document.getElementById('cmdHome').hidden = true;
    view.hidden = false;
    view.replaceChildren(top.node);
    view.scrollTop = top.scrollTop || 0;
    requestAnimationFrame(() => updateEdgeFades(view));
}

// Save the scroller's current position into whatever entry is on top
// *before* it stops being visible (called ahead of push/back navigation).
function consoleSaveScroll() {
    const top = cmdConsoleStack[cmdConsoleStack.length - 1];
    if (top) top.scrollTop = consoleScroller().scrollTop;
}

function consolePush(title, node) {
    consoleSaveScroll();
    cmdConsoleStack.push({ title, node, scrollTop: 0 });
    consoleRenderTop();
}

// Replacing the top view (e.g. "querying..." → results) always lands at the
// top — it's not a navigation the user should be scrolled-back-into.
function consoleReplaceTop(title, node) {
    cmdConsoleStack.pop();
    cmdConsoleStack.push({ title, node, scrollTop: 0 });
    consoleRenderTop();
}

function consoleBack() {
    cmdConsoleStack.pop();
    consoleRenderTop();
}

function consoleNote(text) {
    const div = document.createElement('div');
    div.className = 'cmd-console-note';
    div.textContent = text;
    return div;
}

async function consoleExec(command) {
    const res = await fetch('/api/command', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command }),
    });
    const result = await res.json();
    if (result.error) throw new Error(result.error);
    return result;
}

async function runConsoleQuery(command, { replaceTop = false } = {}) {
    (replaceTop ? consoleReplaceTop : consolePush)('querying...', consoleNote('querying memory...'));
    try {
        const result = await consoleExec(command);
        const { title, node } = renderConsoleResult(command, result);
        consoleReplaceTop(title, node);
    } catch (err) {
        consoleFail(err);
    }
}

function renderConsoleResult(command, result) {
    if (!result.success) return { title: 'error', node: consoleNote('✗ ' + result.message) };
    const data = result.data || {};
    if (result.command === 'entity' && Array.isArray(data.entities)) return renderEntityListView(data.entities);
    if (result.command === 'entity' && data.entity) return renderEntityDetailView(data.entity, data.summary);
    if (result.command === 'concept' && Array.isArray(data.concepts)) return renderConceptListView(data.concepts);
    if (result.command === 'concept' && data.concept) return renderConceptDetailView(data.concept);
    // Fallback: the handler's own formatted text, machine voice
    const pre = document.createElement('pre');
    pre.className = 'cmd-console-pre';
    pre.textContent = result.message || '(no output)';
    return { title: command, node: pre };
}

// onTap may be null — callers that need hold/tap gestures (attachHoldTap)
// wire their own click handling instead of this default one.
function makeCmdCard(name, sub, onTap) {
    const card = document.createElement('button');
    card.className = 'cmd-card';
    const n = document.createElement('span');
    n.className = 'cmd-card-name';
    n.textContent = name;
    card.appendChild(n);
    if (sub) {
        const s = document.createElement('span');
        s.className = 'cmd-card-sub';
        s.textContent = sub;
        card.appendChild(s);
    }
    if (onTap) card.addEventListener('click', onTap);
    return card;
}

// Reusable long-press-vs-tap gesture, mirroring the autocomplete's
// click-vs-pointerdown discipline: scroll gestures must never trigger a
// hold or a tap. pointerdown arms a ~500ms hold timer; any pointermove past
// ~10px, or pointerup/pointercancel before the timer fires, cancels it as a
// normal tap. When the hold fires, the following click is suppressed so a
// hold never also opens/toggles the card it selected.
function attachHoldTap(el, { onTap, onHold, holdDelay = 500, moveThreshold = 10 } = {}) {
    let timer = null;
    let startX = 0, startY = 0;
    let suppressClick = false;

    function clearHoldTimer() {
        if (timer) { clearTimeout(timer); timer = null; }
    }

    el.addEventListener('pointerdown', (e) => {
        if (e.pointerType === 'mouse' && e.button !== 0) return;
        // A hold whose pointer then dragged away never produces a click,
        // which would leave the suppression latched and eat the next tap.
        suppressClick = false;
        startX = e.clientX;
        startY = e.clientY;
        clearHoldTimer();
        timer = setTimeout(() => {
            timer = null;
            suppressClick = true;
            if (onHold) onHold(e);
        }, holdDelay);
    });
    el.addEventListener('pointermove', (e) => {
        if (!timer) return;
        const dx = e.clientX - startX, dy = e.clientY - startY;
        if ((dx * dx + dy * dy) > moveThreshold * moveThreshold) clearHoldTimer();
    });
    el.addEventListener('pointerup', clearHoldTimer);
    el.addEventListener('pointercancel', clearHoldTimer);
    // Kill the mobile long-press context menu / text-selection callout —
    // paired with user-select:none/-webkit-touch-callout:none in CSS.
    el.addEventListener('contextmenu', (e) => e.preventDefault());
    el.addEventListener('click', (e) => {
        if (suppressClick) {
            suppressClick = false;
            e.preventDefault();
            e.stopPropagation();
            return;
        }
        if (onTap) onTap(e);
    });
}

function makeConsoleActionBtn(label, onTap) {
    const btn = document.createElement('button');
    btn.className = 'cmd-action-btn';
    btn.textContent = label;
    btn.addEventListener('click', onTap);
    return btn;
}

// Surface a console action's outcome in the status bar after the drawer closes
function consoleAnnounce(text, type) {
    showNotificationBar();
    addStatusLine(text, type || 'success');
    setTimeout(() => { if (!isWaiting) hideNotificationBar(); }, 4000);
}

// Shared error rendering for console handlers' catch blocks
function consoleFail(err) {
    consoleReplaceTop('error', consoleNote('✗ ' + err.message));
}
function consoleFailAnnounce(err) {
    consoleAnnounce('✗ ' + err.message, 'error');
}

// ── INPUT MIRROR (per-line command tint) ─────────────────────
// A textarea can't color individual lines, so command drafts render through
// a mirror layer: textarea text goes transparent, the mirror paints the
// command line coral and prose lines normal. Fonts stay identical between
// mirror and textarea (only color differs), so the caret never misaligns.
// Pure single-line commands additionally switch both to Fira (machine voice).
function updateInputMirror() {
    const mirror = inputMirror;
    const v = messageInput.value;
    const active = v.trimStart().startsWith('@');
    const pure = active && !v.trim().includes('\n');

    messageInput.classList.toggle('command-mode', pure);
    mirror.classList.toggle('command-mode', pure);
    messageInput.classList.toggle('mirrored', active);

    if (!active) {
        mirror.hidden = true;
        mirror.replaceChildren();
        return;
    }
    mirror.hidden = false;
    mirror.replaceChildren();
    const lines = v.split('\n');
    // The command line is the first NON-EMPTY line — a leading blank line
    // ("\n@recall foo") still executes as a command (backend strips the
    // whole input), so the coral tint must follow it, not index 0.
    const cmdLineIdx = lines.findIndex(l => l.trim() !== '');
    lines.forEach((line, i) => {
        const span = document.createElement('span');
        span.textContent = line + (i < lines.length - 1 ? '\n' : '');
        if (i === cmdLineIdx) span.className = 'mirror-cmd';
        mirror.appendChild(span);
    });
    // Track the textarea's box exactly (it auto-resizes)
    mirror.style.left = messageInput.offsetLeft + 'px';
    mirror.style.top = messageInput.offsetTop + 'px';
    mirror.style.width = messageInput.clientWidth + 'px';
    mirror.style.height = messageInput.clientHeight + 'px';
    mirror.scrollTop = messageInput.scrollTop;
}

// ── COMMAND AUTOCOMPLETE ─────────────────────────────────────
// Type @ at the start of a line → command list; @entity/@concept
// sub-tokens complete from live DB names (via /api/command, cached).

const AC_COMMANDS = [
    { text: '@recall ', label: '@recall', hint: 'search memories' },
    { text: '@entity ', label: '@entity', hint: 'topics' },
    { text: '@concept ', label: '@concept', hint: 'concepts' },
    { text: '@file ', label: '@file', hint: 'files' },
    { text: '@forget ', label: '@forget', hint: 'archive a topic' },
    { text: '@artifact ', label: '@artifact', hint: 'save artifact' },
    { text: '@describe ', label: '@describe', hint: 'describe a file' },
    { text: '@note ', label: '@note', hint: 'AI notes' },
    { text: '@config', label: '@config', hint: 'show settings' },
    { text: '@help', label: '@help', hint: 'command help' },
];
const AC_SUBS = {
    entity: ['list', 'view ', 'merge '],
    concept: ['list', 'view ', 'create ', 'edit ', 'delete '],
    file: ['list', 'view ', 'search '],
};

let acNameCache = { entities: null, concepts: null, fetchedAt: 0 };
let acActiveIndex = -1;
let acItems = [];

async function acEnsureNames() {
    if (acNameCache.entities && Date.now() - acNameCache.fetchedAt < 120000) return;
    try {
        const [er, cr] = await Promise.all([
            consoleExec('@entity list'),
            consoleExec('@concept list'),
        ]);
        acNameCache.entities = ((er.data && er.data.entities) || []).map(e => e.name);
        acNameCache.concepts = ((cr.data && cr.data.concepts) || []).map(c => c.name);
        acNameCache.fetchedAt = Date.now();
        // Names arrived after the keystroke that wanted them — refresh the popup
        if (!cmdAutocomplete.hidden || document.activeElement === messageInput) {
            acUpdate();
        }
    } catch (e) {
        acNameCache.entities = acNameCache.entities || [];
        acNameCache.concepts = acNameCache.concepts || [];
    }
}

// Returns { lineStart, suggestions: [{label, hint, replaceFrom, text}] } or null
function acCompute() {
    const pos = messageInput.selectionStart;
    if (pos !== messageInput.selectionEnd) return null;
    const before = messageInput.value.slice(0, pos);
    const lineStart = before.lastIndexOf('\n') + 1;
    const line = before.slice(lineStart);
    if (!line.startsWith('@')) return null;

    // Typing the command word itself
    const mCmd = line.match(/^@(\S*)$/);
    if (mCmd) {
        const p = mCmd[1].toLowerCase();
        const items = AC_COMMANDS
            .filter(c => c.label.slice(1).startsWith(p) && c.label.slice(1) !== p)
            .map(c => ({ label: c.label, hint: c.hint, replaceFrom: 0, text: c.text }));
        return items.length ? { lineStart, suggestions: items } : null;
    }

    const mHead = line.match(/^@(\w+)\s/);
    if (!mHead) return null;
    const cmd = mHead[1].toLowerCase();
    if (!(cmd in AC_SUBS)) return null;

    // Partial token = text after the last space or pipe on the line
    const sepIdx = Math.max(line.lastIndexOf(' '), line.lastIndexOf('|'));
    const partial = line.slice(sepIdx + 1);
    const partialLower = partial.toLowerCase();
    const replaceFrom = sepIdx + 1;
    const afterHead = line.slice(mHead[0].length);
    const typingFirstToken = !afterHead.includes(' ') && !afterHead.includes('|');

    const items = [];
    if (typingFirstToken) {
        for (const s of AC_SUBS[cmd]) {
            const bare = s.trim();
            if (bare.startsWith(partialLower) && bare !== partialLower) {
                items.push({ label: bare, hint: '', replaceFrom, text: s });
            }
        }
    }
    // Name completion: @entity view/merge/<name>, @concept view/edit/delete
    const wantsNames =
        (cmd === 'entity' && !/^\s*list\b/.test(afterHead)) ||
        (cmd === 'concept' && /^(view|edit|delete)\s/.test(afterHead));
    if (wantsNames) {
        acEnsureNames();  // async warm-up; suggestions appear as you keep typing
        const names = cmd === 'entity' ? (acNameCache.entities || []) : (acNameCache.concepts || []);
        for (const n of names) {
            if (n.toLowerCase().startsWith(partialLower) && n.toLowerCase() !== partialLower) {
                items.push({ label: n, hint: '', replaceFrom, text: n });
                if (items.length >= 8) break;
            }
        }
    }
    return items.length ? { lineStart, suggestions: items } : null;
}

function acHide() {
    const el = cmdAutocomplete;
    el.hidden = true;
    el.replaceChildren();
    acItems = [];
    acActiveIndex = -1;
}

function acApply(item, lineStart) {
    const pos = messageInput.selectionStart;
    const absFrom = lineStart + item.replaceFrom;
    messageInput.value = messageInput.value.slice(0, absFrom) + item.text + messageInput.value.slice(pos);
    const newPos = absFrom + item.text.length;
    messageInput.setSelectionRange(newPos, newPos);
    messageInput.focus();
    messageInput.dispatchEvent(new Event('input'));
}

function acUpdate() {
    const result = acCompute();
    if (!result) { acHide(); return; }
    const el = cmdAutocomplete;
    el.replaceChildren();
    acItems = result.suggestions;
    acActiveIndex = 0;
    result.suggestions.forEach((item, i) => {
        const btn = document.createElement('button');
        btn.className = 'cmd-ac-item' + (i === acActiveIndex ? ' active' : '');
        const l = document.createElement('span');
        l.textContent = item.label;
        btn.appendChild(l);
        if (item.hint) {
            const h = document.createElement('span');
            h.className = 'cmd-ac-hint';
            h.textContent = item.hint;
            btn.appendChild(h);
        }
        // pointerdown only guards focus (keeps the textarea from blurring);
        // apply on click so a scroll gesture over the list never selects
        btn.addEventListener('pointerdown', (e) => e.preventDefault());
        btn.addEventListener('click', () => acApply(item, result.lineStart));
        el.appendChild(btn);
    });
    el.hidden = false;
    el._lineStart = result.lineStart;
}

function acSetActive(index) {
    const el = cmdAutocomplete;
    const buttons = el.querySelectorAll('.cmd-ac-item');
    if (!buttons.length) return;
    acActiveIndex = (index + buttons.length) % buttons.length;
    buttons.forEach((b, i) => b.classList.toggle('active', i === acActiveIndex));
    buttons[acActiveIndex].scrollIntoView({ block: 'nearest' });
}

function acHandleKeydown(e) {
    const el = cmdAutocomplete;
    if (el.hidden) return;
    if (e.key === 'ArrowDown') { e.preventDefault(); acSetActive(acActiveIndex + 1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); acSetActive(acActiveIndex - 1); }
    else if (e.key === 'Tab') {
        e.preventDefault();
        if (acItems[acActiveIndex]) acApply(acItems[acActiveIndex], el._lineStart);
    }
    else if (e.key === 'Escape') { acHide(); }
}

// ── Console forms (Phase C: formified actions) ──
function makeConsoleField(label, el) {
    const wrap = document.createElement('label');
    wrap.className = 'cmd-form-field';
    const l = document.createElement('span');
    l.className = 'cmd-form-label';
    l.textContent = label;
    wrap.appendChild(l);
    wrap.appendChild(el);
    return wrap;
}

function makeConsoleInput(placeholder) {
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'cmd-form-input';
    input.placeholder = placeholder || '';
    return input;
}

function makeConsoleTextarea(placeholder, rows) {
    const ta = document.createElement('textarea');
    ta.className = 'cmd-form-input cmd-form-textarea';
    ta.placeholder = placeholder || '';
    ta.rows = rows || 4;
    return ta;
}

// '|' is the command argument separator — keep user text out of that channel
function pipeSafe(value) {
    return value.replace(/\|/g, '/').trim();
}

// Shared by create (blank, placeholder examples) and edit (prefilled)
function renderConceptForm(existing) {
    const isEdit = !!existing;
    const wrap = document.createElement('div');
    wrap.className = 'cmd-detail';
    const name = makeConsoleInput('e.g. creative_blocks');
    const keywords = makeConsoleInput('comma separated, e.g. stuck, block, procrastination');
    const definition = makeConsoleTextarea('What should the AI know when these keywords come up?', 5);
    if (isEdit) {
        name.value = existing.name;
        name.disabled = true;  // the name is the identity @concept edit keys on
        keywords.value = (existing.trigger_keywords || []).join(', ');
        definition.value = existing.definition || '';
    }
    wrap.appendChild(makeConsoleField('name', name));
    wrap.appendChild(makeConsoleField('trigger keywords', keywords));
    wrap.appendChild(makeConsoleField('definition', definition));
    wrap.appendChild(makeConsoleActionBtn(isEdit ? 'Save changes' : 'Create concept', async () => {
        if (!name.value.trim() || !keywords.value.trim() || !definition.value.trim()) {
            consoleAnnounce('✗ name, keywords, and definition are all required', 'error');
            return;
        }
        const verb = isEdit ? 'edit' : 'create';
        const cmd = `@concept ${verb} ${pipeSafe(name.value)} | ${pipeSafe(keywords.value)} | ${pipeSafe(definition.value)}`;
        try {
            const r = await consoleExec(cmd);
            if (!r.success) throw new Error(r.message);
            consoleAnnounce(r.message);
            runConsoleQuery('@concept list', { replaceTop: true });
        } catch (err) {
            consoleFailAnnounce(err);
        }
    }));
    consolePush(isEdit ? `edit · ${existing.name}` : 'new concept', wrap);
}

function renderConceptCreateForm() { renderConceptForm(null); }

// Typed "@concept create" / "@concept edit <name>" (without | args) opens the
// form instead of being sent. Returns true if the message was intercepted.
async function interceptFormCommand(message) {
    const trimmed = message.trim();
    if (/^@concept\s+create\s*$/i.test(trimmed)) {
        messageInput.value = '';
        messageInput.style.height = 'auto';
        updateInputMirror();
        sendBtn.classList.remove('has-text');
        openCommandsDrawer();
        renderConceptCreateForm();
        return true;
    }
    const mEdit = trimmed.match(/^@concept\s+edit\s+([^|\n]+)$/i);
    if (mEdit) {
        try {
            const r = await consoleExec(`@concept view ${mEdit[1].trim()}`);
            if (!r.success || !r.data || !r.data.concept) throw new Error(r.message || 'concept not found');
            messageInput.value = '';
            messageInput.style.height = 'auto';
            updateInputMirror();
            sendBtn.classList.remove('has-text');
            openCommandsDrawer();
            renderConceptForm(r.data.concept);
            return true;
        } catch (err) {
            consoleFailAnnounce(err);
            return true;  // handled — don't send the broken command through chat
        }
    }
    return false;
}

function renderForgetForm() {
    const wrap = document.createElement('div');
    wrap.className = 'cmd-detail';
    wrap.appendChild(consoleNote('archived memories stop surfacing in context — they are not deleted'));
    const topic = makeConsoleInput('e.g. old apartment hunt');
    wrap.appendChild(makeConsoleField('topic to archive', topic));
    wrap.appendChild(makeConsoleActionBtn('Find memories', async () => {
        const t = pipeSafe(topic.value);
        if (!t) return;
        consolePush('searching...', consoleNote('searching memories...'));
        try {
            const r = await consoleExec(`@forget ${t}`);
            if (!r.success) throw new Error(r.message);
            const previews = (r.data && r.data.previews) || [];
            consoleReplaceTop(`archive · ${previews.length}`, renderForgetPreviewView(t, previews));
        } catch (err) {
            consoleFail(err);
        }
    }));
    consolePush('archive a topic', wrap);
}

function renderForgetPreviewView(topic, previews) {
    const wrap = document.createElement('div');
    wrap.className = 'cmd-detail';
    if (!previews.length) {
        wrap.appendChild(consoleNote(`no memories found matching "${topic}"`));
        return wrap;
    }
    wrap.appendChild(consoleNote(`tap the memories to archive — matching "${topic}"`));
    const list = document.createElement('div');
    list.className = 'cmd-card-list';
    const selected = new Set();
    const archiveBtn = makeConsoleActionBtn('', async () => {
        if (!selected.size) return;
        try {
            const r = await consoleExec('@forget confirm ' + [...selected].join(' '));
            if (!r.success) throw new Error(r.message);
            closeCommandsDrawer();
            consoleAnnounce(r.message);
        } catch (err) {
            consoleFailAnnounce(err);
        }
    });
    archiveBtn.hidden = true;
    for (const p of previews) {
        const card = makeCmdCard(p.description, `${p.timestamp} · ${p.sender}`, () => {
            if (selected.has(p.id)) selected.delete(p.id);
            else selected.add(p.id);
            card.classList.toggle('selected', selected.has(p.id));
            archiveBtn.hidden = selected.size === 0;
            archiveBtn.textContent = `Archive ${selected.size} ${selected.size === 1 ? 'memory' : 'memories'}`;
        });
        list.appendChild(card);
    }
    wrap.appendChild(list);
    wrap.appendChild(archiveBtn);
    return wrap;
}

function renderEntityListView(entities) {
    const wrap = document.createElement('div');
    wrap.className = 'cmd-card-list';
    if (!entities.length) {
        wrap.appendChild(consoleNote('no topics tracked yet'));
        return { title: 'topics · 0', node: wrap };
    }
    entities = [...entities].sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }));

    // Selection mode (for merging) is entered by long-pressing a card — no
    // toolbar toggle. While active, tap toggles selection and hold "peeks"
    // at that card's detail instead of opening it (inverted from the
    // no-selection state, on purpose — see src/frontend/CLAUDE.md).
    const selected = new Set();  // entity names

    const actionBar = document.createElement('div');
    actionBar.className = 'cmd-merge-bar';
    actionBar.hidden = true;
    const mergeBtn = makeConsoleActionBtn('', () => {
        if (selected.size < 2) return;
        const names = [...selected];
        selected.clear();
        syncSelectionUI();
        consoleReplaceTop('merging...', renderMergeProgressView(names));
    });
    const cancelBtn = document.createElement('button');
    cancelBtn.className = 'cmd-merge-cancel';
    cancelBtn.setAttribute('aria-label', 'Cancel selection');
    cancelBtn.textContent = '×';
    cancelBtn.addEventListener('click', () => {
        selected.clear();
        wrap.querySelectorAll('.cmd-card.selected').forEach(c => c.classList.remove('selected'));
        syncSelectionUI();
    });
    actionBar.appendChild(mergeBtn);
    actionBar.appendChild(cancelBtn);

    function syncSelectionUI() {
        const n = selected.size;
        actionBar.hidden = n < 1;
        wrap.classList.toggle('selection-active', n >= 1);
        mergeBtn.disabled = n < 2;
        mergeBtn.textContent = n >= 2 ? `Merge ${n} into one` : 'select another to merge';
    }

    function toggleSelected(name, card) {
        if (selected.has(name)) selected.delete(name);
        else selected.add(name);
        card.classList.toggle('selected', selected.has(name));
        syncSelectionUI();
    }

    for (const e of entities) {
        const card = makeCmdCard(e.name, e.description || '', null);
        attachHoldTap(card, {
            onTap: () => {
                if (selected.size > 0) {
                    toggleSelected(e.name, card);
                } else {
                    runConsoleQuery(`@entity view ${e.name}`);
                }
            },
            onHold: () => {
                if (selected.size > 0) {
                    // Peek: open detail without leaving selection mode.
                    runConsoleQuery(`@entity view ${e.name}`);
                } else {
                    selected.add(e.name);
                    card.classList.add('selected');
                    syncSelectionUI();
                }
            },
        });
        wrap.appendChild(card);
    }
    wrap.appendChild(actionBar);
    return { title: `topics · ${entities.length}`, node: wrap };
}

// Bumped whenever a new merge starts; a poll loop checks this (plus that its
// own progress node is still the visible stack top) before touching the
// console, so navigating away/back or starting another merge cancels it.
let consoleMergeGeneration = 0;

function renderMergeProgressView(names) {
    const gen = ++consoleMergeGeneration;
    const wrap = document.createElement('div');
    wrap.className = 'cmd-merge-progress';

    const namesEl = document.createElement('div');
    namesEl.className = 'cmd-console-note';
    namesEl.textContent = names.join(' · ');
    wrap.appendChild(namesEl);

    // The Mneme logo animation, inline-sized (drawLoadingIcon renders at
    // fixed internal resolution; CSS scales it down). The rAF loop stops
    // itself as soon as this view stops being the live stack top.
    const logo = document.createElement('canvas');
    logo.className = 'cmd-merge-logo';
    wrap.appendChild(logo);
    let logoStart = null;
    function logoFrame(ts) {
        if (!isLive()) return;
        if (logoStart === null) logoStart = ts;
        drawLoadingIcon(logo, ts - logoStart);
        requestAnimationFrame(logoFrame);
    }
    requestAnimationFrame(logoFrame);

    const status = document.createElement('div');
    status.className = 'cmd-merge-status';
    status.textContent = 'choosing the survivor...';
    wrap.appendChild(status);

    // True only while this exact progress node is still the visible top of
    // the stack and no newer merge has superseded it.
    function isLive() {
        const top = cmdConsoleStack[cmdConsoleStack.length - 1];
        return consoleMergeGeneration === gen && top && top.node === wrap;
    }

    (async () => {
        let mergeMessage = '';
        let survivorName = names[0];
        try {
            const r = await consoleExec('@entity merge ' + names.join(' | '));
            if (!isLive()) return;
            if (!r.success) throw new Error(r.message);
            mergeMessage = r.message;
            survivorName = (r.data && r.data.merged_entity && r.data.merged_entity.name) || survivorName;
            status.textContent = 'rebuilding the combined summary...';

            let lastPoll = null;
            // The rebuild bootstraps month by month (~12s each on a big
            // entity) and finishes with the all_time summary — wait for
            // THAT, not the first monthly the view's fallback surfaces,
            // and narrate the months as they land.
            const maxAttempts = 80;  // ~4min at 3s intervals
            for (let i = 0; i < maxAttempts; i++) {
                await new Promise(resolve => setTimeout(resolve, 3000));
                if (!isLive()) return;
                try {
                    const poll = await consoleExec(`@entity view ${survivorName}`);
                    if (!isLive()) return;
                    if (poll.success && poll.data && poll.data.entity) {
                        lastPoll = poll;
                        const s = poll.data.summary;
                        if (s && s.summary && s.period_type === 'all_time') {
                            const detail = renderEntityDetailView(poll.data.entity, s);
                            consoleReplaceTop(detail.title, detail.node);
                            consoleAnnounce(mergeMessage || `merged into '${survivorName}'`);
                            return;
                        }
                        if (s && s.period_start) {
                            status.textContent = `rebuilding — ${s.period_start} done...`;
                        }
                    }
                } catch (pollErr) {
                    // Transient poll failure — keep waiting out the timeout.
                }
            }
            if (!isLive()) return;
            // Timed out — land on the detail view anyway; it shows the
            // "builds automatically" copy until the background rebuild lands.
            const fallbackEntity = (lastPoll && lastPoll.data && lastPoll.data.entity) || { name: survivorName };
            const fallbackSummary = lastPoll && lastPoll.data && lastPoll.data.summary;
            const detail = renderEntityDetailView(fallbackEntity, fallbackSummary);
            consoleReplaceTop(detail.title, detail.node);
            consoleAnnounce((mergeMessage || `merged into '${survivorName}'`) + ' — summary still rebuilding');
        } catch (err) {
            if (!isLive()) return;
            consoleFail(err);
        }
    })();

    return wrap;
}

function renderEntityDetailView(entity, summary) {
    const wrap = document.createElement('div');
    wrap.className = 'cmd-detail';
    if (entity.description) wrap.appendChild(consoleNote(entity.description));
    const body = document.createElement('div');
    body.className = 'cmd-detail-body';
    body.textContent = (summary && summary.summary) ? summary.summary
        : 'No summary yet — one builds automatically the next time this topic comes up.';
    wrap.appendChild(body);
    wrap.appendChild(makeConsoleActionBtn('Bring into next reply', async () => {
        try {
            const r = await consoleExec(`@entity ${entity.name}`);
            if (!r.success) throw new Error(r.message);
            closeCommandsDrawer();
            consoleAnnounce(r.message || `'${entity.name}' will be included in the next retrieval`);
        } catch (err) {
            consoleFailAnnounce(err);
        }
    }));
    return { title: entity.name, node: wrap };
}

// Files view — squircle grid of previews from /api/attachments (structured
// data + thumbnails; richer than what @file list's text output can carry)
async function runFilesView() {
    consolePush('querying...', consoleNote('querying files...'));
    try {
        const res = await fetch('/api/attachments?limit=30');
        const payload = await res.json();
        if (payload.error) throw new Error(payload.error);
        const files = payload.attachments || [];

        const grid = document.createElement('div');
        grid.className = 'cmd-file-grid';
        if (!files.length) grid.appendChild(consoleNote('no files uploaded yet'));
        for (const f of files) {
            const tile = document.createElement('button');
            tile.className = 'cmd-file-tile';
            if (f.thumbnail_url) {
                const img = document.createElement('img');
                img.src = f.thumbnail_url;
                img.alt = f.filename;
                img.loading = 'lazy';
                tile.appendChild(img);
            } else {
                const ext = document.createElement('span');
                ext.className = 'cmd-file-ext';
                ext.textContent = (f.filename.split('.').pop() || 'file').slice(0, 5);
                const name = document.createElement('span');
                name.className = 'cmd-file-name';
                name.textContent = f.filename;
                tile.appendChild(ext);
                tile.appendChild(name);
            }
            tile.addEventListener('click', () => renderFileDetailView(f));
            grid.appendChild(tile);
        }
        consoleReplaceTop(`files · ${files.length}`, grid);
    } catch (err) {
        consoleFail(err);
    }
}

function renderFileDetailView(f) {
    const wrap = document.createElement('div');
    wrap.className = 'cmd-detail';
    if (f.thumbnail_url) {
        const img = document.createElement('img');
        img.className = 'cmd-file-preview';
        img.src = `/api/attachment/${f.uuid}/image`;
        img.alt = f.filename;
        wrap.appendChild(img);
    }
    wrap.appendChild(consoleNote(`${f.filename} · ${(f.created_at || '').slice(0, 10)}`));
    const desc = makeConsoleTextarea('Describe this file so memory search can find it...', 3);
    desc.value = f.ai_description || '';
    wrap.appendChild(makeConsoleField('description', desc));
    const row = document.createElement('div');
    row.className = 'cmd-action-row';
    row.appendChild(makeConsoleActionBtn('Save description', async () => {
        const text = pipeSafe(desc.value);
        if (!text) return;
        try {
            const r = await consoleExec(`@describe ${f.uuid.slice(0, 8)} | ${text}`);
            if (!r.success) throw new Error(r.message);
            consoleAnnounce(r.message);
        } catch (err) {
            consoleFailAnnounce(err);
        }
    }));
    row.appendChild(makeConsoleActionBtn('Show to the AI', () => {
        closeCommandsDrawer();
        insertCommand(`@file view ${f.uuid.slice(0, 8)}`);
    }));
    wrap.appendChild(row);
    consolePush(f.filename, wrap);
}

function renderConceptListView(concepts) {
    const wrap = document.createElement('div');
    wrap.className = 'cmd-card-list';
    if (!concepts.length) wrap.appendChild(consoleNote('no concepts defined yet'));
    concepts = [...concepts].sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }));
    for (const c of concepts) {
        const keywords = (c.trigger_keywords || []).join(', ');
        wrap.appendChild(makeCmdCard(c.name, keywords, () => {
            runConsoleQuery(`@concept view ${c.name}`);
        }));
    }
    return { title: `concepts · ${concepts.length}`, node: wrap };
}

function renderConceptDetailView(concept) {
    const wrap = document.createElement('div');
    wrap.className = 'cmd-detail';
    wrap.appendChild(consoleNote('keywords: ' + (concept.trigger_keywords || []).join(', ')));
    const body = document.createElement('div');
    body.className = 'cmd-detail-body';
    body.textContent = concept.definition || '';
    wrap.appendChild(body);

    const row = document.createElement('div');
    row.className = 'cmd-action-row';
    row.appendChild(makeConsoleActionBtn('Edit', () => {
        renderConceptForm(concept);
    }));
    const del = makeConsoleActionBtn('Delete', async () => {
        if (!del.classList.contains('danger-armed')) {
            del.classList.add('danger-armed');
            del.textContent = 'Really delete?';
            return;
        }
        try {
            const r = await consoleExec(`@concept delete ${concept.name}`);
            if (!r.success) throw new Error(r.message);
            consoleBack();                                   // pop detail
            runConsoleQuery('@concept list', { replaceTop: true });  // refresh list
        } catch (err) {
            consoleFail(err);
        }
    });
    row.appendChild(del);
    wrap.appendChild(row);
    return { title: concept.name, node: wrap };
}

async function showSettings() {
    settingsPage.classList.add('active');
    await loadSettingsValues();
    loadSystemInstructions();
    loadStats();
}

function hideSettings() {
    settingsPage.classList.remove('active');
}

// ── Reusable settings confirmation overlay ──
// One dispatcher wired once (initSettingsConfirmOverlay); showConfirm() just
// updates which callbacks the dispatcher reads, so repeated calls never stack
// extra click listeners on the OK/Cancel buttons.
let _confirmOnOk = null;
let _confirmOnCancel = null;

function showConfirm(text, { okLabel = 'Change', onOk = null, onCancel = null } = {}) {
    const overlay = document.getElementById('settingsConfirmOverlay');
    const textEl = document.getElementById('settingsConfirmText');
    const okBtn = document.getElementById('settingsConfirmOk');
    if (!overlay || !textEl || !okBtn) return;
    textEl.textContent = text;
    okBtn.textContent = okLabel;
    _confirmOnOk = onOk;
    _confirmOnCancel = onCancel;
    overlay.classList.add('active');
}

function hideConfirm() {
    const overlay = document.getElementById('settingsConfirmOverlay');
    if (overlay) overlay.classList.remove('active');
}

function initSettingsConfirmOverlay() {
    const overlay = document.getElementById('settingsConfirmOverlay');
    const cancelBtn = document.getElementById('settingsConfirmCancel');
    const okBtn = document.getElementById('settingsConfirmOk');
    if (!overlay || !cancelBtn || !okBtn) return;

    cancelBtn.addEventListener('click', () => {
        const cb = _confirmOnCancel;
        _confirmOnOk = null;
        _confirmOnCancel = null;
        hideConfirm();
        if (cb) cb();
    });
    okBtn.addEventListener('click', () => {
        const cb = _confirmOnOk;
        _confirmOnOk = null;
        _confirmOnCancel = null;
        hideConfirm();
        if (cb) cb();
    });
    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) cancelBtn.click();
    });
}

// ── System instructions editor ──
let sysInstructionsPristine = null;
let sysInstructionsTemplate = null;

function isSysInstructionsDirty() {
    const textarea = document.getElementById('sysInstructionsEditor');
    if (!textarea || sysInstructionsPristine === null) return false;
    return textarea.value !== sysInstructionsPristine;
}

async function loadSystemInstructions() {
    const textarea = document.getElementById('sysInstructionsEditor');
    const status = document.getElementById('sysInstructionsStatus');
    const resetBtn = document.getElementById('sysInstructionsResetBtn');
    if (!textarea) return;
    try {
        const res = await fetch('/api/system-instructions');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        sysInstructionsPristine = data.content ?? '';
        sysInstructionsTemplate = data.template ?? '';
        textarea.value = sysInstructionsPristine;
        textarea.disabled = false;
        if (resetBtn) resetBtn.disabled = !sysInstructionsTemplate;
        if (status) status.textContent = '';
    } catch (e) {
        sysInstructionsPristine = null;
        sysInstructionsTemplate = null;
        textarea.disabled = true;
        if (resetBtn) resetBtn.disabled = true;
        if (status) status.textContent = 'Could not load system instructions.';
    }
}

async function saveSystemInstructions() {
    const textarea = document.getElementById('sysInstructionsEditor');
    const status = document.getElementById('sysInstructionsStatus');
    if (!textarea) return;
    const content = textarea.value;
    if (!content.trim()) {
        if (status) status.textContent = 'System instructions cannot be empty.';
        return;
    }
    try {
        const res = await fetch('/api/system-instructions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content })
        });
        const data = await res.json().catch(() => ({}));
        if (res.ok && data.success) {
            sysInstructionsPristine = content;
            if (status) status.textContent = 'Saved — takes effect on your next message.';
        } else {
            if (status) status.textContent = data.error || 'Error saving.';
        }
    } catch (e) {
        if (status) status.textContent = 'Error saving.';
    }
}

function resetSystemInstructionsToTemplate() {
    const textarea = document.getElementById('sysInstructionsEditor');
    const status = document.getElementById('sysInstructionsStatus');
    if (!textarea || !sysInstructionsTemplate) return;
    textarea.value = sysInstructionsTemplate;
    if (status) status.textContent = '';
}

function setSnapSelector(id, value) {
    const container = document.getElementById(id);
    if (!container) return;
    const btns = Array.from(container.querySelectorAll('.snap-btn'));
    let bestBtn = btns[0], bestDiff = Infinity;
    btns.forEach(btn => {
        const diff = Math.abs(parseInt(btn.dataset.value) - value);
        if (diff < bestDiff) { bestDiff = diff; bestBtn = btn; }
    });
    btns.forEach(b => b.classList.remove('active'));
    if (bestBtn) bestBtn.classList.add('active');
}

function getSnapValue(id) {
    const container = document.getElementById(id);
    if (!container) return null;
    const active = container.querySelector('.snap-btn.active');
    return active ? parseInt(active.dataset.value) : null;
}

function modelSupportsExtendedContext(model) {
    const id = (model || '').toLowerCase();
    return ['fable', 'opus-4-8', 'opus-4-7', 'opus-4-6', 'sonnet-5', 'sonnet-4-6']
        .some(marker => id.includes(marker));
}

function getSettingsActiveModel() {
    const useTesting = document.getElementById('settingTestingModel')?.checked;
    if (useTesting) return 'claude-haiku-4-5';
    return document.getElementById('settingModelDefault')?.value || 'claude-sonnet-4-6';
}

function updateConversationWindowOptions(model, valueToKeep = null) {
    const selector = document.getElementById('settingRecentTokens');
    const desc = document.getElementById('settingRecentTokensDesc');
    if (!selector) return;

    const supportsExtended = modelSupportsExtendedContext(model);
    selector.classList.toggle('extended-context', supportsExtended);

    if (desc) {
        desc.textContent = supportsExtended
            ? 'These are maximums. Extended windows use 1M context when available and may cost more above 200k.'
            : 'These are maximums. Mneme keeps room for replies, files, and memory search.';
    }

    const current = valueToKeep ?? getSnapValue('settingRecentTokens') ?? 50000;
    const clamped = supportsExtended ? current : Math.min(current, 125000);
    setSnapSelector('settingRecentTokens', clamped);
}

function updateSliderBubble(sliderId, bubbleId) {
    const s = document.getElementById(sliderId), b = document.getElementById(bubbleId);
    if (!s || !b) return;
    const pct = (parseFloat(s.value) - parseFloat(s.min)) / (parseFloat(s.max) - parseFloat(s.min));
    b.style.left = `calc(${pct * 100}% + ${(0.5 - pct) * 16}px)`;
    b.textContent = s.value;
}

function filenameFromContentDisposition(header) {
    if (!header) return null;

    const utfMatch = header.match(/filename\*=UTF-8''([^;]+)/i);
    if (utfMatch) {
        try {
            return decodeURIComponent(utfMatch[1].trim());
        } catch (e) {
            return utfMatch[1].trim();
        }
    }

    const plainMatch = header.match(/filename="?([^";]+)"?/i);
    return plainMatch ? plainMatch[1].trim() : null;
}

async function exportTranscript() {
    const btn = document.getElementById('exportTranscriptBtn');
    const status = document.getElementById('exportTranscriptStatus');
    const format = document.querySelector('#exportTranscriptFormat .transcript-format-option.active')?.dataset.format || 'markdown';

    if (btn) btn.disabled = true;
    if (status) status.textContent = 'Preparing...';

    try {
        const res = await fetch(`/api/export/transcript?format=${encodeURIComponent(format)}`);
        if (!res.ok) {
            let message = `Export failed (${res.status})`;
            try {
                const data = await res.json();
                if (data.error) message = data.error;
            } catch (e) {
                // Ignore non-JSON error bodies.
            }
            throw new Error(message);
        }

        const blob = await res.blob();
        const responseFormat = res.headers.get('X-Mneme-Transcript-Format') || format;
        const extension = responseFormat === 'json' ? 'json' : 'md';
        const filename = filenameFromContentDisposition(res.headers.get('Content-Disposition')) ||
            `mneme-transcript-${new Date().toISOString().slice(0, 10)}.${extension}`;
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);

        const messageCount = res.headers.get('X-Mneme-Message-Count');
        if (status) {
            const formatLabel = responseFormat === 'json' ? 'JSON' : 'Markdown';
            status.textContent = messageCount ? `Exported ${messageCount} messages (${formatLabel})` : `Exported ${formatLabel}`;
            setTimeout(() => {
                if (status.textContent.startsWith('Exported')) status.textContent = '';
            }, 4000);
        }
    } catch (err) {
        console.warn('Transcript export failed:', err);
        if (status) status.textContent = 'Export failed';
        showError(`Transcript export failed: ${err.message}`);
    } finally {
        if (btn) btn.disabled = false;
    }
}


async function loadSettingsValues() {
    try {
        const res = await fetch('/api/settings');
        const data = await res.json();

        // Identity
        document.getElementById('settingUserName').value = data.user_name ?? '';
        document.getElementById('settingInstanceName').value = data.instance_name ?? '';

        // API Keys (masked)
        document.getElementById('settingAnthropicKey').value = data.anthropic_key_masked ?? '';
        document.getElementById('settingOpenaiKey').value = data.openai_key_masked ?? '';
        document.getElementById('settingElevenlabsKey').value = data.elevenlabs_key_masked ?? '';

        // Model — ensure the active model is a selectable option
        const modelSelect = document.getElementById('settingModelDefault');
        const activeModel = data.model_default ?? 'claude-sonnet-4-6';
        if (!modelSelect.querySelector(`option[value="${activeModel}"]`)) {
            // Model from header badge not in dropdown — add it dynamically
            // Parse "claude-sonnet-4-5" → "Sonnet 4.5"
            const parts = activeModel.replace('claude-', '').split('-');
            const name = (parts[0] || '').charAt(0).toUpperCase() + (parts[0] || '').slice(1);
            const version = parts.length >= 3 ? parts.slice(1).join('.') : parts.slice(1).join('-');
            const label = version ? `${name} ${version}` : name;
            const opt = document.createElement('option');
            opt.value = activeModel;
            opt.textContent = label;
            modelSelect.appendChild(opt);
        }
        modelSelect.value = activeModel;
        document.getElementById('settingTestingModel').checked = data.use_testing_model ?? false;
        document.getElementById('settingTemperature').value = data.temperature ?? 1.0;

        // Thinking
        const thinkingEnabled = data.thinking_enabled ?? true;
        document.getElementById('settingThinkingEnabled').checked = thinkingEnabled;
        setSnapSelector('settingThinkingBudget', data.thinking_budget ?? 3000);
        document.getElementById('settingTemperatureSection').style.display = thinkingEnabled ? 'none' : '';
        document.getElementById('settingThinkingBudgetSection').style.display = thinkingEnabled ? '' : 'none';

        // Context
        setSnapSelector('settingRecentTokens', data.recent_messages_tokens ?? 50000);
        updateConversationWindowOptions(getSettingsActiveModel(), data.recent_messages_tokens ?? 50000);
        // memory_context_tokens removed — retrieval uses count limit (max_retrieval_results) only

        // Retrieval
        document.getElementById('settingRetrieval').value = data.retrieval_threshold ?? 0.25;
        document.getElementById('settingMaxRetrieval').value = data.max_retrieval_results ?? 10;
        document.getElementById('settingMaxEntities').value = data.max_entities_per_retrieval ?? 3;
        document.getElementById('settingMaxConcepts').value = data.max_concepts_retrieved ?? 2;
        document.getElementById('settingMaxFiles').value = data.max_files_displayed ?? 5;
        document.getElementById('settingArchiveAge').value = data.deep_archive_age_days ?? 180;

        // Weights
        setWeightsBar(
            data.semantic_weight ?? 0.4,
            data.importance_weight ?? 0.4,
            data.recency_weight ?? 0.2,
            data.entity_match_weight ?? 0.15
        );

        // Features
        document.getElementById('settingConcepts').checked = data.concepts_enabled ?? true;
        document.getElementById('settingEntities').checked = data.entity_summaries_enabled ?? true;
        document.getElementById('settingAttachments').checked = data.attachments_enabled ?? true;
        const ttsEnabled = data.tts_enabled ?? true;
        document.getElementById('settingTTS').checked = ttsEnabled;
        document.getElementById('ttsVoiceLink').style.display = ttsEnabled ? '' : 'none';
        document.getElementById('settingTimeline').checked = data.timeline_enabled ?? true;
        document.getElementById('settingNotes').checked = data.notes_enabled ?? true;

        // System
        const keepAwakeToggle = document.getElementById('settingKeepAwake');
        keepAwakeToggle.checked = data.keep_pc_awake ?? false;
        if (data.keep_pc_awake_supported === false) {
            keepAwakeToggle.disabled = true;
            keepAwakeToggle.checked = false;
            const desc = document.getElementById('keepAwakeDesc');
            if (desc) desc.textContent = 'Not supported on this platform yet.';
        }

        // Update all slider bubbles
        ['settingRetrieval', 'settingMaxRetrieval',
         'settingMaxEntities', 'settingMaxConcepts', 'settingMaxFiles',
         'settingTemperature', 'settingArchiveAge'].forEach(id => updateSliderBubble(id, id + 'Value'));

    } catch (e) { /* silent */ }
}

// ── Retrieval weights bar ──
function setWeightsBar(semantic, importance, recency, entityMatch) {
    const total = semantic + importance + recency + entityMatch;
    const s = Math.round(semantic / total * 100) / 100;
    const i = Math.round(importance / total * 100) / 100;
    const r = Math.round(recency / total * 100) / 100;
    const m = Math.round((1 - s - i - r) * 100) / 100;
    document.getElementById('weightSemantic').style.flex = s;
    document.getElementById('weightImportance').style.flex = i;
    document.getElementById('weightRecency').style.flex = r;
    document.getElementById('weightEntityMatch').style.flex = m;
    document.getElementById('weightSemanticValue').textContent = s.toFixed(2);
    document.getElementById('weightImportanceValue').textContent = i.toFixed(2);
    document.getElementById('weightRecencyValue').textContent = r.toFixed(2);
    document.getElementById('weightEntityMatchValue').textContent = m.toFixed(2);
}

function initWeightsBar() {
    const bar = document.getElementById('settingWeightsBar');
    const handle1 = document.getElementById('weightHandle1');
    const handle2 = document.getElementById('weightHandle2');
    const handle3 = document.getElementById('weightHandle3');
    let activeHandle = null;

    function onPointerDown(e) {
        activeHandle = e.target;
        activeHandle.classList.add('dragging');
        activeHandle.setPointerCapture(e.pointerId);
    }

    function onPointerMove(e) {
        if (!activeHandle) return;
        const rect = bar.getBoundingClientRect();
        const pct = (e.clientX - rect.left) / rect.width;

        const s = parseFloat(document.getElementById('weightSemanticValue').textContent);
        const i = parseFloat(document.getElementById('weightImportanceValue').textContent);
        const r = parseFloat(document.getElementById('weightRecencyValue').textContent);
        const m = parseFloat(document.getElementById('weightEntityMatchValue').textContent);

        const MIN = 0.05;
        let ns = s, ni = i, nr = r, nm = m;

        if (activeHandle === handle1) {
            // Between semantic and importance — only adjust their ratio
            const pair = s + i;
            const raw = Math.max(MIN, Math.min(pair - MIN, pct));
            ns = Math.round(raw * 20) / 20;
            ni = Math.round((pair - ns) * 100) / 100;
        } else if (activeHandle === handle2) {
            // Between importance and recency — only adjust their ratio
            const pair = i + r;
            const raw = Math.max(MIN, Math.min(pair - MIN, pct - s));
            ni = Math.round(raw * 20) / 20;
            nr = Math.round((pair - ni) * 100) / 100;
        } else {
            // Between recency and match — only adjust their ratio
            const pair = r + m;
            const raw = Math.max(MIN, Math.min(pair - MIN, pct - s - i));
            nr = Math.round(raw * 20) / 20;
            nm = Math.round((pair - nr) * 100) / 100;
        }

        if (ns >= 0.05 && ni >= 0.05 && nr >= 0.05 && nm >= 0.05) {
            setWeightsBar(ns, ni, nr, nm);
        }
    }

    function onPointerUp() {
        if (activeHandle) activeHandle.classList.remove('dragging');
        activeHandle = null;
    }

    handle1.addEventListener('pointerdown', onPointerDown);
    handle2.addEventListener('pointerdown', onPointerDown);
    handle3.addEventListener('pointerdown', onPointerDown);
    bar.addEventListener('pointermove', onPointerMove);
    bar.addEventListener('pointerup', onPointerUp);
    bar.addEventListener('pointercancel', onPointerUp);
}

async function loadStats() {
    try {
        const response = await fetch(`${API_BASE}/api/stats`);
        if (!response.ok) throw new Error('Failed to fetch stats');

        const data = await response.json();

        // Update header
        const displayName = data.instance_name || data.profile || 'default';
        window._instanceName = displayName;
        profileName.textContent = displayName;
        messageInput.placeholder = `Write to ${displayName}...`;

        // Update model badge and header
        const modelStr = data.model || 'Unknown';
        updateModelBadge(modelStr);

        document.getElementById('statRecentBudget').textContent =
            `${(data.recent_budget || 0).toLocaleString()} tokens`;
        document.getElementById('statMemoryBudget').textContent =
            `max ${data.memory_limit || 10} results`;
        document.getElementById('statEntityBudget').textContent =
            data.entity_enabled ? `max ${data.entity_limit || 3} entities` : 'Disabled';
        document.getElementById('statConceptBudget').textContent =
            data.concept_enabled ? `max ${data.concept_limit || 2} concepts` : 'Disabled';

        document.getElementById('statActiveTier').textContent =
            `${(data.active_tier || 0).toLocaleString()} messages`;
        document.getElementById('statStandardTier').textContent =
            `${(data.standard_tier || 0).toLocaleString()} messages`;
        document.getElementById('statDeepTier').textContent =
            `${(data.deep_tier || 0).toLocaleString()} messages`;

    } catch (error) {
        console.error('Error loading stats:', error);
        profileName.textContent = 'error';
    }
}

// =============================================================================
// TTS (Phase 9)
// =============================================================================

// TTS with icon-based button (play/stop SVGs)
async function playTTSWithBtn(text, button) {
    if (currentTTSButton === button && currentAudio) {
        stopTTS();
        return;
    }
    if (currentAudio) stopTTS();

    const cleanText = stripMarkdown(text);
    if (!cleanText.trim()) return;

    button.classList.add('loading');

    try {
        const response = await fetch(`${API_BASE}/api/tts`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: cleanText })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'TTS request failed');
        }

        const audioBlob = await response.blob();
        const audioUrl = URL.createObjectURL(audioBlob);
        currentAudio = new Audio(audioUrl);
        currentTTSButton = button;

        button.innerHTML = `<img src="assets/icon-stop.svg" alt="Stop" width="10" height="10">`;
        button.classList.remove('loading');
        button.classList.add('playing');

        currentAudio.addEventListener('ended', () => cleanupTTSWithBtn(button, audioUrl));
        currentAudio.addEventListener('error', () => {
            cleanupTTSWithBtn(button, audioUrl);
            showError('Audio playback failed');
        });

        await currentAudio.play();

    } catch (error) {
        console.error('TTS error:', error);
        button.innerHTML = `<img src="assets/icon-play.svg" alt="Play" width="10" height="10">`;
        button.classList.remove('loading');
        showError(`TTS failed: ${error.message}`);
    }
}

function cleanupTTSWithBtn(button, audioUrl) {
    if (button) {
        button.innerHTML = `<img src="assets/icon-play.svg" alt="Play" width="10" height="10">`;
        button.classList.remove('playing', 'loading');
    }
    if (audioUrl) URL.revokeObjectURL(audioUrl);
    currentAudio = null;
    currentTTSButton = null;
}

function stopTTS() {
    if (currentAudio) {
        currentAudio.pause();
        currentAudio.currentTime = 0;
        const audioUrl = currentAudio.src;
        // Detect which type of button (icon-based vs old music note)
        if (currentTTSButton && currentTTSButton.querySelector('img')) {
            cleanupTTSWithBtn(currentTTSButton, audioUrl);
        } else {
            cleanupTTS(currentTTSButton, audioUrl);
        }
    }
}

function cleanupTTS(button, audioUrl) {
    if (button) {
        button.innerHTML = '&#9834;';
        button.classList.remove('playing', 'loading');
    }
    if (audioUrl) {
        URL.revokeObjectURL(audioUrl);
    }
    currentAudio = null;
    currentTTSButton = null;
}

function stripMarkdown(text) {
    return text
        .replace(/```[\s\S]*?```/g, '')
        .replace(/`[^`]+`/g, '')
        .replace(/\*\*([^\*]+)\*\*/g, '$1')
        .replace(/\*([^\*]+)\*/g, '$1')
        .replace(/\[([^\]]+)\]\([^\)]+\)/g, '$1')
        .replace(/^#+\s*/gm, '')
        .replace(/\s+/g, ' ')
        .trim();
}

// =============================================================================
// THINKING (Phase 10)
// =============================================================================

function attachThinkingBlockCollapse(details) {
    details.addEventListener('click', (e) => {
        if (details.open) {
            e.preventDefault();
            details.removeAttribute('open');
        }
    });
}

function createThinkingBlock(messageDiv) {
    const details = document.createElement('details');
    details.className = 'thinking-block';

    const summary = document.createElement('summary');
    summary.className = 'thinking-summary';
    summary.textContent = 'Thinking...';

    const content = document.createElement('div');
    content.className = 'thinking-content';
    content.setAttribute('data-raw-thinking', '');

    details.appendChild(summary);
    details.appendChild(content);
    attachThinkingBlockCollapse(details);

    const contentDiv = messageDiv.querySelector('.message-content');
    messageDiv.insertBefore(details, contentDiv);

    return details;
}

function appendToThinkingBlock(thinkingBlock, chunk) {
    const content = thinkingBlock.querySelector('.thinking-content');
    const rawThinking = content.getAttribute('data-raw-thinking') + chunk;
    content.setAttribute('data-raw-thinking', rawThinking);
    content.textContent = rawThinking;

    if (streamingAutoScroll) {
        scrollToBottom(true);
    }
}

function finalizeThinkingBlock(thinkingBlock, elapsed) {
    const summary = thinkingBlock.querySelector('.thinking-summary');
    summary.textContent = `Thought for ${elapsed}s`;
}

function createStaticThinkingBlock(messageDiv, thinkingText) {
    const details = document.createElement('details');
    details.className = 'thinking-block';

    const summary = document.createElement('summary');
    summary.className = 'thinking-summary';
    summary.textContent = 'Thinking';

    const content = document.createElement('div');
    content.className = 'thinking-content';
    content.textContent = thinkingText;

    details.appendChild(summary);
    details.appendChild(content);
    attachThinkingBlockCollapse(details);

    const contentDiv = messageDiv.querySelector('.message-content');
    messageDiv.insertBefore(details, contentDiv);
}

// =============================================================================
// FILE ATTACHMENTS (Phase 7)
// =============================================================================

function handleFileSelect(e) {
    const files = Array.from(e.target.files);
    if (files.length > 0) addPendingFiles(files);
    fileInput.value = '';
}

function handlePaste(e) {
    if (isWaiting || migrationInputLocked) return;
    const items = Array.from(e.clipboardData.items);
    const imageItems = items.filter(item => item.type.startsWith('image/'));
    if (imageItems.length === 0) return;

    e.preventDefault();
    const files = imageItems.map(item => {
        const raw = item.getAsFile();
        if (!raw) return null;
        const ext = item.type.split('/')[1] || 'png';
        const name = `pasted-image-${Date.now()}.${ext}`;
        return new File([raw], name, { type: item.type });
    }).filter(Boolean);
    if (files.length > 0) addPendingFiles(files);
}

function handleDragOver(e) {
    e.preventDefault();
    e.stopPropagation();
    if (migrationInputLocked) return;
    inputContainer.classList.add('drag-over');
}

function handleDragLeave(e) {
    e.preventDefault();
    e.stopPropagation();
    inputContainer.classList.remove('drag-over');
}

function handleDrop(e) {
    e.preventDefault();
    e.stopPropagation();
    inputContainer.classList.remove('drag-over');
    if (migrationInputLocked) return;
    const files = Array.from(e.dataTransfer.files);
    if (files.length > 0) addPendingFiles(files);
}

function addPendingFiles(files) {
    for (const file of files) {
        if (file.size > 25 * 1024 * 1024) {
            showError(`File "${file.name}" is too large (max 25MB)`);
            continue;
        }
        pendingFiles.push(file);
    }
    updatePendingAttachmentsUI();
}

function removePendingFile(index) {
    pendingFiles.splice(index, 1);
    updatePendingAttachmentsUI();
}

function updatePendingAttachmentsUI() {
    const existingImages = pendingAttachments.querySelectorAll('img');
    existingImages.forEach(img => {
        if (img.src.startsWith('blob:')) URL.revokeObjectURL(img.src);
    });
    pendingAttachments.innerHTML = '';

    if (pendingFiles.length === 0) {
        pendingAttachments.style.display = 'none';
        pendingAttachments.classList.remove('has-items');
        return;
    }

    pendingAttachments.style.display = 'flex';
    pendingAttachments.classList.add('has-items');

    pendingFiles.forEach((file, index) => {
        const item = document.createElement('div');
        item.className = 'pending-attachment-item';

        const preview = document.createElement('div');
        preview.className = 'attachment-preview';

        if (file.type.startsWith('image/')) {
            const img = document.createElement('img');
            img.src = URL.createObjectURL(file);
            preview.appendChild(img);
            // Tap image to expand preview above input
            preview.addEventListener('click', () => showAttachmentExpanded(img.src));
        } else {
            const icon = document.createElement('span');
            icon.className = 'file-icon';
            if (file.type === 'application/pdf') {
                icon.textContent = 'PDF';
            } else if (file.type === 'application/json') {
                icon.textContent = 'JSON';
            } else {
                icon.textContent = 'TXT';
            }
            preview.appendChild(icon);
        }

        const removeBtn = document.createElement('button');
        removeBtn.className = 'attachment-remove';
        removeBtn.textContent = '\u00d7';
        removeBtn.onclick = (e) => { e.stopPropagation(); removePendingFile(index); };

        item.appendChild(preview);
        item.appendChild(removeBtn);
        pendingAttachments.appendChild(item);
    });
}

function showAttachmentExpanded(src) {
    const existing = document.querySelector('.attachment-expanded-overlay');
    if (existing) { existing.remove(); return; }

    const appContainer = document.querySelector('.app-container');
    const headerH = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--header-h')) || 78;
    const bottomOffset = inputWrapper.offsetHeight + 12;
    const maxH = appContainer.offsetHeight - headerH - 10 - bottomOffset;

    const overlay = document.createElement('div');
    overlay.className = 'attachment-expanded-overlay';
    overlay.style.bottom = bottomOffset + 'px';
    overlay.style.maxHeight = maxH + 'px';

    const img = document.createElement('img');
    img.src = src;
    overlay.appendChild(img);
    overlay.addEventListener('click', () => overlay.remove());
    appContainer.appendChild(overlay);
}

async function uploadPendingFiles() {
    const uploadedUuids = [];

    for (const file of pendingFiles) {
        try {
            const formData = new FormData();
            formData.append('file', file);

            const response = await fetch(`${API_BASE}/api/upload`, {
                method: 'POST',
                body: formData
            });

            if (!response.ok) {
                const error = await response.json();
                showError(`Failed to upload ${file.name}: ${error.error}`);
                continue;
            }

            const result = await response.json();
            uploadedUuids.push(result.uuid);
            addStatusLine(`attached ${file.name}`, 'success');
        } catch (error) {
            console.error('Upload error:', error);
            showError(`Failed to upload ${file.name}: ${error.message}`);
        }
    }

    pendingFiles = [];
    updatePendingAttachmentsUI();
    return uploadedUuids;
}

// =============================================================================
// EMBEDDING MIGRATION
// =============================================================================
//
// One-click re-index. Two audiences, one mechanism: users moving to on-device
// embeddings, and users with unembedded (imported) messages. A DB backup is
// made server-side before any write; the job runs in a background thread and we
// poll GET /api/embeddings/migration-status for progress.

const MIGRATION_SNOOZE_KEY = 'mneme_migration_snooze_until';
const MIGRATION_SNOOZE_MS = 3 * 24 * 60 * 60 * 1000; // 3 days
let migrationPollTimer = null;
let migrationWired = false;
let migrationLastStatus = null;
let migrationWaveProgress = null;  // createWaveProgress instance, lazy
let mobileNotifyPendingAfterMigration = false;

async function fetchMigrationStatus() {
    try {
        const res = await fetch(`${API_BASE}/api/embeddings/migration-status`);
        if (!res.ok) return null;
        return await res.json();
    } catch (e) {
        return null;
    }
}

async function maybeShowMigrationPrompt() {
    // Only auto-nag for local-provider users with pending work, and respect snooze.
    // Returns true if the migration overlay was opened, so callers can defer
    // other startup overlays (e.g. the mobile notify prompt) until it closes.
    const status = await fetchMigrationStatus();
    if (!status) return false;
    setMigrationInputLocked(!!status.running);
    if (status.running) {
        openMigrationModal(status);
        return true;
    }

    const snoozeUntil = parseInt(localStorage.getItem(MIGRATION_SNOOZE_KEY) || '0', 10);
    if (Date.now() < snoozeUntil) return false;
    if (sessionStorage.getItem('mneme_migration_dismissed_session')) return false;

    if (status.current_provider === 'local' && status.pending_count > 0) {
        openMigrationModal(status);
        return true;
    }
    return false;
}

function wireMigrationModal() {
    if (migrationWired) return;
    migrationWired = true;

    const primary = document.getElementById('migrationPrimaryBtn');
    const secondary = document.getElementById('migrationSecondaryBtn');
    const manageBtn = document.getElementById('manageEmbeddingsBtn');

    if (primary) primary.addEventListener('click', onMigrationPrimary);
    if (secondary) secondary.addEventListener('click', onMigrationSecondary);
    if (migrationChatLock) {
        migrationChatLock.addEventListener('click', async () => {
            const status = await fetchMigrationStatus();
            openMigrationModal(status || migrationLastStatus || {});
        });
    }
    if (manageBtn) {
        manageBtn.addEventListener('click', async () => {
            const status = await fetchMigrationStatus();
            openMigrationModal(status || {});
        });
    }
}

function openMigrationModal(status) {
    const overlay = document.getElementById('migrationOverlay');
    if (!overlay) return;
    overlay.classList.add('visible');
    renderMigrationState(status || {});
    // Keep polling live if a job is running.
    if (status && status.running) startMigrationPolling();
}

function hideMigrationModal() {
    const overlay = document.getElementById('migrationOverlay');
    if (overlay) overlay.classList.remove('visible');
    if (migrationWaveProgress) migrationWaveProgress.stop();
    if (migrationLastStatus && migrationLastStatus.running) startMigrationPolling();
    else stopMigrationPolling();
    // If the mobile notify overlay was suppressed while migration was showing,
    // show it now — it still applies its own once-only/localStorage logic.
    if (mobileNotifyPendingAfterMigration) {
        mobileNotifyPendingAfterMigration = false;
        showMobileNotifyIfNeeded();
    }
    if (relocationPendingAfterMigration) {
        relocationPendingAfterMigration = false;
        maybeShowRelocationOffer();
    }
}

function renderMigrationState(status) {
    migrationLastStatus = status || {};
    setMigrationInputLocked(!!status.running);
    const title = document.getElementById('migrationTitle');
    const body = document.getElementById('migrationBody');
    const progress = document.getElementById('migrationProgress');
    const label = document.getElementById('migrationProgressLabel');
    if (!migrationWaveProgress) {
        migrationWaveProgress = createWaveProgress(document.getElementById('migrationProgressWave'));
    }
    const primary = document.getElementById('migrationPrimaryBtn');
    const secondary = document.getElementById('migrationSecondaryBtn');

    const phase = status.phase || 'idle';
    const pending = status.pending_count || 0;
    const target = status.target_count || 0;
    const done = status.done_count || 0;

    // RUNNING (backing up / embedding / verifying)
    if (status.running) {
        title.textContent = 'Re-indexing your memories';
        body.innerHTML = 'This runs on your computer in the background. You can close this panel — just keep Mneme running and your PC awake.';
        progress.hidden = false;
        let pct = 0;
        if (phase === 'backing_up') pct = 3;
        else if (target > 0) pct = Math.min(99, Math.round((done / target) * 100));
        else pct = 5;
        migrationWaveProgress.set(pct / 100);
        if (phase === 'backing_up') label.textContent = 'Creating a safety backup first...';
        else if (phase === 'verifying') label.textContent = 'Verifying...';
        else label.textContent = `${done} of ${target} messages re-indexed`;
        primary.classList.add('hidden');
        secondary.classList.remove('hidden');
        secondary.textContent = 'Hide';
        return;
    }

    // DONE
    if (phase === 'done') {
        progress.hidden = false;
        migrationWaveProgress.set(1);
        if ((status.remaining_count || pending) === 0) {
            title.textContent = 'All set';
            body.innerHTML = status.message || 'Your memories are re-indexed and searchable on your device.';
            label.textContent = 'Complete';
        } else {
            title.textContent = 'Partly done';
            body.innerHTML = (status.message || 'Some messages still need re-indexing.') +
                '<br><br>Your backup is safe and nothing was lost.';
            label.textContent = `${pending} still pending`;
        }
        primary.classList.remove('hidden');
        primary.disabled = false;
        primary.textContent = (pending > 0) ? 'Resume' : 'Done';
        secondary.classList.toggle('hidden', pending === 0);
        secondary.textContent = 'Close';
        return;
    }

    // ERROR
    if (phase === 'error') {
        progress.hidden = true;
        migrationWaveProgress.stop();
        title.textContent = 'Couldn’t finish';
        body.innerHTML = (status.message || 'Something went wrong.') +
            '<br><br>Your backup exists and your messages are unchanged.';
        primary.classList.remove('hidden');
        primary.disabled = false;
        primary.textContent = 'Try again';
        secondary.classList.remove('hidden');
        secondary.textContent = 'Close';
        return;
    }

    // IDLE — either an offer (pending>0) or nothing to do
    progress.hidden = true;
    migrationWaveProgress.stop();
    if (pending > 0) {
        title.textContent = 'Migrate to new embeddings';
        const mins = status.estimated_minutes || 0;
        const minsText = mins < 1 ? 'under a minute' : `about ${mins} minute${mins >= 2 ? 's' : ''}`;
        body.innerHTML = `Recommended, and required for future updates. This re-indexes your memories so search runs with on-device embeddings — <span class="migration-emphasis">no OpenAI key needed</span>. Chat still uses your Anthropic key as before.` +
            `<ul>` +
            `<li>${pending} message${pending === 1 ? '' : 's'} to process, ${minsText}.</li>` +
            `<li>A backup is created automatically first.</li>` +
            `<li>After it starts, keep Mneme running and your PC awake.</li>` +
            `<li>Older messages stay saved either way.</li>` +
            `</ul>`;
        primary.classList.remove('hidden');
        primary.disabled = false;
        primary.textContent = 'Migrate now';
        secondary.classList.remove('hidden');
        secondary.textContent = 'Not now';
    } else {
        title.textContent = 'Embeddings are up to date';
        body.innerHTML = 'All your messages are indexed for the current provider. Nothing to do here.';
        primary.classList.add('hidden');
        secondary.classList.remove('hidden');
        secondary.textContent = 'Close';
    }
}

async function onMigrationPrimary() {
    const primary = document.getElementById('migrationPrimaryBtn');
    // "Done" on a fully-complete run just closes.
    if (primary.textContent === 'Done') { hideMigrationModal(); return; }

    primary.disabled = true;
    primary.textContent = 'Starting...';
    try {
        const res = await fetch(`${API_BASE}/api/embeddings/migrate`, { method: 'POST' });
        const status = await res.json();
        renderMigrationState(status);
        startMigrationPolling();
    } catch (e) {
        renderMigrationState({ phase: 'error', message: 'Could not start migration.' });
    }
}

function onMigrationSecondary() {
    const status = migrationLastStatus || {};
    // If a job is running, "Hide" just closes the modal — the job continues.
    if (!status.running && (status.phase === 'idle' || !status.phase) && (status.pending_count || 0) > 0) {
        // "Not now" — snooze the auto-prompt.
        localStorage.setItem(MIGRATION_SNOOZE_KEY, String(Date.now() + MIGRATION_SNOOZE_MS));
        sessionStorage.setItem('mneme_migration_dismissed_session', '1');
    }
    hideMigrationModal();
}

function startMigrationPolling() {
    stopMigrationPolling();
    migrationPollTimer = setInterval(async () => {
        const status = await fetchMigrationStatus();
        if (!status) return;
        migrationLastStatus = status;
        setMigrationInputLocked(!!status.running);
        // Only repaint if the modal is still open.
        const overlay = document.getElementById('migrationOverlay');
        if (overlay && overlay.classList.contains('visible')) {
            renderMigrationState(status);
        }
        if (!status.running) {
            stopMigrationPolling();
            updateEmbeddingsSettingStatus(status);
        }
    }, 1200);
}

function stopMigrationPolling() {
    if (migrationPollTimer) { clearInterval(migrationPollTimer); migrationPollTimer = null; }
}

function updateEmbeddingsSettingStatus(status) {
    const el = document.getElementById('manageEmbeddingsStatus');
    if (!el || !status) return;
    if (status.running) el.textContent = 'Migration in progress...';
    else if ((status.pending_count || 0) > 0) el.textContent = `${status.pending_count} messages need re-indexing.`;
    else el.textContent = 'All messages are indexed.';
}

// =============================================================================
// DATA RELOCATION OFFER
// =============================================================================
//
// One-time offer to move user data out of the app install folder into
// %LOCALAPPDATA%\Mneme, where a future update/reinstall can't endanger it.
// Mirrors the embedding migration modal's structure (same .migration-* CSS,
// same createWaveProgress bar) rather than inventing a new modal system.
// GET /api/relocation/status tells us whether the offer applies; POST
// /api/relocate kicks off a background move that we poll for progress.

let relocationWired = false;
let relocationWaveProgress = null;  // createWaveProgress instance, lazy
let relocationPollTimer = null;
let relocationPendingAfterMigration = false;

async function maybeShowRelocationOffer() {
    try {
        const res = await fetch(`${API_BASE}/api/relocation/status`);
        if (!res.ok) return;
        const status = await res.json();
        if (status && status.available) {
            openRelocationModal(status);
        }
    } catch (e) {
        // Nice-to-have offer — fail silently rather than blocking startup.
    }
}

function wireRelocationModal() {
    if (relocationWired) return;
    relocationWired = true;

    const primary = document.getElementById('relocationPrimaryBtn');
    const later = document.getElementById('relocationLaterBtn');
    const decline = document.getElementById('relocationDeclineBtn');
    const gotIt = document.getElementById('relocationGotItBtn');
    const closeErr = document.getElementById('relocationCloseBtn');

    if (primary) primary.addEventListener('click', onRelocationStart);
    if (later) later.addEventListener('click', hideRelocationModal);
    if (decline) decline.addEventListener('click', onRelocationDecline);
    if (gotIt) gotIt.addEventListener('click', hideRelocationModal);
    if (closeErr) closeErr.addEventListener('click', hideRelocationModal);
}

function openRelocationModal(status) {
    const overlay = document.getElementById('relocationOverlay');
    if (!overlay) return;
    renderRelocationOffer(status);
    overlay.classList.add('visible');
}

function hideRelocationModal() {
    const overlay = document.getElementById('relocationOverlay');
    if (overlay) overlay.classList.remove('visible');
    stopRelocationPolling();
    if (relocationWaveProgress) relocationWaveProgress.stop();
}

function renderRelocationOffer(status) {
    document.getElementById('relocationTitle').textContent = 'Move your memories to a safer home';
    document.getElementById('relocationBody').innerHTML =
        'Your data currently lives inside the app folder, where an update or reinstall could put it at risk. ' +
        'Mneme can move it to:' +
        `<div class="relocation-path">${escapeHtmlText(status.dst || '')}</div>` +
        'The original stays untouched as a backup.';
    document.getElementById('relocationProgress').hidden = true;
    document.getElementById('relocationActions').hidden = false;
    document.getElementById('relocationDeclineBtn').hidden = false;
    document.getElementById('relocationDoneActions').hidden = true;
    document.getElementById('relocationErrorActions').hidden = true;
    const primary = document.getElementById('relocationPrimaryBtn');
    primary.disabled = false;
    primary.textContent = 'Move my data';
    const later = document.getElementById('relocationLaterBtn');
    later.disabled = false;
}

function escapeHtmlText(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
}

async function onRelocationStart() {
    const primary = document.getElementById('relocationPrimaryBtn');
    const later = document.getElementById('relocationLaterBtn');
    primary.disabled = true;
    primary.textContent = 'Starting...';
    later.disabled = true;
    try {
        const res = await fetch(`${API_BASE}/api/relocate`, { method: 'POST' });
        if (res.status === 409) {
            // Already running (e.g. another tab kicked it off) — just watch it.
            startRelocationProgressView();
            startRelocationPolling();
            return;
        }
        if (!res.ok) {
            const data = await res.json().catch(() => ({}));
            showRelocationError(data.error || 'Could not start the move.');
            return;
        }
        startRelocationProgressView();
        startRelocationPolling();
    } catch (e) {
        showRelocationError('Could not reach Mneme to start the move.');
    }
}

function startRelocationProgressView() {
    document.getElementById('relocationBody').innerHTML =
        'Moving your data. This can take a little while for a large database — keep Mneme running.';
    document.getElementById('relocationProgress').hidden = false;
    document.getElementById('relocationActions').hidden = true;
    document.getElementById('relocationDeclineBtn').hidden = true;
    if (!relocationWaveProgress) {
        relocationWaveProgress = createWaveProgress(document.getElementById('relocationProgressWave'));
    }
    relocationWaveProgress.set(0);
    document.getElementById('relocationProgressLabel').textContent = 'Starting...';
}

function startRelocationPolling() {
    stopRelocationPolling();
    relocationPollTimer = setInterval(pollRelocationStatus, 500);
}

function stopRelocationPolling() {
    if (relocationPollTimer) { clearInterval(relocationPollTimer); relocationPollTimer = null; }
}

async function pollRelocationStatus() {
    let status;
    try {
        const res = await fetch(`${API_BASE}/api/relocation/status`);
        if (!res.ok) return;
        status = await res.json();
    } catch (e) {
        return; // transient network hiccup — keep polling
    }

    const total = status.total_bytes || 0;
    const doneBytes = status.done_bytes || 0;
    const pct = total > 0 ? Math.min(1, doneBytes / total) : 0;
    if (relocationWaveProgress) relocationWaveProgress.set(pct);
    const label = document.getElementById('relocationProgressLabel');
    if (label) {
        label.textContent = total > 0
            ? `${formatRelocationBytes(doneBytes)} of ${formatRelocationBytes(total)}`
            : 'Moving...';
    }

    if (status.error) {
        stopRelocationPolling();
        showRelocationError(status.error);
    } else if (status.done) {
        stopRelocationPolling();
        if (relocationWaveProgress) relocationWaveProgress.set(1);
        showRelocationSuccess();
    }
}

function formatRelocationBytes(n) {
    if (n >= 1024 ** 3) return (n / 1024 ** 3).toFixed(1) + ' GB';
    if (n >= 1024 ** 2) return (n / 1024 ** 2).toFixed(0) + ' MB';
    if (n >= 1024) return (n / 1024).toFixed(0) + ' KB';
    return n + ' B';
}

function showRelocationSuccess() {
    document.getElementById('relocationTitle').textContent = 'Done';
    document.getElementById('relocationBody').innerHTML =
        'Your memories now live outside the app folder. Restart Mneme (tray icon → Quit, then relaunch) to finish.';
    document.getElementById('relocationProgress').hidden = true;
    document.getElementById('relocationActions').hidden = true;
    document.getElementById('relocationDeclineBtn').hidden = true;
    document.getElementById('relocationErrorActions').hidden = true;
    document.getElementById('relocationDoneActions').hidden = false;
}

function showRelocationError(message) {
    document.getElementById('relocationTitle').textContent = "Couldn't move your data";
    document.getElementById('relocationBody').innerHTML =
        escapeHtmlText(message || 'Something went wrong.') + '<br><br>Nothing was changed — your data is exactly where it was.';
    document.getElementById('relocationProgress').hidden = true;
    document.getElementById('relocationActions').hidden = true;
    document.getElementById('relocationDeclineBtn').hidden = true;
    document.getElementById('relocationDoneActions').hidden = true;
    document.getElementById('relocationErrorActions').hidden = false;
}

function onRelocationDecline() {
    fetch(`${API_BASE}/api/relocation/decline`, { method: 'POST' }).catch(() => {});
    hideRelocationModal();
}

// =============================================================================
// MOBILE ACCESS NOTIFICATION
// =============================================================================

function showMobileNotifyIfNeeded() {
    // Only show on desktop, and only once
    if (window.innerWidth < 768) return;
    if (localStorage.getItem('mneme_mobile_notify_shown')) return;

    const overlay = document.getElementById('mobileNotifyOverlay');
    const urlEl = document.getElementById('mobileNotifyUrl');
    const dismissBtn = document.getElementById('mobileNotifyDismiss');
    if (!overlay) return;

    // Build the URL hint — use current hostname (might be Tailscale IP already)
    const port = location.port || '8080';
    const host = location.hostname;
    if (host === 'localhost' || host === '127.0.0.1') {
        urlEl.textContent = `http://[your-tailscale-ip]:${port}`;
    } else {
        urlEl.textContent = `http://${host}:${port}`;
    }

    overlay.classList.add('visible');

    dismissBtn.addEventListener('click', () => {
        overlay.classList.remove('visible');
        localStorage.setItem('mneme_mobile_notify_shown', '1');
    });
}

// =============================================================================
// INIT
// =============================================================================

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}
