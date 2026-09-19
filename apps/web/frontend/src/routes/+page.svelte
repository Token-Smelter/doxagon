<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    import { browser } from '$app/environment';
    import Graph from '$lib/components/Graph.svelte';
    import Toolbar from '$lib/components/Toolbar.svelte';
    import DetailPanel from '$lib/components/DetailPanel.svelte';
    import DiegesisPanel from '$lib/components/DiegesisPanel.svelte';
    import StatusBar from '$lib/components/StatusBar.svelte';
    import TerminalPane from '$lib/components/TerminalPane.svelte';
    import DevTasksModal from '$lib/components/DevTasksModal.svelte';
    import { graph, activeDiegesis, activeWalk, neighborhoodHops, neighborhoodRoot, selectedNode } from '$lib/stores/graph';
    import { media } from '$lib/stores/media';
    import { fetchGraph, fetchScopedGraph, fetchVersion, fetchSlide } from '$lib/api';
    import type { GraphStoneContext } from '$lib/graph/graph-model';

    let pollInterval: ReturnType<typeof setInterval>;
    let currentVersion: string | null = null;
    let currentDiegesis: string | null = null;
    let currentHops: number = 2;
    let currentRoot: string | null = null;
    let error: string | null = null;
    let loading = false;
    let urlInitialized = false;
    let stoneContext: GraphStoneContext | null = null;

    // URL state management
    function readUrlState() {
        if (!browser) return;
        const params = new URLSearchParams(window.location.search);
        const diegesis = params.get('diegesis');
        const walk = params.get('walk');
        const node = params.get('node');

        if (diegesis) activeDiegesis.set(diegesis);
        if (walk) activeWalk.set(walk);
        if (node) selectedNode.set(node);
        const thesis = params.get('thesis');
        const slide = params.get('slide');
        if (thesis && slide) {
            fetchSlide(thesis, slide)
                .then((detail) => stoneContext = { thesis, slide, doxai: detail.doxai })
                .catch(() => stoneContext = null);
        }
        urlInitialized = true;
    }

    function updateUrl() {
        if (!browser || !urlInitialized) return;
        const params = new URLSearchParams(window.location.search);
        if ($activeDiegesis) params.set('diegesis', $activeDiegesis);
        else params.delete('diegesis');
        if ($activeWalk) params.set('walk', $activeWalk);
        else params.delete('walk');
        if ($selectedNode) params.set('node', $selectedNode);
        else params.delete('node');

        const newUrl = params.toString()
            ? `${window.location.pathname}?${params.toString()}`
            : window.location.pathname;

        window.history.replaceState({}, '', newUrl);
    }

    // Sync URL when state changes
    $: if (urlInitialized) {
        updateUrl();
    }
    $: $activeDiegesis, $activeWalk, $selectedNode, updateUrl();

    async function load() {
        error = null;
        loading = true;
        try {
            let data;
            if ($activeDiegesis) {
                data = await fetchScopedGraph({ diegesis: $activeDiegesis, walk: $activeWalk || undefined });
            } else if ($neighborhoodRoot) {
                data = await fetchScopedGraph({ root: $neighborhoodRoot, hops: $neighborhoodHops });
            } else {
                data = await fetchGraph();
            }
            currentVersion = data.version;
            $graph = data;
        } catch (e) {
            error = e instanceof Error ? e.message : 'Failed to load graph';
            console.error('Graph load error:', e);
        } finally {
            loading = false;
        }
    }

    async function checkVersion() {
        try {
            const newVersion = await fetchVersion();
            if (currentVersion && newVersion !== currentVersion) {
                console.log('Graph updated, reloading...');
                await load();
            }
            currentVersion = newVersion;
        } catch (e) {
            console.error('Version check failed:', e);
        }
    }

    // Reactive loading for diegesis changes
    $: {
        if ($activeDiegesis !== currentDiegesis) {
            currentDiegesis = $activeDiegesis;
            load();
        }
    }

    // Reactive loading for neighborhood changes
    $: {
        if ($neighborhoodRoot !== currentRoot || $neighborhoodHops !== currentHops) {
            currentRoot = $neighborhoodRoot;
            currentHops = $neighborhoodHops;
            if ($neighborhoodRoot) {
                load();
            }
        }
    }

    onMount(() => {
        readUrlState();
        load();
        // Poll for version changes every 5 seconds
        pollInterval = setInterval(checkVersion, 5000);
    });

    onDestroy(() => {
        if (pollInterval) clearInterval(pollInterval);
    });
