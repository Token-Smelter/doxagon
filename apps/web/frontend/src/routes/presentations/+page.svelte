<script lang="ts">
    import { onMount } from 'svelte';
    import { browser } from '$app/environment';
    import { goto } from '$app/navigation';
    import { page } from '$app/stores';
    import PresentationView from '$lib/components/presentation/PresentationView.svelte';
    import { fetchTheses, type ThesisListItem } from '$lib/api';

    let projects: ThesisListItem[] = [];
    let loadingProjects = true;
    let railPinned = false;

    async function loadProjects() {
        loadingProjects = true;
        try {
            projects = await fetchTheses();
        } finally {
            loadingProjects = false;
        }
    }

    function selectPresentation(slug: string) {
        const params = new URLSearchParams($page.url.search);
        params.set('thesis', slug);
        void goto(`/presentations?${params.toString()}`);
    }

    function isSameOriginAppPath(value: string | null): value is string {
        if (!value || !value.startsWith('/') || value.startsWith('//')) return false;
        return new URL(value, window.location.origin).origin === window.location.origin;
    }

    onMount(() => void loadProjects());

    $: returnHref = $page.url.searchParams.get('return');
    // The vault presentation named in the URL is the authority for this editor
    // session. There is no separate opened-presentation store to drift from it.
    $: selectedSlug = $page.url.searchParams.get('thesis');
    $: selectedProject = projects.find((item) => item.slug === selectedSlug) ?? null;
</script>

<svelte:head>
    <title>Presentations · Token Smelter</title>
</svelte:head>

