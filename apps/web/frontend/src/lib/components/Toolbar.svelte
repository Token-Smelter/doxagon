<script lang="ts">
    import { createEventDispatcher, onMount } from 'svelte';
    import {
        activeDiegesis,
        neighborhoodHops,
        neighborhoodRoot,
        searchQuery,
        selectedNode,
        selectedLayout,
        showEdgeLabels,
        nodeSpacing,
        curveStyle,
    } from '../stores/graph';
    import { fetchDiegeses, type DiegesisListItem } from '../api';
    import { openDevTasksModal, devTaskCount } from '$lib/stores/devTasks';
    import { media } from '$lib/stores/media';
    import { graph } from '$lib/stores/graph';

    const dispatch = createEventDispatcher();

    let diegeses: DiegesisListItem[] = [];
    let disclosure: HTMLDetailsElement;
    let statsOpen = false;

    onMount(async () => {
        diegeses = await fetchDiegeses().catch(() => []);
    });

    function focusOnSelected() {
        if ($selectedNode) {
            activeDiegesis.set(null);
            neighborhoodRoot.set($selectedNode);
        }
    }

    function clearFocus() {
        neighborhoodRoot.set(null);
    }

    function reset() {
        activeDiegesis.set(null);
        neighborhoodRoot.set(null);
        searchQuery.set('');
        dispatch('reset');
    }

    function closeView() {
        disclosure.open = false;
        statsOpen = false;
    }

    function handleClickOutside(event: MouseEvent) {
        if (disclosure?.open && !disclosure.contains(event.target as Node)) closeView();
    }
</script>

<svelte:window on:click={handleClickOutside} />

