<script lang="ts">
    import { createEventDispatcher, onMount } from 'svelte';

    export let value: string = '';
    export let placeholder: string = 'Click to edit...';
    export let multiline: boolean = false;
    export let label: string | null = null;
    export let onSave: (value: string) => Promise<void>;

    let editing = false;
    let editValue = '';
    let saving = false;
    let error: string | null = null;
    let saved = false;
    let inputElement: HTMLInputElement | HTMLTextAreaElement;
    let viewElement: HTMLButtonElement;
    let capturedHeight: number | null = null;

    function startEdit() {
        // Capture the current height before switching to edit mode
        if (viewElement && multiline) {
            capturedHeight = viewElement.offsetHeight;
        }
        editValue = value || '';
        editing = true;
        error = null;
        // Focus after DOM updates
        setTimeout(() => {
            if (inputElement) {
                inputElement.focus();
                inputElement.select();
            }
        }, 0);
    }

    async function saveEdit() {
        if (saving) return;

        // Don't save if unchanged
        if (editValue === value) {
            editing = false;
            return;
        }

        saving = true;
        error = null;

        try {
            await onSave(editValue);
            editing = false;
            capturedHeight = null;
            saved = true;
            setTimeout(() => saved = false, 2000);
        } catch (e) {
            error = e instanceof Error ? e.message : 'Failed to save';
        } finally {
            saving = false;
        }
    }

    function cancelEdit() {
        editing = false;
        error = null;
        editValue = '';
        capturedHeight = null;
    }

    function handleKeydown(event: KeyboardEvent) {
        if (event.key === 'Escape') {
            event.preventDefault();
            event.stopPropagation();
            cancelEdit();
        } else if (event.key === 'Enter') {
            if (multiline) {
                // Cmd/Ctrl+Enter to save in multiline mode
                if (event.metaKey || event.ctrlKey) {
                    event.preventDefault();
                    event.stopPropagation();
                    saveEdit();
                }
                // Plain Enter creates newline (default behavior)
            } else {
                // Enter saves in single-line mode
                event.preventDefault();
                event.stopPropagation();
                saveEdit();
            }
        }
    }

    function handleBlur() {
        // If already exited edit mode (e.g., via Escape key), don't do anything
        if (!editing) return;

        // Save on blur if there are changes, otherwise just close
        if (editValue !== value && !saving) {
            saveEdit();
        } else if (!saving) {
            cancelEdit();
        }
    }
</script>

