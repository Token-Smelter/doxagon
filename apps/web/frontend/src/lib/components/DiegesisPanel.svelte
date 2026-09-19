<script lang="ts">
    import { tick } from 'svelte';
    import { activeDiegesis, selectedNode, focusRequest, activeWalk } from '$lib/stores/graph';
    import { media } from '$lib/stores/media';
    import { fetchDiegesis, fetchTheses, type ThesisListItem } from '$lib/api';
    import { textSizeIndex } from '$lib/stores/textSize';
    import type { DiegesisDetail } from '$lib/api';
    import SvelteMarkdown from 'svelte-markdown';
    import DOMPurify from 'dompurify';
    import MermaidRenderer from './MermaidRenderer.svelte';

    let diegesis: DiegesisDetail | null = null;
    let thesisList: ThesisListItem[] = [];
    let loading = false;
    let error: string | null = null;
    let expandedSections: Set<string> = new Set();
    let panel: HTMLElement;
    let previousDiegesis: string | null = null;
    let returnFocus: HTMLElement | null = null;

    $: if ($activeDiegesis !== previousDiegesis) {
        if ($activeDiegesis && $media.mobile) {
            if (typeof document !== 'undefined') returnFocus = document.activeElement as HTMLElement;
            tick().then(() => panel?.focus());
        } else if (previousDiegesis && $media.mobile) {
            returnFocus?.focus();
        }
        previousDiegesis = $activeDiegesis;
    }

    $: textSize = textSizeIndex.getSize($textSizeIndex);
    $: canIncrease = textSizeIndex.canIncrease($textSizeIndex);
    $: canDecrease = textSizeIndex.canDecrease($textSizeIndex);

    // Get walk names and current walk's sections
    $: walkNames = diegesis ? Object.keys(diegesis.walks) : [];
    $: currentWalk = $activeWalk || (walkNames.length > 0 ? walkNames[0] : null);
    $: currentWalkSections = diegesis && currentWalk ? diegesis.walks[currentWalk] || [] : [];

    // Count total doxai in current walk
    $: totalDoxaiInWalk = currentWalkSections.reduce((count, sectionKey) => {
        const section = diegesis?.sections[sectionKey];
        return count + (section?.doxai.length || 0);
    }, 0);

    $: if ($activeDiegesis) {
        loadDiegesis($activeDiegesis);
    } else {
        diegesis = null;
    }

    // Convert wikilinks [[slug]] to markdown links and sanitize
    $: processedBody = diegesis?.body
        ? DOMPurify.sanitize(
            diegesis.body.replace(/\[\[([^\]]+)\]\]/g, '[$1](#node:$1)')
          )
        : '';

    async function loadDiegesis(slug: string) {
        loading = true;
        error = null;
        try {
            // Fetch diegesis and thesis list in parallel
            const [diegesisData, thesesData] = await Promise.all([
                fetchDiegesis(slug),
                fetchTheses({ diegesis: slug })
            ]);
            diegesis = diegesisData;
            thesisList = thesesData;
            // Auto-expand first section
            if (diegesis && Object.keys(diegesis.sections).length > 0) {
                const firstSection = Object.keys(diegesis.sections)[0];
                expandedSections = new Set([firstSection]);
            }
            // Set default walk if not already set
            if (!$activeWalk && diegesis && Object.keys(diegesis.walks).length > 0) {
                activeWalk.set(Object.keys(diegesis.walks)[0]);
            }
        } catch (e) {
            error = e instanceof Error ? e.message : 'Failed to load diegesis';
        } finally {
            loading = false;
            await tick();
            if ($media.mobile && $activeDiegesis === slug) panel?.focus();
        }
    }

    function selectNode(slug: string) {
        selectedNode.set(slug);
        focusRequest.set(slug);
    }

    function toggleSection(sectionKey: string) {
        const newSet = new Set(expandedSections);
        if (newSet.has(sectionKey)) {
            newSet.delete(sectionKey);
        } else {
            newSet.add(sectionKey);
        }
        expandedSections = newSet;
    }

    function selectWalk(walkName: string) {
        activeWalk.set(walkName);
    }

    function handleBackdropClick() {
        activeDiegesis.set(null);
    }

    function handleBodyClick(e: MouseEvent) {
        const target = e.target as HTMLElement;
        if (target.tagName === 'A') {
            const href = target.getAttribute('href');
            if (href?.startsWith('#node:')) {
                e.preventDefault();
                const slug = href.slice(6);
                selectNode(slug);
            }
        }
    }
