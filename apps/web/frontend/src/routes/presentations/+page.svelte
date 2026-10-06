<script lang="ts">
    import { onMount } from 'svelte';
    import { browser } from '$app/environment';
    import { goto } from '$app/navigation';
    import { page } from '$app/stores';
    import PresentationView from '$lib/components/presentation/PresentationView.svelte';
    import { fetchDiegeses, fetchTheses, type ThesisListItem } from '$lib/api';

    /** One diegesis and every thesis that argues within it. */
    interface DiegesisGroup {
        /** The diegesis slug a thesis declares, or '' for a thesis that declares none. */
        key: string;
        title: string;
        items: ThesisListItem[];
    }

    let projects: ThesisListItem[] = [];
    let diegesisTitles = new Map<string, string>();
    let loadingProjects = true;
    let railPinned = false;
    let filter = '';
    /** Diegeses the reader opened or closed by hand. Nothing else is remembered. */
    let toggled = new Map<string, boolean>();

    async function loadProjects() {
        loadingProjects = true;
        try {
            // The library names a diegesis; a thesis carries only its slug.
            const [theses, diegeses] = await Promise.all([
                fetchTheses(),
                fetchDiegeses().catch(() => []),
            ]);
            projects = theses;
            diegesisTitles = new Map(diegeses.map((item) => [item.slug, item.title]));
        } finally {
            loadingProjects = false;
        }
    }

    function selectPresentation(slug: string) {
        const params = new URLSearchParams($page.url.search);
        params.set('thesis', slug);
        void goto(`/presentations?${params.toString()}`);
    }

    function toggleDiegesis(key: string, open: boolean) {
        toggled = new Map(toggled).set(key, !open);
    }

    /** Close every diegesis at once, or reopen them all. */
    function toggleEveryDiegesis() {
        const next = !anyOpen;
        toggled = new Map(groups.map((group) => [group.key, next]));
    }

    function groupByDiegesis(items: ThesisListItem[], titles: Map<string, string>): DiegesisGroup[] {
        const groups = new Map<string, DiegesisGroup>();
        for (const item of items) {
            const key = (item.diegesis ?? '').trim();
            let group = groups.get(key);
            if (!group) {
                // A vault may declare a scope its library does not list. The
                // slug it declared still groups, and still names the group.
                group = { key, title: key ? titles.get(key) ?? key : 'No diegesis', items: [] };
                groups.set(key, group);
            }
            group.items.push(item);
        }
        // A thesis that declares no diegesis sorts last; it is a gap in the
        // vault rather than a scope with a name.
        return [...groups.values()].sort((left, right) => {
            if (!left.key || !right.key) return left.key ? -1 : 1;
            return left.title.localeCompare(right.title, undefined, { sensitivity: 'base' });
        });
    }

    function matches(item: ThesisListItem, needle: string): boolean {
        return `${item.name} ${item.slug} ${item.diegesis ?? ''}`.toLowerCase().includes(needle);
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

    $: needle = filter.trim().toLowerCase();
    // Naming a diegesis keeps every thesis inside it, so the filter reaches a
    // scope as well as a title.
    $: groups = groupByDiegesis(projects, diegesisTitles)
        .map((group) => (
            !needle || group.title.toLowerCase().includes(needle)
                ? group
                : { ...group, items: group.items.filter((item) => matches(item, needle)) }
        ))
        .filter((group) => group.items.length > 0);
    $: listed = groups.reduce((count, group) => count + group.items.length, 0);

    // A filtered rail shows every hit, so a collapsed diegesis never hides the
    // thesis the filter just found. Otherwise the reader's own choice governs,
    // and an untouched diegesis is closed unless it holds the open
    // presentation — a vault of any size then reads as a list of scopes.
    $: openGroups = new Set(
        groups
            .filter((group) => (
                Boolean(needle)
                || (toggled.get(group.key) ?? group.items.some((item) => item.slug === selectedSlug))
            ))
            .map((group) => group.key),
    );
    $: anyOpen = groups.some((group) => openGroups.has(group.key));
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
            <input
                class="rail-filter"
                type="search"
                bind:value={filter}
                aria-label="Filter presentations"
                placeholder="Filter presentations…"
            />
            <p class="rail-count" aria-live="polite">
                {#if needle}{listed} of {projects.length}{:else}{projects.length} theses{/if}
                {#if groups.length > 1}
                    <button class="collapse-all" on:click={toggleEveryDiegesis}>
                        {anyOpen ? 'Collapse all' : 'Expand all'}
                    </button>
                {/if}
            </p>
        </header>
        {#if loadingProjects}
            <p class="rail-state">Loading theses…</p>
        {:else if projects.length === 0}
            <p class="rail-state">No theses are available in this vault.</p>
        {:else if groups.length === 0}
            <p class="rail-state">No thesis matches “{filter.trim()}”.</p>
        {:else}
            <ul class="rail-groups">
                {#each groups as group (group.key)}
                    {@const open = openGroups.has(group.key)}
                    <li class="rail-group" data-diegesis={group.key}>
                        <button
                            class="diegesis-toggle"
                            aria-expanded={open}
                            on:click={() => toggleDiegesis(group.key, open)}
                        >
                            <span class="caret" aria-hidden="true">{open ? '▾' : '▸'}</span>
                            <span class="diegesis-title">{group.title}</span>
                            <span class="diegesis-count">{group.items.length}</span>
                        </button>
                        {#if open}
                            <ul class="thesis-list">
                                {#each group.items as project (project.slug)}
                                    <li>
                                        <button
                                            class="thesis-select"
                                            class:active={selectedSlug === project.slug}
                                            aria-pressed={selectedSlug === project.slug}
                                            on:click={() => selectPresentation(project.slug)}
                                        >
                                            <span class="thesis-name">{project.name}</span>
                                            <!-- Steps are a Step project's measure. A document is one
                                                 authored file with no steps to count, so reporting its
                                                 slide_count here would read as "0 steps" of content. -->
                                            <small>{project.presentation_model === 'document' ? 'document' : `${project.slide_count} steps`}</small>
                                        </button>
                                    </li>
                                {/each}
                            </ul>
                        {/if}
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
        /* 2.5x the old 230px rail: enough that a long scope title holds one
           truncated line instead of wrapping to four. */
        --rail-open-width: 575px;
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
        background: var(--dox-frame-ground);
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

    .rail-filter { width: 100%; min-width: 0; height: 2.1rem; margin-top: 0.55rem; padding: 0 0.55rem; color: var(--dox-frame-text); background: var(--dox-frame-surface); border: 1px solid var(--dox-frame-rule); border-radius: var(--dox-radius-sm); font-family: var(--dox-font-mono); font-size: 0.72rem; }
    .rail-filter::placeholder { color: var(--dox-frame-text-muted); opacity: 1; }
    .rail-filter:hover { border-color: var(--dox-frame-text-muted); }
    .rail-count { display: flex; align-items: baseline; justify-content: space-between; gap: 0.5rem; margin: 0.45rem 0 0; letter-spacing: 0.08em; }
    .collapse-all { padding: 0; color: var(--dox-frame-text-muted); background: transparent; border: 0; cursor: pointer; font-family: var(--dox-font-mono); font-size: 0.62rem; letter-spacing: var(--dox-tracking-caps); text-transform: uppercase; }
    .collapse-all:hover { color: var(--dox-frame-text); }

    .project-rail ul { margin: 0; padding: 0; list-style: none; }
    .rail-groups { padding: 0.5rem; }
    .rail-group + .rail-group { margin-top: 0.5rem; }

    .diegesis-toggle { display: flex; align-items: center; gap: 0.45rem; width: 100%; min-height: 2.1rem; padding: 0.4rem 0.45rem; color: var(--dox-frame-text-muted); background: transparent; border: 0; border-bottom: 1px solid var(--dox-frame-rule); cursor: pointer; font-family: var(--dox-font-mono); font-size: 0.66rem; letter-spacing: var(--dox-tracking-caps); text-align: left; text-transform: uppercase; }
    .diegesis-toggle:hover { color: var(--dox-frame-text); }
    .caret { flex: none; width: 0.7rem; font-size: 0.6rem; }
    /* One line per scope, truncated. A collapsed rail is then a fixed-height
       list of scopes however long the titles in a vault run. */
    .diegesis-title { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .diegesis-count { flex: none; color: var(--dox-frame-text-muted); font-variant-numeric: tabular-nums; }

    .thesis-list { padding: 0.4rem 0 0; }
    .thesis-list li + li { margin-top: 0.4rem; }
    .thesis-select { width: 100%; min-height: var(--touch-target-min); padding: 0.7rem; color: var(--dox-frame-text-muted); background: var(--dox-frame-surface); border: 1px solid var(--dox-frame-rule); border-radius: var(--dox-radius-sm); cursor: pointer; text-align: left; }
    .thesis-select:hover { color: var(--dox-frame-text); border-color: var(--dox-frame-rule); }
    .thesis-select.active { color: var(--dox-frame-text); background: var(--dox-frame-surface-raised); border-color: var(--dox-frame-text-muted); }
    .thesis-select span, .thesis-select small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .thesis-name { font-family: var(--dox-font-display); font-weight: 600; }
    .thesis-select small { margin-top: 0.3rem; color: var(--dox-frame-text-muted); font-family: var(--dox-font-mono); font-size: 0.68rem; }

    .rail-state { padding: 1rem; font-family: var(--dox-font-body); letter-spacing: 0; text-transform: none; }
    .workspace-content { min-width: 0; min-height: 0; overflow: hidden; background: var(--dox-frame-surface); }
    .workspace-empty { display: grid; place-content: center; justify-items: start; width: min(42rem, calc(100% - 4rem)); min-height: calc(100% - 4rem); margin: 2rem auto; padding: clamp(2rem, 7vw, 5rem); color: var(--dox-work-text); background: var(--dox-work-surface); border: 1px solid var(--dox-work-rule); border-radius: 0.75rem; box-shadow: var(--dox-work-shadow); text-align: left; }
    .workspace-empty h2 { font-size: clamp(1.8rem, 4vw, 3rem); letter-spacing: -0.03em; text-wrap: balance; }
    .workspace-empty p { max-width: 42ch; color: var(--dox-work-text-muted); font-family: var(--dox-font-body); font-size: 1.1rem; line-height: 1.6; }
    .workspace-empty .folio-mark { margin-bottom: 1rem; color: var(--dox-work-text-muted); font-family: var(--dox-font-mono); font-size: 0.7rem; letter-spacing: var(--dox-tracking-caps); text-transform: uppercase; }

    .rail-toggle { display: none; }
    @media (min-width: 1024px) {
        /* The rail is an overlay, not a column: the editor keeps the full width
           at every rail state, so revealing the list never reflows the canvas
           underneath it. The closed rail is a 40px hover target; the open one
           is wide enough to hold a scope title on a single truncated line. */
        .presentation-workspace { position: relative; grid-template-columns: 40px minmax(0, 1fr); }
        .workspace-content { grid-column: 1 / -1; margin-left: 40px; }
        /* The rail scrolls a whole vault here, so the filter that narrows it
           stays reachable from anywhere in that scroll. */
        .project-rail header { position: sticky; top: 0; z-index: 1; }
        .project-rail {
            position: absolute;
            z-index: 5;
            inset: 0 auto 0 0;
            width: 40px;
            overflow: hidden;
            box-sizing: border-box;
            box-shadow: 3px 0 12px #0003;
            /* Leaving the rail holds it open for a second, then it retracts
               over 750ms. Opening is immediate: a reader reaching for the rail
               should not wait for it. */
            transition: width 750ms ease 1s;
        }
        .project-rail:hover, .project-rail:has(:focus-visible), .project-rail.pinned {
            width: var(--rail-open-width);
            overflow-y: auto;
            transition: width 160ms ease 0s;
        }
        .project-rail header, .project-rail .rail-groups, .project-rail .rail-state { width: var(--rail-open-width); box-sizing: border-box; visibility: hidden; }
        .project-rail:hover header, .project-rail:hover .rail-groups, .project-rail:hover .rail-state,
        .project-rail:has(:focus-visible) header, .project-rail:has(:focus-visible) .rail-groups, .project-rail:has(:focus-visible) .rail-state,
        .project-rail.pinned header, .project-rail.pinned .rail-groups, .project-rail.pinned .rail-state { visibility: visible; }
        .project-rail .rail-toggle { display: block; width: 32px; min-height: 36px; margin: 4px; padding: 0; text-align: center; color: var(--dox-frame-text); }
    }
    @media (max-width: 1023px) {
        /* One column that scrolls as a document. The shell still owns the
           viewport, so nothing here re-declares a viewport height: a long vault
           is shortened by collapsing its diegeses, not by capping the rail. */
        .presentation-workspace { display: flex; flex-direction: column; height: auto; min-height: 100%; }
        .project-rail { flex: none; overflow-x: hidden; overflow-y: visible; border-right: 0; border-bottom: 1px solid var(--dox-frame-rule); }
        .project-rail header { display: flex; flex-wrap: wrap; align-items: baseline; gap: 0.65rem; padding: 0.6rem 0.75rem; }
        .project-rail header p { margin: 0; }
        .rail-filter { flex: 1 1 100%; margin-top: 0; }
        .rail-count { flex: 1 1 100%; margin: 0; }
        .rail-groups { padding: 0.4rem; }
        /* Each diegesis keeps its theses on one swipeable row, so nesting a
           long vault costs vertical space per scope rather than per thesis. */
        .thesis-list { display: flex; gap: 0.35rem; overflow-x: auto; }
        .thesis-list li { flex: none; width: min(14rem, 70vw); }
        .thesis-list li + li { margin-top: 0; }
        .workspace-content { overflow: visible; }
        .workspace-empty { width: calc(100% - 1.5rem); min-height: 24rem; margin: 0.75rem; padding: 1.5rem; }
    }

    @media (prefers-reduced-motion: reduce) {
        .project-rail { transition-duration: 0s; }
    }
</style>
