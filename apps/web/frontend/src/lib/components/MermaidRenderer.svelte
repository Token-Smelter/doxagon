<script lang="ts">
    import { onMount, afterUpdate, onDestroy } from 'svelte';
    import mermaid from 'mermaid';

    // Content prop is used to trigger re-renders when markdown changes
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    export let content: string = '';

    let container: HTMLDivElement;
    let initialized = false;
    let groundObserver: MutationObserver | undefined;

    function configureMermaid() {
        const styles = getComputedStyle(document.body);
        const token = (name: string) => styles.getPropertyValue(name).trim();

        mermaid.initialize({
            startOnLoad: false,
            theme: 'base',
            themeVariables: {
                primaryColor: token('--dox-surface-raised'),
                primaryTextColor: token('--dox-text-primary'),
                primaryBorderColor: token('--dox-rule-strong'),
                lineColor: token('--dox-text-secondary'),
                secondaryColor: token('--dox-surface'),
                tertiaryColor: token('--dox-ground'),
                background: token('--dox-ground'),
                mainBkg: token('--dox-surface-raised'),
                secondBkg: token('--dox-surface'),
                border1: token('--dox-rule-strong'),
                border2: token('--dox-rule'),
                arrowheadColor: token('--dox-text-secondary'),
                fontFamily: token('--dox-font-body'),
                fontSize: '14px',
                textColor: token('--dox-text-primary'),
                nodeTextColor: token('--dox-text-primary')
            },
            flowchart: {
                htmlLabels: true,
                curve: 'basis'
            }
        });
    }

    onMount(() => {
        configureMermaid();
        initialized = true;
        renderDiagrams();
        groundObserver = new MutationObserver(() => {
            configureMermaid();
            void renderDiagrams(true);
        });
        groundObserver.observe(document.body, { attributes: true, attributeFilter: ['class'] });
    });

    afterUpdate(() => {
        if (initialized) {
            renderDiagrams();
        }
    });

    onDestroy(() => groundObserver?.disconnect());

    async function renderSource(wrapper: HTMLElement, code: string) {
        try {
            const id = `mermaid-${Math.random().toString(36).slice(2, 9)}`;
            const { svg } = await mermaid.render(id, code);
            wrapper.className = 'mermaid-diagram';
            wrapper.dataset.mermaidSource = code;
            wrapper.innerHTML = svg;
        } catch (e) {
            console.error('Mermaid render error:', e);
            wrapper.className = 'mermaid-error';
            wrapper.textContent = code;
        }
    }

    async function renderDiagrams(force = false) {
        if (!container) return;

        if (force) {
            const rendered = container.querySelectorAll<HTMLElement>('.mermaid-diagram[data-mermaid-source]');
            await Promise.all(Array.from(rendered, (wrapper) => renderSource(wrapper, wrapper.dataset.mermaidSource || '')));
        }

        const codeBlocks = container.querySelectorAll('pre.mermaid > code, pre.language-mermaid > code, pre > code.language-mermaid');
        for (const block of codeBlocks) {
            const pre = block.parentElement;
            if (!pre || pre.classList.contains('mermaid-rendered')) continue;
            const wrapper = document.createElement('div');
            pre.replaceWith(wrapper);
            await renderSource(wrapper, block.textContent || '');
        }
    }
</script>

<div bind:this={container} class="mermaid-container">
    <slot />
</div>

<style>
    .mermaid-container {
        min-width: 0;
    }

    .mermaid-container :global(.mermaid-diagram) {
        background: var(--dox-surface);
        border: 1px solid var(--dox-rule);
        border-radius: var(--dox-radius);
        padding: 1rem;
        margin: 1rem 0;
        overflow-x: auto;
        overscroll-behavior-inline: contain;
    }

    .mermaid-container :global(.mermaid-diagram svg) {
        display: block;
        max-width: 100%;
        height: auto;
        margin-inline: auto;
    }

    .mermaid-container :global(.mermaid-error) {
        border: 2px dashed var(--dox-status-running);
        border-radius: var(--dox-radius-sm);
        background: color-mix(in srgb, var(--dox-status-running) 10%, var(--dox-surface));
        color: var(--dox-text-primary);
        padding: 0.75rem;
        white-space: pre-wrap;
        overflow-wrap: anywhere;
    }
</style>
