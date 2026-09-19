<script lang="ts">
    import { createEventDispatcher, onDestroy, onMount, tick } from 'svelte';
    import DocumentControls from './DocumentControls.svelte';
    import DocumentNotes from './DocumentNotes.svelte';
    import { DocumentBridge, type DocumentPosition, type DocumentReady } from '$lib/presentation/documentBridge';
    import { documentKeys } from '$lib/presentation/documentKeys';
    import { documentDigest } from '$lib/presentation/documentDigest';
    import type { AuthoredDocument } from '$lib/presentation/authoredDocument';

    export let source: AuthoredDocument | null = null;
    export let embedded = false;
    export let viewportWidth = 0;
    export let viewportHeight = 0;
    const dispatch = createEventDispatcher<{ state: { ready: DocumentReady | null; position: DocumentPosition | null; connected: boolean; presenting: boolean } }>();
    let restoreCue: string | null = null;
    let notesSource: string | null = null;
    const bridge = new DocumentBridge();
    let frame: HTMLIFrameElement;
    let bytes: ArrayBuffer | null = null;
    let renderUrl: string | null = null;
    let downloadComplete = false;
    let connecting = false;
    let filename = '';
    let digest = '';
    let selection = 0;
    let loading = false;
    let ready: DocumentReady | null = null;
    let position: DocumentPosition | null = null;
    let connected = false;
    let failure = '';
    let popupFailure = '';
    let deadline: ReturnType<typeof setTimeout> | null = null;
    let popup: Window | null = null;
    let notes: DocumentNotes | null = null;
    let popupPoll: ReturnType<typeof setInterval> | null = null;
    let presenting = false;
    let mounted = false;

    function clearDeadline() {
        if (deadline !== null) clearTimeout(deadline);
        deadline = null;
    }

    function closeNotes() {
        const cue = presenting ? position?.cue : null;
        if (popupPoll !== null) clearInterval(popupPoll);
        popupPoll = null;
        notes?.$destroy();
        notes = null;
        popup?.close();
        popup = null;
        presenting = false;
        if (cue) void restoreAfterResize(cue);
    }

    function onEscape(event: KeyboardEvent) {
        if (event.key === 'Escape' && presenting) closeNotes();
    }

    export function present() {
        if (!connected) return;
        const cue = position?.cue;
        openNotes();
        presenting = true;
        if (cue) void restoreAfterResize(cue);
    }

    async function restoreAfterResize(cue: string) {
        await tick();
        // Restoring a cue is not navigation: animation from the old viewport's
        // scroll offset can publish unrelated cues while the layout settles.
        if (connected) bridge.go(cue, true);
    }

    function measureViewport(node: HTMLElement) {
        const observer = new ResizeObserver(() => {
            viewportWidth = node.clientWidth;
            viewportHeight = node.clientHeight;
        });
        observer.observe(node);
        return { destroy: () => observer.disconnect() };
    }

    export function reloadDocument(selected: AuthoredDocument, cue: string | null = null) {
        if (presenting) return;
        source = selected;
        restoreCue = cue;
        void openSource(selected);
    }

    onMount(() => {
        mounted = true;
        if (source) void openSource(source);
        const removeKeys = documentKeys(window, navigate);
        // Component teardown does not run when the browser unloads the page.
        window.addEventListener('pagehide', closeNotes);
        window.addEventListener('keydown', onEscape);
        window.addEventListener('message', documentAvailable);
        return () => {
            removeKeys();
            window.removeEventListener('pagehide', closeNotes);
            window.removeEventListener('keydown', onEscape);
            window.removeEventListener('message', documentAvailable);
        };
    });
    onDestroy(() => {
        selection += 1;
        bridge.dispose();
        clearDeadline();
        closeNotes();
    });

    function reject(reason: string) {
        clearDeadline();
        bridge.dispose();
        connected = false;
        connecting = false;
        loading = false;
        failure = reason;
    }

    async function openSource(selected: AuthoredDocument) {
        const request = ++selection;
        loading = true;
        failure = '';
        if (selected.renderUrl) {
            bridge.dispose();
            clearDeadline();
            closeNotes();
            bytes = null;
            ready = null;
            position = null;
            connected = false;
            connecting = false;
            downloadComplete = false;
            notesSource = selected.notesUrl;
            filename = selected.filename;
            digest = selected.sha256;
            renderUrl = selected.renderUrl;
            return;
        }
        try {
            const response = await fetch(selected.url, { cache: 'no-store' });
            if (!response.ok) throw new Error('The saved HTML could not be loaded. Reload the presentation to try again.');
            const content = await response.arrayBuffer();
            if (request !== selection) return;
            await loadDocument(new File([content], selected.filename), selected.sha256, selected.notesUrl);
        } catch (error) {
            if (request === selection) reject(error instanceof Error ? error.message : 'The saved document could not be opened.');
        }
    }

    async function selectDocument(event: Event) {
        const file = (event.currentTarget as HTMLInputElement).files?.[0];
        if (file) await loadDocument(file);
    }

    async function loadDocument(file: File, expectedDigest?: string, companion: string | null = null) {
        const attempt = ++selection;
        bridge.dispose();
        clearDeadline();
        closeNotes();
        notesSource = companion;
        bytes = null;
        renderUrl = null;
        downloadComplete = false;
        connecting = false;
        ready = null;
        position = null;
        connected = false;
        failure = '';
        popupFailure = '';
        digest = '';
        filename = file.name;
        loading = true;
        try {
            if (!/\.html?$/i.test(file.name) || file.size === 0 || file.size > 32 * 1024 * 1024) {
                throw new Error('Choose a self-contained HTML document between 1 byte and 32 MB.');
            }
            const content = await file.arrayBuffer();
            const hash = await documentDigest(content);
            if (attempt !== selection) return;
            digest = hash;
            if (expectedDigest && digest !== expectedDigest) throw new Error('The saved document changed while opening. Reload the presentation to use its current version.');
            bytes = content;
        } catch (error) {
            if (attempt === selection) reject(error instanceof Error ? error.message : 'The document could not be read.');
        }
    }

    function documentAvailable(event: MessageEvent) {
        // This window message only invites a port. State still goes through the
        // bounded bridge validator, never through arbitrary window messages.
        if (!renderUrl || event.source !== frame?.contentWindow || event.data?.type !== 'doxagon:available'
            || connecting || connected || failure) return;
        connect();
    }

    function connect() {
        if (!frame?.contentWindow || (!bytes && !renderUrl)) return;
        connecting = true;
        connected = false;
        loading = true;
        failure = '';
        clearDeadline();
        bridge.connect(frame.contentWindow, {
            ready: (message) => { ready = message; },
            position: (message) => {
                position = message;
                connected = true;
                connecting = false;
                loading = false;
                clearDeadline();
                if (restoreCue) {
                    const cue = restoreCue;
                    restoreCue = null;
                    if (ready?.cues.some(item => item.id === cue)) bridge.go(cue, true);
                }
            },
            rejected: reject,
        }, ready);
        deadline = setTimeout(() => reject('No compatible document bridge responded. Choose a compatible HTML file, or try Reconnect.'), 8000);
    }

    function loadFrame() {
        if (renderUrl) {
            downloadComplete = true;
            // Older self-contained documents announce only after load. An early
            // connection must keep its port, position and notes when load finishes.
            if (!connecting && !connected && !failure) connect();
            return;
        }
        if (!bytes || !frame?.contentWindow) return;
        const content = bytes.slice(0);
        frame.contentWindow.postMessage({ type: 'doxagon:document', bytes: content }, '*', [content]);
        connect();
    }

    function navigate(action: 'next' | 'previous' | 'first' | 'last') {
        if (!connected || !ready) return;
        if (action === 'first') bridge.go(ready.cues[0].id);
        else if (action === 'last') bridge.go(ready.cues[ready.cues.length - 1].id);
        else bridge.send(action);
    }

    export function go(cue: string) {
        if (connected) bridge.go(cue);
    }

    function openNotes() {
        if (!ready) return;
        if (popup && !popup.closed) { popup.focus(); return; }
        closeNotes();
        // Only trusted app code enters this window. The authored sandbox gets
        // neither a popup permission nor a reference to the private notes.
        popup = window.open('', '_blank', 'popup,width=720,height=820');
        if (!popup) {
            popupFailure = 'Speaker notes were blocked. Allow pop-ups for this Doxagon URL, then click Speaker notes again.';
            return;
        }
        popup.opener = null;
        popup.document.title = 'Speaker notes · Doxagon';
        popup.document.documentElement.lang = 'en';
        const viewport = popup.document.createElement('meta');
        viewport.name = 'viewport';
        viewport.content = 'width=device-width, initial-scale=1';
        popup.document.head.append(viewport);
        // Production Svelte styles are extracted into app stylesheets rather
        // than injected at component mount. Copy only trusted host styles.
        for (const style of document.head.querySelectorAll('style, link[rel="stylesheet"]')) {
            popup.document.head.append(style.cloneNode(true));
        }
        notes = new DocumentNotes({ target: popup.document.body, props: { ready, position, connected, popup, navigate, go, sourceUrl: notesSource, endPresentation: closeNotes } });
        popupFailure = '';
        popupPoll = setInterval(() => { if (popup?.closed) closeNotes(); }, 500);
        popup.focus();
    }

    $: if (notes && ready) notes.$set({ ready, position, connected });
    $: dispatch('state', { ready, position, connected, presenting });
