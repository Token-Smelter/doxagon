<script lang="ts">
    import ImageViewer from './ImageViewer.svelte';
    import ImageGenerationDetails from './ImageGenerationDetails.svelte';
    import { imageUrl, itemUrl, inspectionRequest, type DocumentInspection, type InspectionItem, type InspectionPage } from '$lib/presentation/documentInspection';
    import type { DocumentReady } from '$lib/presentation/documentBridge';
    export let view: DocumentInspection;
    export let tab: string;
    export let currentCue: string | null = null;
    export let ready: DocumentReady | null = null;

    let selected: InspectionItem | null = null;
    let page: InspectionPage | null = null;
    let loading = false;
    let failure = '';
    let request = 0;
    let viewing: string | null = null;
    let copied = false;
    let lastSnapshot = '';
    let lastTab = '';
    let expandedImages = new Set<string>();
    $: images = view.items.filter(item => item.kind === 'image');
    $: allImages = view.items.filter(item => ['image', 'original', 'reference'].includes(item.kind) && ['current', 'observed'].includes(item.status));
    $: viewerItems = allImages.filter(item => item.kind === allImages.find(item => item.id === viewing)?.kind);
    $: sources = view.items.filter(item => !['image', 'original', 'notes'].includes(item.kind));
    $: definitions = view.items.filter(item => ['definition', 'generation_style', 'authoring', 'provenance'].includes(item.kind));
    $: viewerImages = viewerItems.map(item => ({ id: item.id, label: item.label, alt: item.alt ?? '', bytes: item.bytes ?? 0, referenced_by: item.usages ?? [] }));
    $: viewerIndex = viewerItems.findIndex(item => item.id === viewing);
    $: notesMatch = ready && view.notes_metadata && ready.documentId === view.notes_metadata.documentId
        && ready.edition === view.notes_metadata.edition
        && JSON.stringify(ready.cues.map(cue => cue.id)) === JSON.stringify(view.notes_metadata.cues);
    $: if (view.snapshot !== lastSnapshot) {
        lastSnapshot = view.snapshot;
        expandedImages = new Set();
        request += 1;
        selected = null; page = null; viewing = null; failure = ''; loading = false;
        lastTab = '';
    }
    $: if (tab !== lastTab) {
        lastTab = tab;
        if (tab === 'notes' && view.notes) void open(view.notes);
        else { request += 1; selected = null; page = null; failure = ''; loading = false; }
    }
    async function open(item: InspectionItem, offset = 0) {
        const attempt = ++request;
        selected = item; loading = true; failure = ''; page = null;
        try {
            const result = await inspectionRequest<InspectionPage>(`${itemUrl(view, item.id)}&offset=${offset}`);
            if (attempt === request) page = result;
        } catch (error) {
            if (attempt === request) failure = (error as Error).message;
        } finally { if (attempt === request) loading = false; }
    }
    async function copyContext() {
        try {
            await navigator.clipboard.writeText(`dox document context --project ${view.project}\nSelected HTML: ${view.document.path}\nSHA-256: ${view.document.sha256}\nSnapshot: ${view.snapshot}`);
            copied = true;
        } catch { failure = 'Clipboard is unavailable. The context command and file identity are shown below.'; }
    }

    function toggleImage(id: string, event: Event) {
        const next = new Set(expandedImages);
        if ((event.currentTarget as HTMLDetailsElement).open) next.add(id); else next.delete(id);
        expandedImages = next;
    }

    function loadThumbnail(node: HTMLImageElement, url: string) {
        let source = url;
        // Keep every card reachable while only fetching thumbnails near the
        // viewport. The observer also respects the desktop inspector's clipping.
        const observer = new IntersectionObserver(entries => {
            if (!entries.some(entry => entry.isIntersecting)) return;
            node.src = source;
            observer.unobserve(node);
        }, { rootMargin: '200px 0px' });
        observer.observe(node);
        return {
            update(url: string) {
                if (url === source) return;
                source = url;
                node.removeAttribute('src');
                observer.observe(node);
            },
            destroy() { observer.disconnect(); },
        };
    }
</script>

