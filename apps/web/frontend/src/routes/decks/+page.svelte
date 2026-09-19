<script lang="ts">
    /**
     * `/decks` is retired as a product surface.
     *
     * It used to be a second Step workbench over a separate synthetic
     * workspace, which meant two authorities for one job. The Step editor is
     * now `/presentations`, opened against the real vault presentation the user
     * selected, so this route only forwards there and keeps no state of its
     * own.
     */
    import { onMount } from 'svelte';
    import { goto } from '$app/navigation';
    import { page } from '$app/stores';

    onMount(() => {
        const params = new URLSearchParams($page.url.search);
        const query = params.toString();
        void goto(query ? `/presentations?${query}` : '/presentations', { replaceState: true });
    });
</script>

<svelte:head><title>Steps · Token Smelter</title></svelte:head>

<main class="redirect" aria-label="Step editor moved">
    <p role="status">
        The Step editor is now the presentation workspace.
        <a href="/presentations">Open /presentations</a>.
    </p>
</main>

<style>
    .redirect {
        display: grid;
        place-content: center;
        height: 100%;
        min-height: 0;
        padding: 2rem;
        color: var(--dox-frame-text);
        background: var(--dox-frame-ground);
    }

    a { color: inherit; text-decoration: underline; }
</style>