</script>

{#if $activeDiegesis}
    {#if $media.mobile}
        <button type="button" class="drawer-backdrop" on:click={handleBackdropClick} aria-label="Close diegesis drawer"></button>
    {/if}
    <!-- svelte-ignore a11y-no-noninteractive-element-interactions -->
    <aside
        bind:this={panel}
        class="diegesis-panel"
        class:mobile={$media.mobile}
        role={$media.mobile ? 'dialog' : 'complementary'}
        aria-modal={$media.mobile ? 'true' : undefined}
        aria-label="Diegesis inspector"
        tabindex="-1"
        on:keydown={(event) => event.key === 'Escape' && handleBackdropClick()}
    >
        {#if loading}
            <div class="loading">Loading...</div>
        {:else if error}
            <div class="error">{error}</div>
        {:else if diegesis}
            <header>
                <div class="header-row">
                    <h2>{diegesis.title}</h2>
                    <div class="size-controls">
                        <button
                            class="size-btn"
                            on:click={() => textSizeIndex.decrease()}
                            disabled={!canDecrease}
                            title="Decrease text size"
                        >−</button>
                        <button
                            class="size-btn"
                            on:click={() => textSizeIndex.increase()}
                            disabled={!canIncrease}
                            title="Increase text size"
                        >+</button>
                    </div>
                </div>
                {#if diegesis.subtitle}
                    <p class="subtitle">{diegesis.subtitle}</p>
                {/if}
            </header>

            <!-- Walk Selector -->
            {#if walkNames.length > 1}
                <section class="walk-selector">
                    <h3>Walks</h3>
                    <div class="walk-tabs">
                        {#each walkNames as walkName}
                            <button
                                class="walk-tab"
                                class:active={currentWalk === walkName}
                                on:click={() => selectWalk(walkName)}
                                aria-pressed={currentWalk === walkName}
                            >
                                {walkName}
                                <span class="walk-count">({diegesis.walks[walkName].length})</span>
                            </button>
                        {/each}
                    </div>
                </section>
            {/if}

            <!-- Sections -->
            <section class="sections" style="font-size: {textSize}">
                <h3>Sections ({totalDoxaiInWalk} nodes)</h3>
                {#each currentWalkSections as sectionKey}
                    {@const section = diegesis.sections[sectionKey]}
                    {#if section}
                        <div class="section">
                            <button
                                class="section-header"
                                on:click={() => toggleSection(sectionKey)}
                                aria-expanded={expandedSections.has(sectionKey)}
                            >
                                <span class="toggle">{expandedSections.has(sectionKey) ? '▼' : '▶'}</span>
                                <span class="section-title">{section.title}</span>
                                <span class="section-count">({section.doxai.length})</span>
                            </button>
                            {#if expandedSections.has(sectionKey)}
                                <ol class="doxai-list">
                                    {#each section.doxai as slug}
                                        <li>
                                            <button
                                                class:active={$selectedNode === slug}
                                                on:click={() => selectNode(slug)}
                                            >
                                                {slug}
                                            </button>
                                        </li>
                                    {/each}
                                </ol>
                            {/if}
                        </div>
                    {/if}
                {/each}
            </section>

            <!-- Theses using this diegesis -->
            {#if thesisList.length > 0}
                <section class="theses">
                    <h3>Linked Theses</h3>
                    {#each thesisList as thesisItem}
                        <div class="thesis-card">
                            <div class="thesis-header">
                                <span class="thesis-icon">{thesisItem.has_presentation ? '📊' : '📝'}</span>
                                <span class="thesis-name">{thesisItem.name}</span>
                            </div>
                            <div class="thesis-meta">
                                <span class="thesis-walk">walk: {thesisItem.walk}</span>
                                {#if thesisItem.slide_count > 0}
                                    <span class="thesis-slides">{thesisItem.slide_count} slides</span>
                                    <span class="thesis-images">
                                        {thesisItem.slides_with_images}/{thesisItem.slide_count} with images
                                    </span>
                                {/if}
                            </div>
                            {#if thesisItem.has_presentation && thesisItem.slide_count > 0}
                                <a
                                    class="view-btn"
                                    href={`/presentations?thesis=${encodeURIComponent(thesisItem.slug)}&return=${encodeURIComponent(`/?diegesis=${$activeDiegesis}${$activeWalk ? `&walk=${$activeWalk}` : ''}`)}`}
                                >
                                    View Presentation
                                </a>
                            {/if}
                        </div>
                    {/each}
                </section>
            {/if}

            {#if diegesis.body}
                <section class="description" style="font-size: {textSize}">
                    <h3>Description</h3>
                    <!-- svelte-ignore a11y-click-events-have-key-events a11y-no-static-element-interactions -->
                    <div class="body markdown" on:click={handleBodyClick}>
                        <MermaidRenderer content={processedBody}>
                            <SvelteMarkdown source={processedBody} />
                        </MermaidRenderer>
                    </div>
                </section>
            {/if}
        {/if}
    </aside>
{/if}

<style>
    .diegesis-panel {
        position: fixed;
        left: 0;
        top: 45px;
        bottom: 0;
        width: 280px;
        min-width: 0;
        background: var(--dox-surface);
        color: var(--dox-text-primary);
        border-right: 1px solid var(--dox-rule);
        padding: 1rem;
        overflow-y: auto;
        z-index: 10;
    }

    .loading, .error {
        color: var(--dox-text-muted);
        font-size: 0.9rem;
    }

    .error {
        color: var(--dox-status-running);
        font-weight: 700;
    }

    .header-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 0.5rem;
    }
    .size-controls {
        display: flex;
        gap: 0.25rem;
    }
    .size-btn {
        width: 24px;
        height: 24px;
        border: none;
        border-radius: 4px;
        background: transparent;
        border: 1px solid var(--dox-rule-strong);
        color: var(--dox-text-primary);
        font-size: 1rem;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
    }
    .size-btn:hover {
        background: var(--dox-surface-raised);
    }
    .size-btn:disabled {
        opacity: 0.3;
        cursor: not-allowed;
    }
    header h2 {
        margin: 0;
        font-size: 1.1rem;
        color: var(--dox-text-primary);
    }

    .subtitle {
        margin: 0;
        font-size: 0.85rem;
        color: var(--dox-text-muted);
    }

    h3 {
        font-size: 0.9rem;
        color: var(--dox-text-muted);
        margin: 1rem 0 0.5rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }

    /* Walk Selector */
    .walk-selector {
        margin-bottom: 0.5rem;
    }

    .walk-tabs {
        display: flex;
        flex-wrap: wrap;
        gap: 0.25rem;
    }

    .walk-tab {
        padding: 0.35rem 0.6rem;
        background: transparent;
        border: 1px solid var(--dox-rule-strong);
        border-radius: var(--dox-radius-sm);
        color: var(--dox-text-secondary);
        font-size: 0.8rem;
        cursor: pointer;
    }

    .walk-tab:hover {
        background: var(--dox-surface-raised);
        color: var(--dox-text-primary);
    }

    .walk-tab.active {
        border: 2px solid var(--dox-text-primary);
        color: var(--dox-text-primary);
        font-weight: 700;
    }

    .walk-count {
        opacity: 0.7;
        font-size: 0.75rem;
    }

    /* Sections */
    .section {
        margin-bottom: 0.25rem;
    }

    .section-header {
        display: flex;
        align-items: center;
        width: 100%;
        padding: 0.5rem;
        background: var(--dox-surface-raised);
        border: 1px solid var(--dox-rule);
        border-radius: var(--dox-radius-sm);
        color: var(--dox-text-secondary);
        cursor: pointer;
        font-size: 0.85rem;
        text-align: left;
        gap: 0.5rem;
    }

    .section-header:hover {
        border-color: var(--dox-rule-strong);
    }

    .toggle {
        color: var(--dox-text-muted);
        font-size: 0.7rem;
        width: 12px;
    }

    .section-title {
        flex: 1;
    }

    .section-count {
        color: var(--dox-text-muted);
        font-size: 0.8rem;
    }

    .doxai-list {
        list-style: none;
        padding: 0;
        margin: 0.25rem 0 0 1.5rem;
    }

    .doxai-list li button {
        display: block;
        width: 100%;
        text-align: left;
        padding: 0.35rem 0.5rem;
        background: transparent;
        border: none;
        color: var(--dox-text-secondary);
        cursor: pointer;
        font-size: 0.8rem;
        border-radius: 4px;
    }

    .doxai-list li button:hover {
        background: var(--dox-surface-raised);
        color: var(--dox-text-primary);
    }

    .doxai-list li button.active {
        border: 2px solid var(--dox-text-primary);
        color: var(--dox-text-primary);
        font-weight: 700;
    }

    /* Theses */
    .thesis-card {
        background: var(--dox-surface-raised);
        border: 1px solid var(--dox-rule);
        border-radius: 6px;
        padding: 0.75rem;
        margin-bottom: 0.5rem;
    }

    .thesis-header {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        margin-bottom: 0.35rem;
    }

    .thesis-icon {
        font-size: 1rem;
    }

    .thesis-name {
        color: var(--dox-text-primary);
        font-family: var(--dox-font-display);
        font-size: 0.85rem;
        font-weight: 500;
    }

    .thesis-meta {
        display: flex;
        font-family: var(--dox-font-mono);
        flex-wrap: wrap;
        gap: 0.5rem;
        font-size: 0.75rem;
        color: var(--dox-text-muted);
        margin-bottom: 0.5rem;
    }

    .thesis-walk,
    .thesis-images {
        color: var(--dox-text-muted);
    }

    .thesis-slides {
        color: var(--dox-text-secondary);
        font-weight: 700;
    }

    .view-btn {
        width: 100%;
        padding: 0.5rem;
        display: flex;
        align-items: center;
        justify-content: center;
        background: var(--dox-text-primary);
        border: 1px solid var(--dox-text-primary);
        border-radius: var(--dox-radius-sm);
        color: var(--dox-ground);
        font-family: var(--dox-font-display);
        font-size: 0.8rem;
        cursor: pointer;
        text-decoration: none;
        transition: opacity 0.15s;
    }

    .view-btn:hover {
        opacity: 0.85;
    }

    .body {
        font-family: var(--dox-font-body);
        font-size: 0.85rem;
        color: var(--dox-text-secondary);
        line-height: 1.5;
    }

    /* Markdown styles */
    .markdown :global(h1) { font-size: 1.2em; margin: 0.8em 0 0.4em; color: var(--dox-text-primary); }
    .markdown :global(h2) { font-size: 1.1em; margin: 0.6em 0 0.3em; color: var(--dox-text-secondary); }
    .markdown :global(p) { margin: 0.5em 0; }
    .markdown :global(a) {
        color: var(--dox-text-primary);
        text-decoration: underline;
        text-underline-offset: 0.18em;
        cursor: pointer;
    }
    .markdown :global(a:hover) {
        text-decoration: underline;
    }
    .markdown :global(ul), .markdown :global(ol) {
        margin: 0.5em 0;
        padding-left: 1.5em;
    }
    .markdown :global(code) {
        background: var(--dox-ground);
        border: 1px solid var(--dox-rule);
        padding: 0.1em 0.3em;
        border-radius: 3px;
        font-size: 0.9em;
    }

    /* Backdrop overlay (mobile only) */
    .drawer-backdrop {
        position: fixed;
        inset: 0;
        background: color-mix(in srgb, var(--dox-ink-950) 52%, transparent);
        border: 0;
        padding: 0;
        z-index: var(--z-drawer-backdrop, 200);
    }

    /* Mobile drawer */
    .diegesis-panel.mobile {
        width: var(--drawer-width, min(280px, 85vw));
        z-index: var(--z-drawer, 210);
        box-shadow: var(--dox-shadow);
        padding-bottom: env(safe-area-inset-bottom);
    }

    @media (max-width: 768px) {
        .diegesis-panel .size-btn,
        .diegesis-panel .section-header,
        .diegesis-panel .walk-tab,
        .diegesis-panel .doxai-list li button,
        .diegesis-panel .view-btn {
            min-height: var(--touch-target-min, 44px);
            display: flex;
            align-items: center;
        }
        .diegesis-panel .doxai-list li button {
            padding: 0.5rem;
            font-size: 0.85rem;
        }
        .diegesis-panel header h2 {
            font-size: 1rem;
            overflow-wrap: break-word;
        }
        .diegesis-panel .thesis-name {
            overflow-wrap: break-word;
        }
    }

    .diegesis-panel :is(button, a):focus-visible,
    .drawer-backdrop:focus-visible {
        outline: 2px solid var(--dox-focus);
        outline-offset: 2px;
    }

    @media (prefers-reduced-motion: reduce) {
        .diegesis-panel * {
            transition: none;
            scroll-behavior: auto;
        }
    }
</style>
