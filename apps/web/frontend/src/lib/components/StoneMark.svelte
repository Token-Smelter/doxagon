<script lang="ts">
    export let title = 'Doxagon Stone';
    export let size = 32;
</script>

<svg
    class="stone-mark"
    width={size}
    height={size}
    viewBox="0 0 48 48"
    role="img"
    aria-label={title}
>
    <circle class="ring" cx="24" cy="24" r="20" />
    <rect class="square" x="14" y="14" width="20" height="20" />
    <path class="triangle" d="M24 12 36 34H12Z" />
    <circle class="core" cx="24" cy="24" r="6" />
</svg>

<style>
    .stone-mark {
        display: block;
        flex: none;
    }

    .ring,
    .square,
    .triangle,
    .core {
        fill: none;
        stroke: var(--dox-accent);
        stroke-width: 2;
        vector-effect: non-scaling-stroke;
    }

    .core {
        fill: var(--dox-accent);
    }
</style>
