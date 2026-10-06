<script lang="ts">
    import { onDestroy, onMount } from 'svelte';
    import DocumentControls from './DocumentControls.svelte';
    import { parseCompanionNotes, type DocumentPosition, type DocumentReady } from '$lib/presentation/documentBridge';
    import { claimHref, claimLabel } from '$lib/presentation/claimLabels';
    import { fetchDoxaLabel } from '$lib/api';
    import { documentKeys } from '$lib/presentation/documentKeys';

    export let ready: DocumentReady;
    export let position: DocumentPosition | null;
    export let connected: boolean;
    export let popup: Window;
    export let navigate: (action: 'next' | 'previous' | 'first' | 'last') => void;
    export let go: (cue: string) => void;
    export let sourceUrl: string | null = null;
    export let endPresentation: (() => void) | null = null;

    let notes: Map<string, string> | null = null;
    let claimLabels = new Map<string, string>();
    let failure = '';
    let filename = '';
    let reading = 0;
    let lastCue: string | undefined;
    $: if (position?.cue !== lastCue) {
        lastCue = position?.cue;
        popup.scrollTo(0, 0);
    }
    $: current = position ? ready.cues[position.index] : null;
    $: upcoming = position ? ready.cues[position.index + 1] : null;
    $: claims = current?.claims ?? [];
    $: resolveClaims(claims);

    async function resolveClaims(ids: string[]) {
        for (const id of ids) {
            if (claimLabels.has(id)) continue;
            // The id stands in while the vault answers, and stays if it cannot.
            claimLabels.set(id, id);
            try {
                const doxa = await fetchDoxaLabel(id);
                claimLabels.set(id, claimLabel(id, doxa.short, doxa.belief));
            } catch {
                claimLabels.set(id, id);
            }
            claimLabels = new Map(claimLabels);
        }
    }

    onMount(() => {
        if (sourceUrl) void openSavedNotes(sourceUrl);
        return documentKeys(popup, (action) => { if (connected) navigate(action); });
    });
    onDestroy(() => { reading += 1; notes?.clear(); });

    async function openSavedNotes(url: string) {
        const request = ++reading;
        try {
            const response = await fetch(url, { cache: 'no-store' });
            if (!response.ok) throw new Error('The saved notes could not be loaded. Choose a matching companion below to recover.');
            const content = await response.blob();
            if (request !== reading) return;
            await loadNotes(new File([content], 'notes.json'));
        } catch (error) {
            if (request === reading) failure = error instanceof Error ? error.message : 'The saved notes could not be read.';
        }
    }

    async function selectNotes(event: Event) {
        const file = (event.currentTarget as HTMLInputElement).files?.[0];
        if (file) await loadNotes(file);
    }

    async function loadNotes(file: File) {
        const attempt = ++reading;
        notes = null;
        filename = '';
        try {
            if (file.size > 2 * 1024 * 1024) throw new Error('Choose a notes JSON file smaller than 2 MB.');
            const candidate = parseCompanionNotes(JSON.parse(await file.text()), ready);
            if (attempt !== reading) return;
            if (candidate === null) throw new Error('These notes do not match this document, edition and cue order. Choose its matching companion notes.');
            notes = candidate;
            filename = file.name;
            failure = '';
        } catch (error) {
            if (attempt === reading) failure = error instanceof Error ? error.message : 'The notes file could not be read.';
        }
    }
</script>

