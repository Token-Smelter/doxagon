<script lang="ts">
    /**
     * The presenter console.
     *
     * It drives exactly the server session the editor opened: the presenter
     * sends actions, the server issues snapshots, and every other client —
     * the audience display above all — adopts those snapshots. There is no
     * browser-originated cursor here, and no slide/step pair: one action names
     * one Step and the server resolves it against the registered edge table.
     */
    import { onDestroy, onMount, tick } from 'svelte';
    import { page } from '$app/stores';
    import CheckpointPreview from '$lib/components/deck/CheckpointPreview.svelte';
    import DocumentPlayer from '$lib/components/presentation/DocumentPlayer.svelte';
    import { findAuthoredDocument, type AuthoredDocument } from '$lib/presentation/authoredDocument';
    import {
        presentationBase,
        presentationClient,
        slideOutline,
        type DeckPayload,
        type PresentationClient,
        type SlideRun,
        type Snapshot,
        type WorkspaceView,
    } from '$lib/presentation/deck';
    import { currentCuePassage, currentPassage, documentScript, slideScript } from '$lib/presentation/script';

    let documentSource: AuthoredDocument | null = null;
    let loadRequest = 0;
    let client: PresentationClient | null = null;
    let workspace: WorkspaceView | null = null;
    let deck: DeckPayload | null = null;
    let snapshot: Snapshot | null = null;
    let loading = true;
    let failure = '';
    let elapsed = 0;
    let paused = false;
    let ticker: ReturnType<typeof setInterval> | null = null;
    let stage: CheckpointPreview | null = null;
    let scriptPane: HTMLElement | null = null;
    let stepList: HTMLElement | null = null;
    let reducedMotion = false;

    $: presentationSlug = $page.params.thesis ?? '';
    $: requestedSession = $page.url.searchParams.get('session');

    onMount(() => {
        reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        ticker = setInterval(() => {
            if (!paused) elapsed += 1;
        }, 1000);
    });

    onDestroy(() => {
        loadRequest += 1;
        if (ticker !== null) clearInterval(ticker);
    });

    async function load(slug: string) {
        const request = ++loadRequest;
        loading = true;
        failure = '';
        documentSource = null;
        client = null;
        try {
            // A selected document owns presentation. Do not open or migrate the
            // checkpoint store first: that would revive the old rendering path.
            const source = await findAuthoredDocument(slug);
            if (request !== loadRequest) return;
            if (source) {
                documentSource = source;
                return;
            }
            const bound = presentationClient(presentationBase(slug));
            const nextWorkspace = await bound.readWorkspace();
            const nextDeck = await bound.readDeck();
            if (request !== loadRequest) return;
            client = bound;
            workspace = nextWorkspace;
            deck = nextDeck;
        } catch (error) {
            if (request === loadRequest) failure = `${(error as { code?: string }).code ?? 'PRES_WORKSPACE_UNAVAILABLE'}: ${(error as Error).message}`;
        } finally {
            if (request === loadRequest) loading = false;
        }
    }

    const pad = (value: number) => String(value).padStart(2, '0');

    const runOf = (runs: SlideRun[], checkpointId: string | null) =>
        runs.find((run) => run.steps.some((item) => item.id === checkpointId)) ?? null;

    function describePosition(
        run: SlideRun | null,
        stepInRun: number,
        slides: number,
        index: number,
        total: number,
    ): string {
        if (run === null) return index >= 0 ? `Step ${index + 1} of ${total}` : '';
        if (run.number === null) return `Step ${index + 1} of ${total}`;
        const slide = `Slide ${run.number} of ${slides}`;
        return run.steps.length > 1 ? `${slide} · step ${stepInRun + 1} of ${run.steps.length}` : slide;
    }

    $: if (presentationSlug) void load(presentationSlug);
    $: current = snapshot?.checkpoint_id ?? null;
    $: currentCue = snapshot?.cue ?? null;
    // A document is one Step with an authored interior: its script is its cues.
    $: activeCheckpoint = deck?.checkpoints.find((item) => item.id === current) ?? null;
    $: documentCues = activeCheckpoint?.mode === 'document' ? activeCheckpoint.cues ?? [] : [];
    $: cueNotes = activeCheckpoint?.cue_notes ?? {};
    $: steps = workspace?.checkpoints ?? [];
    $: currentIndex = steps.findIndex((item) => item.id === current);
    $: upcoming = currentIndex >= 0 ? steps[currentIndex + 1] ?? null : null;
    $: nextCue = documentCues.length > 0 ? documentCues[documentCues.indexOf(currentCue ?? '') + 1] ?? null : null;
    const notesFor = (checkpointId: string) => deck?.checkpoints.find((item) => item.id === checkpointId)?.notes;
    // A deck's Steps belong to slides, and a presenter navigates the slide as
    // much as the Step: the outline is the deck's own groups, not a flat list
    // this console invented. A deck that declares none reads as one run.
    $: outline = slideOutline(steps, workspace?.groups ?? []);
    // Slides, not runs: a deck that returns to a slide plays it twice and still
    // holds the one slide.
    $: slideCount = new Set(outline.filter((run) => run.number !== null).map((run) => run.groupId)).size;
    $: currentRun = runOf(outline, current);
    $: stepInRun = currentRun ? currentRun.steps.findIndex((item) => item.id === current) : -1;
    $: position = documentCues.length > 0
        ? `${activeCheckpoint?.label ?? ''} · ${Math.max(1, documentCues.indexOf(currentCue ?? '') + 1)} of ${documentCues.length}`
        : describePosition(currentRun, stepInRun, slideCount, currentIndex, steps.length);
    $: nextRun = runOf(outline, upcoming?.id ?? null);
    $: nextOpensSlide =
        nextRun !== null && currentRun !== null && nextRun !== currentRun && nextRun.number !== null;
    $: timer = `${pad(Math.floor(elapsed / 3600))}:${pad(Math.floor(elapsed / 60) % 60)}:${pad(elapsed % 60)}`;
    // The script is the whole slide's notes, one passage per Step; the current
    // passage is emphasized and the pane scrolls it to a fixed reading line so
    // an advance reads as the next paragraph arriving, not as a page change.
    // Both shapes read as one scrolling column: current emphasized, the next
    // already in view, the previous still above it.
    $: passages = documentCues.length > 0
        ? documentScript(current ?? '', documentCues, cueNotes)
        : slideScript(currentRun, notesFor);
    $: reading = documentCues.length > 0
        ? currentCuePassage(passages, documentCues, currentCue)
        : currentPassage(passages, currentRun, current);
    $: void (reading, passages, current, followReading());

    async function followReading() {
        await tick();
        const behavior = reducedMotion ? 'auto' : 'smooth';
        const pane = scriptPane;
        const target = pane?.querySelector<HTMLElement>('.passage.is-current');
        if (pane && target) {
            // Reading line at roughly a fifth of the pane, so the next passage
            // is already in view below the current one. The first passage
            // starts at the top: nothing precedes it to leave room for.
            const top = reading === 0 ? 0 : target.offsetTop - pane.clientHeight * 0.2;
            pane.scrollTo({ top: Math.max(0, top), behavior });
        }
        const list = stepList;
        const marker = list?.querySelector<HTMLElement>('li.is-current');
        if (list && marker) {
            const above = marker.offsetTop < list.scrollTop;
            const below = marker.offsetTop + marker.offsetHeight > list.scrollTop + list.clientHeight;
            if (above || below) list.scrollTo({ top: marker.offsetTop - list.clientHeight / 3, behavior });
        }
    }
