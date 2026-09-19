<script lang="ts">
    import { onDestroy, onMount } from 'svelte';
    import PresentationWorkspace from '$lib/components/PresentationWorkspace.svelte';
    import { findAuthoredDocument, type AuthoredDocument } from '$lib/presentation/authoredDocument';

    export let presentationSlug: string;
    export let title = '';

    let source: AuthoredDocument | null = null;
    let loading = true;
    let failure = '';
    let mounted = true;

    onMount(async () => {
        try {
            const selected = await findAuthoredDocument(presentationSlug);
            if (mounted) source = selected;
        } catch (error) {
            if (mounted) failure = error instanceof Error ? error.message : 'The presentation could not be opened.';
        } finally {
            if (mounted) loading = false;
        }
    });
    onDestroy(() => { mounted = false; });
</script>

{#if loading}
    <p class="state" role="status">Opening the presentation…</p>
{:else if failure}
    <p class="state" role="alert">{failure}</p>
{:else}
    <PresentationWorkspace {presentationSlug} {title} documentSource={source} />
{/if}

<style>
    .state { padding: 2rem; color: var(--dox-frame-text); }
</style>
