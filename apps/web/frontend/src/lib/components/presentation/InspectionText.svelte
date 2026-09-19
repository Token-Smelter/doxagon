<script lang="ts">
    import { inspectionRequest, itemUrl, type DocumentInspection, type InspectionPage } from '$lib/presentation/documentInspection';
    export let view: DocumentInspection;
    export let identity: string;
    export let label: string;
    let page: InspectionPage | null = null;
    let failure = '';
    let loading = false;
    let request = 0;
    $: if (view && identity) void read(view, identity);
    async function read(selectedView: DocumentInspection, selectedId: string, offset = 0) {
        const attempt = ++request;
        loading = true; failure = '';
        try {
            const result = await inspectionRequest<InspectionPage>(`${itemUrl(selectedView, selectedId)}&offset=${offset}`);
            if (attempt === request) page = result;
        } catch (error) {
            if (attempt === request) { page = null; failure = (error as Error).message; }
        } finally { if (attempt === request) loading = false; }
    }
</script>

{#if loading}<p role="status">Loading {label.toLowerCase()}…</p>{/if}
{#if failure}<p role="alert">{failure}</p>{/if}
{#if page}
    <pre role="region" tabindex="0" aria-label={label}>{page.text || 'No text is available.'}</pre>
    {#if page.next != null || page.offset}
        <div class="pager">
            <button type="button" disabled={loading || !page.offset} on:click={() => read(view, identity, Math.max(0, (page?.offset ?? 0) - 16000))}>Previous text</button>
            <span>{page.offset ?? 0} / {page.total ?? 0} characters</span>
            <button type="button" disabled={loading || page.next == null} on:click={() => page?.next != null && read(view, identity, page.next)}>More text</button>
        </div>
    {/if}
{/if}

<style>
    pre { margin: 0.5rem 0; padding: 0.75rem; max-height: 26rem; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; border: 1px solid var(--dox-frame-rule); border-radius: 5px; font-size: 0.8rem; line-height: 1.6; }
    pre:focus-visible { outline: 2px solid var(--dox-frame-text); outline-offset: 2px; }
    .pager { display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center; }
    button { min-height: 44px; padding: 0.5rem; color: inherit; background: var(--dox-frame-surface); border: 1px solid var(--dox-frame-rule); border-radius: 5px; cursor: pointer; }
    button:disabled { opacity: 0.5; }
</style>
