<script lang="ts">
    import { tick } from 'svelte';
    import { fetchEdgeDetail, updateEdge, type EdgeDetail, type EdgeType, type EdgeConfidence, type EvidenceStrength } from '../api';
    import { selectedNode } from '../stores/graph';
    import { media } from '../stores/media';

    export let source: string;
    export let target: string;
    export let onClose: () => void;

    let edge: EdgeDetail | null = null;
    let loading = false;
    let error: string | null = null;
    let saving = false;
    let saved = false;

    // Editable fields
    let editType: EdgeType;
    let editAlias: string;
    let editConfidence: EdgeConfidence;
    let editDisputed: boolean;
    let editReviewerNotes: string;

    // Copy state
    let copied = false;
    let panel: HTMLDivElement;
    let returnFocus: HTMLElement | null = null;
    let openedEdge = '';

    $: if (`${source}:${target}` !== openedEdge) {
        if ($media.mobile && typeof document !== 'undefined') returnFocus = document.activeElement as HTMLElement;
        openedEdge = `${source}:${target}`;
        if ($media.mobile) tick().then(() => panel?.focus());
    }

    const edgeTypes: EdgeType[] = ['supports', 'contradicts', 'requires', 'elaborates', 'grounds', 'causes', 'resolves'];
    const confidenceLevels: EdgeConfidence[] = ['high', 'medium', 'low'];

    $: if (source && target) {
        loadEdge(source, target);
    }

    async function loadEdge(s: string, t: string) {
        loading = true;
        error = null;
        try {
            edge = await fetchEdgeDetail(s, t);
            editType = edge.type;
            editAlias = edge.alias || '';
            editConfidence = edge.confidence;
            editDisputed = edge.disputed;
            editReviewerNotes = edge.reviewer_notes || '';
        } catch (e) {
            error = "Failed to load edge details";
        } finally {
            loading = false;
        }
    }

    async function saveChanges() {
        if ($media.mobile) return; // Read-only on mobile — mutation guard
        if (!edge) return;
        saving = true;
        try {
            await updateEdge(source, target, {
                type: editType,
                alias: editAlias || undefined,
                confidence: editConfidence,
                disputed: editDisputed,
                reviewer_notes: editReviewerNotes || undefined,
            });
            saved = true;
            setTimeout(() => saved = false, 2000);
            // Reload to get updated data
            await loadEdge(source, target);
        } catch (e) {
            error = "Failed to save changes";
        } finally {
            saving = false;
        }
    }

    function close() {
        onClose();
        if ($media.mobile) tick().then(() => returnFocus?.focus());
    }

    function goToNode(slug: string) {
        selectedNode.set(slug);
        close();
    }

    async function copyMetadata() {
        if (!edge) return;

        const metadata = `Edge: ${source} → ${target}
Type: ${edge.type}${edge.alias ? ` ("${edge.alias}")` : ''}
Confidence: ${edge.confidence}
Strength: ${edge.strength}
${edge.disputed ? 'Disputed: yes\n' : ''}
Rationale:
${edge.rationale || edge.annotation || '(none)'}
${edge.reviewer_notes ? `\nReviewer Notes:\n${edge.reviewer_notes}` : ''}
${edge.provenance?.method ? `\nProvenance: ${edge.provenance.method}${edge.provenance.phantasia ? ` (${edge.provenance.phantasia})` : ''}` : ''}`;

        await navigator.clipboard.writeText(metadata);
        copied = true;
        setTimeout(() => copied = false, 1500);
    }
</script>