<div class="panel" role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`} data-testid="document-inspector" data-document-keyboard="ignore">
    {#if tab === 'overview'}
        <p class="hint">{view.cues.length} declared cues · {view.usages.length} image placements · {images.length} embedded images</p>
        <h3>{view.title}</h3>
        <p>{view.audience}</p>
        <dl><dt>Rendering</dt><dd>Single-page HTML · {view.document.path}</dd><dt>Preview cue</dt><dd>{currentCue ?? 'Connecting…'}</dd>
            {#each Object.entries(view.links) as [key, value]}<dt>{key}</dt><dd>{value}</dd>{/each}
        </dl>
        <div class="source-catalogue">
            {#each ['source', 'assets', 'notes'] as destination}
                <button type="button" on:click={() => tab = destination}>{destination === 'source' ? 'HTML, CSS and scripts' : destination === 'assets' ? 'Images and generation styles' : 'Private notes'}</button>
            {/each}
        </div>
        <details><summary>Inspection checks · {view.coverage} coverage</summary>
            <ul>{#each view.checks as check}<li><strong>{check.code}</strong>: {check.message}</li>{/each}</ul>
            <p>HTML SHA-256 <code>{view.document.sha256}</code></p>
            <p>Snapshot <code>{view.snapshot}</code></p>
        </details>
        <button type="button" on:click={copyContext}>{copied ? 'Copied agent context' : 'Copy agent context'}</button>
        <p class="hint"><code>dox document context --project {view.project}</code></p>
    {:else if tab === 'source'}
        <h3>Document source</h3>
        <p class="hint">Select a file or inline block. Text is paged and embedded image bytes are omitted.</p>
        <div class="source-catalogue">
            {#each sources as item}<button type="button" aria-pressed={selected?.id === item.id} on:click={() => open(item)}><strong>{item.kind}: {item.label}</strong><code>{item.path ?? item.id}</code></button>{/each}
        </div>
    {:else if tab === 'assets'}
        <h3>Images and generation styles</h3>
        <p class="hint">Originals are linked only when the recorded hashes can be checked. An unknown generation history does not prevent playback.</p>
    {:else if tab === 'notes'}
        <h3>Private companion notes</h3>
        <p class="hint">Notes are loaded only when this panel or Speaker notes is opened. The player validates the companion against its document, edition and cue order.</p>
        {#if !view.notes}<p>No companion notes are selected.</p>{/if}
        {#if ready}<p class="hint">Playing {ready.documentId} · edition {ready.edition}</p>{/if}
        {#if ready && view.notes}<p role="status">{notesMatch ? 'Notes match the loaded document, edition and cue order.' : 'Notes do not match the loaded document, edition and cue order.'}</p>{/if}
    {:else if tab === 'groups'}
        <h3>Sections and cues</h3>
        <ul>{#each view.sections as section}<li>{section.title} · line {section.line}</li>{/each}</ul>
        <p class="hint">{ready?.cues.length ?? 0} cues verified by the player; {view.cues.length} declared in HTML.</p>
        <ol>{#each view.cues as cue}<li>{cue.title} · <code>{cue.id}</code> · line {cue.line}</li>{/each}</ol>
    {/if}

    {#if tab === 'overview' || tab === 'assets'}
        <h3>All presentation images</h3>
        <ul class="overview-gallery">
            {#each images as item (item.id)}
                <li class:expanded={expandedImages.has(item.id)}>
                    <button type="button" class="image-open" aria-label={`View ${item.label}`} title={`View ${item.label}`} on:click={() => { viewing = item.id; }}>
                        <img use:loadThumbnail={imageUrl(view, item.id, true)} alt={item.alt || item.label} decoding="async" on:error={() => failure = 'An image is unavailable. Refresh the document to check its current revision.'} />
                    </button>
                    <strong>{item.label}</strong><small>{item.width} × {item.height} · {item.usages?.length ?? 0} placement(s)</small>
                    <small>{item.provenance?.replaceAll('_', ' ')}</small>
                    <details on:toggle={event => toggleImage(item.id, event)}><summary>Image details and generation</summary>
                        {#if expandedImages.has(item.id)}<ImageGenerationDetails {view} imageId={item.id} />{/if}
                        <p>Embedded SHA-256 <code>{item.sha256}</code></p>
                        <ul>{#each view.usages.filter(usage => usage.image === item.id) as usage}<li><code>{usage.id}</code> · {usage.section ?? 'document'} · line {usage.line}{usage.stable ? '' : ' · observed position; no stable slot ID'}</li>{/each}</ul>
                        {#if item.original}
                            {@const original = view.items.find(source => source.id === item.original)}
                            <p><code>{original?.path}</code> · {original?.status}</p>
                            {#if original?.status === 'current'}<button type="button" on:click={() => { viewing = original.id; }}>View original</button>{/if}
                        {/if}
                    </details>
                </li>
            {:else}<li>No embedded raster images found.</li>{/each}
        </ul>
    {/if}
    {#if tab === 'assets'}
        {#if view.authoring?.assets.length}
            <h3>Registered assets and candidates</h3>
            <p class="hint">Validation: {view.authoring.validation}. Candidates remain separate from the images embedded in the page.</p>
            {#each view.authoring.assets as asset}
                <details><summary>{asset.label} · {asset.usages.length ? `${asset.usages.length} registered placements` : 'Unused asset'}</summary>
                    <p><code>{asset.key}</code> · {asset.dialect}</p>
                    {#if asset.definition}
                        {@const item = view.items.find(item => item.id === asset.definition)}
                        {#if item}<button type="button" on:click={() => open(item)}>Inspect definition</button>{/if}
                    {/if}
                    {#each asset.variants as variant}
                        <p><code>{variant.id}</code> · {variant.status} · {variant.provenance}</p>
                        <p class="hint">Current definition: {variant.current_definition.replaceAll('_', ' ')}{variant.generated_with ? ` · Generated with ${variant.generated_with.provider} / ${variant.generated_with.model}` : ''}</p>
                        {#if variant.image && variant.status === 'current'}<button type="button" on:click={() => { viewing = variant.image; }}>View candidate</button>{/if}
                        {#if variant.receipt}
                            {@const receipt = view.items.find(item => item.id === variant.receipt)}
                            {#if receipt}<button type="button" on:click={() => open(receipt)}>Inspect receipt</button>{/if}
                        {/if}
                    {/each}
                </details>
            {/each}
        {/if}
        {#if view.usages.some(usage => !usage.image)}
            <h3>Unresolved image placements</h3>
            <ul>{#each view.usages.filter(usage => !usage.image) as usage}<li>{usage.alt || usage.id} · line {usage.line} · embedded raster unavailable; inspect the document source</li>{/each}</ul>
        {/if}
        <h3>Definitions, styles and provenance</h3>
        <div class="source-catalogue">{#each definitions as item}<button type="button" on:click={() => open(item)}><strong>{item.kind}: {item.label}</strong><code>{item.path}</code></button>{/each}</div>
    {/if}
    {#if loading}<p role="status">Loading source…</p>{/if}
    {#if failure}<p role="alert">{failure}</p>{/if}
    {#if selected && page}
        <h3>{selected.label}</h3>
        <p class="hint">{selected.path ?? selected.kind} · {selected.status}</p>
        {#if selected.dependencies?.length}<p>Ordered dependencies: {selected.dependencies.join(' → ')}</p>{/if}
        {#if selected.references?.length}
            <details><summary>Reference inputs ({selected.references.length})</summary>
                <ul>{#each selected.references as reference}
                    {@const item = view.items.find(item => item.id === reference)}
                    <li><code>{item?.path}</code> · {item?.status}
                        {#if item?.status === 'current'}<a href={imageUrl(view, item.id)} download={item.label}>Open reference image</a>{/if}
                    </li>
                {/each}</ul>
            </details>
        {/if}
        <pre role="region" tabindex="0" aria-label={tab === 'notes' ? 'Private notes source' : 'Read-only source'}>{page.text ?? ''}</pre>
        <div class="pager">
            <button type="button" disabled={!page.offset} on:click={() => selected && open(selected, Math.max(0, (page?.offset ?? 0)-16000))}>Previous source page</button>
            <span>{page.offset ?? 0} / {page.total ?? 0} characters</span>
            <button type="button" disabled={page.next == null} on:click={() => selected && page?.next != null && open(selected, page.next)}>Next source page</button>
        </div>
    {/if}
</div>

{#if viewerIndex >= 0}
    <ImageViewer images={viewerImages} index={viewerIndex} urlFor={(id) => imageUrl(view, id)} originalUrlFor={(id) => { const original = allImages.find(item => item.id === id)?.original; return original && allImages.some(item => item.id === original && item.status === 'current') ? imageUrl(view, original) : null; }} downloadLabel={viewerItems[viewerIndex]?.kind !== 'image' ? 'Download original' : 'Download embedded image'} on:close={() => viewing = null}>
        <svelte:fragment slot="details" let:imageId><ImageGenerationDetails {view} {imageId} /></svelte:fragment>
    </ImageViewer>
{/if}

<style>
    .panel { font-size: 0.875rem; line-height: 1.55; min-width: 0; }
    h3 { font-family: var(--dox-font-display); font-size: 1.05rem; margin: 1rem 0 0.5rem; }
    .hint, small { color: var(--dox-frame-text-muted); }
    button { color: var(--dox-frame-text); background: var(--dox-frame-surface); border: 1px solid var(--dox-frame-rule); border-radius: 5px; padding: 0.5rem 0.75rem; min-height: 36px; font: inherit; cursor: pointer; }
    button:disabled { opacity: 0.45; cursor: default; }
    :is(button, pre, summary):focus-visible { outline: 2px solid var(--dox-frame-text); outline-offset: 2px; }
    code, dd, p, li { overflow-wrap: anywhere; }
    dl { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 0.3rem 0.75rem; } dd { margin: 0; }
    details { margin-block: 0.5rem; } summary { cursor: pointer; }
    .source-catalogue { display: grid; gap: 0.4rem; }
    .source-catalogue button { text-align: left; } .source-catalogue code { display: block; font-size: 0.75rem; }
    .overview-gallery { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 220px), 1fr)); gap: 0.9rem; list-style: none; padding: 0; }
    .overview-gallery li { min-width: 0; } strong, small { display: block; }
    .overview-gallery li.expanded { grid-column: 1 / -1; }
    .image-open { width: 100%; padding: 0; border: 0; background: transparent; cursor: zoom-in; }
    .image-open img { width: 100%; height: 160px; object-fit: contain; background: var(--dox-frame-ground); }
    pre { max-height: 32rem; overflow: auto; padding: 0.75rem; border: 1px solid var(--dox-frame-rule); white-space: pre-wrap; overflow-wrap: anywhere; font-size: 0.8rem; }
    .pager { display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; }
    @media (max-width: 1023px) { button { min-height: 44px; } }
</style>
