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
const profileCard = document.getElementById('profileCard');
const profileNewInstance = document.getElementById('profileNewInstance');
const profileGreeting = document.getElementById('profileGreeting');
const startingHeadline = document.getElementById('startingHeadline');
const loadingOverlay = document.getElementById('loadingOverlay');
const loadingCanvas = document.getElementById('loadingCanvas');
const backBtn = document.getElementById('backBtn');
const forwardBtn = document.getElementById('forwardBtn');
const headerCenter = document.getElementById('headerCenter');

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
let chatActive = false;
let loadingAnimId = null;          // rAF id for loading animation
let creationFlowModel = null;      // model selected during profile creation flow
let hasProfiles = false;           // whether any profiles exist (for navigation)
let lastPinnedActions = null;
let streamingAutoScroll = true;
let pendingUserTimestamp = null;   // { div, time } — deferred until AI responds

// Spinner frames
const SPINNER_FRAMES = ['\u2819', '\u2839', '\u2838', '\u283C', '\u2834', '\u2826', '\u2827', '\u2807', '\u280F'];
let spinnerIndex = 0;

// =============================================================================
// MODEL SELECTOR STATE
// =============================================================================

// Alt model definitions for "Others" swap
const MODEL_SELECTOR_MAIN_HTML = null; // set on DOMContentLoaded
const MODEL_SELECTOR_ALT = [
    { id: 'claude-opus-4-5', icon: 'assets/model-opus.svg', name: 'Opus', version: '4.5' },
    { id: 'claude-sonnet-4-5', icon: 'assets/model-sonnet.svg', name: 'Sonnet', version: '4.5' },
];
let modelSelectorShowingOthers = false;

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
        await fetch('/api/set-model', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model_id: modelId })
        });
    } catch (e) {
        // Non-fatal — badge still updates optimistically
    }
    updateModelBadge(modelId);
}

