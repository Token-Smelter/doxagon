<script lang="ts">
    import { onDestroy, onMount } from 'svelte';
    import { graph, selectedNode, selectedEdge, focusRequest, searchQuery, impactRequest, impactCount, selectedLayout, showEdgeLabels, nodeSpacing, curveStyle } from '../stores/graph';
    import { media } from '../stores/media';
    import { createGraphModel, downstream, type GraphStoneContext, type RenderNode } from '../graph/graph-model';
    import type { Graph as GraphResponse } from '../api';
    import { GraphLayoutController, circleFallback, finitePositions, hasUsableBounds, type Position } from '../graph/graph-layout';
    import { GraphRenderer } from '../graph/graph-renderer';

    export let stoneContext: GraphStoneContext | null = null;

    let svg: SVGSVGElement;
    let host: HTMLDivElement;
    let renderer: GraphRenderer;
    let layout: GraphLayoutController;
    let observer: ResizeObserver | undefined;
    let positions = new Map<string, Position>();
    let model = $graph ? createGraphModel($graph, stoneContext) : null;
    let hoveredNode: string | null = null;
    let hoveredEdge: string | null = null;
    let previewedNode: string | null = null;
    let focusedNode: string | null = null;
    let impact = new Set<string>();
    let userCamera = false;
    let layoutTimer: ReturnType<typeof setTimeout> | undefined;
    let redrawFrame = 0;
    let previousGraph: GraphResponse | null = null;
    let previousGraphContent = '';
    let previousStoneContext: GraphStoneContext | null = null;
    let previousStoneContent = '';
    let previousLayout = $selectedLayout;
    let previousSpacing = $nodeSpacing;
    let layoutTicks = 0;
    let layoutComplete = false;
    let layoutGeneration = 0;

    function bounds() { return { width: host?.clientWidth ?? 0, height: host?.clientHeight ?? 0 }; }
    function selectedRenderState() {
        return { selectedNode: $selectedNode, focusedNode, selectedEdge: $selectedEdge, hoveredNode, hoveredEdge, previewedNode, impact, search: $searchQuery, showLabels: $showEdgeLabels, curve: $curveStyle };
    }
    function redraw() { if (renderer && model) renderer.render(model, Object.fromEntries(positions), selectedRenderState()); }
    function scheduleRedraw() {
        if (redrawFrame) return;
        redrawFrame = requestAnimationFrame(() => { redrawFrame = 0; redraw(); });
    }
    function scheduleDisplayRedraw(_node: string | null, _edge: { source: string; target: string } | null, _search: string, _labels: boolean, _curve: string) {
        if (renderer && model) scheduleRedraw();
    }
    function scheduleLayout(structural = false) {
        clearTimeout(layoutTimer);
        layoutTimer = setTimeout(() => void runLayout(structural), structural ? 0 : 100);
    }
    async function runLayout(structural = false) {
        const generation = ++layoutGeneration;
        const requestModel = model;
        const requestLayout = $selectedLayout;
        const requestSpacing = $nodeSpacing;
        const requestBounds = bounds();
        if (!$graph || !requestModel || document.hidden || !hasUsableBounds(requestBounds)) return;
        layoutComplete = false;
        // Paint deterministic finite positions immediately; the worker only refines them.
        if (!positions.size || structural) {
            positions = new Map(Object.entries(circleFallback(requestModel.nodes.map(({ id, degree, kind }) => ({ id, degree, kind })), requestBounds, requestSpacing)));
            layoutTicks = 0;
            layoutComplete = true;
            redraw();
            if (structural || !userCamera) renderer.fit($media.mobile ? 16 : 32);
            else renderer.clamp($media.mobile ? 16 : 32);
        }
        const result = await layout.request(requestModel, requestLayout, requestSpacing, requestBounds, positions).catch(() => null);
        if (!result || generation !== layoutGeneration || requestModel !== model || requestLayout !== $selectedLayout || requestSpacing !== $nodeSpacing || !finitePositions(result.positions, requestModel.nodes)) return;
        positions = new Map(Object.entries(result.positions));
        layoutTicks = result.ticks;
        layoutComplete = true;
        redraw();
        if (structural || !userCamera) renderer.fit($media.mobile ? 16 : 32);
        else renderer.clamp($media.mobile ? 16 : 32);
    }
    function selectNode(node: RenderNode) {
        previewedNode = $media.mobile && node.kind === 'doxa' ? node.id : null;
        if (node.kind === 'stone') {
            if (!stoneContext?.thesis || !stoneContext.slide) return;
            const params = new URLSearchParams();
            params.set('thesis', stoneContext.thesis);
            params.set('slide', stoneContext.slide);
            window.location.assign(`/presentations?${params.toString()}`);
            return;
        }
        focusedNode = node.id;
        selectedNode.set(node.slug); selectedEdge.set(null); scheduleRedraw();
    }
    function selectEdge(edge: { source: string; target: string }) { previewedNode = null; focusedNode = null; selectedNode.set(null); selectedEdge.set({ source: edge.source, target: edge.target }); scheduleRedraw(); }
    function clear() { selectedNode.set(null); selectedEdge.set(null); focusedNode = null; hoveredNode = null; hoveredEdge = null; previewedNode = null; scheduleRedraw(); }
    function moveNode(id: string, position: Position) { positions.set(id, position); positions = new Map(positions); redraw(); }
    function nodeIds() { return model?.nodes.map((node) => node.id) ?? []; }

    export function focusNode(id: string) {
        const node = model?.nodes.find((candidate) => candidate.id === id);
        if (!node) return;
        focusedNode = node.id;
        if (node.kind === 'doxa') {
            selectedNode.set(node.slug);
            selectedEdge.set(null);
        }
        renderer?.focus(node.id);
        redraw();
    }
    export function showImpact(nodeId: string): number { if (!model) return 0; impact = new Set(downstream(model, nodeId)); redraw(); return impact.size; }
    export function clearImpact() { impact = new Set(); redraw(); }
    export function fit() { userCamera = false; renderer?.fit($media.mobile ? 16 : 32); }
    export function zoomIn() { userCamera = true; renderer?.zoomBy(1.2); }
    export function zoomOut() { userCamera = true; renderer?.zoomBy(1 / 1.2); }

    function handleKeydown(event: KeyboardEvent) {
        const target = event.target as HTMLElement;
        if (target.matches('input, textarea, select, button, [contenteditable="true"]') || target.isContentEditable) return;
        if (event.key === '+' || event.key === '=') { event.preventDefault(); zoomIn(); return; }
        if (event.key === '-') { event.preventDefault(); zoomOut(); return; }
        if (event.key === '0') { event.preventDefault(); fit(); return; }
        if (event.key === 'Escape') { clear(); return; }
        const ids = nodeIds();
        if (!ids.length) return;
        const current = focusedNode ?? $selectedNode;
        if (event.key === 'Home' || event.key === 'End') { event.preventDefault(); focusNode(event.key === 'Home' ? ids[0] : ids[ids.length - 1]); return; }
        if (event.key === 'Enter' || event.key === ' ') {
            const node = model?.nodes.find((candidate) => candidate.id === current);
            if (node) { event.preventDefault(); selectNode(node); }
            return;
        }
        if (!current || !model) return;
        const next = event.key === 'ArrowRight' || event.key === 'ArrowDown' ? model.outgoing.get(current)?.[0] : event.key === 'ArrowLeft' || event.key === 'ArrowUp' ? model.incoming.get(current)?.[0] : null;
        if (next) { event.preventDefault(); focusNode(next); }
    }

    $: if ($graph) {
        const graphContent = JSON.stringify($graph);
        const stoneContent = stoneContext ? `${stoneContext.thesis}\u0000${stoneContext.slide}\u0000${stoneContext.doxai.join('\u0000')}` : '';
        if ($graph !== previousGraph || graphContent !== previousGraphContent || stoneContext !== previousStoneContext || stoneContent !== previousStoneContent) {
            previousGraph = $graph;
            previousGraphContent = graphContent;
            previousStoneContext = stoneContext;
            previousStoneContent = stoneContent;
            model = createGraphModel($graph, stoneContext);
            const valid = new Set(model.nodes.map((node) => node.id));
            if (focusedNode && !valid.has(focusedNode)) focusedNode = null;
            positions = new Map([...positions].filter(([id]) => valid.has(id)));
            scheduleLayout(true);
        }
    }
    $: scheduleDisplayRedraw($selectedNode, $selectedEdge, $searchQuery, $showEdgeLabels, $curveStyle);
    $: if (renderer && $selectedLayout !== previousLayout) { previousLayout = $selectedLayout; positions = new Map(); scheduleLayout(true); }
    $: if (renderer && $nodeSpacing !== previousSpacing) { previousSpacing = $nodeSpacing; scheduleLayout(true); }
    $: if ($focusRequest) { focusNode($focusRequest); focusRequest.set(null); }
    $: if ($impactRequest) { impactCount.set(showImpact($impactRequest)); impactRequest.set(null); }
    $: if ($impactCount === 0) clearImpact();

    onMount(() => {
        layout = new GraphLayoutController();
        renderer = new GraphRenderer(svg, { selectNode, selectEdge, clear, hoverNode: (id) => { hoveredNode = id; redraw(); }, hoverEdge: (id) => { hoveredEdge = id; redraw(); }, moveNode, cameraChanged: () => { userCamera = true; }, zoomChanged: scheduleRedraw });
        observer = new ResizeObserver(() => {
            scheduleLayout(false);
            if (userCamera) requestAnimationFrame(() => renderer?.clamp($media.mobile ? 16 : 32));
        });
        observer.observe(host);
        const visible = () => { if (!document.hidden) scheduleLayout(true); };
        document.addEventListener('visibilitychange', visible);
        scheduleLayout(true);
        return () => document.removeEventListener('visibilitychange', visible);
    });
    onDestroy(() => { clearTimeout(layoutTimer); cancelAnimationFrame(redrawFrame); observer?.disconnect(); layout?.destroy(); renderer?.destroy(); });
