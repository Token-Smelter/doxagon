/**
 * The document shell — a whole authored page over the one runtime.
 *
 * The realm fills the viewport and owns its own scrolling, so the author's
 * sticky sections, viewport units, overlays, and full-bleed visuals are the
 * real thing rather than an approximation inside a stage box. The host does not
 * measure author DOM: the realm reports the cue it selected, and the host asks
 * it to travel. Next/Back/Jump and reading are therefore the same document.
 */

const payload = JSON.parse(document.getElementById('doxagon-deck-payload').textContent);
const stage = document.getElementById('doxagon-stage');
const status = document.getElementById('doxagon-status');
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const order = payload.checkpoint_order;

let cues = [];
let currentCue = null;

const runtime = createDeckRuntime({
    deck: payload,
    mount: stage,
    reducedMotion,
    onState(state) {
        if (state.checkpointId === null) return;
        stage.dataset.checkpoint = state.checkpointId;
        if (status) status.textContent = state.diagnostics.join(' ') || '';
    },
    onCue(checkpointId, cue) {
        currentCue = cue;
        document.documentElement.dataset.doxagonCue = cue;
        const hash = `#${cue}`;
        if (window.location.hash !== hash) window.history.replaceState(null, '', hash);
    },
});

/* Within a document the cues are the page's own; across documents the deck's
 * registered edges still decide. One command therefore reads as one move
 * whether the next state is a scroll away or a whole new document. */
async function step(delta) {
    const index = cues.indexOf(currentCue);
    if (index >= 0 && index + delta >= 0 && index + delta < cues.length) {
        await runtime.travel(cues[index + delta], { smooth: !reducedMotion });
        return;
    }
    await runtime.dispatch({ type: delta > 0 ? 'NEXT' : 'PREVIOUS' }).catch(() => {});
    await observe();
}

async function observe() {
    const report = await runtime.observe(0.5).catch(() => null);
    cues = report?.cues ?? [];
    currentCue = report?.cue ?? null;
    document.documentElement.dataset.doxagonCues = String(cues.length);
}

window.addEventListener('keydown', (event) => {
    const node = event.target;
    if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey) return;
    if (node && (node.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(node.tagName))) return;
    // Arrow/Page/Space keys inside the realm are the author's to handle; this
    // shell only binds the explicit presentation keys the host owns.
    if (['ArrowRight', 'PageDown'].includes(event.key)) { event.preventDefault(); void step(1); }
    else if (['ArrowLeft', 'PageUp'].includes(event.key)) { event.preventDefault(); void step(-1); }
});

window.doxagonDocument = {
    runtime,
    cues: () => cues,
    currentCue: () => currentCue,
    step,
    travel: (cue) => runtime.travel(cue, { smooth: false }),
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

const linked = window.location.hash.slice(1);

runtime.seek(order[0]).then(async () => {
    await observe();
    if (linked && cues.includes(linked)) await runtime.travel(linked, { smooth: false });
    document.documentElement.dataset.doxagonReady = 'true';
}, (error) => {
    if (status) status.textContent = `${error.code}: ${error.message}`;
    document.documentElement.dataset.doxagonReady = 'failed';
});
