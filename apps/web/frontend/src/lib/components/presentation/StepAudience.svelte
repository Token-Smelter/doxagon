<script lang="ts">
    /**
     * The audience display.
     *
     * It joins the presenter's server session and adopts only server-issued
     * snapshots, so it renders exactly the Step the session names — the same
     * runtime, the same registered bytes, the same revision pin the editor
     * previews and the exporters capture. It originates no cursor and offers
     * no control, because a second cursor authority is the bug this replaces.
     */
    import { createEventDispatcher, onDestroy, onMount } from 'svelte';
    import CheckpointPreview from '$lib/components/deck/CheckpointPreview.svelte';
    import type { DeckPayload, PresentationClient } from '$lib/presentation/deck';

    export let client: PresentationClient;
    export let deck: DeckPayload | null = null;
    export let sessionId: string;
    /** Where the presenter view lives, offered when its window was blocked. */
    export let presenterUrl: string | null = null;

    const dispatch = createEventDispatcher<{ close: void }>();

    let surface: HTMLElement;

    function onKeydown(event: KeyboardEvent) {
        if (event.key === 'Escape') dispatch('close');
    }

    onMount(() => {
        window.addEventListener('keydown', onKeydown);
        surface?.focus();
    });

    onDestroy(() => window.removeEventListener('keydown', onKeydown));
</script>

<section
    class="audience"
    role="dialog"
    aria-modal="true"
    aria-label="Audience display"
    data-testid="audience-display"
    tabindex="-1"
    bind:this={surface}
>
    <button type="button" class="audience-exit" on:click={() => dispatch('close')}>Exit presentation</button>
    {#if presenterUrl !== null}
        <p class="audience-notice" role="alert" data-testid="presenter-blocked">
            The presenter window was blocked by this browser.
            <a href={presenterUrl} target="presenter" rel="opener">Open the presenter view</a>
            for notes and controls.
        </p>
    {/if}
    <div class="audience-stage">
        <CheckpointPreview {client} {deck} {sessionId} follow controls={false} readout={false} />
    </div>
</section>

<style>
    .audience {
        position: fixed;
        inset: 0;
        z-index: var(--z-modal, 900);
        display: grid;
        place-items: center;
        /* The shell owns the viewport; a fixed overlay is positioned against
           it by `inset`, not by re-declaring a viewport height. Declaring the
           overlay a size container is what lets the stage below be measured
           against *this* box: `cqh` resolves to the overlay's own height, so no
           descendant needs a viewport unit to size itself. */
        container-type: size;
        background: var(--dox-brand-nigredo, #0b0b0d);
    }

    .audience:focus-visible { outline: 2px solid var(--dox-frame-text); outline-offset: -4px; }

    .audience-stage {
        display: grid;
        /* Sized from the containing overlay, never from the viewport: the stage
           is as wide as a 16:9 frame of the overlay's own height allows, and
           never wider than the overlay itself. */
        width: min(100%, calc((100cqh - 4rem) * 16 / 9));
        max-width: 100%;
        padding: 1rem;
        box-sizing: border-box;
    }

    .audience-exit {
        position: absolute;
        top: 1rem;
        right: 1rem;
        min-height: 44px;
        padding: 0 0.75rem;
        color: var(--dox-frame-text);
        background: color-mix(in srgb, var(--dox-frame-text) 12%, transparent);
        border: 1px solid var(--dox-frame-rule, currentColor);
        border-radius: 2px;
        font: inherit;
        cursor: pointer;
    }

    .audience-exit:focus-visible { outline: 2px solid var(--dox-frame-text); outline-offset: 1px; }

    .audience-notice {
        position: absolute;
        top: 1rem;
        left: 1rem;
        right: 12rem;
        margin: 0;
        padding: 0.6rem 0.8rem;
        color: var(--dox-frame-text);
        background: color-mix(in srgb, var(--dox-frame-text) 12%, transparent);
        border: 1px solid var(--dox-frame-rule, currentColor);
        border-radius: 2px;
        font-size: 0.9rem;
    }

    .audience-notice a { color: inherit; font-weight: 600; }
</style>