</script>

<div
    class="app-container"
    class:has-diegesis-panel={$activeDiegesis}
    data-mobile={$media.mobile || undefined}
    data-shell={$media.shell}
>
    <Toolbar on:reset={load} />

    {#if error}
        <div class="error-banner">
            <span>{error}</span>
            <button on:click={load}>Retry</button>
        </div>
    {/if}

    <div class="main-area">
        <DiegesisPanel />
        <div class="graph-area">
            <div class="graph-context" aria-hidden="true">
                <h1>Knowledge Graph</h1>
                <p>A living field of claims, tensions, and evidence. Select one belief to enter its neighborhood.</p>
            </div>
            <Graph {stoneContext} />
            {#if loading}
                <div class="loading-overlay">Loading...</div>
            {/if}
        </div>
        <DetailPanel />
    </div>
    {#if !$media.mobile}
        <StatusBar />
    {/if}
    {#if !$media.mobile}
        <TerminalPane />
        <DevTasksModal />
    {/if}
</div>

<style>
    .app-container {
        display: flex;
        flex: 1;
        flex-direction: column;
        min-width: 0;
        min-height: 0;
        height: 100%;
        background: var(--dox-frame-ground);
        color: var(--dox-frame-text);
    }
    .main-area {
        flex: 1;
        position: relative;
        overflow: hidden;
        display: flex;
        padding: 12px 14px 36px;
        background: var(--dox-frame-ground);
    }
    .graph-area {
        flex: 1;
        position: relative;
        min-width: 0;
        overflow: hidden;
        border: 1px solid var(--dox-work-rule);
        border-radius: calc(var(--dox-radius) + 1px);
        background: var(--dox-work-surface);
        box-shadow: var(--dox-work-shadow);
    }
    .graph-context {
        position: absolute;
        z-index: 2;
        top: 24px;
        left: 28px;
        max-width: min(29rem, calc(100% - 9rem));
        color: var(--dox-work-text);
        pointer-events: none;
    }
    .graph-context h1 {
        margin: 0 0 0.4rem;
        font: 700 1.55rem/1.05 var(--dox-font-display);
        letter-spacing: -0.01em;
        text-wrap: balance;
    }
    .graph-context p {
        max-width: 46ch;
        margin: 0;
        color: var(--dox-work-text-muted);
        font: italic 1rem/1.35 var(--dox-font-body);
        text-wrap: pretty;
    }
    .has-diegesis-panel .graph-area {
        margin-left: 280px;
    }

    @media (max-width: 768px) {
        .main-area {
            padding: 8px;
        }
        .graph-context {
            top: 14px;
            left: 14px;
            max-width: calc(100% - 7rem);
        }
        .graph-context h1 {
            font-size: 1.15rem;
        }
        .graph-context p {
            display: none;
        }
        .has-diegesis-panel .graph-area {
            margin-left: 0;
        }
    }
    .error-banner {
        position: fixed;
        top: 60px;
        left: 50%;
        transform: translateX(-50%);
        background: var(--dox-status-running);
        color: var(--dox-text-on-running);
        padding: 0.75rem 1.5rem;
        border-radius: 4px;
        display: flex;
        align-items: center;
        gap: 1rem;
        z-index: 100;
        pointer-events: none;
    }
    .error-banner button {
        background: color-mix(in srgb, var(--dox-text-on-running) 20%, transparent);
        border: none;
        color: var(--dox-text-on-running);
        padding: 0.25rem 0.75rem;
        border-radius: 3px;
        cursor: pointer;
        pointer-events: auto;
    }
    .error-banner button:hover {
        background: color-mix(in srgb, var(--dox-text-on-running) 30%, transparent);
    }
    .loading-overlay {
        position: absolute;
        top: 50%;
        left: 50%;
        transform: translate(-50%, -50%);
        background: var(--dox-ink-950);
        padding: 1rem 2rem;
        border: 1px solid var(--dox-ink-800);
        border-radius: var(--dox-radius-sm);
        color: var(--dox-ink-300);
    }
</style>
