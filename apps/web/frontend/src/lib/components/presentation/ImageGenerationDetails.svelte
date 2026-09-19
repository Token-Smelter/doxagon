<script lang="ts">
    import { inspectionRequest, itemUrl, imageUrl, type DocumentInspection, type InspectionPage, type ImageGeneration } from '$lib/presentation/documentInspection';
    import InspectionText from './InspectionText.svelte';
    export let view: DocumentInspection;
    export let imageId: string;
    let generation: ImageGeneration | null = null;
    let failure = '';
    let request = 0;
    let expanded = new Set<string>();
    $: if (view && imageId) void load(view, imageId);
    const item = (id: string) => view.items.find(item => item.id === id);
    const settings = (value: Record<string, unknown>) => Object.entries(value).map(([key, value]) => `${key.replaceAll('_', ' ')}: ${String(value)}`).join(' · ');
    function toggle(key: string, event: Event) {
        const next = new Set(expanded);
        if ((event.currentTarget as HTMLDetailsElement).open) next.add(key);
        else next.delete(key);
        expanded = next;
    }
    async function load(selectedView: DocumentInspection, selectedId: string) {
        const attempt = ++request;
        generation = null; failure = ''; expanded = new Set();
        try {
            const result = await inspectionRequest<InspectionPage>(itemUrl(selectedView, selectedId));
            if (attempt === request) generation = result.generation ?? { origins: [], message: 'No generation inputs are linked to this image.' };
        } catch (error) { if (attempt === request) failure = (error as Error).message; }
    }
</script>