<div class="editable-field" class:editing class:multiline>
    {#if label}
        <label class="field-label">{label}</label>
    {/if}

    {#if editing}
        <div class="edit-container">
            {#if multiline}
                <textarea
                    bind:this={inputElement}
                    bind:value={editValue}
                    on:keydown={handleKeydown}
                    on:blur={handleBlur}
                    disabled={saving}
                    {placeholder}
                    class="edit-input"
                    class:saving
                    style={capturedHeight ? `height: ${capturedHeight}px;` : ''}
                ></textarea>
            {:else}
                <input
                    type="text"
                    bind:this={inputElement}
                    bind:value={editValue}
                    on:keydown={handleKeydown}
                    on:blur={handleBlur}
                    disabled={saving}
                    {placeholder}
                    class="edit-input"
                    class:saving
                />
            {/if}
            <div class="edit-actions">
                {#if saving}
                    <span class="saving-indicator">Saving...</span>
                {:else}
                    <span class="edit-hint">
                        {multiline ? 'Cmd+Enter to save' : 'Enter to save'} · Esc to cancel
                    </span>
                {/if}
            </div>
            {#if error}
                <div class="edit-error">{error}</div>
            {/if}
        </div>
    {:else}
        <button
            bind:this={viewElement}
            class="view-content"
            class:empty={!value}
            class:multiline
            on:click={startEdit}
            title="Click to edit"
        >
            {#if value}
                {#if multiline}
                    <pre class="content-text">{value}</pre>
                {:else}
                    <span class="content-text">{value}</span>
                {/if}
            {:else}
                <span class="placeholder-text">{placeholder}</span>
            {/if}
            {#if saved}
                <span class="saved-icon">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline points="20 6 9 17 4 12"></polyline>
                    </svg>
                </span>
            {:else}
                <span class="edit-icon">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                        <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                    </svg>
                </span>
            {/if}
        </button>
    {/if}
</div>

<style>
    .editable-field {
        position: relative;
    }

    .field-label {
        display: block;
        font-size: 0.75rem;
        color: var(--dox-text-muted);
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin-bottom: 0.35rem;
    }

    /* View mode */
    .view-content {
        display: flex;
        align-items: flex-start;
        gap: 0.5rem;
        width: 100%;
        padding: 0.5rem 0.75rem;
        background: transparent;
        border: 1px solid transparent;
        border-radius: 6px;
        text-align: left;
        cursor: text;
        transition: all 0.15s;
        color: var(--dox-text-primary);
        font-size: inherit;
        font-family: inherit;
        line-height: 1.5;
    }

    .view-content:hover {
        background: color-mix(in srgb, var(--dox-text-primary) 3%, transparent);
        border-color: var(--dox-rule-strong);
    }

    .view-content:hover .edit-icon {
        opacity: 1;
    }

    .view-content.empty {
        color: var(--dox-rule-strong);
    }

    .view-content.multiline {
        align-items: flex-start;
    }

    .content-text {
        flex: 1;
        margin: 0;
        white-space: pre-wrap;
        word-break: break-word;
        font-family: inherit;
        font-size: inherit;
    }

    .view-content.multiline .content-text {
        font-family: var(--dox-font-mono);
        font-size: 0.85rem;
    }

    .placeholder-text {
        flex: 1;
        font-style: italic;
    }

    .edit-icon {
        flex-shrink: 0;
        color: var(--dox-rule-strong);
        opacity: 0;
        transition: opacity 0.15s;
    }

    .saved-icon {
        flex-shrink: 0;
        color: var(--dox-status-output);
        opacity: 1;
        animation: fade-out 2s ease-out forwards;
    }

    @keyframes fade-out {
        0%, 70% { opacity: 1; }
        100% { opacity: 0; }
    }

    /* Edit mode */
    .edit-container {
        display: flex;
        flex-direction: column;
        gap: 0.35rem;
        max-width: 100%;
        overflow: hidden;
    }

    .edit-input {
        width: 100%;
        padding: 0.5rem 0.75rem;
        background: var(--dox-ground);
        border: 1px solid var(--dox-rule-strong);
        border-radius: var(--dox-radius-sm);
        color: var(--dox-text-primary);
        font-size: inherit;
        font-family: inherit;
        line-height: 1.5;
        outline: none;
        transition: border-color 0.15s;
        box-sizing: border-box;
    }

    .edit-input:focus {
        border-color: var(--dox-focus);
    }

    .edit-input.saving {
        opacity: 0.6;
        cursor: wait;
    }

    textarea.edit-input {
        min-height: 60px;
        resize: none;
        font-family: var(--dox-font-mono);
        font-size: 0.85rem;
        overflow-y: auto;
        box-sizing: border-box;
    }

    .edit-actions {
        display: flex;
        justify-content: flex-end;
    }

    .edit-hint {
        font-size: 0.7rem;
        color: var(--dox-text-muted);
    }

    .saving-indicator {
        font-size: 0.75rem;
        color: var(--dox-text-primary);
    }

    .edit-error {
        background: var(--dox-status-running);
        color: var(--dox-brand-paper-2);
        padding: 0.35rem 0.5rem;
        border-radius: 4px;
        font-size: 0.75rem;
    }

    @media (max-width: 768px) {
        .view-content, .edit-input { min-height: var(--touch-target-min); }
    }

    @media (prefers-reduced-motion: reduce) {
        .view-content, .edit-icon, .edit-input { transition: none; }
        .saved-icon { animation: none; }
    }
</style>
