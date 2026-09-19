<script lang="ts">
    import { onMount, tick } from 'svelte';
    import { selectedNode, selectedEdge, impactRequest, impactCount } from '../stores/graph';
    import { fetchDoxa, fetchSlideUsages, type DoxaDetail, type SlideUsage } from '../api';
    import { textSizeIndex } from '../stores/textSize';
    import { media } from '$lib/stores/media';
    import SvelteMarkdown from 'svelte-markdown';
    import MermaidRenderer from './MermaidRenderer.svelte';
    import EdgeDetailPanel from './EdgeDetailPanel.svelte';

    const DEFAULT_PANEL_WIDTH = 400;
    const MIN_PANEL_WIDTH = 320;
    const MAX_PANEL_WIDTH = 720;
    const MIN_GRAPH_WIDTH = 320;
    const PANEL_WIDTH_STORAGE_KEY = 'doxagon.detail-panel-width.v1';

    let showingImpact = false;
    let panel: HTMLDivElement;
    let panelWidth = DEFAULT_PANEL_WIDTH;
    let panelWidthMax = MAX_PANEL_WIDTH;
    let preferredPanelWidth = DEFAULT_PANEL_WIDTH;
    let resizeStartX = 0;
    let resizeStartWidth = DEFAULT_PANEL_WIDTH;
    let resizingPointerId: number | null = null;
    let priorSelection: string | null = null;
    let returnFocus: HTMLElement | null = null;

    $: if ($selectedNode !== priorSelection) {
        if ($selectedNode && $media.mobile) {
            if (typeof document !== 'undefined') returnFocus = document.activeElement as HTMLElement;
            tick().then(() => panel?.focus());
        } else if (priorSelection && $media.mobile) {
            returnFocus?.focus();
        }
        priorSelection = $selectedNode;
    }

    function panelWidthMaximum() {
        if (typeof window === 'undefined') return MAX_PANEL_WIDTH;
        return Math.min(
            MAX_PANEL_WIDTH,
            Math.max(MIN_PANEL_WIDTH, window.innerWidth - MIN_GRAPH_WIDTH),
        );
    }

    function clampPanelWidth(width: number) {
        return Math.min(panelWidthMaximum(), Math.max(MIN_PANEL_WIDTH, width));
    }

    function persistPanelWidth() {
        try {
            localStorage.setItem(
                PANEL_WIDTH_STORAGE_KEY,
                JSON.stringify({ version: 1, width: preferredPanelWidth }),
            );
        } catch {
            // Storage is optional; a private browsing failure should not affect resizing.
        }
    }

    function applyPreferredPanelWidth(width: number, persist = false) {
        preferredPanelWidth = width;
        panelWidth = clampPanelWidth(width);
        if (persist) persistPanelWidth();
    }

    function restorePanelWidth() {
        try {
            const stored = localStorage.getItem(PANEL_WIDTH_STORAGE_KEY);
            if (!stored) return;
            const parsed = JSON.parse(stored);
            if (parsed?.version === 1 && typeof parsed.width === 'number' && Number.isFinite(parsed.width)) {
                applyPreferredPanelWidth(parsed.width);
            }
        } catch {
            // Ignore unavailable storage and malformed preferences.
        }
    }

    function handleViewportResize() {
        panelWidthMax = panelWidthMaximum();
        panelWidth = clampPanelWidth(preferredPanelWidth);
    }

    function finishPanelResize() {
        resizingPointerId = null;
        window.removeEventListener('pointermove', handlePanelResize);
        window.removeEventListener('pointerup', finishPanelResize);
        window.removeEventListener('pointercancel', finishPanelResize);
    }

    function beginPanelResize(event: PointerEvent) {
        if ($media.mobile || event.button !== 0) return;
        event.preventDefault();
        resizeStartX = event.clientX;
        resizeStartWidth = panelWidth;
        resizingPointerId = event.pointerId;
        (event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId);
        window.addEventListener('pointermove', handlePanelResize);
        window.addEventListener('pointerup', finishPanelResize);
        window.addEventListener('pointercancel', finishPanelResize);
    }

    function handlePanelResize(event: PointerEvent) {
        if (event.pointerId !== resizingPointerId) return;
        applyPreferredPanelWidth(resizeStartWidth + resizeStartX - event.clientX, true);
    }

    function resetPanelWidth() {
        applyPreferredPanelWidth(DEFAULT_PANEL_WIDTH, true);
    }

    function handleSeparatorKeydown(event: KeyboardEvent) {
        if ($media.mobile) return;
        const step = event.shiftKey ? 32 : 16;
        switch (event.key) {
            case 'ArrowLeft':
                event.preventDefault();
                applyPreferredPanelWidth(panelWidth + step, true);
                break;
            case 'ArrowRight':
                event.preventDefault();
                applyPreferredPanelWidth(panelWidth - step, true);
                break;
            case 'Home':
                event.preventDefault();
                applyPreferredPanelWidth(MIN_PANEL_WIDTH, true);
                break;
            case 'End':
                event.preventDefault();
                applyPreferredPanelWidth(panelWidthMaximum(), true);
                break;
        }
    }

    onMount(() => {
        panelWidthMax = panelWidthMaximum();
        restorePanelWidth();
        window.addEventListener('resize', handleViewportResize);
        return () => {
            window.removeEventListener('resize', handleViewportResize);
            finishPanelResize();
        };
    });

    let sheetStartY = 0;
    let sheetDeltaY = 0;
    let isDraggingSheet = false;

    function handleSheetTouchStart(e: TouchEvent) {
        const target = e.target as HTMLElement;
        if (!target.closest('.header') && !target.closest('.drag-handle')) return;
        sheetStartY = e.touches[0].clientY;
        isDraggingSheet = true;
        sheetDeltaY = 0;
    }

    function handleSheetTouchMove(e: TouchEvent) {
        if (!isDraggingSheet) return;
        const delta = e.touches[0].clientY - sheetStartY;
        sheetDeltaY = Math.max(0, delta);
    }

    function handleSheetTouchEnd() {
        if (!isDraggingSheet) return;
        isDraggingSheet = false;
        if (sheetDeltaY > 100) {
            close();
        }
        sheetDeltaY = 0;
    }

    function toggleImpact() {
        if (showingImpact) {
            impactCount.set(0);
            showingImpact = false;
        } else if ($selectedNode) {
            impactRequest.set($selectedNode);
            showingImpact = true;
        }
    }

    let impactSelection: string | null = null;

    // Reset impact only when selection changes, not when the impact count updates.
    $: if ($selectedNode !== impactSelection) {
        impactSelection = $selectedNode;
        showingImpact = false;
        impactCount.set(0);
    }
    $: if ($impactCount > 0 && $selectedNode === impactSelection) {
        showingImpact = true;
    }

    let doxa: DoxaDetail | null = null;
    let slideUsages: SlideUsage[] = [];
    let loading = false;
    let error: string | null = null;

    $: textSize = textSizeIndex.getSize($textSizeIndex);
    $: canIncrease = textSizeIndex.canIncrease($textSizeIndex);
    $: canDecrease = textSizeIndex.canDecrease($textSizeIndex);

    $: if ($selectedNode) {
        loadDoxa($selectedNode);
    } else {
        doxa = null;
    }

    async function loadDoxa(slug: string) {
        loading = true;
        error = null;
        try {
            const [doxaData, usages] = await Promise.all([
                fetchDoxa(slug),
                fetchSlideUsages(slug).catch(() => []),
            ]);
            if ($selectedNode !== slug) return;
            doxa = doxaData;
            slideUsages = usages;
        } catch (e) {
            error = "Failed to load details";
        } finally {
            loading = false;
            await tick();
            if ($media.mobile && $selectedNode === slug) panel?.focus();
        }
    }
    
    function close() {
        selectedNode.set(null);
    }

    function graphReturnHref() {
        const params = new URLSearchParams(window.location.search);
        params.set('node', $selectedNode || '');
        return `${window.location.pathname}?${params.toString()}`;
    }

    let copied = false;
    async function copySlug() {
        if ($selectedNode) {
            await navigator.clipboard.writeText($selectedNode);
            copied = true;
            setTimeout(() => copied = false, 1500);
        }
    }