<div bind:this={panel} class="edge-panel" class:mobile={$media.mobile} role={$media.mobile ? 'dialog' : 'complementary'} aria-modal={$media.mobile ? 'true' : undefined} aria-label="Edge details" tabindex="-1">
    <div class="header">
        <h3>Edge Details</h3>
        <div class="header-controls">
            <button
                class="copy-btn"
                class:copied
                on:click={copyMetadata}
                title="Copy edge metadata"
                aria-label={copied ? 'Edge metadata copied' : 'Copy edge metadata'}
            >
                {copied ? '✓' : '⎘'}
            </button>
            <button class="close-btn" on:click={close} title="Close">×</button>
        </div>
    </div>

    <div class="content">
        {#if loading}
            <p>Loading...</p>
        {:else if error}
            <p class="error">{error}</p>
        {:else if edge}
            <div class="edge-path">
                <button class="node-link" on:click={() => goToNode(source)}>{source}</button>
                <span class="arrow">→</span>
                <span class="edge-type {edge.type}">{edge.type}</span>
                <span class="arrow">→</span>
                <button class="node-link" on:click={() => goToNode(target)}>{target}</button>
            </div>

            {#if edge.alias || editAlias}
            <div class="alias-display">
                <span class="alias-text">"{editAlias || edge.alias}"</span>
            </div>
            {/if}

            <div class="section">
                <h4>Rationale</h4>
                <p class="rationale">{edge.rationale || edge.annotation || '(No rationale provided)'}</p>
            </div>

            <div class="section">
                <h4>Metadata</h4>
                <div class="meta-grid">
                    <span class="meta-label">Type</span>
                    {#if $media.mobile}
                        <span class="value">{edge.type}</span>
                    {:else}
                        <select bind:value={editType} aria-label="Edge type">
                            {#each edgeTypes as t}
                                <option value={t}>{t}</option>
                            {/each}
                        </select>
                    {/if}

                    <span class="meta-label">Alias</span>
                    {#if $media.mobile}
                        <span class="value">{edge.alias || '—'}</span>
                    {:else}
                        <input
                            type="text"
                            bind:value={editAlias}
                            aria-label="Edge alias"
                            placeholder="e.g., 'enables', 'contradicts by showing'"
                        />
                    {/if}

                    <span class="meta-label">Confidence</span>
                    {#if $media.mobile}
                        <span class="value">{edge.confidence}</span>
                    {:else}
                        <select bind:value={editConfidence} aria-label="Edge confidence">
                            {#each confidenceLevels as c}
                                <option value={c}>{c}</option>
                            {/each}
                        </select>
                    {/if}

                    <span class="meta-label">Strength</span>
                    <span class="value">{edge.strength}</span>

                    <span class="meta-label">Disputed</span>
                    {#if $media.mobile}
                        <span class="value">{edge.disputed ? 'Yes' : 'No'}</span>
                    {:else}
                        <label class="checkbox">
                            <input type="checkbox" bind:checked={editDisputed} />
                            Flag for review
                        </label>
                    {/if}
                </div>
            </div>

            {#if !$media.mobile}
                <div class="section">
                    <h4>Reviewer Notes</h4>
                    <textarea
                        bind:value={editReviewerNotes}
                        placeholder="Add notes about this edge..."
                        rows="3"
                    ></textarea>
                </div>

                <div class="actions">
                    <button
                        class="save-btn"
                        class:saved
                        on:click={saveChanges}
                        disabled={saving}
                    >
                        {#if saving}
                            Saving...
                        {:else if saved}
                            ✓ Saved
                        {:else}
                            Save Changes
                        {/if}
                    </button>
                </div>
            {:else if edge.reviewer_notes}
                <div class="section">
                    <h4>Reviewer Notes</h4>
                    <p class="rationale">{edge.reviewer_notes}</p>
                </div>
            {/if}

            <div class="section provenance">
                <h4>Provenance</h4>
                <p>
                    <strong>Method:</strong> {edge.provenance?.method || 'unknown'}
                    {#if edge.provenance?.phantasia}
                        <br /><strong>Phantasia:</strong> {edge.provenance.phantasia}
                    {/if}
                    {#if edge.created}
                        <br /><strong>Created:</strong> {edge.created}
                    {/if}
                </p>
            </div>
        {/if}
    </div>
</div>

<style>
    .edge-panel {
        position: absolute;
        top: 60px;
        right: 0;
        bottom: 0;
        width: 420px;
        min-width: 0;
        background: var(--dox-surface);
        color: var(--dox-text-primary);
        border-left: 1px solid var(--dox-rule);
        display: flex;
        flex-direction: column;
        box-shadow: var(--dox-shadow);
        z-index: 100;
    }

    /* Mobile bottom sheet */
    .edge-panel.mobile {
        position: fixed;
        top: auto;
        right: 0;
        bottom: 0;
        left: 0;
        width: 100%;
        max-height: var(--bottom-sheet-max-height, 60vh);
        border-left: none;
        border-top: 1px solid var(--dox-rule);
        border-radius: 12px 12px 0 0;
        box-shadow: var(--dox-shadow);
        z-index: var(--z-bottom-sheet, 220);
        padding-bottom: env(safe-area-inset-bottom);
    }

    @media (max-width: 768px) {
        .edge-panel .meta-grid {
            grid-template-columns: 1fr;
            gap: 0.5rem;
        }
        .edge-panel .node-link,
        .edge-panel .header-controls button {
            min-width: var(--touch-target-min, 44px);
            min-height: var(--touch-target-min, 44px);
            display: inline-flex;
            align-items: center;
        }
        .edge-panel .content {
            padding: 0.75rem;
        }
    }

    .header {
        padding: 0.5rem 1rem;
        background: var(--dox-surface-raised);
        border-bottom: 1px solid var(--dox-rule);
        display: flex;
        justify-content: space-between;
        align-items: center;
    }
    .header h3 {
        margin: 0;
        font-size: 0.95rem;
    }
    .header-controls {
        display: flex;
        gap: 0.25rem;
        align-items: center;
    }
    .copy-btn {
        width: 28px;
        height: 28px;
        border: 1px solid var(--dox-rule-strong);
        border-radius: var(--dox-radius-sm);
        background: transparent;
        color: var(--dox-text-primary);
        font-size: 1.1rem;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
    }
    .copy-btn:hover {
        background: var(--dox-surface-raised);
    }
    .copy-btn.copied {
        border-color: var(--dox-status-neutral);
    }
    .close-btn {
        width: 28px;
        height: 28px;
        border: 1px solid var(--dox-rule-strong);
        border-radius: var(--dox-radius-sm);
        background: transparent;
        color: var(--dox-text-primary);
        font-size: 1.1rem;
        cursor: pointer;
    }
    .close-btn:hover {
        border-color: var(--dox-status-running);
        background: var(--dox-surface-raised);
    }
    .content {
        padding: 1rem;
        overflow-y: auto;
        flex: 1;
    }
    .edge-path {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        flex-wrap: wrap;
        margin-bottom: 1rem;
        padding: 0.75rem;
        background: var(--dox-surface-raised);
        border: 1px solid var(--dox-rule);
        border-radius: var(--dox-radius);
    }
    .node-link {
        background: transparent;
        border: 1px solid var(--dox-rule-strong);
        color: var(--dox-text-primary);
        padding: 0.25rem 0.5rem;
        border-radius: 4px;
        cursor: pointer;
        font-size: 0.85rem;
    }
    .node-link:hover {
        background: var(--dox-surface-raised);
    }
    .arrow {
        color: var(--dox-text-muted);
    }
    .edge-type {
        padding: 0.25rem 0.5rem;
        border-radius: 4px;
        font-size: 0.8rem;
        font-weight: bold;
        text-transform: uppercase;
    }
    .edge-type {
        border: 1px solid var(--dox-rule-strong);
        color: var(--dox-text-primary);
    }
    .edge-type.contradicts {
        border: 2px dashed var(--dox-status-running);
    }
    .edge-type.requires {
        border-width: 2px;
    }

    .alias-display {
        margin-bottom: 1rem;
        padding: 0.5rem 0.75rem;
        background: var(--dox-surface-raised);
        border: 1px solid var(--dox-rule);
        border-radius: var(--dox-radius-sm);
    }
    .alias-text {
        color: var(--dox-text-secondary);
        font-style: italic;
        font-size: 0.95rem;
    }

    .section {
        margin-bottom: 1.25rem;
    }
    .section h4 {
        margin: 0 0 0.5rem 0;
        font-size: 0.85rem;
        color: var(--dox-text-muted);
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    .rationale {
        margin: 0;
        line-height: 1.5;
        color: var(--dox-text-secondary);
    }
    .meta-grid {
        display: grid;
        grid-template-columns: auto 1fr;
        gap: 0.5rem 1rem;
        align-items: center;
    }
    .meta-label {
        font-size: 0.85rem;
        color: var(--dox-text-muted);
    }
    .meta-grid select,
    .meta-grid input[type="text"] {
        background: var(--dox-ground);
        border: 1px solid var(--dox-rule-strong);
        color: var(--dox-text-primary);
        padding: 0.35rem 0.5rem;
        border-radius: 4px;
    }
    .meta-grid input[type="text"] {
        font-family: inherit;
    }
    .meta-grid .value {
        color: var(--dox-text-primary);
    }
    .checkbox {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        cursor: pointer;
    }
    .checkbox input {
        width: 16px;
        height: 16px;
    }
    textarea {
        width: 100%;
        background: var(--dox-ground);
        border: 1px solid var(--dox-rule-strong);
        color: var(--dox-text-primary);
        padding: 0.5rem;
        border-radius: 4px;
        resize: vertical;
        font-family: inherit;
    }
    .provenance p {
        margin: 0;
        font-size: 0.85rem;
        color: var(--dox-text-muted);
        line-height: 1.6;
    }
    .actions {
        margin-top: 1rem;
        padding-top: 1rem;
        border-top: 1px solid var(--dox-rule);
    }
    .save-btn {
        width: 100%;
        padding: 0.6rem;
        border: 1px solid var(--dox-rule-strong);
        border-radius: var(--dox-radius-sm);
        background: var(--dox-text-primary);
        color: var(--dox-ground);
        font-size: 0.9rem;
        cursor: pointer;
    }
    .save-btn:hover:not(:disabled) {
        opacity: 0.85;
    }
    .save-btn:disabled {
        opacity: 0.6;
        cursor: not-allowed;
    }
    .save-btn.saved {
        outline: 2px solid var(--dox-status-neutral);
    }
    .error {
        color: var(--dox-status-running);
        font-weight: 700;
    }

    .edge-panel :is(button, input, select, textarea):focus-visible {
        outline: 2px solid var(--dox-focus);
        outline-offset: 2px;
    }

    @media (prefers-reduced-motion: reduce) {
        .edge-panel * {
            scroll-behavior: auto;
            transition: none;
        }
    }
</style>
