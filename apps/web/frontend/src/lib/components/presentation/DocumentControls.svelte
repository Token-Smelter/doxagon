<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import type { DocumentPosition, DocumentReady } from '$lib/presentation/documentBridge';

    export let ready: DocumentReady | null = null;
    export let position: DocumentPosition | null = null;
    export let connected = false;
    const dispatch = createEventDispatcher<{ next: void; previous: void; go: string }>();
</script>

<div class="document-controls" role="group" aria-label="Document navigation">
    <button type="button" disabled={!connected || position?.index === 0} on:click={() => dispatch('previous')}>Back</button>
    <button type="button" disabled={!connected || position?.index === (ready?.cues.length ?? 0) - 1} on:click={() => dispatch('next')}>Next</button>
    <label>
        <span class="label">Cue</span>
        <select aria-label="Jump to cue" disabled={!connected} value={position?.cue ?? ''} on:change={(event) => dispatch('go', event.currentTarget.value)}>
            {#if !position}<option value="">Waiting for document</option>{/if}
            {#each ready?.cues ?? [] as cue, index (cue.id)}
                <option value={cue.id}>{index + 1}. {cue.title}</option>
            {/each}
        </select>
    </label>
    <output aria-label="Current cue" data-testid="document-cue">{position ? `${position.index + 1} / ${position.total}` : '—'}</output>
</div>

<style>
    .document-controls { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; min-width: 0; }
    button, select { min-height: 44px; border: 1px solid var(--dox-frame-rule, #71695d); border-radius: 4px; color: var(--dox-frame-text, #efe6d2); background: var(--dox-frame-surface, #282219); font: inherit; padding: 0.45rem 0.75rem; }
    button:not(:disabled), select:not(:disabled) { cursor: pointer; }
    button:hover:not(:disabled), select:hover:not(:disabled) { background: var(--dox-frame-surface-raised, #3d382f); }
    :is(button, select):focus-visible { outline: 2px solid var(--dox-frame-text, #efe6d2); outline-offset: 2px; }
    :disabled { opacity: 0.5; }
    label { display: flex; align-items: center; gap: 0.5rem; flex: 1; min-width: 9rem; }
    select { width: 100%; min-width: 0; max-width: 40rem; }
    .label, output { color: var(--dox-frame-text-muted, #b9af9d); font-size: 0.8rem; white-space: nowrap; }
</style>