<main class="presentation-workspace" aria-label="Presentation workspace">
    <aside class="project-rail" class:pinned={railPinned} aria-label="Presentation projects">
        <button class="rail-toggle" aria-label="Toggle presentations sidebar" aria-pressed={railPinned} on:click={() => railPinned = !railPinned}>☰</button>
        <header>
            <p>Presentations</p>
            <h1>Theses</h1>
            <a class="return-link" href="/presentations/document">Open HTML document</a>
            {#if browser && isSameOriginAppPath(returnHref)}
                <a class="return-link" href={returnHref}>Return to graph</a>
            {/if}
        </header>
        {#if loadingProjects}
            <p class="rail-state">Loading theses…</p>
        {:else if projects.length === 0}
            <p class="rail-state">No theses are available in this vault.</p>
        {:else}
            <ul>
                {#each projects as project}
                    <li>
                        <button
                            class:active={selectedSlug === project.slug}
                            aria-pressed={selectedSlug === project.slug}
                            on:click={() => selectPresentation(project.slug)}
                        >
                            <span class="thesis-name">{project.name}</span>
                            <small>{project.slide_count} steps</small>
                        </button>
                    </li>
                {/each}
            </ul>
        {/if}
    </aside>

    <section class="workspace-content" aria-live="polite">
        {#if !selectedSlug}
            <div class="workspace-empty" role="status">
                <p class="folio-mark">Presentation folio</p>
                <h2>Select a thesis</h2>
                <p>Choose a thesis from the project rail to open its Steps, live canvas, and inspector.</p>
            </div>
        {:else}
            {#key selectedSlug}
                <PresentationView
                    presentationSlug={selectedSlug}
                    title={selectedProject?.title || selectedProject?.name || selectedSlug}
                />
            {/key}
        {/if}
    </section>
</main>

<style>
    .presentation-workspace {
        display: grid;
        grid-template-columns: 12.5rem minmax(0, 1fr);
        min-width: 0;
        min-height: 0;
        height: 100%;
        color: var(--dox-frame-text);
        background: var(--dox-frame-ground);
    }

    .project-rail {
        min-width: 0;
        overflow-y: auto;
        background: var(--dox-frame-ground);
        border-right: 1px solid var(--dox-frame-rule);
    }

    .project-rail header {
        padding: 1rem;
        border-bottom: 1px solid var(--dox-frame-rule);
    }

    .project-rail p {
        margin: 0 0 0.3rem;
        color: var(--dox-frame-text-muted);
        font-family: var(--dox-font-mono);
        font-size: 0.68rem;
        letter-spacing: var(--dox-tracking-caps);
        text-transform: uppercase;
    }

    .project-rail h1, .workspace-empty h2 { margin: 0; font-family: var(--dox-font-display); }
    .project-rail h1 { color: var(--dox-frame-text); font-size: 1.1rem; }
    .return-link { display: inline-block; min-height: var(--touch-target-min); margin-top: 0.55rem; color: var(--dox-frame-text-muted); font-family: var(--dox-font-mono); font-size: 0.7rem; }
    .return-link:hover { color: var(--dox-frame-text); }
    .project-rail li + li { margin-top: 0.4rem; }
    .project-rail ul { margin: 0; padding: 0.5rem; list-style: none; }
    .project-rail button { width: 100%; min-height: var(--touch-target-min); padding: 0.7rem; color: var(--dox-frame-text-muted); background: var(--dox-frame-surface); border: 1px solid var(--dox-frame-rule); border-radius: var(--dox-radius-sm); cursor: pointer; text-align: left; }
    .project-rail button:hover { color: var(--dox-frame-text); background: var(--dox-frame-surface); border-color: var(--dox-frame-rule); }
    .project-rail button.active { color: var(--dox-frame-text); background: var(--dox-frame-surface-raised); border-color: var(--dox-frame-text-muted); }
    .project-rail button span, .project-rail button small { display: block; overflow-wrap: anywhere; }
    .project-rail button > .thesis-name { font-family: var(--dox-font-display); font-weight: 600; }
    .project-rail button small { margin-top: 0.3rem; color: var(--dox-frame-text-muted); font-family: var(--dox-font-mono); font-size: 0.68rem; }
    .rail-state { padding: 1rem; font-family: var(--dox-font-body); letter-spacing: 0; text-transform: none; }
    .workspace-content { min-width: 0; min-height: 0; overflow: hidden; background: var(--dox-frame-surface); }
    .workspace-empty { display: grid; place-content: center; justify-items: start; width: min(42rem, calc(100% - 4rem)); min-height: calc(100% - 4rem); margin: 2rem auto; padding: clamp(2rem, 7vw, 5rem); color: var(--dox-work-text); background: var(--dox-work-surface); border: 1px solid var(--dox-work-rule); border-radius: 0.75rem; box-shadow: var(--dox-work-shadow); text-align: left; }
    .workspace-empty h2 { font-size: clamp(1.8rem, 4vw, 3rem); letter-spacing: -0.03em; text-wrap: balance; }
    .workspace-empty p { max-width: 42ch; color: var(--dox-work-text-muted); font-family: var(--dox-font-body); font-size: 1.1rem; line-height: 1.6; }
    .workspace-empty .folio-mark { margin-bottom: 1rem; color: var(--dox-work-text-muted); font-family: var(--dox-font-mono); font-size: 0.7rem; letter-spacing: var(--dox-tracking-caps); text-transform: uppercase; }

    .rail-toggle { display: none; }
    @media (min-width: 1024px) {
        .presentation-workspace { position: relative; grid-template-columns: 40px minmax(0, 1fr); transition: grid-template-columns 0s 150ms; }
        .presentation-workspace:has(.project-rail:hover),
        .presentation-workspace:has(.project-rail :focus-visible),
        .presentation-workspace:has(.project-rail.pinned) { grid-template-columns: 230px minmax(0, 1fr); transition-delay: 0s; }
        .workspace-content { grid-column: 2; }
        .project-rail { position: absolute; z-index: 5; inset: 0 auto 0 0; width: 40px; transition: width 0s 150ms; overflow: hidden; box-sizing: border-box; box-shadow: 3px 0 12px #0003; }
        .project-rail:hover, .project-rail:has(:focus-visible), .project-rail.pinned { width: 230px; overflow-y: auto; transition-delay: 0s; }
        .project-rail header, .project-rail ul { width: 230px; box-sizing: border-box; visibility: hidden; }
        .project-rail:hover header, .project-rail:hover ul, .project-rail:has(:focus-visible) header, .project-rail:has(:focus-visible) ul, .project-rail.pinned header, .project-rail.pinned ul { visibility: visible; }
        .project-rail .rail-toggle { display: block; width: 32px; min-height: 36px; margin: 4px; padding: 0; text-align: center; color: var(--dox-frame-text); }
    }
    @media (max-width: 1023px) {
        /* One column that scrolls as a document. The shell still owns the
           viewport, so nothing here re-declares a viewport height. */
        .presentation-workspace { display: flex; flex-direction: column; height: auto; min-height: 100%; }
        .project-rail { flex: none; overflow-x: auto; overflow-y: hidden; border-right: 0; border-bottom: 1px solid var(--dox-frame-rule); }
        .project-rail header { display: flex; align-items: baseline; gap: 0.65rem; padding: 0.6rem 0.75rem; }
        .project-rail header p { margin: 0; }
        .project-rail ul { display: flex; width: max-content; min-width: 100%; padding: 0.4rem; gap: 0.35rem; }
        .project-rail li { width: min(14rem, 70vw); }
        .project-rail li + li { margin-top: 0; }
        .workspace-content { overflow: visible; }
        .workspace-empty { width: calc(100% - 1.5rem); min-height: 24rem; margin: 0.75rem; padding: 1.5rem; }
    }

    @media (min-width: 1400px) {
        .presentation-workspace { grid-template-columns: 40px minmax(0, 1fr); }
    }
</style>
