<script lang="ts">
    import { createEventDispatcher, onDestroy, onMount } from 'svelte';
    import {
        acceptsSnapshot,
        type DeckActionRequest,
        type DeckPayload,
        type PresentationClient,
        type Snapshot,
    } from '$lib/presentation/deck';
    import { loadRuntime, type DeckRuntime, type DeckState } from '$lib/presentation/runtime';

    /** The presentation this stage belongs to. Every call is bound to it. */
    export let client: PresentationClient;
    export let deck: DeckPayload | null = null;
    export let checkpointId: string | null = null;
    /**
     * Join an already-open session instead of opening one.
     *
     * The audience display and the presenter console are two clients of one
     * server session, so the audience adopts the presenter's session id and
     * never opens a second cursor authority.
     */
    export let sessionId: string | null = null;
    /** A follower reads snapshots and never sends an action. */
    export let follow = false;
    export let controls = true;
    export let readout = true;

    const dispatch = createEventDispatcher<{ state: DeckState; session: Snapshot }>();

    let mount: HTMLDivElement;
    let runtime: DeckRuntime | null = null;
    let detach: (() => void) | null = null;
    let state: DeckState | null = null;
    let failure = '';
    let reducedMotion = false;
    let mounted = false;
    let presented: string | null = null;
    // The server owns the cursor. This component holds the last snapshot it was
    // issued so it can reject a stale, forked, or foreign-revision one; it
    // never mints a position of its own.
    let snapshot: Snapshot | null = null;
    let sessionFailure = '';
    // The revision this runtime and session were built from. A promoted
    // mutation answers with a new revision, and a preview that kept rendering
    // the old payload would be a second, stale deck beside the inspector.
    let pinned: string | null = null;
    // `runtime` and `snapshot` are only assigned after an await, so a reactive
    // re-run could enter start() twice and open a second session — which would
    // silently reset the server cursor. These latch synchronously for exactly
    // as long as the work is in flight; once start() has finished, `runtime`
    // itself blocks re-entry.
    let starting = false;
    let opening = false;
    let repinning = false;
    // The last value of the `checkpointId` prop this component reacted to. A
    // control action moves the server cursor before the parent's selection
    // catches up, so reacting to "prop differs from presented" would fire a
    // SEEK back to the stale selection and oscillate the cursor.
    let requested: string | null | undefined = undefined;
    // The cue this stage last published or adopted, so a realm notice that
    // merely echoes the position does not become another action.
    let presentedCue: string | null = null;
    // Actions run one at a time. Two overlapping actions each validated their
    // response against the snapshot they captured before awaiting, so a late
    // answer to the earlier action still looked like a legal successor and
    // overwrote the later one — the cursor moved backwards on the client while
    // the server sat on the newer position.
    let queue: Promise<void> = Promise.resolve();
    let actionGeneration = 0;
    let poll: ReturnType<typeof setInterval> | null = null;

    onMount(async () => {
        reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        mounted = true;
        await start();
    });

    onDestroy(() => {
        if (poll !== null) clearInterval(poll);
        detach?.();
        runtime?.destroy();
    });

    async function start() {
        if (!mounted || deck === null || runtime !== null || starting) return;
        starting = true;
        try {
            const payload = deck;
            const module = await loadRuntime();
            runtime = module.createDeckRuntime({
                deck: payload,
                mount,
                reducedMotion,
                onCue(checkpointId, cue) {
                    // A presenter reading a document moves the server cursor:
                    // the audience follows snapshots, so a scroll nobody
                    // published would leave the two surfaces showing different
                    // parts of the same page. A follower only renders.
                    //
                    // The realm withholds notices while a requested travel is
                    // in flight, so a cue arriving here is one a reader reached.
                    if (follow || cue === presentedCue) return;
                    presentedCue = cue;
                    if (snapshot?.checkpoint_id === checkpointId) {
                        void act({ type: 'SEEK', checkpointId, cue });
                    }
                },
                onState(next) {
                    // A render report is not an error verdict. Clearing
                    // `failure` here used to erase a refused action's code as
                    // soon as the runtime emitted its next state.
                    state = next;
                    // Opening first renders the server's initial cursor. Keep
                    // it from replacing a Step the author chose while that
                    // request was in flight; start() seeks their choice next.
                    if (!starting) dispatch('state', next);
                },
            });
            pinned = payload.revision;
            // Keyboard controls send the same session actions the buttons do.
            // Binding the runtime's own key handler here would advance the
            // local deck without telling the server, which is a second cursor
            // authority. A follower has no controls, so it binds none.
            if (!follow) detach ??= attachSessionKeys();
            await beginSession();
            // A session held across a repin has already issued a cursor;
            // present exactly it rather than asking the server to move again.
            if (snapshot !== null && presented === null) await adopt(snapshot);
            // The opened session already issued a checkpoint; only ask for
            // another one when the workspace is pointing somewhere else.
            if (!follow && checkpointId !== null && checkpointId !== presented) {
                await act({ type: 'SEEK', checkpointId });
            }
            if (follow && poll === null) poll = setInterval(() => void refresh(), 400);
        } finally {
            starting = false;
            if (state !== null) dispatch('state', state);
        }
    }

    /**
     * Rebuild this preview on the revision the workspace now reads.
     *
     * A promotion replaces the deck payload, so the realm has to be rebuilt
     * from the new bytes and the live session moved onto the new revision by
     * ending its epoch. Repinning is the only way the held snapshot and the
     * rendered bytes can name the same revision.
     */
    async function repin() {
        const payload = deck;
        if (payload === null || repinning || starting) return;
        repinning = true;
        const held = snapshot;
        try {
            detach?.();
            detach = null;
            await runtime?.destroy();
            runtime = null;
            presented = null;
            state = null;
            snapshot = null;
            if (held !== null) {
                // Adopt the repinned snapshot outright: it opens a new epoch,
                // which the previous revision's acceptance rule cannot admit.
                snapshot = follow
                    ? await client.readSession(held.session_id)
                    : await client.repinSession(held.session_id, payload.revision);
                sessionFailure = '';
            }
        } catch (error) {
            snapshot = null;
            sessionFailure = `${(error as { code?: string }).code ?? 'PRES_SESSION_UNAVAILABLE'}`;
        } finally {
            repinning = false;
        }
        await start();
    }

    /** Keyboard equivalents of the on-screen controls, routed through the session. */
    function attachSessionKeys(): () => void {
        const keys: Record<string, DeckActionRequest> = {
            ArrowRight: { type: 'NEXT' },
            PageDown: { type: 'NEXT' },
            ' ': { type: 'NEXT' },
            ArrowLeft: { type: 'PREVIOUS' },
            PageUp: { type: 'PREVIOUS' },
            Home: { type: 'HOME' },
            End: { type: 'END' },
        };
        const listener = (event: KeyboardEvent) => {
            const action = keys[event.key];
            if (action === undefined || event.defaultPrevented) return;
            if (event.metaKey || event.ctrlKey || event.altKey) return;
            const node = event.target as HTMLElement | null;
            if (node && (node.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(node.tagName))) return;
            event.preventDefault();
            void act(action);
        };
        window.addEventListener('keydown', listener);
        return () => window.removeEventListener('keydown', listener);
    }

    /**
     * Ask the server for the session this stage presents.
     *
     * A follower joins the session it was given; it never opens one, because a
     * second session would be a second cursor. A stage that cannot reach the
     * session service still renders locally, but it says so rather than
     * presenting a locally invented cursor as an authoritative one.
     */
    async function beginSession() {
        if (deck === null || snapshot !== null || opening) return;
        opening = true;
        try {
            snapshot = sessionId
                ? await client.readSession(sessionId)
                : await client.openSession(deck.revision);
            sessionFailure = '';
            // Published before `adopt` too, so a consumer learns the session id
            // even if the realm is not yet able to present it.
            dispatch('session', snapshot);
            await adopt(snapshot);
        } catch (error) {
            snapshot = null;
            sessionFailure = `${(error as { code?: string }).code ?? 'PRES_SESSION_UNAVAILABLE'}`;
        } finally {
            opening = false;
        }
    }

    /** Adopt the server's latest snapshot for a followed session. */
    async function refresh() {
        const held = snapshot;
        if (held === null || runtime === null || repinning) return;
        try {
            const issued = await client.readSession(held.session_id);
            if (snapshot !== held || !acceptsSnapshot(held, issued)) return;
            presented = issued.checkpoint_id;
            snapshot = issued;
            await adopt(issued);
        } catch (error) {
            sessionFailure = `${(error as { code?: string }).code ?? 'PRES_SESSION_UNAVAILABLE'}`;
        }
    }

    /** Present exactly the checkpoint the server's snapshot names. */
    async function adopt(issued: Snapshot) {
        if (runtime === null) return;
        presented = issued.checkpoint_id;
        presentedCue = issued.cue ?? null;
        const rendered = await runtime.adopt(issued);
        if (snapshot !== issued) return;
        failure = rendered.diagnostics.join('\n');
        // Every accepted snapshot is published, not only the one that opened
        // the session. A consumer binds its own readouts — the presenter's
        // notes, next step, and current-step marker above all — to the cursor
        // the server issued, so publishing only the join snapshot would leave
        // those readouts describing the first step for the whole talk.
        dispatch('session', issued);
    }

    /**
     * Send one action to the server and adopt the snapshot it issues.
     *
     * The server resolves the destination and preserves traversal intent.
     * The client does not compute the next checkpoint,
     * and it refuses a snapshot its current one does not accept.
     */
    export function act(action: DeckActionRequest): Promise<void> {
        if (['SEEK', 'HOME', 'END'].includes(action.type)) {
            actionGeneration += 1;
            runtime?.cancel();
        }
        const expected = actionGeneration;
        const performCurrent = () => expected === actionGeneration ? perform(action) : Promise.resolve();
        const next = queue.then(performCurrent, performCurrent);
        queue = next.catch(() => {});
        return next;
    }

    async function perform(action: DeckActionRequest) {
        if (runtime === null) return;
        const held = snapshot;
        if (held === null) {
            failure = 'PRES_SESSION_UNAVAILABLE: no server session issues this cursor';
            return;
        }
        try {
            const issued = await client.applyAction(held.session_id, action, held.deck_revision);
            // Compare against the snapshot held *now*, not the one this action
            // started from: a repin or a reopened session may have adopted a
            // newer cursor while this request was in flight, and adopting an
            // older successor over it would regress the presented state.
            if (snapshot !== held || !acceptsSnapshot(held, issued)) {
                failure = 'PRES_SNAPSHOT_REJECTED: the issued snapshot does not follow the held one';
                return;
            }
            // Latch what is being presented in the same synchronous step as the
            // snapshot. Assigning only `snapshot` here let a reactive re-run
            // observe the new snapshot beside the previous `presented` and send
            // the same seek again, which ran the cursor away.
            presented = issued.checkpoint_id;
            snapshot = issued;
            await adopt(issued);
        } catch (error) {
            if ((error as { code?: string }).code === 'PRES_NAVIGATION_CANCELLED') return;
            failure = `${(error as { code?: string }).code ?? 'PRES_CHECKPOINT_FAILED'}: ${(error as Error).message}`;
        }
    }

    $: if (mounted && deck !== null && runtime === null && !repinning) start();
    $: if (deck !== null && pinned !== null && deck.revision !== pinned) repin();
    // Every user-initiated selection is a server SEEK. Calling runtime.seek
    // directly would render a checkpoint the held snapshot does not name, and
    // the next NEXT/PREVIOUS would then resolve from the server's older one.
    $: if (checkpointId !== requested) {
        requested = checkpointId;
        if (
            !follow
            && runtime !== null
            && snapshot !== null
            && checkpointId !== null
            && checkpointId !== presented
            && !repinning
        ) {
            void act({ type: 'SEEK', checkpointId });
        }
    }