function updateModelBadge(modelId) {
    // New format: claude-{family}-{major}-{minor}[-{date}]  e.g. claude-sonnet-4-6, claude-haiku-4-5-20251001
    // Old format: claude-{major}-{family}-{date}            e.g. claude-3-opus-20240229
    let name = '', version = '';

    const newFmt = modelId.match(/^claude-([a-z]+)-(\d+)-(\d+)/i);
    const oldFmt = !newFmt && modelId.match(/^claude-(\d+)-([a-z]+)/i);

    if (newFmt) {
        name = newFmt[1];
        version = `${newFmt[2]}.${newFmt[3]}`;
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
    modelBadgeIcon.src = ['opus', 'sonnet', 'haiku'].includes(name.toLowerCase())
        ? `assets/model-${name.toLowerCase()}.svg`
        : 'assets/model-sonnet.svg';
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

function drawLoadingFrame(timestamp) {
    if (!loadStartTime) loadStartTime = timestamp;
    const time = timestamp - loadStartTime;
    const { spacing, scrollSpeed, wobbleAmp, widthAmp, subs, connSubs, cornerDip } = LOAD_CFG;

    const ctx = loadingCanvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    if (loadingCanvas.width !== LOAD_W * dpr) {
        loadingCanvas.width = LOAD_W * dpr;
        loadingCanvas.height = LOAD_H * dpr;
        ctx.scale(dpr, dpr);
    }

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

        // Determine model icon
        let modelFamily = 'sonnet';
        const match = (p.model || '').match(/claude-([a-z]+)/i);
        if (match && ['opus', 'sonnet', 'haiku'].includes(match[1].toLowerCase())) {
            modelFamily = match[1].toLowerCase();
        }

        // Parse model display
        let modelName = '', modelVersion = '';
        const newFmt = (p.model || '').match(/^claude-([a-z]+)-(\d+)-(\d+)/i);
        if (newFmt) {
            modelName = newFmt[1].charAt(0).toUpperCase() + newFmt[1].slice(1);
            modelVersion = `${newFmt[2]}.${newFmt[3]}`;
        }

        const icon = document.createElement('img');
        icon.src = `assets/model-${modelFamily}.svg`;
        icon.alt = '';
        icon.width = 18;
        icon.height = 18;
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
    chatActive = false;
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
    showMobileNotifyIfNeeded();

    // Event listeners
    sendBtn.addEventListener('click', sendMessage);
    errorClose.addEventListener('click', hideError);
    settingsBtnHeader.addEventListener('click', showSettings);
    settingsBackBtn.addEventListener('click', hideSettings);

    // Wire slider oninput — show value bubble while adjusting
    const allSliders = [
        'settingRetrieval', 'settingMaxRetrieval',
        'settingMaxEntities', 'settingMaxConcepts', 'settingMaxFiles',
        'settingTemperature', 'settingThinkingBudget', 'settingRecentTokens',
        'settingArchiveAge'
    ];
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

    // Model default dropdown — confirmation popup
    let pendingModelValue = null;
    const modelDropdown = document.getElementById('settingModelDefault');
    const confirmOverlay = document.getElementById('settingsConfirmOverlay');
    const confirmText = document.getElementById('settingsConfirmText');
    const confirmCancel = document.getElementById('settingsConfirmCancel');
    const confirmOk = document.getElementById('settingsConfirmOk');

    modelDropdown.addEventListener('change', function() {
        const newModel = this.value;
        const label = this.options[this.selectedIndex].text;
        pendingModelValue = { value: newModel, previous: this._previousValue || this.value };
        confirmText.textContent = `Change default model to ${label}? This affects all new conversations.`;
        confirmOverlay.classList.add('active');
    });
    modelDropdown.addEventListener('focus', function() { this._previousValue = this.value; });
    confirmCancel.addEventListener('click', () => {
        if (pendingModelValue) modelDropdown.value = pendingModelValue.previous;
        pendingModelValue = null;
        confirmOverlay.classList.remove('active');
    });
    confirmOk.addEventListener('click', () => {
        pendingModelValue = null;
        confirmOverlay.classList.remove('active');
    });
    confirmOverlay.addEventListener('click', (e) => {
        if (e.target === confirmOverlay) confirmCancel.click();
    });

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
            thinking_budget: parseInt(document.getElementById('settingThinkingBudget').value),
            // Context
            recent_messages_tokens: parseInt(document.getElementById('settingRecentTokens').value),
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
        };
        try {
            const res = await fetch('/api/settings', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload)
            });
            const data = await res.json();
            status.textContent = data.success ? 'Saved.' : (data.error || 'Error saving.');
            setTimeout(() => { status.textContent = ''; }, 3000);
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

    // File attachment — + button opens bottom drawer
    attachBtn.addEventListener('click', openBottomDrawer);
    drawerAttachOption.addEventListener('click', () => { closeBottomDrawer(); fileInput.click(); });
    drawerCommandOption.addEventListener('click', () => { closeBottomDrawer(); openCommandsDrawer(); });
    bottomDrawerOverlay.addEventListener('click', () => { closeBottomDrawer(); closeCommandsDrawer(); });
    commandsDrawer.addEventListener('click', (e) => {
        const pill = e.target.closest('.cmd-pill');
        if (pill) { const cmd = pill.dataset.cmd; if (cmd) insertCommand(cmd); closeCommandsDrawer(); }
    });
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
    });

    // Model badge click -> open main selector
    modelBadge.addEventListener('click', (e) => {
        e.stopPropagation();
        openModelSelector();
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
        selectModel(modelId);

        // If on starting screen, begin profile creation flow
        if (!startingScreen.classList.contains('hidden')) {
            startProfileCreationFlow(modelId);
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
    chatActive = false;
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
    backBtn.style.display = '';
    settingsBtnHeader.style.display = '';
    forwardBtn.style.display = 'none';
}

function startProfileCreationFlow(modelId) {
    creationFlowModel = modelId;
    closeModelSelectors();

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
    notificationBar.classList.remove('idle');
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
    // Switch to idle (dimmed) — bar stays visible with last status
    notificationBar.classList.remove('active');
    notificationBar.classList.add('idle');
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
            console.log('Streaming mode:', streamingEnabled ? 'enabled' : 'disabled');
            console.log('TTS mode:', ttsEnabled ? 'enabled' : 'disabled');
            console.log('Thinking mode:', thinkingEnabled ? 'enabled' : 'disabled', '| Show:', showThinking);
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

async function sendMessage() {
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

    // Transition to chat view on first message
    if (!chatActive) {
        transitionToChatView();
    }

    streamingAutoScroll = true;
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
            addStatusLine(`uploading ${pendingFiles.length} file(s)...`, 'info');
            uploadedUuids = await uploadPendingFiles();
        }

        // Show message bubble for text or file-only sends — no file-note injection
        if (message || uploadedUuids.length > 0) {
            sentMessageEl = addMessage('user', message, true, null, null, attachmentMeta);
        }

        messageInput.value = '';
        messageInput.style.height = 'auto';
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
            await handleStreamAbort(null, sentMessageEl);
            return;
        }

        console.error('Error sending message:', error);

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

                    addStatusLine('done', 'success');

                    console.log('Stream complete:', {
                        is_command: event.data.is_command,
                        context_info: event.data.context_info
                    });
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
// STREAM ABORT + CONTINUE FLOW
// =============================================================================

async function handleStreamAbort(originalMessageId, userBubbleEl) {
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
    pill.innerHTML = '<span>Response interrupted. Want me to continue?</span>';

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
                        addStatusLine('done', 'success');
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

    addStatusLine('done', 'success');

    console.log('Response received:', {
        is_command: data.is_command,
        context_info: data.context_info
    });
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
    copyBtn.addEventListener('click', () => {
        const rawContent = contentDiv ? contentDiv.getAttribute('data-raw-content') || contentDiv.textContent : '';
        navigator.clipboard.writeText(rawContent).then(() => {
            copyBtn.title = 'Copied!';
            copyBtn.classList.add('copy-active');
            setTimeout(() => {
                copyBtn.title = 'Copy';
                copyBtn.classList.remove('copy-active');
            }, 1200);
        }).catch(err => {
            console.warn('Copy failed:', err);
        });
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

async function loadHistory() {
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
        console.log('History loaded:', data.messages ? data.messages.length : 0, 'messages');

        if (data.messages && data.messages.length > 0) {
            messagesContainer.innerHTML = '';

            const displayMessages = data.messages.filter(msg => {
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

            displayMessages.reverse();

            displayMessages.forEach(msg => {
                addMessage(msg.sender, msg.content, false, msg.timestamp, msg.metadata);
            });

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
            `<details class="cmd-run-block"><summary class="cmd-highlight">ran python</summary>` +
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

function addMessage(sender, content, scroll = true, timestamp = null, metadata = null, attachments = []) {
    // Transition to chat view if not already
    if (!chatActive) {
        transitionToChatView();
    }

    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${sender}`;

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

    messagesContainer.appendChild(messageDiv);

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

        const triggerCopy = () => {
            const raw = contentDiv.getAttribute('data-raw-content') || contentDiv.textContent;
            navigator.clipboard.writeText(raw).then(() => {
                if (flashTimer !== null) clearTimeout(flashTimer);
                messageDiv.classList.add('copy-flash');
                flashTimer = setTimeout(() => {
                    messageDiv.classList.remove('copy-flash');
                    flashTimer = null;
                }, 800);
            }).catch((err) => {
                console.warn('Copy failed:', err);
            });
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
    messageInput.disabled = waiting;
    sendBtn.disabled = waiting;

    if (waiting) {
        clearStatusLog();
        showNotificationBar();
        // Do NOT auto-expand — status updates appear in the collapsed 1-2 row bar
        startSpinner();
        addStatusLine('processing message...', 'info');
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
        // After 4s: switch to idle (dimmed). Do NOT collapse — bar stays visible with "done"
        setTimeout(() => {
            if (!isWaiting) {
                hideNotificationBar();
            }
        }, 4000);
        messageInput.focus();
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
    const current = messageInput.value;
    const needsNewline = current.length > 0 && !current.endsWith('\n');
    messageInput.value = (needsNewline ? current + '\n' : current) + cmd;
    messageInput.focus();
    messageInput.setSelectionRange(messageInput.value.length, messageInput.value.length);
    messageInput.dispatchEvent(new Event('input'));
}

function openBottomDrawer() {
    bottomDrawer.classList.add('active');
    bottomDrawerOverlay.classList.add('active');
}

function closeBottomDrawer() {
    bottomDrawer.classList.remove('active');
    bottomDrawerOverlay.classList.remove('active');
}

function openCommandsDrawer() {
    commandsDrawer.classList.add('active');
    bottomDrawerOverlay.classList.add('active');
}

function closeCommandsDrawer() {
    commandsDrawer.classList.remove('active');
    bottomDrawerOverlay.classList.remove('active');
}

async function showSettings() {
    settingsPage.classList.add('active');
    await loadSettingsValues();
    loadStats();
}

function hideSettings() {
    settingsPage.classList.remove('active');
}

function updateSliderBubble(sliderId, bubbleId) {
    const s = document.getElementById(sliderId), b = document.getElementById(bubbleId);
    if (!s || !b) return;
    const pct = (parseFloat(s.value) - parseFloat(s.min)) / (parseFloat(s.max) - parseFloat(s.min));
    b.style.left = `calc(${pct * 100}% + ${(0.5 - pct) * 16}px)`;
    b.textContent = s.value;
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
        document.getElementById('settingThinkingBudget').value = data.thinking_budget ?? 10000;
        document.getElementById('settingTemperatureSection').style.display = thinkingEnabled ? 'none' : '';
        document.getElementById('settingThinkingBudgetSection').style.display = thinkingEnabled ? '' : 'none';

        // Context
        document.getElementById('settingRecentTokens').value = data.recent_messages_tokens ?? 50000;
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

        // Update all slider bubbles
        ['settingRetrieval', 'settingMaxRetrieval',
         'settingMaxEntities', 'settingMaxConcepts', 'settingMaxFiles',
         'settingTemperature', 'settingThinkingBudget', 'settingRecentTokens',
         'settingArchiveAge'].forEach(id => updateSliderBubble(id, id + 'Value'));

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
    if (isWaiting) return;
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
            addStatusLine(`uploaded: ${file.name}`, 'success');
            console.log('Uploaded file:', result);

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