</script>

<svelte:head><title>Presenter · {presentationSlug}</title></svelte:head>

{#if documentSource && !loading}
    {#key presentationSlug}
        <DocumentPlayer source={documentSource} />
    {/key}
{:else}
<main class="presenter" aria-label="Presenter console">
    <a class="document-link" href="/presentations/document">Open HTML document instead</a>
    {#if loading}
        <p class="presenter-state" role="status">Opening the presentation…</p>
    {:else if failure}
        <p class="presenter-state error" role="alert" data-testid="presenter-failure">{failure}</p>
    {:else}
        <header class="presenter-head">
            <div>
                <p class="presenter-mark">Presenter</p>
                <h1>{presentationSlug}</h1>
                <p class="presenter-position" data-testid="presenter-position">{position}</p>
            </div>
            <div class="presenter-timer">
                <span data-testid="presenter-timer">{timer}</span>
                <button type="button" on:click={() => (paused = !paused)}>{paused ? 'Resume' : 'Pause'}</button>
                <button type="button" on:click={() => (elapsed = 0)}>Reset</button>
            </div>
        </header>

        <section class="presenter-stage" aria-label="Current step">
            {#if client}
                <CheckpointPreview
                    bind:this={stage}
                    {client}
                    {deck}
                    sessionId={requestedSession}
                    on:session={(event) => (snapshot = event.detail)}
                    on:state={() => {}}
                />
            {/if}
        </section>

        <aside class="presenter-side">
            <section class="step-order" aria-label="Step order">
                <h2>Steps</h2>
                <div class="step-list" bind:this={stepList} data-testid="presenter-steps">
                    {#each outline as run (run.key)}
                        {#if run.number !== null}
                            <h3
                                id="run-{run.key}"
                                class="run-head"
                                class:is-current={run === currentRun}
                                data-group={run.groupId}
                            >
                                <span class="run-index">{run.number}</span>
                                <span class="run-label">{run.label}</span>
                            </h3>
                        {/if}
                        <ol aria-labelledby={run.number === null ? undefined : `run-${run.key}`}>
                            {#each run.steps as item (item.id)}
                                <li class:is-current={item.id === current}>
                                    <button
                                        type="button"
                                        data-checkpoint={item.id}
                                        aria-current={item.id === current ? 'true' : 'false'}
                                        on:click={() => stage?.act({ type: 'SEEK', checkpointId: item.id })}
                                    >
                                        <span class="step-index">{item.index + 1}</span>
                                        <span class="step-label">{item.label}</span>
                                    </button>
                                </li>
                            {/each}
                        </ol>
                    {/each}
                </div>
            </section>
            <section aria-label="Next step">
                <h2>Next</h2>
                <p data-testid="presenter-next">
                    {#if nextCue !== null}
                        <span class="next-scope">Next cue</span>
                        {nextCue}
                    {:else if upcoming === null}
                        End of presentation
                    {:else}
                        <span class="next-scope">{nextOpensSlide ? 'Next slide' : 'Next step'}</span>
                        {upcoming.label}
                    {/if}
                </p>
            </section>
            <section class="script" aria-label="Presenter notes">
                <h2>Notes</h2>
                <div class="script-pane" bind:this={scriptPane} data-testid="presenter-notes" data-reading={reading}>
                    {#if passages.length === 0}
                        <p class="passage is-empty">No notes for this slide.</p>
                    {:else}
                        <!-- A document's passages share one checkpoint, so the
                             cue is what distinguishes them. -->
                        {#each passages as passage, index (passage.cue ?? passage.checkpointId)}
                            <p
                                class="passage"
                                class:is-current={index === reading}
                                class:is-spoken={index < reading}
                                data-passage={passage.cue ?? passage.checkpointId}
                                aria-current={index === reading ? 'step' : undefined}
                            >{passage.text}</p>
                        {/each}
                    {/if}
                </div>
            </section>
        </aside>
    {/if}
</main>
{/if}

<style>
    /* The app shell owns the viewport; this console fills the space it is
       given and scrolls its own regions. */
    .presenter {
        display: grid;
        grid-template-columns: minmax(0, 1fr) minmax(16rem, 22rem);
        grid-template-rows: auto auto minmax(0, 1fr);
        gap: 1rem;
        height: 100%;
        min-height: 0;
        padding: 1rem;
        box-sizing: border-box;
        overflow: hidden;
        color: var(--dox-frame-text);
        background: var(--dox-frame-ground);
    }

    .presenter :is(button):not(:disabled) {
        color: var(--dox-frame-text);
        background: color-mix(in srgb, var(--dox-frame-text) 8%, transparent);
        border: 1px solid var(--dox-frame-rule, currentColor);
        border-radius: 2px;
        min-height: 44px;
        font: inherit;
        cursor: pointer;
    }

    .presenter :is(button):focus-visible { outline: 2px solid var(--dox-frame-text); outline-offset: 1px; }

    .presenter-head { grid-column: 1 / -1; display: flex; flex-wrap: wrap; gap: 1rem; align-items: baseline; justify-content: space-between; }
    .presenter-mark { margin: 0 0 0.2rem; color: var(--dox-frame-text-muted); font-family: var(--dox-font-mono); font-size: 0.68rem; letter-spacing: var(--dox-tracking-caps); text-transform: uppercase; }
    .presenter-head h1 { margin: 0; font-family: var(--dox-font-display); font-size: 1.3rem; }
    .presenter-timer { display: flex; gap: 0.5rem; align-items: center; font-family: var(--font-mono, ui-monospace, monospace); font-size: 1.1rem; }
    .presenter-timer button { padding: 0 0.75rem; }

    .presenter-stage, .presenter-side { min-height: 0; min-width: 0; overflow: auto; }
    .presenter-stage { display: grid; }
    /* The side column is split, not stacked: the Steps list scrolls inside
       its own share and the script keeps a guaranteed region beneath it, so a
       long deck can never push the notes off the presenter's screen. */
    .presenter-side { display: grid; grid-template-rows: minmax(0, 1fr) auto minmax(0, 1.2fr); gap: 1rem; align-content: stretch; overflow: hidden; }
    .step-order { display: grid; grid-template-rows: auto minmax(0, 1fr); min-height: 0; }
    .step-list { overflow-y: auto; min-height: 0; padding-right: 0.5rem; }
    .presenter-side h2 { margin: 0 0 0.35rem; font-family: var(--dox-font-display); font-size: 0.9rem; }
    .presenter-side ol { list-style: none; margin: 0; padding: 0; display: grid; gap: 0.25rem; }
    /* The slide a run of Steps belongs to reads as a heading over them, so the
       indented Steps below it are visibly that slide's and not the deck's. */
    .run-head { display: grid; grid-template-columns: 2rem minmax(0, 1fr); gap: 0.5rem; margin: 0.6rem 0 0.25rem; font-family: var(--dox-font-display); font-size: 0.8rem; font-weight: 400; }
    .run-head:first-child { margin-top: 0; }
    .run-head.is-current .run-label { color: var(--dox-frame-text); }
    .run-label { color: var(--dox-frame-text-muted); }
    .run-index { font-family: var(--font-mono, ui-monospace, monospace); color: var(--dox-frame-text-muted); }
    .run-head + ol { padding-left: 2.5rem; }
    .presenter-position { margin: 0.2rem 0 0; color: var(--dox-frame-text-muted); font-family: var(--font-mono, ui-monospace, monospace); font-size: 0.8rem; }
    .next-scope { color: var(--dox-frame-text-muted); font-family: var(--dox-font-mono); font-size: 0.68rem; letter-spacing: var(--dox-tracking-caps); text-transform: uppercase; }
    .presenter-side li button { display: grid; grid-template-columns: 2rem minmax(0, 1fr); gap: 0.5rem; width: 100%; padding: 0.4rem; text-align: left; }
    .presenter-side li.is-current button { outline: 2px solid var(--dox-frame-text); }
    .step-index { font-family: var(--font-mono, ui-monospace, monospace); color: var(--dox-frame-text-muted); }
    .document-link { grid-column: 1 / -1; color: var(--dox-frame-text-muted); }
    /* The script pane owns its own scroll so the reading line can be pinned
       without moving the Steps list or the stage. */
    .script { display: grid; grid-template-rows: auto minmax(0, 1fr); min-height: 0; }
    .script-pane { overflow-y: auto; min-height: 0; padding-right: 0.5rem; scroll-behavior: smooth; }
    .passage {
        margin: 0 0 1em;
        white-space: pre-wrap;
        font-family: var(--dox-font-body);
        line-height: 1.5;
        color: var(--dox-frame-text-muted);
        /* Emphasis crossfades between passages; the scroll carries the reading
           line. Together an advance reads as the next paragraph arriving. */
        transition: color 250ms ease-out, opacity 250ms ease-out;
    }
    .passage.is-current { color: var(--dox-frame-text); }
    .passage.is-spoken { opacity: 0.55; }
    .passage.is-empty { color: var(--dox-frame-text-muted); }
    @media (prefers-reduced-motion: reduce) {
        .script-pane { scroll-behavior: auto; }
        .passage { transition: none; }
    }
    .presenter-state { margin: 0; padding: 2rem; }
    .presenter-state.error { color: var(--dox-signal-alert, #ff9a8b); }

    @media (max-width: 1023px) {
        .presenter {
            grid-template-columns: minmax(0, 1fr);
            grid-template-rows: auto auto auto;
            height: auto;
            min-height: 100%;
            overflow: visible;
        }

        .presenter-stage, .presenter-side { overflow: visible; }
        /* Stacked, the page scrolls; the split regions become plain blocks
           with bounded heights so neither hides the other. */
        .presenter-side { grid-template-rows: auto; }
        .step-list { max-height: 18rem; }
        .script-pane { max-height: 22rem; }
    }
</style>
