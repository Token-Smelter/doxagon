<script lang="ts">
    import { onDestroy } from 'svelte';
    import {
        terminalOpen,
        terminalMinimized,
        terminalPosition,
        terminalSize,
        terminalJobs,
        activeJobId,
        activeJob,
        jobList,
        closeTerminal,
        toggleMinimize,
        clearTerminal,
        closeJob,
        setActiveJob,
    } from '$lib/stores/terminal';

    // Dragging state
    let isDragging = false;
    let dragOffset = { x: 0, y: 0 };

    // Resizing state
    let isResizing = false;
    let resizeStart = { x: 0, y: 0, width: 0, height: 0 };

    // Auto-scroll reference
    let outputContainer: HTMLElement;

    // Auto-scroll to bottom when new output arrives
    $: if (outputContainer && $activeJob?.output.length) {
        setTimeout(() => {
            if (outputContainer) {
                outputContainer.scrollTop = outputContainer.scrollHeight;
            }
        }, 0);
    }

    function startDrag(e: MouseEvent) {
        if ((e.target as HTMLElement).closest('.resize-handle')) return;
        if ((e.target as HTMLElement).closest('.tab-bar')) return;
        isDragging = true;
        dragOffset = {
            x: e.clientX - $terminalPosition.x,
            y: e.clientY - $terminalPosition.y,
        };
        e.preventDefault();
    }

    function startResize(e: MouseEvent) {
        isResizing = true;
        resizeStart = {
            x: e.clientX,
            y: e.clientY,
            width: $terminalSize.width,
            height: $terminalSize.height,
        };
        e.preventDefault();
        e.stopPropagation();
    }

    function handleMouseMove(e: MouseEvent) {
        if (isDragging) {
            terminalPosition.set({
                x: Math.max(0, e.clientX - dragOffset.x),
                y: Math.max(0, e.clientY - dragOffset.y),
            });
        } else if (isResizing) {
            const newWidth = Math.max(300, resizeStart.width + (e.clientX - resizeStart.x));
            const newHeight = Math.max(150, resizeStart.height + (e.clientY - resizeStart.y));
            terminalSize.set({ width: newWidth, height: newHeight });
        }
    }

    function handleMouseUp() {
        isDragging = false;
        isResizing = false;
    }

    // Global mouse listeners for drag/resize
    function handleGlobalMouseMove(e: MouseEvent) {
        if (isDragging || isResizing) {
            handleMouseMove(e);
        }
    }

    function handleGlobalMouseUp() {
        handleMouseUp();
    }

    // Status indicator class
    function getStatusClass(status: string | undefined): string {
        return {
            running: 'status-running',
            complete: 'status-complete',
            error: 'status-error',
        }[status || 'idle'] || 'status-idle';
    }

    // Truncate title for tab display
    function truncateTitle(title: string, maxLen: number = 20): string {
        if (title.length <= maxLen) return title;
        return title.slice(0, maxLen - 2) + '...';
    }

    // Cleanup on destroy
    onDestroy(() => {
        closeTerminal();
    });
</script>

<svelte:window on:mousemove={handleGlobalMouseMove} on:mouseup={handleGlobalMouseUp} />

