<script lang="ts">
    import { createEventDispatcher, onMount } from 'svelte';
    import type { DocumentPosition, DocumentReady } from '$lib/presentation/documentBridge';

    export let ready: DocumentReady | null = null;
    export let position: DocumentPosition | null = null;
    export let connected = false;
    export let expandableCues = false;
    let picker: HTMLDetailsElement;
    let trigger: HTMLElement;
    let cuesOpen = false;
    $: if (!connected) cuesOpen = false;

    function closeCues() {
        cuesOpen = false;
        trigger?.focus();
    }

    function leaveCues(event: FocusEvent) {
        if (!picker.contains(event.relatedTarget as Node)) cuesOpen = false;
    }

    onMount(() => {
        if (!expandableCues) return;
        // The notes controls live in a separate window, not the player's document.
        const owner = picker.ownerDocument;
        const dismiss = (event: PointerEvent) => {
            if (!picker.contains(event.target as Node)) cuesOpen = false;
        };
        owner.addEventListener('pointerdown', dismiss);
        return () => owner.removeEventListener('pointerdown', dismiss);
    });
    const dispatch = createEventDispatcher<{ next: void; previous: void; go: string }>();
</script>

<div class="document-controls" role="group" aria-label="Document navigation">
    <button type="button" disabled={!connected || position?.index === 0} on:click={() => dispatch('previous')}>Back</button>
    <button type="button" disabled={!connected || position?.index === (ready?.cues.length ?? 0) - 1} on:click={() => dispatch('next')}>Next</button>
    {#if expandableCues}
        <div class="cue-picker">
            <span class="label">Cue</span>
            <details bind:this={picker} bind:open={cuesOpen} on:keydown={(event) => {
                if (event.key === 'Escape' && cuesOpen) {
                    event.preventDefault();
                    event.stopPropagation();
                    closeCues();
                }
            }} on:focusout={leaveCues}>
                <summary bind:this={trigger} aria-label="Jump to cue" aria-disabled={!connected} on:click={(event) => { if (!connected) event.preventDefault(); }}>
                    {position ? `${position.index + 1}. ${ready?.cues[position.index]?.title ?? position.cue}` : 'Waiting for document'}
                </summary>
                {#if connected}
                    <ul aria-label="Cues">
                        {#each ready?.cues ?? [] as cue, index (cue.id)}
                            <li><button type="button" aria-current={position?.cue === cue.id ? 'step' : undefined} on:click={() => {
                                dispatch('go', cue.id);
                                closeCues();
                            }}>{index + 1}. {cue.title}</button></li>
                        {/each}
                    </ul>
                {/if}
            </details>
        </div>
    {:else}
    <label>
        <span class="label">Cue</span>
        <select aria-label="Jump to cue" disabled={!connected} value={position?.cue ?? ''} on:change={(event) => dispatch('go', event.currentTarget.value)}>
            {#if !position}<option value="">Waiting for document</option>{/if}
            {#each ready?.cues ?? [] as cue, index (cue.id)}
                <option value={cue.id}>{index + 1}. {cue.title}</option>
            {/each}
        </select>
    </label>
    {/if}
    <output aria-label="Current cue" data-testid="document-cue">{position ? `${position.index + 1} / ${position.total}` : '—'}</output>
</div>

<style>
    .document-controls { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; min-width: 0; }
    button, select, summary { min-height: 44px; border: 1px solid var(--dox-frame-rule, #71695d); border-radius: 4px; color: var(--dox-frame-text, #efe6d2); background: var(--dox-frame-surface, #282219); font: inherit; padding: 0.45rem 0.75rem; }
    button:not(:disabled), select:not(:disabled), summary:not([aria-disabled="true"]) { cursor: pointer; }
    button:hover:not(:disabled), select:hover:not(:disabled), summary:hover:not([aria-disabled="true"]) { background: var(--dox-frame-surface-raised, #3d382f); }
    :is(button, select, summary):focus-visible { outline: 2px solid var(--dox-frame-text, #efe6d2); outline-offset: 2px; }
    :disabled, [aria-disabled="true"] { opacity: 0.5; }
    .cue-picker { display: flex; align-items: center; gap: 0.5rem; flex: 1; min-width: 9rem; }
    details { position: relative; flex: 1; min-width: 0; max-width: 40rem; }
    summary { box-sizing: border-box; overflow-wrap: anywhere; }
    ul { position: absolute; top: 100%; inset-inline: 0; z-index: 1; max-height: min(20rem, 50dvh); overflow-y: auto; margin: 0.25rem 0 0; padding: 0.25rem; list-style: none; border: 1px solid var(--dox-frame-rule, #71695d); border-radius: 4px; background: var(--dox-frame-surface, #282219); box-shadow: 0 8px 20px rgb(0 0 0 / 0.25); scrollbar-color: var(--dox-frame-text-muted, #b9af9d) var(--dox-frame-surface, #282219); }
    li button { width: 100%; text-align: left; overflow-wrap: anywhere; border-color: transparent; }
    li button[aria-current="step"] { border-color: var(--dox-frame-text-muted, #b9af9d); }
    label { display: flex; align-items: center; gap: 0.5rem; flex: 1; min-width: 9rem; }
    select { width: 100%; min-width: 0; max-width: 40rem; }
    .label, output { color: var(--dox-frame-text-muted, #b9af9d); font-size: 0.8rem; white-space: nowrap; }
</style>