</script>

{#if $selectedNode}
    <div
        bind:this={panel}
        id="doxa-detail-panel"
        class="detail-panel"
        class:mobile={$media.mobile}
        role={$media.mobile ? 'dialog' : 'complementary'}
        aria-modal={$media.mobile ? 'true' : undefined}
        aria-label={`Doxa details for ${$selectedNode}`}
        tabindex="-1"
        on:touchstart={handleSheetTouchStart}
        on:touchmove={handleSheetTouchMove}
        on:touchend={handleSheetTouchEnd}
        style={$media.mobile && sheetDeltaY > 0
            ? `transform: translateY(${sheetDeltaY}px)`
            : `--detail-panel-width: ${panelWidth}px`}
    >
        {#if !$media.mobile}
            <div
                class="resize-separator"
                role="separator"
                aria-orientation="vertical"
                aria-controls="doxa-detail-panel"
                aria-label={`Doxa details for ${$selectedNode}`}
                aria-valuemin={MIN_PANEL_WIDTH}
                aria-valuemax={panelWidthMax}
                aria-valuenow={panelWidth}
                tabindex="0"
                on:pointerdown={beginPanelResize}
                on:dblclick={resetPanelWidth}
                on:keydown={handleSeparatorKeydown}
            ></div>
        {/if}
        {#if $media.mobile}
            <div class="drag-handle"><span class="drag-bar"></span></div>
        {/if}
        <div class="header">
            <h3>{$selectedNode}</h3>
            <div class="header-controls">
                <button
                    class="copy-btn"
                    class:copied
                    on:click={copySlug}
                    title="Copy slug to clipboard"
                    aria-label={copied ? 'Slug copied' : 'Copy slug to clipboard'}
                >
                    {copied ? '✓' : '⎘'}
                </button>
                <button
                    class="impact-btn"
                    class:active={showingImpact}
                    on:click={toggleImpact}
                    title="Show downstream impact"
                    aria-pressed={showingImpact}
                >
                    {#if showingImpact && $impactCount > 0}
                        ⚡{$impactCount}
                    {:else}
                        ⚡
                    {/if}
                </button>
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
                <button class="close-btn" on:click={close} title="Close panel">×</button>
            </div>
        </div>
        
        <div class="content" style="font-size: {textSize}">
            {#if loading}
                <p>Loading...</p>
            {:else if error}
                <p class="error">{error}</p>
            {:else if doxa}
                <h2>{doxa.belief}</h2>
                <div class="meta">
                    {#each doxa.tags as tag}
                        <span class="tag">{tag}</span>
                    {/each}
                </div>
                
                <div class="markdown prose">
                    <MermaidRenderer content={doxa.content}>
                        <SvelteMarkdown source={doxa.content} />
                    </MermaidRenderer>
                </div>

                {#if slideUsages.length}
                    <section class="slide-usages" aria-label="Slides using this doxa">
                        <h4>Slides using this</h4>
                        <ul>
                            {#each slideUsages as usage}
                                <li>
                                    <a href={`/presentations?thesis=${encodeURIComponent(usage.thesis_slug)}&slide=${encodeURIComponent(usage.slide_slug)}&return=${encodeURIComponent(graphReturnHref())}`}>
                                        {usage.thesis_title} · {usage.slide_number}. {usage.slide_title}
                                    </a>
                                </li>
                            {/each}
                        </ul>
                    </section>
                {/if}
                
                {#if doxa.incoming.length}
                    <h4>Incoming</h4>
                    <ul>
                        {#each doxa.incoming as edge}
                            <li>
                                <button class="edge-link" on:click={() => selectedEdge.set({ source: edge.source, target: $selectedNode || '' })} title="View edge details">←</button>
                                <span class="edge-type">{edge.type}</span> —
                                <button class="link" on:click={() => selectedNode.set(edge.source)}>{edge.source}</button>
                            </li>
                        {/each}
                    </ul>
                {/if}

                {#if doxa.outgoing.length}
                    <h4>Outgoing</h4>
                    <ul>
                        {#each doxa.outgoing as edge}
                            <li>
                                <button class="edge-link" on:click={() => selectedEdge.set({ source: $selectedNode || '', target: edge.target })} title="View edge details">→</button>
                                <span class="edge-type">{edge.type}</span> —
                                <button class="link" on:click={() => selectedNode.set(edge.target)}>{edge.target}</button>
                            </li>
                        {/each}
                    </ul>
                {/if}
            {/if}
        </div>
    </div>
{/if}

{#if $selectedEdge}
    <EdgeDetailPanel
        source={$selectedEdge.source}
        target={$selectedEdge.target}
        onClose={() => selectedEdge.set(null)}
    />
{/if}

<style>
    .detail-panel {
        position: absolute;
        top: 60px; /* Below toolbar */
        right: 0;
        bottom: 0;
        width: var(--detail-panel-width, 400px);
        min-width: 0;
        max-width: calc(100vw - 320px);
        box-sizing: border-box;
        background: var(--dox-surface);
        color: var(--dox-text-primary);
        border-left: 1px solid var(--dox-rule);
        display: flex;
        flex-direction: column;
        box-shadow: var(--dox-shadow);
    }
    .resize-separator {
        position: absolute;
        z-index: 1;
        top: 0;
        bottom: 0;
        left: -8px;
        width: 16px;
        cursor: col-resize;
        touch-action: none;
        outline: none;
    }
    .resize-separator::after {
        position: absolute;
        top: 0;
        bottom: 0;
        left: 7px;
        width: 2px;
        background: var(--dox-rule-strong);
        content: '';
        transition: background-color 0.15s ease-out, width 0.15s ease-out;
    }
    .resize-separator:hover::after,
    .resize-separator:focus-visible::after {
        width: 4px;
        left: 6px;
        background: var(--dox-focus);
    }
    .resize-separator:focus-visible {
        outline: 2px solid var(--dox-focus);
        outline-offset: -2px;
    }
    .header {
        padding: 0.5rem 1rem;
        background: var(--dox-surface-raised);
        border-bottom: 1px solid var(--dox-rule);
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 0.5rem;
    }
    .header h3 {
        margin: 0;
        flex: 1;
        font-size: 0.9rem;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    .header-controls {
        display: flex;
        gap: 0.25rem;
        align-items: center;
    }
    .size-btn, .close-btn, .impact-btn, .copy-btn {
        width: 28px;
        height: 28px;
        border: none;
        border-radius: 4px;
        background: transparent;
        color: var(--dox-text-primary);
        border: 1px solid var(--dox-rule-strong);
        font-size: 1.1rem;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
    }
    .size-btn:hover, .close-btn:hover, .impact-btn:hover, .copy-btn:hover {
        background: var(--dox-surface-raised);
    }
    .size-btn:disabled {
        opacity: 0.3;
        cursor: not-allowed;
    }
    .copy-btn.copied {
        border-color: var(--dox-status-neutral);
    }
    .impact-btn {
        font-size: 0.9rem;
        width: auto;
        padding: 0 8px;
    }
    .impact-btn.active {
        border: 2px dashed var(--dox-status-running);
        color: var(--dox-text-primary);
    }
    .close-btn:hover {
        border-color: var(--dox-status-running);
    }
    .content {
        padding: 1rem;
        overflow-y: auto;
        flex: 1;
    }
    .meta {
        display: flex;
        gap: 0.5rem;
        margin: 0.5rem 0;
        flex-wrap: wrap;
    }
    .tag {
        background: var(--dox-surface-raised);
        border: 1px solid var(--dox-rule);
        padding: 0.1rem 0.4rem;
        border-radius: 4px;
        font-size: 0.8rem;
    }
    .link {
        background: none;
        border: none;
        color: var(--dox-text-primary);
        text-decoration: underline;
        cursor: pointer;
        padding: 0;
    }
    .edge-link {
        background: var(--dox-surface-raised);
        border: 1px solid var(--dox-rule-strong);
        color: var(--dox-text-primary);
        padding: 0.15rem 0.4rem;
        border-radius: 3px;
        cursor: pointer;
        font-size: 0.8rem;
        margin-right: 0.25rem;
    }
    .edge-link:hover {
        background: var(--dox-surface-raised);
        border-color: var(--dox-text-primary);
    }
    .slide-usages a {
        color: var(--dox-text-primary);
        text-decoration-thickness: 0.12em;
        text-underline-offset: 0.18em;
        overflow-wrap: anywhere;
    }
    .edge-type {
        color: var(--dox-text-muted);
        font-size: 0.85rem;
    }
    
    .markdown :global(h1) { font-size: 1.5em; margin-bottom: 0.5em; }
    .markdown :global(p) { margin-bottom: 1em; line-height: 1.5; }
    .markdown :global(pre) { background: var(--dox-ground); border: 1px solid var(--dox-rule); padding: 0.5rem; overflow-x: auto; }

    /* Mobile bottom sheet */
    .detail-panel.mobile {
        position: fixed;
        top: auto;
        right: 0;
        bottom: 0;
        left: 0;
        width: 100%;
        max-width: none;
        max-height: var(--bottom-sheet-max-height, 60vh);
        border-left: none;
        border-top: 1px solid var(--dox-rule);
        border-radius: 12px 12px 0 0;
        box-shadow: var(--dox-shadow);
        z-index: var(--z-bottom-sheet, 220);
        transition: transform 0.2s ease-out;
        padding-bottom: env(safe-area-inset-bottom);
    }

    .drag-handle {
        display: flex;
        justify-content: center;
        padding: 8px 0 4px;
        cursor: grab;
    }

    .drag-bar {
        width: 36px;
        height: 4px;
        background: var(--dox-text-muted);
        border-radius: 2px;
    }

    @media (max-width: 768px) {
        .detail-panel .header-controls button {
            min-width: var(--touch-target-min, 44px);
            min-height: var(--touch-target-min, 44px);
        }
        .detail-panel .content {
            font-size: 1rem;
            padding: 0.75rem;
        }
        .detail-panel .content h2 {
            font-size: 1.1rem;
        }
        .detail-panel .link,
        .detail-panel .edge-link,
        .detail-panel .slide-usages a {
            min-height: var(--touch-target-min, 44px);
            display: inline-flex;
            align-items: center;
        }
    }

    .detail-panel :is(button, a):focus-visible {
        outline: 2px solid var(--dox-focus);
        outline-offset: 2px;
    }

    @media (prefers-reduced-motion: reduce) {
        .detail-panel.mobile,
        .resize-separator::after {
            transition: none;
        }
    }
</style>