{#if $terminalOpen}
    <div
        class="terminal-pane"
        class:minimized={$terminalMinimized}
        style="
            left: {$terminalPosition.x}px;
            top: {$terminalPosition.y}px;
            width: {$terminalMinimized ? 'auto' : $terminalSize.width + 'px'};
            height: {$terminalMinimized ? 'auto' : $terminalSize.height + 'px'};
        "
    >
        <div
            class="terminal-header"
            on:mousedown={startDrag}
            role="banner"
        >
            <div class="header-left">
                <span class="status-dot {getStatusClass($activeJob?.status)}" aria-hidden="true"></span>
                <span class="terminal-title">Terminal · {$activeJob?.status ?? 'idle'}</span>
            </div>
            <div class="header-actions">
                <button
                    class="action-btn"
                    on:click|stopPropagation={clearTerminal}
                    title="Clear output"
                >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M3 6h18M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2"></path>
                    </svg>
                </button>
                <button
                    class="action-btn"
                    on:click|stopPropagation={toggleMinimize}
                    title={$terminalMinimized ? 'Expand' : 'Minimize'}
                >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        {#if $terminalMinimized}
                            <polyline points="15 3 21 3 21 9"></polyline>
                            <polyline points="9 21 3 21 3 15"></polyline>
                            <line x1="21" y1="3" x2="14" y2="10"></line>
                            <line x1="3" y1="21" x2="10" y2="14"></line>
                        {:else}
                            <line x1="5" y1="12" x2="19" y2="12"></line>
                        {/if}
                    </svg>
                </button>
                <button
                    class="action-btn close-btn"
                    on:click|stopPropagation={closeTerminal}
                    title="Close"
                >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <line x1="18" y1="6" x2="6" y2="18"></line>
                        <line x1="6" y1="6" x2="18" y2="18"></line>
                    </svg>
                </button>
            </div>
        </div>

        {#if !$terminalMinimized}
            <!-- Tab bar for multiple jobs -->
            {#if $jobList.length > 0}
                <div class="tab-bar">
                    {#each $jobList as job (job.id)}
                        <button
                            class="tab"
                            class:active={$activeJobId === job.id}
                            on:click={() => setActiveJob(job.id)}
                            title={job.title}
                        >
                            <span class="tab-status {getStatusClass(job.status)}" aria-hidden="true"></span>
                            <span class="tab-title">{truncateTitle(job.title)} · {job.status}</span>
                            <button
                                class="tab-close"
                                on:click|stopPropagation={() => closeJob(job.id)}
                                title="Close tab"
                            >
                                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                    <line x1="18" y1="6" x2="6" y2="18"></line>
                                    <line x1="6" y1="6" x2="18" y2="18"></line>
                                </svg>
                            </button>
                        </button>
                    {/each}
                </div>
            {/if}

            <div class="terminal-content" bind:this={outputContainer}>
                {#if $activeJob}
                    {#each $activeJob.output as line}
                        <div
                            class="output-line"
                            class:status-line={line.startsWith('[STATUS]')}
                            class:error-line={line.startsWith('[ERROR]') || line.startsWith('[Connection')}
                            class:complete-line={line.startsWith('[COMPLETE]') || line.startsWith('[Process exited with code 0]')}
                        >{line}</div>
                    {/each}
                    {#if $activeJob.status === 'running'}
                        <div class="cursor-blink">_</div>
                    {/if}
                {:else}
                    <div class="no-job">No active job</div>
                {/if}
            </div>

            <div
                class="resize-handle"
                on:mousedown={startResize}
                role="separator"
                aria-orientation="both"
            ></div>
        {/if}
    </div>
{/if}

<style>
    .terminal-pane {
        position: fixed;
        background: var(--dox-ink-950);
        border: 1px solid var(--dox-ink-800);
        border-radius: var(--dox-radius);
        box-shadow: var(--dox-shadow);
        z-index: 1000;
        display: flex;
        flex-direction: column;
        min-width: 300px;
        min-height: 150px;
        overflow: hidden;
    }

    .terminal-pane.minimized {
        min-width: auto;
        min-height: auto;
    }

    .terminal-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 0.5rem 0.75rem;
        background: var(--dox-ink-900);
        border-bottom: 1px solid var(--dox-rule-strong);
        cursor: grab;
        user-select: none;
    }

    .terminal-header:active {
        cursor: grabbing;
    }

    .header-left {
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }

    .status-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
    }

    .status-idle {
        background: var(--dox-text-muted);
    }

    .status-running {
        background: var(--dox-status-running);
        animation: pulse 1.5s infinite;
    }

    .status-complete {
        background: var(--dox-status-output);
    }

    .status-error {
        background: var(--dox-status-running);
    }

    @keyframes pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.5; }
    }

    .terminal-title {
        font-size: 0.8rem;
        font-weight: 500;
        color: var(--dox-ink-400);
        font-family: var(--dox-font-mono);
    }

    .header-actions {
        display: flex;
        gap: 0.25rem;
    }

    .action-btn {
        width: 24px;
        height: 24px;
        background: transparent;
        border: none;
        border-radius: var(--dox-radius-sm);
        color: var(--dox-ink-400);
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: all 0.15s;
    }

    .action-btn:hover {
        background: var(--dox-rule-strong);
        color: var(--dox-text-on-running);
    }

    .action-btn.close-btn:hover {
        background: var(--dox-status-running);
        color: var(--dox-brand-paper-2);
    }

    /* Tab bar */
    .tab-bar {
        display: flex;
        gap: 2px;
        padding: 4px 4px 0;
        background: var(--dox-ink-950);
        border-bottom: 1px solid var(--dox-rule-strong);
        overflow-x: auto;
        scrollbar-width: thin;
        scrollbar-color: var(--dox-ink-800) var(--dox-ink-950);
    }

    .tab-bar::-webkit-scrollbar {
        height: 4px;
    }

    .tab-bar::-webkit-scrollbar-track {
        background: var(--dox-ink-950);
    }

    .tab-bar::-webkit-scrollbar-thumb {
        background: var(--dox-ink-800);
        border-radius: 2px;
    }

    .tab {
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 6px 8px;
        background: var(--dox-ink-900);
        border: none;
        border-radius: 4px 4px 0 0;
        color: var(--dox-ink-400);
        font-size: 0.7rem;
        font-family: var(--dox-font-mono);
        cursor: pointer;
        transition: all 0.15s;
        flex-shrink: 0;
        max-width: 200px;
    }

    .tab:hover {
        background: var(--dox-ink-900);
        color: var(--dox-text-secondary);
    }

    .tab.active {
        background: var(--dox-ink-950);
        color: var(--dox-text-on-running);
        border-bottom: 2px solid var(--dox-status-running);
        margin-bottom: -1px;
    }

    .tab-status {
        width: 6px;
        height: 6px;
        border-radius: 50%;
        flex-shrink: 0;
    }

    .tab-title {
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    .tab-close {
        width: 16px;
        height: 16px;
        padding: 0;
        background: transparent;
        border: none;
        border-radius: 3px;
        color: var(--dox-text-muted);
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
        transition: all 0.15s;
    }

    .tab-close:hover {
        background: var(--dox-ink-800);
        color: var(--dox-text-on-running);
    }

    .tab.active .tab-close:hover {
        background: var(--dox-status-running);
        color: var(--dox-brand-paper-2);
    }

    .terminal-content {
        flex: 1;
        padding: 0.75rem;
        overflow-y: auto;
        font-family: var(--dox-font-mono);
        font-size: 0.75rem;
        line-height: 1.5;
        color: var(--dox-ink-300);
        background: var(--dox-ink-950);
    }

    .output-line {
        white-space: pre-wrap;
        word-break: break-all;
    }

    .status-line {
        color: var(--dox-brand-paper-2);
    }

    .error-line {
        color: var(--dox-brand-paper-2);
    }

    .complete-line {
        color: var(--dox-brand-gold-hi);
    }

    .no-job {
        color: var(--dox-ink-400);
        font-style: italic;
    }

    .cursor-blink {
        display: inline;
        animation: blink 1s step-end infinite;
        color: var(--dox-text-on-running);
    }

    @keyframes blink {
        0%, 100% { opacity: 1; }
        50% { opacity: 0; }
    }

    .resize-handle {
        position: absolute;
        right: 0;
        bottom: 0;
        width: 16px;
        height: 16px;
        cursor: se-resize;
        background: linear-gradient(
            135deg,
            transparent 50%,
            var(--dox-ink-800) 50%,
            var(--dox-ink-800) 60%,
            transparent 60%,
            transparent 70%,
            var(--dox-ink-800) 70%,
            var(--dox-ink-800) 80%,
            transparent 80%
        );
    }

    .resize-handle:hover {
        background: linear-gradient(
            135deg,
            transparent 50%,
            var(--dox-text-muted) 50%,
            var(--dox-text-muted) 60%,
            transparent 60%,
            transparent 70%,
            var(--dox-text-muted) 70%,
            var(--dox-text-muted) 80%,
            transparent 80%
        );
    }

    @media (max-width: 768px) {
        .action-btn { min-width: var(--touch-target-min); min-height: var(--touch-target-min); }
    }

    @media (prefers-reduced-motion: reduce) {
        .action-btn, .tab, .tab-close { transition: none; }
        .status-running, .cursor-blink { animation: none; }
    }
</style>