<div class="toolbar" aria-label="Graph instruments">
    <label class="primary-field search-field">
        <span>Search</span>
        <input aria-label="Search" type="search" bind:value={$searchQuery} placeholder="Search claims, evidence, tags…" />
    </label>

    <label class="primary-field scope-field">
        <span>Scope</span>
        <select aria-label="Diegesis" bind:value={$activeDiegesis} on:change={() => neighborhoodRoot.set(null)}>
            <option value={null}>All knowledge</option>
            {#each diegeses as diegesis}
                <option value={diegesis.slug}>{diegesis.title}</option>
            {/each}
        </select>
    </label>

    <div class="focus-control">
        <span class="primary-label">Focus</span>
        <button
            type="button"
            on:click={focusOnSelected}
            disabled={!$selectedNode}
            title="Show neighborhood around selected node"
        >
            {$neighborhoodRoot ? 'Focused' : 'Focus selected'}
        </button>
        {#if $neighborhoodRoot}
            <button type="button" on:click={clearFocus} class="clear-focus" aria-label="Clear focus">×</button>
        {/if}
    </div>

    <details bind:this={disclosure} class="view-disclosure">
        <summary class="overflow-btn">View <span aria-hidden="true">⌄</span></summary>
        <div class="overflow-menu">
            <div class="view-heading">
                <div>
                    <strong>View</strong>
                    <span>Graph rendering and scope depth</span>
                </div>
                <button type="button" class="close-view" on:click={closeView} aria-label="Close View options">×</button>
            </div>

            <label class="control-field">
                <span>Layout</span>
                <select aria-label="Layout" bind:value={$selectedLayout}>
                    <option value="fcose">Force-directed</option>
                    <option value="breadthfirst">Hierarchical</option>
                    <option value="concentric">Radial</option>
                    <option value="circle">Circle</option>
                </select>
            </label>

            <label class="control-field">
                <span>Curves</span>
                <select aria-label="Curves" bind:value={$curveStyle}>
                    <option value="unbundled-bezier">Bezier</option>
                    <option value="taxi">Orthogonal</option>
                    <option value="straight">Straight</option>
                </select>
            </label>

            <label class="range-field">
                <span>Spacing <output>{$nodeSpacing}</output></span>
                <input aria-label="Spacing" type="range" min="50" max="200" bind:value={$nodeSpacing} />
            </label>

            <label class="range-field">
                <span>Depth <output>{$neighborhoodHops}</output></span>
                <input aria-label="Depth" type="range" min="1" max="3" bind:value={$neighborhoodHops} />
            </label>

            <label class="switch-field">
                <span>Edge labels</span>
                <input aria-label="Labels" type="checkbox" bind:checked={$showEdgeLabels} />
            </label>

            <div class="view-actions">
                <button type="button" on:click={() => { reset(); closeView(); }}>Reset View</button>
                <button type="button" class="dev-tasks-btn" on:click={openDevTasksModal}>
                    Dev Tasks
                    {#if $devTaskCount > 0}<span class="task-badge">{$devTaskCount}</span>{/if}
                </button>
                <a href="/pipeline" class="pipeline-link">Pipeline →</a>
            </div>

            {#if $media.mobile}
                <section class="overflow-stats-section" aria-label="Graph statistics">
                    <button
                        type="button"
                        class="stats-toggle-btn"
                        on:click={() => statsOpen = !statsOpen}
                        aria-expanded={statsOpen}
                    >
                        Graph stats <span aria-hidden="true">{statsOpen ? '−' : '+'}</span>
                    </button>
                    {#if statsOpen}
                        <div class="stats-grid">
                            <span class="stat-label">Nodes</span><span class="stat-value">{$graph?.nodes.length ?? 0}</span>
                            <span class="stat-label">Edges</span><span class="stat-value">{$graph?.edges.length ?? 0}</span>
                            <span class="stat-label">Avg Degree</span>
                            <span class="stat-value">{$graph && $graph.nodes.length ? (($graph.edges.length * 2) / $graph.nodes.length).toFixed(1) : '0'}</span>
                            <span class="stat-label">Orphans</span>
                            <span class="stat-value">
                                {#if $graph}
                                    {@const connected = new Set($graph.edges.flatMap((edge) => [edge.source, edge.target]))}
                                    {$graph.nodes.filter((node) => !connected.has(node.slug)).length}
                                {:else}0{/if}
                            </span>
                            <span class="stat-label">Evidence</span>
                            <span class="stat-value">{$graph && $graph.nodes.length ? Math.round(($graph.nodes.filter((node) => (node.evidence?.length ?? 0) > 0).length / $graph.nodes.length) * 100) : 0}%</span>
                        </div>
                    {/if}
                </section>
            {/if}
        </div>
    </details>
</div>

<style>
    .toolbar {
        position: relative;
        z-index: 20;
        display: grid;
        grid-template-columns: minmax(16rem, 1fr) minmax(13rem, 0.7fr) auto auto;
        align-items: end;
        gap: 0.9rem;
        min-width: 0;
        padding: 0.65rem clamp(0.75rem, 2vw, 2rem) 0.75rem;
        color: var(--dox-frame-text);
        background: var(--dox-frame-ground);
        border-bottom: 1px solid var(--dox-frame-rule);
        font-family: var(--dox-font-mono);
    }

    .primary-field, .focus-control, .control-field, .range-field {
        display: grid;
        min-width: 0;
        gap: 0.28rem;
    }

    .primary-field > span, .primary-label, .control-field > span, .range-field > span {
        color: var(--dox-frame-text-muted);
        font: 600 0.55rem/1 var(--dox-font-mono);
        letter-spacing: 0.15em;
        text-transform: uppercase;
    }

    input, select, button, summary, a {
        font-family: var(--dox-font-mono);
    }

    .primary-field input, .primary-field select, .control-field select {
        width: 100%;
        min-width: 0;
        height: 2.1rem;
        padding: 0 0.65rem;
        color: var(--dox-frame-text);
        background: var(--dox-frame-surface);
        border: 1px solid var(--dox-frame-rule);
        border-radius: var(--dox-radius-sm);
        font-size: 0.72rem;
    }

    .primary-field input::placeholder { color: var(--dox-frame-text-muted); opacity: 1; }
    .primary-field input:hover, .primary-field select:hover, .control-field select:hover { border-color: var(--dox-frame-text-muted); }

    button, .pipeline-link, summary {
        min-height: 2.1rem;
        padding: 0 0.7rem;
        color: var(--dox-frame-text);
        background: transparent;
        border: 1px solid var(--dox-frame-rule);
        border-radius: var(--dox-radius-sm);
        cursor: pointer;
        font-size: 0.65rem;
        font-weight: 600;
        letter-spacing: 0.06em;
        text-transform: uppercase;
    }

    button:hover:not(:disabled), .pipeline-link:hover, summary:hover { background: var(--dox-frame-surface-raised); }
    button:disabled { color: var(--dox-frame-text-muted); cursor: not-allowed; opacity: 0.55; }

    .focus-control {
        position: relative;
    }

    .clear-focus {
        position: absolute;
        right: 0;
        bottom: 0;
        min-width: 2.1rem;
        padding: 0;
        border-width: 0 0 0 1px;
    }

    .view-disclosure { position: relative; }
    .view-disclosure summary { display: flex; align-items: center; justify-content: space-between; gap: 0.55rem; list-style: none; }
    .view-disclosure summary::-webkit-details-marker { display: none; }
    .view-disclosure[open] summary { background: var(--dox-frame-surface-raised); }

    .overflow-menu {
        position: absolute;
        top: calc(100% + 0.55rem);
        right: 0;
        z-index: var(--z-toolbar-overflow);
        display: grid;
        grid-template-columns: repeat(2, minmax(9rem, 1fr));
        gap: 1rem;
        width: min(28rem, calc(100vw - 1.5rem));
        padding: 1rem;
        color: var(--dox-frame-text);
        background: var(--dox-frame-surface);
        border: 1px solid var(--dox-frame-rule);
        border-radius: var(--dox-radius);
        box-shadow: var(--dox-shadow);
    }

    .view-heading, .view-actions, .overflow-stats-section { grid-column: 1 / -1; }
    .view-heading { display: flex; align-items: start; justify-content: space-between; gap: 1rem; padding-bottom: 0.75rem; border-bottom: 1px solid var(--dox-frame-rule); }
    .view-heading strong { display: block; font: 650 1rem/1 var(--dox-font-display); }
    .view-heading span { display: block; margin-top: 0.3rem; color: var(--dox-frame-text-muted); font-size: 0.65rem; }
    .close-view { min-width: 2.1rem; padding: 0; font-size: 1rem; }

    .control-field select { height: 2.4rem; }
    .range-field output { float: right; color: var(--dox-frame-text); }
    input[type='range'] { width: 100%; height: 2.4rem; margin: 0; appearance: none; background: transparent; cursor: pointer; }
    input[type='range']::-webkit-slider-runnable-track { height: 3px; background: var(--dox-frame-rule); border-radius: 999px; }
    input[type='range']::-webkit-slider-thumb { width: 16px; height: 16px; margin-top: -6.5px; appearance: none; background: var(--dox-frame-text); border: 3px solid var(--dox-frame-surface); border-radius: 50%; box-shadow: 0 0 0 1px var(--dox-frame-text-muted); }
    input[type='range']::-moz-range-track { height: 3px; background: var(--dox-frame-rule); border: 0; }
    input[type='range']::-moz-range-thumb { width: 12px; height: 12px; background: var(--dox-frame-text); border: 3px solid var(--dox-frame-surface); border-radius: 50%; }

    .switch-field { display: flex; grid-column: 1 / -1; align-items: center; justify-content: space-between; min-height: 2.75rem; border-block: 1px solid var(--dox-frame-rule); }
    .switch-field input { position: relative; width: 2.4rem; height: 1.3rem; appearance: none; background: var(--dox-frame-surface-raised); border: 1px solid var(--dox-frame-text-muted); border-radius: 999px; cursor: pointer; }
    .switch-field input::after { content: ''; position: absolute; top: 3px; left: 3px; width: 0.75rem; height: 0.75rem; background: var(--dox-frame-text-muted); border-radius: 50%; transition: transform 160ms ease-out, background 160ms ease-out; }
    .switch-field input:checked::after { background: var(--dox-frame-text); transform: translateX(1rem); }

    .view-actions { display: flex; flex-wrap: wrap; gap: 0.5rem; }
    .pipeline-link { display: inline-flex; align-items: center; text-decoration: none; }
    .dev-tasks-btn { display: inline-flex; align-items: center; gap: 0.4rem; }
    .task-badge { min-width: 1.2rem; padding: 0.1rem 0.3rem; color: var(--dox-text-on-running); background: var(--dox-status-running); border-radius: var(--dox-radius-pill); text-align: center; }

    .overflow-stats-section { padding-top: 0.25rem; border-top: 1px solid var(--dox-frame-rule); }
    .stats-toggle-btn { display: flex; width: 100%; align-items: center; justify-content: space-between; }
    .stats-grid { display: grid; grid-template-columns: 1fr auto; gap: 0.35rem 1rem; margin-top: 0.6rem; padding: 0.7rem; background: var(--dox-frame-ground); border: 1px solid var(--dox-frame-rule); border-radius: var(--dox-radius-sm); font-size: 0.7rem; }
    .stat-label { color: var(--dox-frame-text-muted); }
    .stat-value { color: var(--dox-frame-text); text-align: right; }

    @media (max-width: 768px) {
        .toolbar {
            grid-template-columns: minmax(5rem, 1fr) minmax(5rem, 0.75fr) auto auto;
            gap: 0.4rem;
            padding: 0.45rem 0.5rem 0.5rem;
            align-items: center;
        }
        .primary-field > span, .primary-label { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
        .primary-field input, .primary-field select, button, summary { min-height: var(--touch-target-min); height: var(--touch-target-min); font-size: 0.72rem; }
        .primary-field input, .primary-field select { font-size: 16px; }
        .focus-control { display: block; }
        .focus-control > button:first-of-type { width: 100%; min-width: var(--touch-target-min); padding-inline: 0.55rem; }
        .focus-control > button:first-of-type { font-size: 0; }
        .focus-control > button:first-of-type::after { content: 'Focus'; font-size: 0.68rem; }
        .clear-focus { display: none; }
        .view-disclosure summary { min-width: var(--touch-target-min); padding-inline: 0.55rem; }
        .overflow-menu {
            position: fixed;
            inset: auto 0 0;
            grid-template-columns: 1fr 1fr;
            width: 100%;
            max-height: min(72vh, 38rem);
            overflow-y: auto;
            padding: 1rem max(1rem, env(safe-area-inset-right)) max(1rem, env(safe-area-inset-bottom)) max(1rem, env(safe-area-inset-left));
            border-radius: var(--dox-radius) var(--dox-radius) 0 0;
        }
        .overflow-menu button, .overflow-menu a, .overflow-menu select, .overflow-menu input { min-height: var(--touch-target-min); }
    }

    @media (max-width: 374px) {
        .toolbar { grid-template-columns: minmax(4.5rem, 1fr) minmax(4.5rem, 0.7fr) 44px 52px; gap: 0.25rem; }
        .view-disclosure summary { font-size: 0; gap: 0; }
        .view-disclosure summary::before { content: 'View'; font-size: 0.65rem; }
        .view-disclosure summary span { display: none; }
    }

    @media (prefers-reduced-motion: reduce) {
        .toolbar *, .switch-field input::after { transition-duration: 0s !important; }
    }
</style>
