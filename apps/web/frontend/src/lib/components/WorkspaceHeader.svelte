<script lang="ts">
    import { onMount } from 'svelte';
    import { page } from '$app/stores';
    import StoneMark from './StoneMark.svelte';
    import {
        groundPreference,
        initializeGroundPreference,
        toggleGroundPreference,
        workspaceForPath,
        workspaceNavigation,
    } from '$lib/stores/workspace';

    $: activeWorkspace = workspaceForPath($page.url.pathname);

    onMount(initializeGroundPreference);
</script>

<header class="workspace-header" data-ground={$groundPreference}>
    <a class="brand" href="/" aria-label="Token Smelter home">
        <StoneMark size={30} />
        <span class="brand-copy">
            <span class="brand-title">Token Smelter</span>
            <span class="brand-subtitle">Doxagon</span>
        </span>
    </a>

    <nav class="workspace-nav" aria-label="Workspace">
        {#each workspaceNavigation.filter((workspace) => workspace.available) as workspace}
            <a href={workspace.href} aria-current={activeWorkspace === workspace.id ? 'page' : undefined}>
                {workspace.label}
            </a>
        {/each}
    </nav>

    <button
        class="ground-toggle"
        type="button"
        on:click={toggleGroundPreference}
        aria-pressed={$groundPreference === 'nigredo'}
        aria-label={$groundPreference === 'cream' ? 'Use nigredo ground' : 'Use cream ground'}
    >
        <span aria-hidden="true">{$groundPreference === 'cream' ? '◐' : '◑'}</span>
        <span class="ground-label">{$groundPreference === 'cream' ? 'Nigredo' : 'Cream'}</span>
    </button>
</header>

<style>
    .workspace-header {
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto auto;
        align-items: center;
        min-width: 0;
        min-height: 4.125rem;
        padding: 0.65rem clamp(0.75rem, 2vw, 2rem);
        gap: clamp(0.75rem, 2vw, 2rem);
        color: var(--dox-frame-text);
        background: var(--dox-frame-ground);
        border-bottom: 1px solid var(--dox-frame-rule);
        font-family: var(--dox-font-display);
    }

    .brand {
        display: inline-flex;
        align-items: center;
        min-width: 0;
        color: inherit;
        text-decoration: none;
        gap: 0.6rem;
    }

    .brand-copy {
        display: grid;
        min-width: 0;
        line-height: 1;
    }

    .brand-title {
        overflow: hidden;
        font-size: 0.95rem;
        font-weight: 650;
        letter-spacing: var(--dox-tracking-caps);
        text-overflow: ellipsis;
        text-transform: uppercase;
        white-space: nowrap;
    }

    .brand-subtitle {
        margin-top: 0.3rem;
        color: var(--dox-frame-text-muted);
        font-family: var(--dox-font-mono);
        font-size: 0.65rem;
        letter-spacing: var(--dox-tracking-caps);
        text-transform: uppercase;
    }

    .workspace-nav {
        display: flex;
        align-self: stretch;
        align-items: stretch;
        gap: 0.85rem;
    }

    .workspace-nav a {
        display: inline-flex;
        align-items: center;
        min-height: var(--touch-target-min);
        color: var(--dox-frame-text-muted);
        border-bottom: 2px solid transparent;
        font-family: var(--dox-font-mono);
        font-size: 0.72rem;
        letter-spacing: var(--dox-tracking);
        text-decoration: none;
        text-transform: uppercase;
    }

    .workspace-nav a[aria-current='page'] {
        color: var(--dox-frame-text);
        border-bottom-color: var(--dox-frame-text);
    }

    .ground-toggle {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-width: var(--touch-target-min);
        min-height: var(--touch-target-min);
        padding: 0.45rem 0.7rem;
        gap: 0.45rem;
        color: var(--dox-frame-text);
        background: transparent;
        border: 1px solid var(--dox-frame-rule);
        border-radius: var(--dox-radius-sm);
        cursor: pointer;
        font-family: var(--dox-font-mono);
        font-size: 0.72rem;
        letter-spacing: var(--dox-tracking);
        text-transform: uppercase;
    }

    .ground-toggle:hover {
        background: var(--dox-frame-surface-raised);
    }

    @media (max-width: 480px) {
        .workspace-header {
            grid-template-columns: minmax(0, 1fr) auto;
            gap: 0.4rem 0.75rem;
            min-height: 0;
            padding-block: 0.5rem;
        }

        .workspace-nav {
            grid-column: 1 / -1;
            grid-row: 2;
        }

        .workspace-nav a {
            min-height: var(--touch-target-min);
            font-size: 0.66rem;
        }

        .brand {
            min-height: var(--touch-target-min);
        }

        .brand-title {
            font-size: 0.78rem;
        }

        .brand-subtitle,
        .ground-label {
            display: none;
        }

        .ground-toggle {
            padding-inline: 0.45rem;
        }
    }
</style>
