/**
 * The offline export shell — the only privileged executable in an exported deck.
 *
 * It is concatenated after the runtime inside one pinned module, so the export
 * carries exactly one script whose digest the document's CSP names. It reads
 * the deck from an inert JSON block, drives the same absolute-seek runtime the
 * workspace uses, and issues no request of any kind.
 */

const payload = JSON.parse(document.getElementById('doxagon-deck-payload').textContent);
const stage = document.getElementById('doxagon-stage');
const controls = document.getElementById('doxagon-controls');
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

const label = document.createElement('span');
label.className = 'doxagon-label';
const status = document.createElement('span');
status.className = 'doxagon-error';
status.setAttribute('role', 'status');

const actions = [
    ['HOME', 'First checkpoint'],
    ['PREVIOUS', 'Back'],
    ['NEXT', 'Next'],
    ['END', 'Last checkpoint'],
];

const runtime = createDeckRuntime({
    deck: payload,
    mount: stage,
    reducedMotion,
    onState(state) {
        const index = payload.checkpoint_order.indexOf(state.checkpointId);
        const checkpoint = payload.checkpoints.find((item) => item.id === state.checkpointId);
        label.textContent = `${index + 1} / ${payload.checkpoint_order.length} · ${checkpoint ? checkpoint.label : ''}`;
        label.dataset.checkpointId = state.checkpointId;
        label.dataset.signature = state.signature || '';
        status.textContent = '';
    },
});

for (const [type, text] of actions) {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = text;
    button.dataset.action = type;
    button.addEventListener('click', () => {
        runtime.dispatch({ type }).catch((error) => { status.textContent = `${error.code}: ${error.message}`; });
    });
    controls.appendChild(button);
}
controls.append(label, status);
attachControls(runtime);

/* Tests and the raster exporter drive the deck through this handle; it exposes
 * the runtime's own state and signatures, never a private replay list. */
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

runtime.seek(payload.checkpoint_order[0]).then(
    () => { document.documentElement.dataset.doxagonReady = 'true'; },
    (error) => { status.textContent = `${error.code}: ${error.message}`; document.documentElement.dataset.doxagonReady = 'failed'; },
);
