<script lang="ts">
    import type { GenerateImageOptions, ImageResolution } from '$lib/api';

    export let generating: boolean = false;
    export let status: string = '';
    export let defaultResolution: ImageResolution = '2k';
    export let defaultAspectRatio: string = '16:9';
    export let defaultVersions: number = 1;
    export let onGenerate: (options?: GenerateImageOptions) => void;

    let dropdownOpen = false;

    // Local state for options
    let resolution: ImageResolution = defaultResolution;
    let aspectRatio: string = defaultAspectRatio;
    let versions: number = defaultVersions;

    // Update defaults when props change
    $: resolution = defaultResolution;
    $: aspectRatio = defaultAspectRatio;
    $: versions = defaultVersions;

    const resolutions: { value: ImageResolution; label: string }[] = [
        { value: '1k', label: '1K (1024×576)' },
        { value: '2k', label: '2K (1920×1080)' },
        { value: '4k', label: '4K (3840×2160)' },
    ];

    const aspectRatios = [
        { value: '16:9', label: '16:9 (Landscape)' },
        { value: '4:3', label: '4:3 (Standard)' },
        { value: '1:1', label: '1:1 (Square)' },
        { value: '9:16', label: '9:16 (Portrait)' },
    ];

    const versionOptions = [
        { value: 1, label: '1 image' },
        { value: 2, label: '2 images' },
        { value: 3, label: '3 images' },
        { value: 4, label: '4 images' },
    ];

    function handleMainClick() {
        if (generating) return;
        onGenerate(); // Use defaults from definition.md
    }

    function handleGenerateWithOptions() {
        if (generating) return;
        dropdownOpen = false;
        onGenerate({ resolution, aspect_ratio: aspectRatio, versions });
    }

    function toggleDropdown(e: MouseEvent) {
        e.stopPropagation();
        if (!generating) {
            dropdownOpen = !dropdownOpen;
        }
    }

    function closeDropdown() {
        dropdownOpen = false;
    }

    function getButtonText(): string {
        if (status === 'assembling') return 'Assembling...';
        if (status === 'generating') return 'Generating...';
        return 'Generate';
    }
</script>

<svelte:window on:click={closeDropdown} />