</script>

<div bind:this={host} class="graph-container" data-layout-complete={layoutComplete} data-layout-ticks={layoutTicks}>
    <svg bind:this={svg} class="graph-svg" on:keydown={handleKeydown} role="group" tabindex="0" aria-label="Knowledge graph"></svg>
    <div class="graph-camera-controls" aria-label="Graph camera controls">
        <button type="button" on:click={zoomIn} aria-label="Zoom in">+</button>
        <button type="button" on:click={zoomOut} aria-label="Zoom out">−</button>
        <button type="button" on:click={fit}>Fit</button>
    </div>
    {#if model && model.nodes.length >= 2000}
        <div class="graph-status" role="status">Large graph · {model.nodes.length.toLocaleString()} nodes · labels off</div>
    {/if}
</div>

<style>
    .graph-container { position: relative; width: 100%; height: 100%; min-height: 0; overflow: hidden; background: var(--dox-work-surface); color: var(--dox-work-text); touch-action: none; }
    .graph-svg { width: 100%; height: 100%; display: block; outline: 2px solid transparent; outline-offset: -3px; }
    .graph-svg:focus-visible { outline-color: var(--dox-focus); }
    .graph-camera-controls { position: absolute; inset: 12px 12px auto auto; display: flex; gap: 4px; }
    .graph-camera-controls button { min-width: 36px; min-height: 36px; padding: 0 8px; color: var(--dox-work-text); background: var(--dox-work-surface-raised); border: 1px solid var(--dox-work-rule); border-radius: var(--dox-radius-sm); cursor: pointer; font: 12px var(--dox-font-mono); }
    .graph-status { position: absolute; inset: 12px 12px auto auto; padding: 6px 9px; border: 1px solid var(--dox-border); background: var(--dox-work-surface); color: var(--dox-work-text); font: 12px var(--dox-font-mono); pointer-events: none; }
    :global(.graph-edge) { cursor: pointer; opacity: .58; }
    :global(.graph-edge.is-backbone) { opacity: .38; }
    :global(.graph-edge.is-overview-muted) { opacity: .07; }
    :global(.graph-edge.is-dimmed), :global(.graph-node.is-dimmed) { opacity: .14; }
    :global(.graph-edge.is-selected), :global(.graph-edge.is-neighborhood) { opacity: .92; }
    :global(.graph-edge.is-selected) { stroke-width: 4px; }
    :global(.graph-node) { cursor: grab; }
    :global(.graph-node.is-overview-secondary) { opacity: .28; }
    :global(.graph-node.is-overview-orphan) { opacity: .09; }
    :global(.graph-node.is-anchor), :global(.graph-node.is-selected), :global(.graph-node.is-hovered), :global(.graph-node.is-neighbor), :global(.graph-node.is-impact), :global(.graph-node:focus) { opacity: 1; }
    :global(.graph-node:focus .node-mark), :global(.graph-node.is-selected .node-mark) { stroke: var(--dox-focus); stroke-width: 3px; }
    :global(.graph-node.is-hovered .node-mark), :global(.graph-node.is-neighbor .node-mark), :global(.graph-node.is-impact .node-mark) { stroke-width: 3px; }
    :global(.graph-node.is-hovered .node-mark), :global(.graph-node.is-impact .node-mark) { stroke: var(--dox-focus); }
    :global(.node-hit-target) { cursor: grab; }
    :global(.edge-label), :global(.anchor-label text), :global(.node-label-card text), :global(.evidence-overflow) { font: 11px var(--dox-font-mono); fill: var(--dox-work-text); pointer-events: none; paint-order: stroke; stroke: var(--dox-work-surface); stroke-width: 4px; }
    :global(.anchor-label), :global(.node-label-card) { pointer-events: none; }
    :global(.anchor-label text) { font-size: 10px; font-weight: 600; opacity: .78; letter-spacing: .01em; }
    :global(.node-label-card text), :global(.evidence-overflow) { stroke-width: 3px; }
</style>