<main class="notes" aria-label="Document speaker notes">
    <header>
        <div class="heading"><h1>Speaker notes</h1>{#if endPresentation}<button type="button" on:click={endPresentation}>End presentation</button>{/if}</div>
        <DocumentControls {ready} {position} {connected} expandableCues on:next={() => navigate('next')} on:previous={() => navigate('previous')} on:go={(event) => go(event.detail)} />
        {#if !connected}<p role="status">Document disconnected. Reconnect from the player to continue.</p>{/if}
    </header>
    <section class="reading" aria-label="Current note">
        <h2>{current?.title ?? 'Waiting for the document'}</h2>
        <p class="note" data-testid="speaker-note">{current && notes ? notes.get(current.id) : 'Choose the companion notes.json below. Nothing is uploaded or added to the audience document.'}</p>
        {#if claims.length > 0}
            <nav class="claims" aria-label="Claims in this cue">
                <h3>Claims in this cue</h3>
                <ul>
                    {#each claims as claim (claim)}
                        <li><a class="chip" data-testid="claim-chip" href={claimHref(claim)} target="_blank" rel="noreferrer">{claimLabels.get(claim) ?? claim}</a></li>
                    {/each}
                </ul>
            </nav>
        {/if}
        <details>
            <summary>Coming next</summary>
            <h3>{upcoming?.title ?? 'End of document'}</h3>
            <p class="note">{upcoming && notes ? notes.get(upcoming.id) : ''}</p>
        </details>
    </section>
    <section class="selection" aria-label="Choose private notes">
        <label for="notes-file">Choose companion notes</label>
        <input id="notes-file" type="file" accept="application/json,.json" on:change={selectNotes} />
        {#if filename}<p role="status">Loaded {filename} · local to this window</p>{/if}
        {#if failure}<p class="error" role="alert">{failure}</p>{/if}
        <p class="identity">{ready.documentId} · edition {ready.edition}</p>
        <p>Use these controls or scroll in the player. Both control the same loaded document. Closing this window discards the notes.</p>
    </section>
</main>

<style>
    :global(body) { margin: 0; }
    .notes { min-height: 100%; background: #efe6d2; color: #16130f; font: 18px/1.55 Georgia, serif; }
    header { position: sticky; top: 0; z-index: 1; padding: 1rem 1.5rem; color: #efe6d2; background: #16130f; font: 14px/1.5 system-ui, sans-serif; }
    .heading { display: flex; justify-content: space-between; align-items: center; gap: 1rem; margin-bottom: 0.75rem; }
    h1 { font-size: 1.1rem; margin: 0; }
    .heading button { padding: 0.5rem 0.75rem; min-height: 44px; border: 1px solid #b9af9d; color: inherit; background: transparent; font: inherit; cursor: pointer; }
    .heading button:focus-visible { outline: 2px solid currentColor; outline-offset: 2px; }
    h2 { font-size: 1.6rem; line-height: 1.25; text-wrap: balance; margin-top: 0; }
    h3 { font-size: 1.1rem; }
    .reading, .selection { padding: 1.5rem; max-width: 70ch; margin-inline: auto; overflow-wrap: anywhere; }
    .note { white-space: pre-wrap; }
    .claims { margin-top: 1.5rem; font: 14px/1.5 system-ui, sans-serif; }
    .claims h3 { font-size: 0.8rem; letter-spacing: var(--dox-tracking-caps, 0.16em); text-transform: uppercase; color: #5c5347; margin: 0 0 0.5rem; }
    .claims ul { display: flex; flex-wrap: wrap; gap: 0.4rem; list-style: none; padding: 0; margin: 0; }
    .chip { display: inline-block; min-height: 32px; padding: 0.35rem 0.7rem; border: 1px solid var(--dox-work-rule, #b9af9d); border-radius: var(--dox-radius-pill, 999px); background: var(--dox-work-surface-raised, #f5eedc); color: var(--dox-work-text, #16130f); text-decoration: none; }
    .chip:hover { background: var(--dox-work-surface, #efe6d2); }
    .chip:focus-visible { outline: 2px solid #6b5113; outline-offset: 2px; }
    details { border-top: 1px solid #b9af9d; padding-top: 1rem; margin-top: 2rem; }
    summary { min-height: 44px; cursor: pointer; }
    .selection { border-top: 1px solid #b9af9d; font: 14px/1.5 system-ui, sans-serif; }
    label, input { display: block; margin-bottom: 0.5rem; }
    input { max-width: 100%; min-height: 44px; font: inherit; }
    .identity { color: #5c5347; }
    .error { color: #8c2b20; }
    :is(input, summary):focus-visible { outline: 2px solid #6b5113; outline-offset: 2px; }
</style>
