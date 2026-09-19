<script lang="ts">
    import WorkspaceHeader from '$lib/components/WorkspaceHeader.svelte';
</script>

<div class="workspace-shell">
    <WorkspaceHeader />
    <div class="workspace-route">
        <slot />
    </div>
</div>

<style>
    .workspace-shell {
        display: flex;
        flex-direction: column;
        min-width: 0;
        height: 100svh;
        min-height: 100svh;
        overflow-x: clip;
        background: var(--dox-frame-ground);
        color: var(--dox-frame-text);
    }

    .workspace-route {
        display: flex;
        flex: 1;
        flex-direction: column;
        min-width: 0;
        min-height: 0;
    }
</style>