</script>

<section class="checkpoint-preview" class:is-bare={!controls && !readout} aria-label="Step preview">
    <div class="realm" bind:this={mount} data-checkpoint={state?.checkpointId ?? ''}></div>
    {#if controls || readout}
        <div class="preview-bar">
            {#if controls}
                <div class="preview-controls" role="group" aria-label="Step controls">
                    <button type="button" data-action="HOME" on:click={() => act({ type: 'HOME' })}>First</button>
                    <button type="button" data-action="PREVIOUS" on:click={() => act({ type: 'PREVIOUS' })}>Back</button>
                    <button type="button" data-action="NEXT" on:click={() => act({ type: 'NEXT' })}>Next</button>
                    <button type="button" data-action="END" on:click={() => act({ type: 'END' })}>Last</button>
                </div>
            {/if}
            {#if readout}
                <details class="preview-details" data-advanced="true"><summary>Preview details</summary><dl class="preview-readout">
                    <dt>Step</dt>
                    <dd data-testid="preview-checkpoint">{state?.checkpointId ?? '—'}</dd>
                    <dt>Signature</dt>
                    <dd data-testid="preview-signature">{state?.signature ?? '—'}</dd>
                    <dt>Cursor</dt>
                    <dd data-testid="preview-cursor">
                        {snapshot ? `${snapshot.epoch}.${snapshot.sequence}` : (sessionFailure || '—')}
                    </dd>
                    <dt>Motion</dt>
                    <dd data-testid="preview-motion">{reducedMotion ? 'reduced' : 'full'}</dd>
                </dl></details>
            {/if}
        </div>
    {/if}
    {#if failure}
        <p class="preview-failure" role="alert" data-testid="preview-failure">{failure}</p>
    {/if}
</section>

<style>
    .checkpoint-preview {
        display: grid;
        grid-template-rows: minmax(0, 1fr) auto auto;
        min-height: 0;
        gap: 0.5rem;
    }

    .checkpoint-preview.is-bare {
        grid-template-rows: minmax(0, 1fr) auto;
        gap: 0;
    }

    .realm {
        position: relative;
        /* The stage holds a stable presentation shape inside whatever space the
           workspace gives it. Deriving its height from the viewport width made
           a narrow screen paint a realm taller than the screen; deriving it
           from the available box does not. */
        aspect-ratio: 16 / 9;
        width: 100%;
        max-height: 100%;
        min-height: 0;
        margin-inline: auto;
        border: 1px solid var(--dox-frame-rule, currentColor);
        /* A checkpoint document is author-controlled and may declare no colours
           at all. The realm therefore presents a neutral canvas rather than the
           dark workspace chrome, so default author text stays readable instead
           of rendering near-black on a near-black frame. */
        color-scheme: light;
        background: Canvas;
        overflow: hidden;
    }

    .checkpoint-preview.is-bare .realm {
        border: 0;
    }

    .realm :global(iframe) {
        position: absolute;
        inset: 0;
        width: 100%;
        height: 100%;
        border: 0;
        background: transparent;
    }

    .preview-bar {
        display: flex;
        flex-wrap: wrap;
        gap: 0.75rem;
        align-items: center;
        justify-content: space-between;
    }

    .preview-controls {
        display: flex;
        gap: 0.5rem;
    }

    .preview-controls button {
        min-width: 44px;
        min-height: 44px;
        padding: 0 0.75rem;
        font: inherit;
        /* States its own foreground against the frame ground; inheriting the
           user-agent button colour drew near-black on near-black. */
        color: var(--dox-frame-text);
        background: color-mix(in srgb, var(--dox-frame-text) 12%, var(--dox-frame-ground));
        border: 1px solid color-mix(in srgb, var(--dox-frame-text) 45%, var(--dox-frame-ground));
        border-radius: 6px;
        cursor: pointer;
    }


    .preview-controls { flex-wrap: wrap; }
    .preview-controls button { font-size: 0.8125rem; font-weight: 600; }
    .preview-controls button:hover { border-color: var(--dox-frame-text); background: var(--dox-frame-surface-raised); }
    .preview-controls button[data-action="NEXT"] { background: var(--dox-frame-text); color: var(--dox-frame-ground); }
    .preview-details { width: 100%; font-size: 0.75rem; color: var(--dox-frame-text-muted); }
    .preview-details summary { cursor: pointer; padding: 0.5rem 0; }
    .preview-details summary:focus-visible { outline: 2px solid currentColor; }
    .preview-controls button:focus-visible {
        outline: 2px solid var(--dox-frame-text);
        outline-offset: 1px;
    }

    .preview-readout {
        display: grid;
        grid-template-columns: auto auto;
        gap: 0 0.5rem;
        margin: 0;
        font-family: var(--font-mono, ui-monospace, monospace);
        font-size: 0.75rem;
    }

    .preview-readout dt {
        color: var(--dox-frame-text-muted);
    }

    .preview-readout dd {
        margin: 0;
        overflow-wrap: anywhere;
    }

    .preview-failure {
        margin: 0;
        color: var(--dox-signal-alert, #ff9a8b);
        font-size: 0.875rem;
    }

    @media (max-width: 900px) {
        /* Stacked, the preview is a block in a scrolling document. A `1fr`
           realm row under a container shorter than its content let the control
           bar paint outside the preview and over the inspector below it. Auto
           rows size to content, and the realm keeps its own aspect ratio. */
        .checkpoint-preview {
            grid-template-rows: auto auto auto;
            min-height: auto;
        }

        .realm { max-height: none; }
    }
</style>
