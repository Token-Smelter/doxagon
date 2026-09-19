<script lang="ts">
    /**
     * In-app viewer for one presentation's images.
     *
     * A native dialog rather than a new tab: it keeps the editor's state, its
     * focus, and its session intact, and it lets a person step through every
     * image in the deck without leaving the workspace. Nothing here mutates the
     * deck; the viewer reads the same revision-pinned content endpoint the
     * galleries render from.
     */
    import { createEventDispatcher } from 'svelte';
    import type { AssetView } from '$lib/presentation/deck';

    export let images: Pick<AssetView, 'id' | 'label' | 'alt' | 'bytes' | 'referenced_by'>[] = [];
    export let index = 0;
    export let urlFor: (assetId: string) => string;
    export let downloadLabel = 'Download original';
    export let originalUrlFor: ((assetId: string) => string | null) | null = null;

    const dispatch = createEventDispatcher<{ close: void }>();

    let dialog: HTMLDialogElement;
    let loaded = false;
    let natural = { width: 0, height: 0 };
    let zoom = 0;
    let comparing = false;
    let error = '';

    $: image = images[index] ?? null;
    $: if (image) { loaded = false; zoom = 0; error = ''; }
    $: originalUrl = image && originalUrlFor ? originalUrlFor(image.id) : null;
    $: if (dialog && !dialog.open) dialog.showModal();

    function step(delta: number) {
        if (images.length === 0) return;
        index = (index + delta + images.length) % images.length;
    }

    function onKeydown(event: KeyboardEvent) {
        if ((event.target as HTMLElement).closest('[data-image-keyboard="ignore"]')) return;
        if (event.key === 'ArrowRight') { event.preventDefault(); step(1); }
        else if (event.key === 'ArrowLeft') { event.preventDefault(); step(-1); }
    }

    function onLoad(event: Event) {
        const node = event.currentTarget as HTMLImageElement;
        natural = { width: node.naturalWidth, height: node.naturalHeight };
        loaded = true;
    }

    const kilobytes = (bytes: number) => bytes >= 1024 * 1024
        ? `${(bytes / (1024 * 1024)).toFixed(1)} MB`
        : `${Math.max(1, Math.round(bytes / 1024))} KB`;
</script>

<!-- svelte-ignore a11y-no-noninteractive-element-interactions -->
<dialog
    class="viewer"
    bind:this={dialog}
    aria-label="Image viewer"
    data-testid="image-viewer"
    on:close={() => dispatch('close')}
    on:keydown={onKeydown}
    on:click={(event) => { if (event.target === dialog) dialog.close(); }}
