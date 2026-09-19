<script lang="ts">
  import { createEventDispatcher } from "svelte";
  import {
    filteredPhantasiai,
    phantasiaStatusFilter,
    selectedPhantasia,
  } from "../../stores/pipeline";
  import type { PhantasiaStatus } from "../../api";

  const dispatch = createEventDispatcher<{ create: void }>();
  const statuses: (PhantasiaStatus | null)[] = [
    null,
    "unprocessed",
    "processing",
    "processed",
    "failed",
    "archived",
  ];

  function formatDate(dateStr: string): string {
    return new Date(dateStr).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
    });
  }
</script>

<div class="phantasia-list">
  <div class="header">
    <div class="header-top">
      <h3>Phantasiai</h3>
      <button class="new-btn" on:click={() => dispatch("create")}
        >Create phantasia</button
      >
    </div>
    <div class="filters" aria-label="Filter phantasiai by status">
      {#each statuses as status}
        <button
          class="filter-btn"
          class:active={$phantasiaStatusFilter === status}
          aria-pressed={$phantasiaStatusFilter === status}
          on:click={() => phantasiaStatusFilter.set(status)}
        >
          <span class="filter-mark" aria-hidden="true"></span>{status ?? "All"}
        </button>
      {/each}
    </div>
  </div>

  <div class="list" aria-live="polite">
    {#if $filteredPhantasiai.length === 0}
      <div class="empty">
        <span aria-hidden="true">○</span> No phantasiai found
      </div>
    {:else}
      {#each $filteredPhantasiai as phantasia}
        <button
          class="item"
          class:selected={$selectedPhantasia === phantasia.slug}
          aria-pressed={$selectedPhantasia === phantasia.slug}
          on:click={() => selectedPhantasia.set(phantasia.slug)}
        >
          <div class="item-header">
            <span class="title">{phantasia.title}</span>
            <span class="status {phantasia.status}"
              ><span class="status-mark" aria-hidden="true"
              ></span>{phantasia.status}</span
            >
          </div>
          <div class="item-meta">
            <span class="source" title={phantasia.source}
              >{phantasia.source.length > 40
                ? phantasia.source.slice(0, 40) + "..."
                : phantasia.source}</span
            >
            <span class="date">{formatDate(phantasia.encountered)}</span>
          </div>
          <div class="item-stats">
            <span class="stat"
              ><strong>{phantasia.doxai_count}</strong> doxai</span
            >
            <span class="stat"
              ><strong>{phantasia.evidence_count}</strong> evidence</span
            >
          </div>
        </button>
      {/each}
    {/if}
  </div>
</div>

<style>
  .phantasia-list {
    display: flex;
    flex-direction: column;
    height: 100%;
    min-width: 0;
    background: var(--dox-surface);
    border: 1px solid var(--dox-rule);
    border-radius: var(--dox-radius);
    overflow: hidden;
    box-shadow: var(--dox-shadow-sm);
  }
  .header {
    padding: 1rem;
    border-bottom: 1px solid var(--dox-rule);
  }
  .header-top {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 0.75rem;
    margin-bottom: 0.75rem;
  }
  h3 {
    margin: 0;
    color: var(--dox-text-primary);
    font: 600 1rem var(--dox-font-display);
  }
  button {
    font: inherit;
  }
  .new-btn {
    min-height: 36px;
    padding: 0.4rem 0.7rem;
    background: var(--dox-status-running);
    border: 1px solid var(--dox-status-running);
    border-radius: var(--dox-radius-sm);
    color: var(--dox-text-on-running);
    cursor: pointer;
    font: 600 0.75rem var(--dox-font-mono);
  }
  .new-btn::before {
    content: "+";
    margin-right: 0.35rem;
    font-size: 1rem;
  }
  .filters {
    display: flex;
    gap: 0.35rem;
    flex-wrap: wrap;
  }
  .filter-btn {
    min-height: 32px;
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    padding: 0.25rem 0.5rem;
    background: transparent;
    border: 1px solid var(--dox-rule);
    border-radius: var(--dox-radius-pill);
    color: var(--dox-text-secondary);
    cursor: pointer;
    font: 0.7rem var(--dox-font-mono);
    text-transform: capitalize;
  }
  .filter-mark {
    width: 0.45rem;
    height: 0.45rem;
    border: 1px solid currentColor;
    border-radius: 50%;
  }
  .filter-btn:hover {
    border-color: var(--dox-rule-strong);
    color: var(--dox-text-primary);
  }
  .filter-btn.active {
    background: var(--dox-status-running);
    border-color: var(--dox-status-running);
    color: var(--dox-text-on-running);
  }
  .filter-btn.active .filter-mark {
    background: currentColor;
    border-radius: 1px;
  }
  .list {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding: 0.5rem;
  }
  .empty {
    padding: 2rem 1rem;
    text-align: center;
    color: var(--dox-text-muted);
  }
  .empty span {
    display: block;
    margin-bottom: 0.4rem;
    font: 1.4rem var(--dox-font-display);
  }
  .item {
    width: 100%;
    margin-bottom: 0.5rem;
    padding: 0.75rem;
    background: var(--dox-surface-raised);
    border: 1px solid var(--dox-rule);
    border-radius: var(--dox-radius);
    color: var(--dox-text-primary);
    cursor: pointer;
    text-align: left;
    transition:
      border-color 0.15s ease,
      background 0.15s ease;
  }
  .item:hover {
    border-color: var(--dox-rule-strong);
  }
  .item.selected {
    border-width: 2px;
    border-color: var(--dox-focus);
    background: color-mix(
      in srgb,
      var(--dox-status-running) 11%,
      var(--dox-surface)
    );
  }
  .item-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 0.5rem;
    margin-bottom: 0.5rem;
  }
  .title {
    min-width: 0;
    font: 600 0.9rem/1.3 var(--dox-font-display);
    overflow-wrap: anywhere;
  }
  .status {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    flex-shrink: 0;
    padding: 0.18rem 0.38rem;
    border: 1px solid currentColor;
    border-radius: var(--dox-radius-pill);
    font: 0.62rem var(--dox-font-mono);
    text-transform: uppercase;
  }
  .status-mark {
    width: 0.42rem;
    height: 0.42rem;
    border: 1px solid currentColor;
    border-radius: 50%;
  }
  .unprocessed {
    color: var(--dox-text-secondary);
    background: color-mix(
      in srgb,
      var(--dox-status-warning) 12%,
      var(--dox-surface)
    );
  }
  .unprocessed .status-mark {
    border-color: var(--dox-status-warning);
    background: var(--dox-status-warning);
  }
  .processing,
  .failed,
  .abandoned {
    color: var(--dox-text-on-running);
    background: var(--dox-status-running);
    border-color: var(--dox-status-running);
  }
  .processing .status-mark {
    border-radius: 1px;
    background: currentColor;
  }
  .processed {
    color: var(--dox-text-accent);
    background: color-mix(
      in srgb,
      var(--dox-status-output) 15%,
      var(--dox-surface)
    );
  }
  .processed .status-mark {
    border-radius: 0;
    transform: rotate(45deg);
  }
  .archived {
    color: var(--dox-text-muted);
    background: color-mix(
      in srgb,
      var(--dox-status-neutral) 16%,
      var(--dox-surface)
    );
  }
  .archived .status-mark {
    border-radius: 0;
  }
  .failed .status-mark,
  .abandoned .status-mark {
    border-radius: 0;
    transform: rotate(45deg);
  }
  .item-meta {
    display: flex;
    justify-content: space-between;
    gap: 0.5rem;
    margin-bottom: 0.5rem;
    color: var(--dox-text-muted);
    font: 0.7rem var(--dox-font-mono);
  }
  .source {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .date {
    flex-shrink: 0;
  }
  .item-stats {
    display: flex;
    gap: 1rem;
    color: var(--dox-text-secondary);
    font: 0.68rem var(--dox-font-mono);
  }
  strong {
    color: var(--dox-text-primary);
  }
  @media (max-width: 768px) {
    .new-btn,
    .filter-btn,
    .item {
      min-height: var(--touch-target-min);
    }
    .filter-btn {
      padding-inline: 0.65rem;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .item {
      transition: none;
    }
  }
</style>
