<script lang="ts">
    import { onDestroy, tick } from 'svelte';
    import {
        devTasks,
        devTasksModalOpen,
        devTasksSubmitting,
        devTasksError,
        addDevTask,
        removeDevTask,
        clearDevTasks,
        closeDevTasksModal,
    } from '$lib/stores/devTasks';
    import { connectToJobStream } from '$lib/stores/terminal';
    import {
        submitDevTasks,
        preflightDevTasks,
        getDevTaskStatus,
        getDevTaskDiff,
        mergeDevTask,
        rejectDevTask,
        type DevTaskStatus,
        type DevTasksStatusResponse,
        type DevTasksDiffResponse,
    } from '$lib/api';

    let newTaskContent = '';
    let preflightWarning: string | null = null;

    // Active job tracking
    let activeJobId: string | null = null;
    let jobStatus: DevTasksStatusResponse | null = null;
    let jobDiff: DevTasksDiffResponse | null = null;
    let pollInterval: ReturnType<typeof setInterval> | null = null;
    let merging = false;
    let rejecting = false;
    let modalElement: HTMLElement;
    let returnFocus: HTMLElement | null = null;
    let wasOpen = false;

    $: if ($devTasksModalOpen && !wasOpen) {
        wasOpen = true;
        returnFocus = document.activeElement as HTMLElement;
        tick().then(() => modalElement?.focus());
    } else if (!$devTasksModalOpen && wasOpen) {
        wasOpen = false;
        returnFocus?.focus();
        returnFocus = null;
    }

    // View mode: 'input' or 'review'
    $: viewMode = activeJobId && jobStatus && ['awaiting_approval', 'failed', 'error'].includes(jobStatus.status)
        ? 'review'
        : 'input';

    function handleAddTask() {
        if (!newTaskContent.trim()) return;
        addDevTask(newTaskContent);
        newTaskContent = '';
    }

    function handleKeydown(e: KeyboardEvent) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleAddTask();
        }
    }

    async function pollJobStatus() {
        if (!activeJobId) return;

        try {
            jobStatus = await getDevTaskStatus(activeJobId);

            // If job is ready for review, fetch diff
            if (['awaiting_approval', 'failed'].includes(jobStatus.status) && !jobDiff) {
                try {
                    jobDiff = await getDevTaskDiff(activeJobId);
                } catch (e) {
                    console.error('Failed to fetch diff:', e);
                }
            }

            // Stop polling when job reaches terminal state
            if (['merged', 'rejected', 'awaiting_approval', 'failed', 'error'].includes(jobStatus.status)) {
                stopPolling();
            }
        } catch (e) {
            console.error('Failed to poll job status:', e);
        }
    }

    function startPolling(jobId: string) {
        activeJobId = jobId;
        pollInterval = setInterval(pollJobStatus, 1500);
        pollJobStatus(); // Immediate first poll
    }

    function stopPolling() {
        if (pollInterval) {
            clearInterval(pollInterval);
            pollInterval = null;
        }
    }

    function resetJobState() {
        stopPolling();
        activeJobId = null;
        jobStatus = null;
        jobDiff = null;
        merging = false;
        rejecting = false;
    }

    async function handleSubmit() {
        if ($devTasks.length === 0) return;

        // Run preflight check
        try {
            const preflight = await preflightDevTasks();
            if (preflight.warning) {
                preflightWarning = preflight.warning;
            }
        } catch (e) {
            // Continue anyway if preflight fails
        }

        devTasksSubmitting.set(true);
        devTasksError.set(null);

        try {
            const response = await submitDevTasks($devTasks.map(t => t.content));

            if (response.job_id) {
                // Connect to terminal stream
                connectToJobStream(response.job_id, 'Dev Tasks');

                // Start polling for status
                startPolling(response.job_id);

                // Clear task input (but keep modal open to show progress)
                clearDevTasks();
            }
        } catch (e) {
            devTasksError.set(e instanceof Error ? e.message : 'Submission failed');
        } finally {
            devTasksSubmitting.set(false);
        }
    }

    async function handleMerge() {
        if (!activeJobId) return;
        merging = true;
        devTasksError.set(null);

        try {
            await mergeDevTask(activeJobId);
            resetJobState();
            closeDevTasksModal();
        } catch (e) {
            devTasksError.set(e instanceof Error ? e.message : 'Merge failed');
        } finally {
            merging = false;
        }
    }

    async function handleReject() {
        if (!activeJobId) return;
        rejecting = true;
        devTasksError.set(null);

        try {
            await rejectDevTask(activeJobId);
            resetJobState();
            closeDevTasksModal();
        } catch (e) {
            devTasksError.set(e instanceof Error ? e.message : 'Reject failed');
        } finally {
            rejecting = false;
        }
    }

    function handleBackdropClick(e: MouseEvent) {
        if (e.target === e.currentTarget) {
            handleClose();
        }
    }

    function handleModalKeydown(e: KeyboardEvent) {
        if (e.key === 'Escape') {
            e.preventDefault();
            handleClose();
            return;
        }
        if (e.key !== 'Tab') return;
        const focusable = Array.from(modalElement.querySelectorAll<HTMLElement>(
            'button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), a[href]',
        ));
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (e.shiftKey && document.activeElement === first) {
            e.preventDefault();
            last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
            e.preventDefault();
            first.focus();
        }
    }

    function handleClose() {
        resetJobState();
        preflightWarning = null;
        closeDevTasksModal();
    }

    function getStatusLabel(status: DevTaskStatus): string {
        switch (status) {
            case 'pending': return 'Setting up...';
            case 'processing': return 'Processing tasks...';
            case 'testing': return 'Running tests...';
            case 'awaiting_approval': return 'Tests passed - Review changes';
            case 'failed': return 'Tests failed - Review changes';
            case 'error': return 'Error occurred';
            case 'merged': return 'Merged';
            case 'rejected': return 'Rejected';
            default: return status;
        }
    }

    function getStatusColor(status: DevTaskStatus): string {
        switch (status) {
            case 'pending':
            case 'processing':
            case 'testing':
                return 'var(--dox-status-running)'; // blue
            case 'awaiting_approval':
                return 'var(--dox-status-output)'; // green
            case 'failed':
            case 'error':
                return 'var(--dox-status-running)'; // red
            case 'merged':
                return 'var(--dox-status-output)'; // green
            case 'rejected':
                return 'var(--dox-text-muted)'; // gray
            default:
                return 'var(--dox-text-muted)';
        }
    }

    onDestroy(() => {
        stopPolling();
    });
