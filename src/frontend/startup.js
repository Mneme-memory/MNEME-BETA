const canvas = document.getElementById('startupCanvas');
const phaseEl = document.getElementById('startupPhase');
const detailEl = document.getElementById('startupDetail');
const shellEl = document.querySelector('.startup-shell');

const LOAD_W = 150, LOAD_H = 160;
const LOAD_CX = 75, LOAD_CY = 80;
const LOAD_PATH_R = 59, LOAD_CLIP_R = 74;
const LOAD_BASE_WIDTH = 14;
const LOAD_NOTCH_MIN = 0.55;
const LOAD_TAU = Math.PI * 2;
const LOAD_CFG = {
    spacing: 22, scrollSpeed: 50, wobbleAmp: 0.5,
    widthAmp: 0.75, subs: 20, connSubs: 4, cornerDip: 0.22
};

let loadStartTime = null;

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

function drawLoadingFrame(timestamp) {
    if (!loadStartTime) loadStartTime = timestamp;
    const time = timestamp - loadStartTime;
    const { spacing, scrollSpeed, wobbleAmp, widthAmp, subs, connSubs, cornerDip } = LOAD_CFG;

    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    if (canvas.width !== LOAD_W * dpr) {
        canvas.width = LOAD_W * dpr;
        canvas.height = LOAD_H * dpr;
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

    const fadeZone = spacing * 0.7;
    for (const p of points) {
        const dist = Math.min(p.x - (LOAD_CX - LOAD_PATH_R), (LOAD_CX + LOAD_PATH_R) - p.x);
        p.w *= 0.8 + 0.2 * Math.max(Math.min(dist / fadeZone, 1), 0);
    }

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
    requestAnimationFrame(drawLoadingFrame);
}

// ── Wave progress bar ────────────────────────────────────────
// Self-contained copy of createWaveProgress from app.js (the startup
// page must work before the app loads) — keep the two in sync.
function createWaveProgress(canvas) {
    const ctx = canvas.getContext('2d');
    const coral = '#d97757';
    const chalk = '#76746e';
    let shown = 0;
    let target = 0;
    let phase = 0;
    let amp = 1;
    let animId = null;
    let lastTs = null;

    function draw(ts) {
        const dt = lastTs === null ? 1 / 60 : Math.min((ts - lastTs) / 1000, 0.1);
        lastTs = ts;
        const dpr = window.devicePixelRatio || 1;
        const cssW = canvas.offsetWidth;
        const cssH = canvas.offsetHeight;
        if (cssW === 0) {
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
        const trackEnd = cssW - dotR;
        const waveEnd = Math.max(3, (trackEnd - gap) * shown);

        ctx.strokeStyle = coral;
        ctx.lineWidth = 2;
        ctx.lineCap = 'round';
        ctx.lineJoin = 'round';
        const period = 24;
        const waveAmp = Math.min(cssH * 0.32, 5) * amp;
        ctx.beginPath();
        for (let px = 0; px <= waveEnd; px++) {
            const env = Math.max(0, Math.min(1, px / 14, (waveEnd - px) / 14));
            const raw = Math.sin((px / period) * 2 * Math.PI - phase);
            const shaped = Math.sign(raw) * Math.pow(Math.abs(raw), 0.45);
            const blend = env * amp;
            const wave = raw * (1 - blend) + shaped * blend;
            const y = midY - wave * waveAmp * env;
            if (px === 0) ctx.moveTo(px, y);
            else ctx.lineTo(px, y);
        }
        ctx.stroke();

        if (waveEnd + gap < trackEnd - gap) {
            ctx.strokeStyle = chalk;
            ctx.lineWidth = 1.5;
            ctx.beginPath();
            ctx.moveTo(waveEnd + gap, midY);
            ctx.lineTo(trackEnd - gap, midY);
            ctx.stroke();
        }

        ctx.fillStyle = coral;
        ctx.beginPath();
        ctx.arc(trackEnd - dotR, midY, dotR, 0, Math.PI * 2);
        ctx.fill();

        phase += 4.5 * dt;

        if (target >= 1 && shown > 0.995 && amp < 0.01) {
            animId = null;
            return;
        }
        animId = requestAnimationFrame(draw);
    }

    return {
        set(p) {
            target = Math.max(0, Math.min(1, p));
            if (target < 1) amp = Math.max(amp, 0.001);
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

const bootProgress = createWaveProgress(document.getElementById('startupProgress'));

function setCopy(status) {
    phaseEl.textContent = status.phase || 'Starting Mneme';
    detailEl.textContent = status.detail || 'Preparing the local memory system...';
    shellEl.classList.toggle('failed', status.state === 'failed');
    if (status.state === 'failed') {
        bootProgress.stop();
    } else if (typeof status.step === 'number' && status.steps) {
        bootProgress.set(status.step / status.steps);
    }
}

async function pollStartupStatus() {
    try {
        const response = await fetch('/api/startup/status', { cache: 'no-store' });
        const status = await response.json();
        setCopy(status);

        if (status.state === 'ready') {
            // Let the wave finish its exhale before opening the app
            bootProgress.set(1);
            setTimeout(() => window.location.replace('/'), 800);
            return;
        }
    } catch (e) {
        setCopy({
            phase: 'Waiting for Mneme',
            detail: 'The local server is still opening its door...',
        });
    }

    setTimeout(pollStartupStatus, 650);
}

// Preview mode: open startup.html?preview from any static server to cycle
// through the real states without running Mneme (design iteration aid).
function runPreviewLoop() {
    const states = [
        { phase: 'Loading configuration', detail: 'Reading Mneme settings and active profile...', step: 1, steps: 7 },
        { phase: 'Opening memory database', detail: 'Connecting to the active profile and checking stored messages...', step: 2, steps: 7 },
        { phase: 'Preparing embeddings', detail: 'Loading the local retrieval pipeline...', step: 3, steps: 7 },
        { phase: 'Rebalancing memory tiers', detail: 'Making sure recent, searchable, and archived memories are in the right places...', step: 6, steps: 7 },
        { phase: 'Mneme is ready', detail: 'Opening...', step: 7, steps: 7 },
        { phase: 'Mneme could not start', detail: 'Check the terminal window for details.', state: 'failed' },
        { phase: 'Starting Mneme', detail: 'Preparing the local memory system...', step: 0, steps: 7 },
    ];
    let i = 0;
    setCopy(states[0]);
    setInterval(() => {
        i = (i + 1) % states.length;
        setCopy(states[i]);
    }, 2500);
}

requestAnimationFrame(drawLoadingFrame);
if (new URLSearchParams(window.location.search).has('preview')) {
    runPreviewLoop();
} else {
    pollStartupStatus();
}