<section aria-label="Image generation inputs" data-testid="image-generation-details" data-image-keyboard="ignore">
    <h3>Behind this image</h3>
    {#if failure}<p role="alert">{failure}</p>
    {:else if !generation}<p role="status">Loading generation inputs…</p>
    {:else}
        <p class="hint">{generation.message}</p>
        {#if generation.association === 'stale_original' || generation.association === 'missing_original'}
            <p class="notice">The linked original has changed or is missing. These inputs cannot be verified against the embedded image.</p>
        {/if}
        {#each generation.origins as origin, index}
            {#if generation.origins.length > 1}<h4>{origin.label}</h4>{/if}
            <h4>Saved generation</h4>
            {#if origin.provider}<p>{Object.values(origin.provider).join(' · ')}</p>{/if}
            {#if origin.saved_settings}<p class="hint">{settings(origin.saved_settings)}</p>{/if}
            {#each origin.saved_prompts as prompt}
                <details on:toggle={event => toggle(`${index}:${prompt.item}`, event)}>
                    <summary>Saved assembled prompt · {prompt.status === 'verified' ? 'receipt verified' : prompt.status === 'unverified' ? 'image association unverified' : 'changed or missing'}</summary>
                    {#if prompt.status !== 'verified'}<p class="notice">This saved file is not verified as the exact prompt that produced this image.</p>{/if}
                    {#if expanded.has(`${index}:${prompt.item}`)}<InspectionText {view} identity={prompt.item} label="Saved assembled prompt" />{/if}
                </details>
            {:else}<p class="hint">No saved assembled prompt is available for this image.</p>{/each}
            {#if origin.receipt || origin.saved_config}
                {@const identity = origin.receipt ?? origin.saved_config ?? ''}
                <details on:toggle={event => toggle(`${index}:receipt`, event)}>
                    <summary>{origin.receipt ? 'Generation receipt' : 'Saved generation settings · image association unverified'}</summary>
                    {#if expanded.has(`${index}:receipt`)}<InspectionText {view} {identity} label="Saved generation record" />{/if}
                </details>
            {/if}
            {#if origin.recorded_references.length}
                <details><summary>Recorded reference images ({origin.recorded_references.length})</summary>
                    <ol>{#each origin.recorded_references as ref}<li>{item(ref.item)?.label} · {ref.status.replaceAll('_', ' ')}<code>{ref.sha256}</code></li>{/each}</ol>
                </details>
            {/if}
            <h4>Current image definition</h4>
            <p class="hint">{origin.current_definition === 'matches_receipt' ? 'Current inputs match the hashes in the generation receipt.' : origin.current_definition === 'changed' ? 'Inputs have changed since generation. The current assembly below may differ from the saved prompt.' : 'Current inputs are shown for inspection; their historical versions are not verified.'}</p>
            {#if origin.image_tags.length}<div class="tags" aria-label="Tags in image prompt">{#each origin.image_tags as tag}<span>[{tag}]</span>{/each}</div>{/if}
            {#if origin.image_prompt}<InspectionText {view} identity={origin.image_prompt} label="Image-specific prompt" />
            {:else}<p>No image-specific definition is available.</p>{/if}
            {#if origin.definition}
                <details on:toggle={event => toggle(`${index}:source`, event)}><summary>Full image definition and settings</summary>
                    {#if expanded.has(`${index}:source`)}<InspectionText {view} identity={origin.definition} label="Full image definition" />{/if}
                </details>
            {/if}
            {#if origin.constraints}
                <details on:toggle={event => toggle(`${index}:constraints`, event)}><summary>Image-specific constraints</summary>
                    {#if expanded.has(`${index}:constraints`)}<InspectionText {view} identity={origin.constraints} label="Image-specific constraints" />{/if}
                </details>
            {/if}
            <h4>Inherited styles and tags</h4>
            {#each origin.components as component}
                <details on:toggle={event => toggle(`${index}:style:${component.key}`, event)}>
                    <summary><span class="component-name">{component.key}</span> <span class="hint">· {component.role === 'global' ? 'Global' : component.role === 'direct' ? 'Image style' : 'Inherited'}</span>
                        {#each component.tags as tag}<span class="tag">[{tag}]</span>{/each}
                    </summary>
                    {#if component.requires.length}<p class="hint">Requires: {component.requires.join(' → ')}</p>{/if}
                    {#if expanded.has(`${index}:style:${component.key}`) && component.body}<InspectionText {view} identity={component.body} label={`Style ${component.key}`} />{/if}
                    {#if component.status !== 'current'}<p>Style definition is unavailable.</p>{/if}
                    {#if component.references.length && expanded.has(`${index}:style:${component.key}`)}
                        <p class="hint">Reference inputs:</p>
                        <ul class="references">{#each component.references as id}<li>
                            {#if item(id)?.status === 'current'}
                                <a href={imageUrl(view, id)} target="_blank" rel="noreferrer"><img src={imageUrl(view, id, true)} alt={item(id)?.label} loading="lazy" />{item(id)?.label}</a>
                            {:else}{item(id)?.label} · {item(id)?.status}{/if}
                        </li>{/each}</ul>
                    {/if}
                </details>
            {:else}<p class="hint">No inherited styles are declared.</p>{/each}
            {#if origin.unresolved_tags.length}<p class="notice">Tags without a matching declaration in the current style chain: {origin.unresolved_tags.map(tag => `[${tag}]`).join(', ')}.</p>{/if}
            {#if origin.references.length}<p class="hint">Image-specific references: {origin.references.map(id => item(id)?.label ?? id).join(', ')}</p>{/if}
            {#if origin.current_assembled}
                <details on:toggle={event => toggle(`${index}:assembled`, event)}>
                    <summary>Assembled prompt from current inputs</summary>
                    <p class="hint">Rebuilt using the generation assembler. No generation was run.</p>
                    {#if origin.current_settings}<p class="hint">{settings(origin.current_settings)}</p>{/if}
                    {#if expanded.has(`${index}:assembled`)}<InspectionText {view} identity={origin.current_assembled} label="Current assembled prompt" />{/if}
                </details>
            {/if}
            {#each origin.issues as issue}<p class="notice">{issue}</p>{/each}
        {/each}
    {/if}
</section>

<style>
    section { min-width: 0; font-size: 0.85rem; line-height: 1.55; overflow-wrap: anywhere; }
    h3 { margin: 0 0 0.5rem; font-size: 1.1rem; }
    h4 { margin: 1.2rem 0 0.4rem; font-size: 0.95rem; }
    p { margin: 0.5rem 0; }
    .hint { color: var(--dox-frame-text-muted); }
    .notice { padding-left: 0.65rem; border-left: 2px solid var(--dox-frame-rule); }
    details { padding: 0.6rem 0; border-bottom: 1px solid var(--dox-frame-rule); }
    summary { cursor: pointer; min-height: 32px; align-content: center; }
    summary:focus-visible { outline: 2px solid var(--dox-frame-text); }
    .component-name { font-weight: 600; }
    .tags { display: flex; flex-wrap: wrap; gap: 0.3rem; }
    .tags span, .tag { display: inline-block; padding: 0.1rem 0.35rem; border: 1px solid var(--dox-frame-rule); border-radius: 4px; font-size: 0.75rem; }
    .tag { margin-left: 0.4rem; }
    code { display: block; font-size: 0.7rem; }
    .references { list-style: none; padding: 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 0.5rem; }
    .references a { color: inherit; }
    .references img { display: block; width: 100%; height: 100px; object-fit: contain; }
</style>