</script>

<main class="document-player" class:presenting class:embedded aria-label={presenting ? 'Audience display' : 'Document player'} data-testid={presenting ? 'authored-audience' : 'authored-player'}>
    {#if !embedded}
    <header class="player-head">
        <div class="title"><h1>{source ? source.filename : 'Document player'}</h1><a href="/presentations">Back to presentations</a></div>
        {#if !source}
            <div class="file-control"><label for="document-file">Open local HTML</label><input id="document-file" type="file" accept="text/html,.html,.htm" data-ready={mounted} on:change={selectDocument} /></div>
        {/if}
        <button type="button" disabled={!connected} on:click={present}>Present</button>
        <button type="button" disabled={!ready} on:click={openNotes}>Speaker notes</button>
    </header>
    {/if}

    {#if presenting}
        <aside class="audience-tools" aria-label="Presentation controls">
            <button type="button" on:click={closeNotes}>Exit presentation</button>
            {#if popupFailure}
                <p role="alert">{popupFailure}</p>
                <button type="button" on:click={present}>Open speaker notes</button>
            {/if}
        </aside>
    {/if}

    {#if bytes || renderUrl}
        <section class="stage" aria-label="Loaded document" use:measureViewport>
            {#key selection}
                <iframe bind:this={frame} src={renderUrl ?? '/document-host.html'} title="Isolated document player" sandbox="allow-scripts" allow="fullscreen" referrerpolicy="no-referrer" on:load={loadFrame}></iframe>
            {/key}
        </section>
    {:else if source}
        <section class="empty" aria-label="Saved presentation">
            <h2>{failure ? 'Could not open the saved presentation' : 'Opening the saved presentation…'}</h2>
            <p>{source.filename}</p>
            {#if failure}
                <p>The saved HTML could not be loaded. Retry without changing the document or selecting another file.</p>
                <button type="button" on:click={() => source && openSource(source)}>Retry opening</button>
            {:else}
                <p role="status">Loading and checking the document. Navigation and speaker notes will be available when it opens.</p>
            {/if}
        </section>
    {:else}
        <section class="empty" aria-label="Open a document">
            <h2>One document. Uninterrupted.</h2>
            <p>Choose a self-contained HTML presentation with a Doxagon document bridge. Its own scrolling and animations stay in charge; cues give you places to go.</p>
            <p>Files stay in this browser. Open <strong>Speaker notes</strong> afterward to select the matching companion notes.json in a separate window.</p>
            <p class="hint">No upload, conversion or vault changes. Ordinary Step presentations remain in the presentation workspace.</p>
        </section>
    {/if}

    <footer>
        <DocumentControls {ready} {position} {connected} on:next={() => navigate('next')} on:previous={() => navigate('previous')} on:go={(event) => go(event.detail)} />
        <div class="status-line">
            <span role="status">{loading ? 'Opening document…' : connected ? (renderUrl && !downloadComplete ? 'Controls ready · remaining images are downloading…' : 'Connected · scroll freely inside the document') : failure ? 'Document unavailable' : source ? 'Waiting for the saved document' : 'Select a compatible document to begin'}</span>
            {#if bytes || renderUrl}<button type="button" on:click={connect}>Reconnect</button>{/if}
            {#if embedded}<button type="button" disabled={!ready} on:click={openNotes}>Speaker notes</button>{/if}
            {#if renderUrl && failure}<button type="button" on:click={() => window.location.reload()}>Reload saved presentation</button>{/if}
            {#if digest}<details><summary>File identity</summary><p>{filename}<br />{renderUrl ? 'Server-verified' : 'Browser-verified'} SHA-256 {digest}<br />{ready ? `${ready.documentId} · edition ${ready.edition}` : 'Identity not established'}</p></details>{/if}
        </div>
        {#if failure}<p class="error" role="alert">{failure}</p>{/if}
        {#if popupFailure && !presenting}<p class="error" role="alert">{popupFailure}</p>{/if}
        <p class="hint">Arrows / Space navigate when controls are not focused. Use the Doxagon Speaker notes button; document-owned pop-ups are isolated. Reduced motion follows your browser setting.</p>
    </footer>
</main>

<style>
    .document-player { display: flex; flex-direction: column; height: 100%; min-height: 0; min-width: 0; color: var(--dox-frame-text); background: var(--dox-frame-ground); }
    .embedded:not(.presenting) { height: auto; }
    .embedded:not(.presenting) > .stage { flex: none; width: 100%; aspect-ratio: 16 / 9; min-height: 0; }
    .embedded footer > .hint { display: none; }
    .presenting { position: fixed; inset: 0; z-index: var(--z-modal, 900); }
    .presenting > .player-head, .presenting > footer { display: none; }
    .audience-tools { position: absolute; top: 0.25rem; right: 0.5rem; z-index: 1; max-width: min(32rem, calc(100% - 1rem)); }
    .audience-tools p { padding: 0.75rem; background: var(--dox-frame-ground); font-size: 0.9rem; }
    .player-head { display: flex; flex-wrap: wrap; align-items: center; gap: 0.75rem 1.5rem; padding: 0.75rem 1rem; border-bottom: 1px solid var(--dox-frame-rule); }
    .title { flex: 1; }
    h1 { margin: 0; font-size: 1.1rem; }
    a { color: var(--dox-frame-text-muted); font-size: 0.8rem; }
    .file-control { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; font-size: 0.8rem; }
    input { max-width: 17rem; min-width: 0; min-height: 44px; padding-block: 0.5rem; font: inherit; }
    button { min-height: 44px; padding: 0.5rem 0.75rem; color: var(--dox-frame-text); border: 1px solid var(--dox-frame-rule); border-radius: 4px; background: var(--dox-frame-surface); font: inherit; font-size: 0.85rem; }
    button:not(:disabled) { cursor: pointer; }
    button:hover:not(:disabled) { background: var(--dox-frame-surface-raised); }
    button:disabled { opacity: 0.5; }
    :is(button, input, a, summary):focus-visible { outline: 2px solid var(--dox-frame-text); outline-offset: 2px; }
    .stage { flex: 1; min-height: 16rem; min-width: 0; position: relative; background: white; }
    iframe { position: absolute; inset: 0; height: 100%; width: 100%; border: 0; }
    .empty { flex: 1; min-height: 15rem; overflow: auto; align-content: center; padding: 2rem; }
    .empty h2 { font-size: 2rem; text-wrap: balance; margin-block: 0 1rem; }
    .empty p { max-width: 64ch; font-family: var(--dox-font-body); font-size: 1.15rem; line-height: 1.5; }
    footer { flex: none; padding: 0.65rem 1rem; border-top: 1px solid var(--dox-frame-rule); }
    .status-line { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem 1rem; font-size: 0.8rem; margin-top: 0.35rem; }
    .status-line > span { flex: 1; }
    summary { cursor: pointer; padding-block: 0.5rem; }
    details p { overflow-wrap: anywhere; max-width: 70ch; }
    .hint { margin: 0.4rem 0 0; color: var(--dox-frame-text-muted); font-size: 0.75rem; }
    .error { color: #ffb4a8; margin: 0.5rem 0; font-size: 0.9rem; }
    @media (max-width: 600px) {
        .player-head { gap: 0.4rem; padding: 0.5rem; }
        .title { min-width: 100%; }
        .file-control { flex: 1; }
        input { width: 11rem; }
        footer { padding: 0.5rem; }
        footer > .hint { display: none; }
        .empty { padding: 1rem; }
    }
</style>