<div class="generate-button-container">
    <div class="split-button" class:generating class:open={dropdownOpen}>
        <button
            class="main-btn"
            disabled={generating}
            on:click={handleMainClick}
            title="Generate image with default settings"
        >
            {getButtonText()}
        </button>
        <button
            class="dropdown-btn"
            disabled={generating}
            on:click={toggleDropdown}
            title="Generation options"
            aria-label="Generation options"
            aria-expanded={dropdownOpen}
        >
            <svg width="10" height="6" viewBox="0 0 10 6" fill="currentColor">
                <path d="M1 1l4 4 4-4" stroke="currentColor" stroke-width="1.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
        </button>
    </div>

    {#if dropdownOpen}
        <div class="dropdown-menu" on:click|stopPropagation role="group" aria-label="Generation options">
            <div class="dropdown-section">
                <label class="dropdown-label">Resolution</label>
                <div class="option-group">
                    {#each resolutions as opt}
                        <button
                            class="option-btn"
                            class:selected={resolution === opt.value}
                            on:click={() => resolution = opt.value}
                        >
                            {opt.label}
                        </button>
                    {/each}
                </div>
            </div>

            <div class="dropdown-section">
                <label class="dropdown-label">Aspect Ratio</label>
                <div class="option-group">
                    {#each aspectRatios as opt}
                        <button
                            class="option-btn"
                            class:selected={aspectRatio === opt.value}
                            on:click={() => aspectRatio = opt.value}
                        >
                            {opt.label}
                        </button>
                    {/each}
                </div>
            </div>

            <div class="dropdown-section">
                <label class="dropdown-label">Versions</label>
                <div class="option-group horizontal">
                    {#each versionOptions as opt}
                        <button
                            class="option-btn small"
                            class:selected={versions === opt.value}
                            on:click={() => versions = opt.value}
                        >
                            {opt.value}
                        </button>
                    {/each}
                </div>
            </div>

            <div class="dropdown-actions">
                <button class="generate-with-options-btn" on:click={handleGenerateWithOptions}>
                    Generate with these settings
                </button>
            </div>
        </div>
    {/if}
</div>

<style>
    .generate-button-container {
        position: relative;
        display: inline-block;
    }

    .split-button {
        display: flex;
        border-radius: 6px;
        overflow: hidden;
    }

    .main-btn {
        padding: 0.35rem 0.75rem;
        background: var(--dox-ink-900);
        border: none;
        color: var(--dox-ink-100);
        font-size: 0.85rem;
        cursor: pointer;
        transition: background 0.15s;
        border-right: 1px solid color-mix(in srgb, var(--dox-ink-100) 20%, transparent);
    }

    .main-btn:hover:not(:disabled) {
        background: var(--dox-ink-800);
    }

    .main-btn:disabled {
        opacity: 0.6;
        cursor: wait;
    }

    .dropdown-btn {
        padding: 0.35rem 0.5rem;
        background: var(--dox-ink-900);
        border: none;
        color: var(--dox-ink-100);
        cursor: pointer;
        transition: background 0.15s;
        display: flex;
        align-items: center;
        justify-content: center;
    }

    .dropdown-btn:hover:not(:disabled) {
        background: var(--dox-ink-800);
    }

    .dropdown-btn:disabled {
        opacity: 0.6;
        cursor: not-allowed;
    }

    .split-button.generating .main-btn,
    .split-button.generating .dropdown-btn {
        background: var(--dox-rule-strong);
    }

    .split-button.open .dropdown-btn {
        background: var(--dox-ink-800);
    }

    .dropdown-menu {
        position: absolute;
        top: calc(100% + 4px);
        right: 0;
        background: var(--dox-surface);
        border: 1px solid var(--dox-rule-strong);
        border-radius: var(--dox-radius);
        padding: 0.75rem;
        min-width: 220px;
        z-index: 100;
        box-shadow: var(--dox-shadow);
    }

    .dropdown-section {
        margin-bottom: 0.75rem;
    }

    .dropdown-section:last-of-type {
        margin-bottom: 0.5rem;
    }

    .dropdown-label {
        display: block;
        font-size: 0.7rem;
        color: var(--dox-text-muted);
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin-bottom: 0.35rem;
    }

    .option-group {
        display: flex;
        flex-direction: column;
        gap: 0.25rem;
    }

    .option-group.horizontal {
        flex-direction: row;
        gap: 0.35rem;
    }

    .option-btn {
        padding: 0.35rem 0.6rem;
        background: var(--dox-ground);
        border: 1px solid var(--dox-rule-strong);
        border-radius: var(--dox-radius-sm);
        color: var(--dox-text-secondary);
        font-size: 0.8rem;
        cursor: pointer;
        transition: all 0.15s;
        text-align: left;
    }

    .option-btn.small {
        padding: 0.35rem 0.6rem;
        text-align: center;
        flex: 1;
    }

    .option-btn:hover {
        background: var(--dox-surface-raised);
        border-color: var(--dox-rule-strong);
    }

    .option-btn.selected {
        background: var(--dox-ink-900);
        border-color: var(--dox-ink-800);
        color: var(--dox-ink-100);
    }

    .dropdown-actions {
        margin-top: 0.75rem;
        padding-top: 0.75rem;
        border-top: 1px solid var(--dox-ink-800);
    }

    .generate-with-options-btn {
        width: 100%;
        padding: 0.5rem;
        background: var(--dox-ink-900);
        border: none;
        border-radius: 4px;
        color: var(--dox-ink-100);
        font-size: 0.85rem;
        cursor: pointer;
        transition: background 0.15s;
    }

    .generate-with-options-btn:hover {
        background: var(--dox-ink-800);
    }

    @media (max-width: 768px) {
        .main-btn, .dropdown-btn, .option-btn, .generate-with-options-btn { min-height: var(--touch-target-min); }
        .dropdown-btn { min-width: var(--touch-target-min); }
    }

    @media (prefers-reduced-motion: reduce) {
        .main-btn, .dropdown-btn, .option-btn, .generate-with-options-btn { transition: none; }
    }
</style>