>
    {#if image}
        <div class="viewer-body">
            <header class="viewer-head">
                <div class="viewer-title">
                    <h2>{image.label}</h2>
                    <p class="viewer-position" data-testid="image-viewer-position">{index + 1} of {images.length}</p>
                </div>
                <button type="button" class="viewer-close" data-testid="image-viewer-close" on:click={() => dialog.close()}>Close</button>
            </header>
            <div class="viewer-tools" aria-label="Image view controls">
                <button type="button" on:click={() => zoom = 0} aria-pressed={zoom === 0}>Fit</button>
                <button type="button" on:click={() => zoom = 1} aria-pressed={zoom === 1}>Actual pixels</button>
                <button type="button" aria-label="Zoom out" on:click={() => zoom = Math.max(0.25, (zoom || 1) / 1.5)}>−</button>
                <button type="button" aria-label="Zoom in" on:click={() => zoom = Math.min(8, (zoom || 1) * 1.5)}>+</button>
                <span aria-live="polite">{zoom ? `${Math.round(zoom * 100)}%` : 'Fit to window'}</span>
                {#if originalUrl}<button type="button" aria-pressed={comparing} on:click={() => comparing = !comparing}>Compare original</button>{/if}
            </div>
            <div class="viewer-content" class:with-details={!!$$slots.details}>
            <div class="viewer-stage">
                <button type="button" class="viewer-step" aria-label="Previous image" disabled={images.length < 2} on:click={() => step(-1)}>‹</button>
                <div class="viewer-panes" class:comparing={comparing && !!originalUrl}>
                <div class="image-pane" class:zoomed={zoom > 0}>
                {#key image.id}
                    <img
                        class="viewer-image"
                        class:is-loaded={loaded}
                        src={urlFor(image.id)}
                        alt={image.alt || image.label}
                        data-testid="image-viewer-image"
                        style:width={zoom ? `${natural.width * zoom}px` : undefined}
                        on:load={onLoad}
                        on:error={() => error = 'This image is unavailable at the inspected revision. Refresh the workspace.'}
                    />
                {/key}
                </div>
                {#if comparing && originalUrl}
                    <figure class="image-pane"><figcaption>Original</figcaption><img class="comparison-image" src={originalUrl} alt={`Original: ${image.alt || image.label}`} /></figure>
                {/if}
                </div>
                {#if error}<p class="viewer-loading" role="alert">{error}</p>
                {:else if !loaded}
                    <p class="viewer-loading" role="status">Loading…</p>
                {/if}
                <button type="button" class="viewer-step" aria-label="Next image" disabled={images.length < 2} on:click={() => step(1)}>›</button>
            </div>
            {#if $$slots.details}<aside class="generation-details" aria-label="Generation details" data-image-keyboard="ignore"><slot name="details" imageId={image.id} /></aside>{/if}
            </div>
            <footer class="viewer-foot">
                <dl class="viewer-meta">
                    <dt>Alt text</dt><dd>{image.alt ?? 'none'}</dd>
                    <dt>Size</dt><dd>{loaded ? `${natural.width} × ${natural.height} px · ` : ''}{kilobytes(image.bytes)}</dd>
                    <dt>Used by</dt><dd>{image.referenced_by.length ? image.referenced_by.join(', ') : 'No registered usage'}</dd>
                </dl>
                <a class="viewer-download" href={urlFor(image.id)} download={image.label}>{downloadLabel}</a>
            </footer>
        </div>
    {/if}
</dialog>

<style>
    /* A modal dialog lives in the top layer, so its containing block is the
       viewport itself; `inset` and percentage sizes measure that box without
       naming a viewport unit, and the body is then sized against the dialog. */
    .viewer {
        inset: 2%;
        width: min(96%, 1400px);
        height: 96%;
        max-width: none;
        max-height: none;
        margin: auto;
        padding: 0;
        overflow: hidden;
        border: 1px solid var(--dox-frame-rule, currentColor);
        border-radius: 8px;
        color: var(--dox-frame-text);
        background: var(--dox-frame-ground);
        box-sizing: border-box;
    }

    .viewer::backdrop { background: color-mix(in srgb, var(--dox-brand-nigredo, #0b0b0d) 82%, transparent); }

    .viewer-body {
        display: grid;
        grid-template-rows: auto auto minmax(0, 1fr) auto;
        gap: 0.75rem;
        height: 100%;
        padding: 1rem;
        box-sizing: border-box;
    }

    .viewer-head, .viewer-foot { display: flex; flex-wrap: wrap; gap: 0.75rem; align-items: center; justify-content: space-between; }
    .viewer-title { display: flex; flex-wrap: wrap; gap: 0.25rem 0.75rem; align-items: baseline; min-width: 0; }
    .viewer-title h2 { margin: 0; font-family: var(--dox-font-display); font-size: 1.05rem; overflow-wrap: anywhere; }
    .viewer-position { margin: 0; font-family: var(--dox-font-mono); font-size: 0.75rem; color: var(--dox-frame-text-muted); }

    .viewer-stage {
        position: relative;
        display: grid;
        grid-template-columns: auto minmax(0, 1fr) auto;
        gap: 0.5rem;
        align-items: center;
        min-height: 0;
    }
    .viewer-content { min-height: 0; min-width: 0; display: grid; }
    .viewer-content.with-details { grid-template-columns: minmax(0, 3fr) minmax(300px, 2fr); gap: 1rem; }
    .generation-details { min-height: 0; overflow: auto; border-left: 1px solid var(--dox-frame-rule); padding-left: 1rem; }

    .viewer-loading {
        position: absolute;
        inset: 50% auto auto 50%;
        transform: translate(-50%, -50%);
        margin: 0;
        font-family: var(--dox-font-mono);
        font-size: 0.8rem;
        color: var(--dox-frame-text-muted);
    }

    .viewer-image {
        justify-self: center;
        max-width: 100%;
        max-height: 100%;
        object-fit: contain;
        background: #fff;
        border-radius: 4px;
        opacity: 0;
        transition: opacity 180ms ease-out;
    }

    .viewer-image.is-loaded { opacity: 1; }
    .viewer-tools { display: flex; flex-wrap: wrap; gap: 0.4rem; }
    .viewer-panes { height: 100%; min-height: 0; min-width: 0; display: grid; grid-template-columns: minmax(0, 1fr); gap: 0.75rem; }
    .viewer-panes.comparing { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .image-pane { display: grid; place-items: center; min-width: 0; min-height: 0; margin: 0; overflow: auto; }
    .image-pane.zoomed { display: block; }
    .image-pane.zoomed img { max-width: none; max-height: none; }
    .comparison-image { max-width: 100%; max-height: 100%; object-fit: contain; }
    figcaption { font-size: 0.8rem; }

    .viewer button, .viewer-download {
        min-height: 44px;
        padding: 0 0.85rem;
        display: inline-flex;
        align-items: center;
        color: var(--dox-frame-text);
        background: color-mix(in srgb, var(--dox-frame-text) 10%, var(--dox-frame-ground));
        border: 1px solid color-mix(in srgb, var(--dox-frame-text) 45%, var(--dox-frame-ground));
        border-radius: 6px;
        font: inherit;
        font-weight: 600;
        text-decoration: none;
        cursor: pointer;
    }

    .viewer-step { min-width: 44px; font-size: 1.5rem; line-height: 1; justify-content: center; }
    .viewer button:disabled { opacity: 0.4; cursor: default; }
    .viewer button:hover:not(:disabled), .viewer-download:hover { border-color: var(--dox-frame-text); }
    .viewer button:focus-visible, .viewer-download:focus-visible { outline: 2px solid var(--dox-frame-text); outline-offset: 1px; }

    .viewer-meta {
        display: grid;
        grid-template-columns: auto minmax(0, 1fr);
        gap: 0.15rem 0.6rem;
        margin: 0;
        font-size: 0.8rem;
        min-width: 0;
    }

    .viewer-meta dt { color: var(--dox-frame-text-muted); }
    .viewer-meta dd { margin: 0; overflow-wrap: anywhere; }

    @media (prefers-reduced-motion: reduce) {
        .viewer-image { transition: none; }
    }

    @media (max-width: 720px) {
        .viewer-content.with-details { grid-template-columns: minmax(0, 1fr); grid-template-rows: minmax(160px, 1fr) minmax(0, 1fr); }
        .generation-details { border-left: 0; border-top: 1px solid var(--dox-frame-rule); padding: 0.75rem 0 0; }
        .viewer { inset: 0; width: 100%; height: 100%; border: 0; border-radius: 0; }
        .viewer-body { padding: 0.75rem; }
        .viewer-stage { grid-template-columns: minmax(0, 1fr); }
        .viewer-panes.comparing { grid-template-columns: minmax(0, 1fr); grid-template-rows: repeat(2, minmax(0, 1fr)); }
        /* Over the image edges rather than beside it: a narrow screen has no
           width to spare, and a touch user still needs a way to step. */
        .viewer .viewer-step {
            position: absolute;
            top: 50%;
            transform: translateY(-50%);
            background: color-mix(in srgb, var(--dox-frame-ground) 78%, transparent);
        }
        .viewer .viewer-step:first-child { left: 0.25rem; }
        .viewer .viewer-step:last-child { right: 0.25rem; }
    }
</style>
