<script lang="ts">
  import { pipelineStats, totalPhantasiai } from "../../stores/pipeline";
  import { createEventDispatcher } from "svelte";
  const dispatch = createEventDispatcher<{
    navigate: { view: "phantasiai" | "evidence" | "inbox" | "doxai" };
  }>();
  function navigate(view: "phantasiai" | "evidence" | "inbox" | "doxai") {
    dispatch("navigate", { view });
  }
</script>

<section class="pipeline-stats" aria-labelledby="pipeline-overview">
  <header>
    <p class="eyebrow">The conversion path</p>
    <h2 id="pipeline-overview">Pipeline overview</h2>
  </header>
  <div class="stages">
    <button class="stage inbox" on:click={() => navigate("inbox")}
      ><span class="stage-header"
        ><span class="stage-icon" aria-hidden="true">↓</span><span>Inbox</span
        ></span
      ><strong>{$pipelineStats?.inbox_count ?? 0}</strong><span
        class="stage-label">items awaiting review</span
      ></button
    >
    <span class="arrow" aria-hidden="true">→</span>
    <button class="stage phantasiai" on:click={() => navigate("phantasiai")}
      ><span class="stage-header"
        ><span class="stage-icon" aria-hidden="true">◉</span><span
          >Phantasiai</span
        ></span
      ><strong>{$totalPhantasiai}</strong><span class="stage-label"
        >encounters in process</span
      ><span class="stage-breakdown"
        >{#if $pipelineStats?.phantasiai}{#each Object.entries($pipelineStats.phantasiai) as [status, count]}<span
              class="status-chip {status}"
              ><span aria-hidden="true"></span>{status}: {count}</span
            >{/each}{/if}</span
      ></button
    >
    <span class="arrow" aria-hidden="true">→</span>
    <div class="output-group">
      <button class="stage doxai" on:click={() => navigate("doxai")}
        ><span class="stage-header"
          ><span class="stage-icon" aria-hidden="true">□</span><span>Doxai</span
          ></span
        ><strong>{$pipelineStats?.doxai_count ?? 0}</strong><span
          class="stage-label">fixed beliefs</span
        ></button
      ><button class="stage evidence" on:click={() => navigate("evidence")}
        ><span class="stage-header"
          ><span class="stage-icon" aria-hidden="true">○</span><span
            >Evidence</span
          ></span
        ><strong>{$pipelineStats?.evidence_count ?? 0}</strong><span
          class="stage-label">artifacts</span
        ></button
      >
    </div>
  </div>
  <div class="secondary-stats">
    <span><b>Edges</b>{$pipelineStats?.edges_count ?? 0}</span><span
      ><b>Diegeses</b>{$pipelineStats?.diegeses_count ?? 0}</span
    >
  </div>
</section>

<style>
  .pipeline-stats {
    padding: clamp(1rem, 3vw, 1.5rem);
    background: var(--dox-surface);
    border: 1px solid var(--dox-rule);
    border-radius: var(--dox-radius);
    box-shadow: var(--dox-shadow-sm);
  }
  .eyebrow {
    margin: 0 0 0.3rem;
    color: var(--dox-text-muted);
    font: 0.65rem var(--dox-font-mono);
    letter-spacing: var(--dox-tracking-caps);
    text-transform: uppercase;
  }
  h2 {
    margin: 0 0 1.25rem;
    color: var(--dox-text-primary);
    font: 600 1.3rem var(--dox-font-display);
  }
  .stages {
    display: flex;
    align-items: stretch;
    gap: 0.5rem;
    flex-wrap: wrap;
  }
  button {
    font: inherit;
  }
  .arrow {
    display: grid;
    place-items: center;
    color: var(--dox-text-muted);
    font: 1.4rem var(--dox-font-display);
  }
  .stage {
    display: flex;
    flex: 1 1 9rem;
    flex-direction: column;
    align-items: center;
    min-width: 9rem;
    padding: 1rem;
    background: var(--dox-surface-raised);
    border: 1px solid var(--dox-rule);
    border-radius: var(--dox-radius);
    color: var(--dox-text-primary);
    cursor: pointer;
    text-align: center;
    transition:
      border-color 0.15s ease,
      background 0.15s ease;
  }
  .stage:hover {
    border-color: var(--dox-rule-strong);
  }
  .stage:focus-visible {
    outline: 2px solid var(--dox-focus);
    outline-offset: 2px;
  }
  .stage-header {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 0.4rem;
    color: var(--dox-text-secondary);
    font: 600 0.8rem var(--dox-font-mono);
  }
  .stage-icon {
    display: grid;
    place-items: center;
    width: 1.1rem;
    height: 1.1rem;
    border: 1px solid currentColor;
    border-radius: 50%;
  }
  .phantasiai {
    border-color: var(--dox-status-running);
    background: var(--dox-status-running);
    color: var(--dox-text-on-running);
  }
  .phantasiai .stage-header,
  .phantasiai .stage-label {
    color: var(--dox-text-on-running);
  }
  .phantasiai .stage-icon {
    border-radius: 1px;
    background: var(--dox-text-on-running);
    color: var(--dox-status-running);
  }
  .doxai {
    border-color: var(--dox-status-output);
  }
  .doxai .stage-icon {
    border-radius: 0;
    color: var(--dox-text-accent);
  }
  .evidence .stage-icon {
    border-style: double;
  }
  .stage strong {
    margin-top: 0.5rem;
    font: 600 2rem/1 var(--dox-font-display);
  }
  .stage-label {
    margin-top: 0.3rem;
    color: var(--dox-text-muted);
    font: 0.68rem var(--dox-font-mono);
  }
  .stage-breakdown {
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: 0.25rem;
    margin-top: 0.65rem;
  }
  .status-chip {
    display: inline-flex;
    align-items: center;
    gap: 0.2rem;
    padding: 0.15rem 0.3rem;
    border: 1px solid currentColor;
    border-radius: var(--dox-radius-pill);
    color: var(--dox-text-secondary);
    font: 0.58rem var(--dox-font-mono);
  }
  .status-chip > span {
    width: 0.35rem;
    height: 0.35rem;
    border: 1px solid currentColor;
    border-radius: 50%;
  }
  .status-chip.processing,
  .status-chip.failed,
  .status-chip.abandoned {
    background: var(--dox-status-running);
    border-color: var(--dox-status-running);
    color: var(--dox-text-on-running);
  }
  .status-chip.processing > span,
  .status-chip.failed > span,
  .status-chip.abandoned > span {
    border-radius: 0;
    background: currentColor;
  }
  .status-chip.unprocessed {
    color: var(--dox-text-secondary);
  }
  .status-chip.unprocessed > span {
    border-color: var(--dox-status-warning);
    background: var(--dox-status-warning);
  }
  .status-chip.processed {
    color: var(--dox-text-accent);
  }
  .status-chip.processed > span {
    border-radius: 0;
    transform: rotate(45deg);
  }
  .status-chip.archived {
    color: var(--dox-text-muted);
  }
  .status-chip.archived > span {
    border-radius: 0;
  }
  .output-group {
    display: flex;
    flex: 1 1 16rem;
    gap: 0.5rem;
  }
  .output-group .stage {
    min-width: 0;
  }
  .secondary-stats {
    display: flex;
    gap: 1.5rem;
    margin-top: 1.25rem;
    padding-top: 1rem;
    border-top: 1px solid var(--dox-rule);
    color: var(--dox-text-secondary);
    font: 0.78rem var(--dox-font-mono);
  }
  .secondary-stats span {
    display: flex;
    gap: 0.5rem;
  }
  .secondary-stats b {
    color: var(--dox-text-muted);
    font-weight: 400;
  }
  @media (max-width: 768px) {
    .stage {
      min-height: var(--touch-target-min);
    }
    .arrow {
      width: 100%;
      height: 1rem;
      transform: rotate(90deg);
    }
    .output-group {
      flex-basis: 100%;
    }
  }
  @media (max-width: 380px) {
    .output-group {
      flex-direction: column;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .stage {
      transition: none;
    }
  }
</style>
