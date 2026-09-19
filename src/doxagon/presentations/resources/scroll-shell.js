/**
 * The scroll shell — the article-shaped input adapter over the one runtime.
 *
 * It is concatenated after the runtime inside one pinned module, exactly as the
 * deck shell is. The realm stays a fixed-viewport, internally scrolling sandbox
 * pinned beside the prose; the HOST document is the long scrolling surface. A
 * reading line crosses `[data-cue]` sections to enter cues and `[data-track]`
 * sections to sample progress. Nothing here stretches the realm to document
 * height: the sandbox keeps its own innerHeight, scrollY, and sticky semantics.
 */

const payload = JSON.parse(document.getElementById('doxagon-deck-payload').textContent);
const article = document.getElementById('doxagon-article');
const stage = document.getElementById('doxagon-stage');
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const order = payload.checkpoint_order;
const cueSections = Array.from(document.querySelectorAll('[data-cue]'))
    .filter((node) => order.includes(node.dataset.cue));
const trackSections = Array.from(document.querySelectorAll('[data-track]'));

let currentCue = null;
let frame = null;
let settling = Promise.resolve();

const readingLine = () => window.innerHeight * (Number(article.dataset.readingLine) || 0.4);

/* The registered edge table decides whether a move is a neighbour (so its
 * authored transition plays) or a jump (so the destination reconstructs). */
function neighbour(from, to) {
    if (payload.edges.some((edge) => edge.from === from && edge.to === to)) return { type: 'NEXT' };
    if (payload.edges.some((edge) => edge.to === from && edge.from === to)) return { type: 'PREVIOUS' };
    return null;
}

const runtime = createDeckRuntime({
    deck: payload,
    mount: stage,
    reducedMotion,
    onState(state) {
        if (state.checkpointId === null) return;
        currentCue = state.checkpointId;
        stage.dataset.checkpoint = state.checkpointId;
        const hash = `#cue-${state.checkpointId}`;
        if (window.location.hash !== hash) window.history.replaceState(null, '', hash);
    },
});

function cueAtReadingLine() {
    const line = readingLine();
    let found = null;
    for (const section of cueSections) {
        if (section.getBoundingClientRect().top <= line) found = section.dataset.cue;
        else break;
    }
    return found ?? order[0];
}

function trackAtReadingLine() {
    const line = readingLine();
    for (const section of trackSections) {
        const rect = section.getBoundingClientRect();
        if (rect.top <= line && rect.bottom >= line && rect.height > 0) {
            return { track: section.dataset.track, progress: (line - rect.top) / rect.height };
        }
    }
    return null;
}

/* One evaluation per animation frame, latest geometry wins. Cue changes are
 * serialised through the runtime; samples are latest-value by construction. */
function evaluate() {
    frame = null;
    const target = cueAtReadingLine();
    if (target !== currentCue) {
        const from = currentCue;
        settling = settling.then(() => {
            if (runtime.state().checkpointId === target) return;
            const move = from === null ? null : neighbour(from, target);
            return (move ? runtime.dispatch(move) : runtime.seek(target)).catch(() => {});
        });
    }
    const sample = trackAtReadingLine();
    if (sample !== null) runtime.sample(sample.track, sample.progress).catch(() => {});
}

function schedule() {
    if (frame === null) frame = window.requestAnimationFrame(evaluate);
}


function scrollToCue(index) {
    const section = cueSections[Math.max(0, Math.min(cueSections.length - 1, index))];
    if (!section) return;
    const top = window.scrollY + section.getBoundingClientRect().top - readingLine() + 8;
    window.scrollTo({ top, behavior: reducedMotion ? 'auto' : 'smooth' });
}

window.addEventListener('keydown', (event) => {
    const node = event.target;
    if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey) return;
    if (node && (node.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(node.tagName))) return;
    const index = cueSections.findIndex((section) => section.dataset.cue === currentCue);
    if (['ArrowDown', 'PageDown', ' '].includes(event.key)) { event.preventDefault(); scrollToCue(index + 1); }
    else if (['ArrowUp', 'PageUp'].includes(event.key)) { event.preventDefault(); scrollToCue(index - 1); }
});

window.doxagonScroll = {
    runtime,
    currentCue: () => currentCue,
    readingLine,
    cues: cueSections.map((section) => section.dataset.cue),
    settled: () => settling,
};
window.doxagonDeck = {
    runtime,
    revision: payload.revision,
    runtimeVersion: RUNTIME_VERSION,
    seek: (checkpointId) => runtime.seek(checkpointId),
    dispatch: (action) => runtime.dispatch(action),
    state: () => runtime.state(),
    signatures: () => runtime.signatures(),
    scroll: () => runtime.scroll(),
};

/* A deep link names a cue; land its section on the reading line first so the
 * ordinary rule enters it, rather than special-casing the initial state. */
const linked = window.location.hash.startsWith('#cue-') ? window.location.hash.slice(5) : null;
const initialIndex = linked === null ? -1 : cueSections.findIndex((section) => section.dataset.cue === linked);
const initialCue = initialIndex >= 0 ? linked : order[0];
if (initialIndex > 0) {
    // Land the linked section a clear step past the reading line so the first
    // geometry pass agrees with the seek instead of rounding back a cue.
    const section = cueSections[initialIndex];
    window.scrollTo({ top: window.scrollY + section.getBoundingClientRect().top - readingLine() + 8, behavior: 'auto' });
}

/* Geometry drives navigation only after the first cue is in. The deep-link
 * scrollTo above already fires a scroll event; letting it seek during boot
 * would cancel the very seek it is trying to confirm. */
runtime.seek(initialCue).then(
    () => {
        window.addEventListener('scroll', schedule, { passive: true });
        window.addEventListener('resize', schedule);
        schedule();
        document.documentElement.dataset.doxagonReady = 'true';
    },
    (error) => { stage.dataset.error = `${error.code}: ${error.message}`; document.documentElement.dataset.doxagonReady = 'failed'; },
);