</script>

{#if $devTasksModalOpen}
    <div class="modal-backdrop" on:click={handleBackdropClick} role="presentation">
        <div
            class="modal"
            class:wide={viewMode === 'review'}
            bind:this={modalElement}
            role="dialog"
            aria-modal="true"
            aria-labelledby="dev-tasks-title"
            tabindex="-1"
            on:keydown={handleModalKeydown}
        >
            <div class="modal-header">
                <h2 id="dev-tasks-title">Dev Tasks</h2>
                {#if viewMode === 'input'}
                    <span class="subtitle">Request UI/code modifications</span>
                {:else if jobStatus}
                    <span class="status-badge" style="background: {getStatusColor(jobStatus.status)}">
                        {getStatusLabel(jobStatus.status)}
                    </span>
                {/if}
                <button class="close-btn" on:click={handleClose} aria-label="Close Dev Tasks">&times;</button>
            </div>

            {#if viewMode === 'input'}
                <!-- Task Input Mode -->
                <div class="task-input">
                    <textarea
                        bind:value={newTaskContent}
                        on:keydown={handleKeydown}
                        placeholder="Describe a change to make to the web app...&#10;e.g., 'Add a loading spinner to the slide viewer'"
                        rows="3"
                        disabled={$devTasksSubmitting}
                    ></textarea>
                    <button class="add-btn" on:click={handleAddTask} disabled={!newTaskContent.trim() || $devTasksSubmitting}>
                        Add Task
                    </button>
                </div>

                <div class="task-list">
                    {#if $devTasks.length === 0}
                        <div class="empty-state">No tasks added yet</div>
                    {:else}
                        {#each $devTasks as task (task.id)}
                            <div class="task-item">
                                <span class="task-content">{task.content}</span>
                                <button class="remove-btn" on:click={() => removeDevTask(task.id)} aria-label="Remove task">×</button>
                            </div>
                        {/each}
                    {/if}
                </div>

                {#if activeJobId && jobStatus && !['awaiting_approval', 'failed', 'error'].includes(jobStatus.status)}
                    <div class="progress-message">
                        <span class="spinner"></span>
                        {jobStatus.message || getStatusLabel(jobStatus.status)}
                    </div>
                {/if}

                {#if preflightWarning}
                    <div class="warning-message">{preflightWarning}</div>
                {/if}

                {#if $devTasksError}
                    <div class="error-message">{$devTasksError}</div>
                {/if}

                <div class="modal-actions">
                    <button class="clear-btn" on:click={clearDevTasks} disabled={$devTasks.length === 0 || $devTasksSubmitting}>
                        Clear All
                    </button>
                    <button class="cancel-btn" on:click={handleClose}>Cancel</button>
                    <button
                        class="submit-btn"
                        on:click={handleSubmit}
                        disabled={$devTasksSubmitting || $devTasks.length === 0 || !!activeJobId}
                    >
                        {#if $devTasksSubmitting}
                            Processing...
                        {:else}
                            Submit {$devTasks.length} Task{$devTasks.length !== 1 ? 's' : ''}
                        {/if}
                    </button>
                </div>

            {:else}
                <!-- Review Mode -->
                {#if jobStatus}
                    <div class="review-content">
                        {#if jobStatus.diff_stats}
                            <div class="diff-stats">
                                <span class="stat">{jobStatus.diff_stats.files_changed} file{jobStatus.diff_stats.files_changed !== 1 ? 's' : ''} changed</span>
                                <span class="stat additions">+{jobStatus.diff_stats.insertions}</span>
                                <span class="stat deletions">-{jobStatus.diff_stats.deletions}</span>
                            </div>
                        {/if}

                        {#if jobStatus.status === 'failed' && jobStatus.test_results}
                            <div class="test-failure-notice">
                                <strong>Tests failed</strong> - Review output in terminal. You can still merge if the errors are acceptable.
                            </div>
                        {/if}

                        {#if jobDiff}
                            <div class="diff-section">
                                <div class="files-list">
                                    <strong>Changed files:</strong>
                                    {#each jobDiff.files as file}
                                        <div class="file-item">{file}</div>
                                    {/each}
                                </div>

                                <div class="diff-viewer">
                                    <pre>{jobDiff.diff}</pre>
                                </div>
                            </div>
                        {:else}
                            <div class="loading-diff">Loading diff...</div>
                        {/if}
                    </div>

                    {#if $devTasksError}
                        <div class="error-message">{$devTasksError}</div>
                    {/if}

                    <div class="modal-actions review-actions">
                        <button class="reject-btn" on:click={handleReject} disabled={merging || rejecting}>
                            {#if rejecting}
                                Rejecting...
                            {:else}
                                Reject Changes
                            {/if}
                        </button>
                        <button class="merge-btn" on:click={handleMerge} disabled={merging || rejecting}>
                            {#if merging}
                                Merging...
                            {:else}
                                Merge to Main
                            {/if}
                        </button>
                    </div>
                {/if}
            {/if}
        </div>
    </div>
{/if}

<style>
    .modal-backdrop {
        position: fixed;
        inset: 0;
        background: color-mix(in srgb, var(--dox-ink-950) 70%, transparent);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 1000;
    }

    .modal {
        background: var(--dox-surface);
        border: 1px solid var(--dox-rule-strong);
        border-radius: 12px;
        width: 90%;
        max-width: 600px;
        max-height: 80vh;
        display: flex;
        flex-direction: column;
        box-shadow: var(--dox-shadow);
        transition: max-width 0.2s;
    }

    .modal.wide {
        max-width: 900px;
    }

    .modal-header {
        display: flex;
        align-items: center;
        gap: 0.75rem;
        padding: 1rem 1.25rem;
        border-bottom: 1px solid var(--dox-rule-strong);
    }

    .modal-header h2 {
        margin: 0;
        font-size: 1.1rem;
        font-weight: 600;
        color: var(--dox-text-primary);
    }

    .subtitle {
        color: var(--dox-text-muted);
        font-size: 0.85rem;
    }

    .status-badge {
        padding: 0.25rem 0.75rem;
        border-radius: 12px;
        font-size: 0.8rem;
        font-weight: 500;
        color: var(--dox-text-on-running);
    }

    .close-btn {
        margin-left: auto;
        width: 32px;
        height: 32px;
        background: transparent;
        border: none;
        color: var(--dox-text-muted);
        font-size: 1.5rem;
        cursor: pointer;
        border-radius: 6px;
    }

    .close-btn:hover {
        background: var(--dox-rule-strong);
        color: var(--dox-text-primary);
    }

    .task-input {
        padding: 1rem 1.25rem;
        border-bottom: 1px solid var(--dox-rule-strong);
        display: flex;
        flex-direction: column;
        gap: 0.75rem;
    }

    .task-input textarea {
        width: 100%;
        background: var(--dox-ground);
        border: 1px solid var(--dox-rule-strong);
        border-radius: 6px;
        padding: 0.75rem;
        color: var(--dox-text-primary);
        font-family: inherit;
        font-size: 0.9rem;
        resize: vertical;
    }

    .task-input textarea:focus {
        outline: none;
        border-color: var(--dox-ink-900);
    }

    .task-input textarea::placeholder {
        color: var(--dox-text-muted);
    }

    .task-input textarea:disabled {
        opacity: 0.5;
    }

    .add-btn {
        align-self: flex-end;
        padding: 0.5rem 1rem;
        background: var(--dox-ink-900);
        border: none;
        border-radius: 6px;
        color: var(--dox-ink-100);
        font-size: 0.9rem;
        cursor: pointer;
    }

    .add-btn:hover:not(:disabled) {
        background: var(--dox-ink-800);
    }

    .add-btn:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .task-list {
        flex: 1;
        overflow-y: auto;
        padding: 0.75rem 1.25rem;
        min-height: 100px;
        max-height: 250px;
    }

    .empty-state {
        color: var(--dox-text-muted);
        text-align: center;
        padding: 2rem;
        font-size: 0.9rem;
    }

    .task-item {
        display: flex;
        align-items: flex-start;
        gap: 0.75rem;
        padding: 0.75rem;
        background: var(--dox-ground);
        border-radius: 6px;
        margin-bottom: 0.5rem;
    }

    .task-content {
        flex: 1;
        font-size: 0.9rem;
        color: var(--dox-text-primary);
        white-space: pre-wrap;
    }

    .remove-btn {
        width: 24px;
        height: 24px;
        background: transparent;
        border: none;
        color: var(--dox-text-muted);
        font-size: 1.25rem;
        cursor: pointer;
        border-radius: 4px;
        flex-shrink: 0;
    }

    .remove-btn:hover {
        background: var(--dox-rule-strong);
        color: var(--dox-status-running);
    }

    .progress-message {
        margin: 0 1.25rem;
        padding: 0.75rem;
        background: var(--dox-ink-900);
        color: var(--dox-brand-paper-2);
        border-radius: 6px;
        font-size: 0.85rem;
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }

    .spinner {
        width: 14px;
        height: 14px;
        border: 2px solid var(--dox-status-running);
        border-top-color: transparent;
        border-radius: 50%;
        animation: spin 1s linear infinite;
    }

    @keyframes spin {
        to { transform: rotate(360deg); }
    }

    .warning-message {
        margin: 0.5rem 1.25rem 0;
        padding: 0.75rem;
        background: var(--dox-status-warning);
        color: var(--dox-text-on-warning);
        border-radius: 6px;
        font-size: 0.85rem;
    }

    .error-message {
        margin: 0.5rem 1.25rem 0;
        padding: 0.75rem;
        background: var(--dox-status-running);
        color: var(--dox-brand-paper-2);
        border-radius: 6px;
        font-size: 0.85rem;
    }

    .modal-actions {
        display: flex;
        justify-content: flex-end;
        gap: 0.75rem;
        padding: 1rem 1.25rem;
        border-top: 1px solid var(--dox-rule-strong);
    }

    .clear-btn {
        padding: 0.5rem 1rem;
        background: transparent;
        border: 1px solid var(--dox-rule-strong);
        border-radius: 6px;
        color: var(--dox-text-muted);
        font-size: 0.9rem;
        cursor: pointer;
        margin-right: auto;
    }

    .clear-btn:hover:not(:disabled) {
        background: var(--dox-rule-strong);
        color: var(--dox-text-primary);
    }

    .clear-btn:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .cancel-btn {
        padding: 0.5rem 1rem;
        background: transparent;
        border: 1px solid var(--dox-rule-strong);
        border-radius: 6px;
        color: var(--dox-text-secondary);
        font-size: 0.9rem;
        cursor: pointer;
    }

    .cancel-btn:hover {
        background: var(--dox-rule-strong);
    }

    .submit-btn {
        padding: 0.5rem 1.25rem;
        background: var(--dox-ink-900);
        border: none;
        border-radius: 6px;
        color: var(--dox-ink-100);
        font-size: 0.9rem;
        font-weight: 500;
        cursor: pointer;
    }

    .submit-btn:hover:not(:disabled) {
        background: var(--dox-ink-800);
    }

    .submit-btn:disabled {
        opacity: 0.6;
        cursor: not-allowed;
    }

    /* Review Mode Styles */
    .review-content {
        flex: 1;
        overflow-y: auto;
        padding: 1rem 1.25rem;
        display: flex;
        flex-direction: column;
        gap: 1rem;
    }

    .diff-stats {
        display: flex;
        gap: 1rem;
        font-size: 0.85rem;
    }

    .stat {
        color: var(--dox-text-muted);
    }

    .stat.additions {
        color: var(--dox-status-output);
    }

    .stat.deletions {
        color: var(--dox-status-running);
    }

    .test-failure-notice {
        padding: 0.75rem;
        background: var(--dox-status-running);
        color: var(--dox-brand-paper-2);
        border-radius: 6px;
        font-size: 0.85rem;
    }

    .diff-section {
        display: flex;
        flex-direction: column;
        gap: 0.75rem;
    }

    .files-list {
        font-size: 0.85rem;
        color: var(--dox-text-muted);
    }

    .file-item {
        padding: 0.25rem 0;
        color: var(--dox-text-primary);
        font-family: var(--dox-font-mono);
        font-size: 0.8rem;
    }

    .diff-viewer {
        background: var(--dox-ground);
        border: 1px solid var(--dox-rule-strong);
        border-radius: 6px;
        overflow: auto;
        max-height: 350px;
    }

    .diff-viewer pre {
        margin: 0;
        padding: 1rem;
        font-family: var(--dox-font-mono);
        font-size: 0.75rem;
        line-height: 1.5;
        color: var(--dox-text-primary);
        white-space: pre;
    }

    .loading-diff {
        color: var(--dox-text-muted);
        text-align: center;
        padding: 2rem;
    }

    .review-actions {
        justify-content: flex-end;
    }

    .reject-btn {
        padding: 0.5rem 1.25rem;
        background: transparent;
        border: 1px solid var(--dox-status-running);
        border-radius: 6px;
        color: var(--dox-status-running);
        font-size: 0.9rem;
        font-weight: 500;
        cursor: pointer;
    }

    .reject-btn:hover:not(:disabled) {
        background: var(--dox-status-running);
        color: var(--dox-text-on-running);
    }

    .reject-btn:disabled {
        opacity: 0.6;
        cursor: not-allowed;
    }

    .merge-btn {
        padding: 0.5rem 1.25rem;
        background: var(--dox-status-output);
        border: none;
        border-radius: 6px;
        color: var(--dox-text-on-output);
        font-size: 0.9rem;
        font-weight: 500;
        cursor: pointer;
    }

    .merge-btn:hover:not(:disabled) {
        background: var(--dox-brand-gold-hi);
        color: var(--dox-text-on-output);
    }

    .merge-btn:disabled {
        opacity: 0.6;
        cursor: not-allowed;
    }

    @media (max-width: 768px) {
        .modal { width: calc(100% - 1rem); max-height: calc(100vh - 1rem); }
        .modal-actions { flex-wrap: wrap; }
        .modal button { min-height: var(--touch-target-min); }
        .close-btn, .remove-btn { min-width: var(--touch-target-min); }
    }

    @media (prefers-reduced-motion: reduce) {
        .modal { transition: none; }
        .spinner { animation: none; }
    }
</style>
