<script lang="ts">
  import { selectedPhantasia } from "../../stores/pipeline";
  import {
    fetchPhantasia,
    extractPhantasia,
    archivePhantasia,
  } from "../../api";
  import type { PhantasiaDetail, ExtractionResult } from "../../api";
  import { createEventDispatcher } from "svelte";
  import SvelteMarkdown from "svelte-markdown";

  const dispatch = createEventDispatcher<{
    close: void;
    extracted: { slug: string };
  }>();
  let phantasia: PhantasiaDetail | null = null;
  let loading = true;
  let error: string | null = null;
  let extracting = false;
  let extractionResult: ExtractionResult | null = null;
  $: if ($selectedPhantasia) loadPhantasia($selectedPhantasia);
  async function loadPhantasia(slug: string, resetExtraction = true) {
    loading = true;
    error = null;
    if (resetExtraction) extractionResult = null;
    try {
      phantasia = await fetchPhantasia(slug);
    } catch {
      error = "Failed to load phantasia";
      phantasia = null;
    } finally {
      loading = false;
    }
  }
  async function handleExtract() {
    if (!phantasia) return;
    extracting = true;
    error = null;
    extractionResult = null;
    try {
      extractionResult = await extractPhantasia(phantasia.slug);
      await loadPhantasia(phantasia.slug, false);
      dispatch("extracted", { slug: phantasia.slug });
    } catch (e) {
      error = e instanceof Error ? e.message : "Extraction failed";
    } finally {
      extracting = false;
    }
  }
  async function handleArchive() {
    if (
      !phantasia ||
      !confirm(
        `Archive "${phantasia.title}"? This will hide it from the main list.`,
      )
    )
      return;
    try {
      await archivePhantasia(phantasia.slug);
      dispatch("close");
      dispatch("extracted", { slug: phantasia.slug });
    } catch {
      error = "Failed to archive";
    }
  }
  function formatDate(dateStr: string) {
    return new Date(dateStr).toLocaleDateString("en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  }
</script>

<div class="phantasia-detail">
  {#if loading}<div class="state">
      <span aria-hidden="true">◌</span>Loading phantasia…
    </div>
  {:else if error}<div class="state error" role="alert">
      <span aria-hidden="true">!</span>{error}
    </div>
  {:else if phantasia}
    <div class="header">
      <div>
        <p class="eyebrow">Encountered {formatDate(phantasia.encountered)}</p>
        <h2>{phantasia.title}</h2>
        <div class="meta">
          <span class="status {phantasia.status}"
            ><span class="status-mark" aria-hidden="true"
            ></span>{phantasia.status}</span
          >{#if phantasia.channel}<span>via {phantasia.channel}</span>{/if}
        </div>
      </div>
      <button
        class="close-btn"
        on:click={() => dispatch("close")}
        aria-label="Close phantasia detail">×</button
      >
    </div>
    <div class="source-block">
      <strong>Source</strong><span>{phantasia.source}</span>
    </div>
    {#if phantasia.tags.length > 0}<div class="tags" aria-label="Tags">
        {#each phantasia.tags as tag}<span class="tag">{tag}</span>{/each}
      </div>{/if}
    <div class="content"><SvelteMarkdown source={phantasia.content} /></div>
    <section class="extractions-section" aria-labelledby="artifacts-heading">
      <h3 id="artifacts-heading">Extracted artifacts</h3>
      {#if extractionResult}<div class="extraction-result" role="status">
          <span class="result-item success"
            ><strong>{extractionResult.created_doxai.length}</strong>doxai
            created</span
          ><span class="result-item success"
            ><strong>{extractionResult.created_evidence.length}</strong>evidence
            created</span
          ><span class="result-item"
            ><strong>{extractionResult.created_edges}</strong>edges created</span
          ><span class="result-item muted"
            ><strong>{extractionResult.skipped_duplicates}</strong>duplicates
            skipped</span
          >
        </div>{/if}
      <div class="extraction-lists">
        <div class="extraction-group">
          <h4>Doxai ({phantasia.extracted_doxai.length})</h4>
          {#if phantasia.extracted_doxai.length > 0}<ul>
              {#each phantasia.extracted_doxai as doxa}<li>
                  <a href="/?node={doxa.slug}">{doxa.belief || doxa.slug}</a>
                </li>{/each}
            </ul>{:else}<p>○ None extracted</p>{/if}
        </div>
        <div class="extraction-group">
          <h4>Evidence ({phantasia.extracted_evidence.length})</h4>
          {#if phantasia.extracted_evidence.length > 0}<ul>
              {#each phantasia.extracted_evidence as ev}<li>
                  {ev.assertion || ev.slug}
                </li>{/each}
            </ul>{:else}<p>○ None extracted</p>{/if}
        </div>
      </div>
    </section>
    <div class="actions">
      {#if phantasia.status !== "processed" && phantasia.status !== "archived"}<button
          class="extract-btn"
          on:click={handleExtract}
          disabled={extracting}
          >{extracting ? "Extracting…" : "Extract doxai"}</button
        >{/if}{#if phantasia.status !== "archived"}<button
          class="archive-btn"
          on:click={handleArchive}>Archive phantasia</button
        >{/if}
    </div>
  {:else}<div class="state">
      <span aria-hidden="true">○</span>Select a phantasia to view details
    </div>{/if}
</div>

<style>
  .phantasia-detail {
    height: 100%;
    min-width: 0;
    overflow-y: auto;
    padding: 1rem;
    background: var(--dox-surface);
    border: 1px solid var(--dox-rule);
    border-radius: var(--dox-radius);
    box-shadow: var(--dox-shadow-sm);
    color: var(--dox-text-primary);
  }
  .state {
    display: grid;
    place-items: center;
    gap: 0.5rem;
    min-height: 12rem;
    padding: 2rem;
    color: var(--dox-text-muted);
    text-align: center;
  }
  .state > span {
    font: 1.5rem var(--dox-font-display);
  }
  .state.error {
    color: var(--dox-text-on-running);
    background: var(--dox-status-running);
    border: 1px solid var(--dox-status-running);
    border-radius: var(--dox-radius-sm);
  }
  .header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 1rem;
    margin-bottom: 1rem;
  }
  .eyebrow {
    margin: 0 0 0.3rem;
    color: var(--dox-text-muted);
    font: 0.65rem var(--dox-font-mono);
    letter-spacing: var(--dox-tracking);
  }
  h2,
  h3,
  h4 {
    font-family: var(--dox-font-display);
  }
  h2 {
    margin: 0 0 0.5rem;
    font-size: 1.3rem;
  }
  h3 {
    margin: 0 0 0.75rem;
    font-size: 1rem;
  }
  h4 {
    margin: 0 0 0.5rem;
    color: var(--dox-text-secondary);
    font-size: 0.84rem;
  }
  button {
    font: inherit;
  }
  .close-btn {
    display: grid;
    place-items: center;
    flex: 0 0 36px;
    min-height: 36px;
    background: transparent;
    border: 1px solid var(--dox-rule);
    border-radius: var(--dox-radius-sm);
    color: var(--dox-text-primary);
    cursor: pointer;
    font-size: 1.3rem;
  }
  .close-btn:hover {
    background: var(--dox-surface-raised);
  }
  .meta,
  .tags {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 0.5rem;
    color: var(--dox-text-muted);
    font: 0.72rem var(--dox-font-mono);
  }
  .status {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    padding: 0.18rem 0.38rem;
    border: 1px solid currentColor;
    border-radius: var(--dox-radius-pill);
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
  }
  .unprocessed .status-mark {
    border-color: var(--dox-status-warning);
    background: var(--dox-status-warning);
  }
  .processing,
  .failed,
  .abandoned {
    background: var(--dox-status-running);
    border-color: var(--dox-status-running);
    color: var(--dox-text-on-running);
  }
  .processing .status-mark {
    background: currentColor;
    border-radius: 1px;
  }
  .processed {
    color: var(--dox-text-accent);
  }
  .processed .status-mark {
    border-radius: 0;
    transform: rotate(45deg);
  }
  .archived {
    color: var(--dox-text-muted);
  }
  .archived .status-mark {
    border-radius: 0;
  }
  .failed .status-mark,
  .abandoned .status-mark {
    border-radius: 0;
    transform: rotate(45deg);
  }
  .source-block {
    display: grid;
    grid-template-columns: 5rem minmax(0, 1fr);
    gap: 0.75rem;
    margin-bottom: 1rem;
    padding: 0.75rem;
    background: var(--dox-surface-raised);
    border: 1px solid var(--dox-rule);
    border-radius: var(--dox-radius-sm);
    font-size: 0.85rem;
  }
  .source-block strong {
    font-family: var(--dox-font-mono);
    color: var(--dox-text-secondary);
  }
  .source-block span {
    overflow-wrap: anywhere;
    color: var(--dox-text-primary);
  }
  .tags {
    margin-bottom: 1rem;
  }
  .tag {
    padding: 0.2rem 0.4rem;
    border: 1px solid var(--dox-rule);
    border-radius: var(--dox-radius-pill);
  }
  .content {
    padding: 1rem;
    margin-bottom: 1rem;
    background: var(--dox-ground);
    border: 1px solid var(--dox-rule);
    border-radius: var(--dox-radius-sm);
    color: var(--dox-text-primary);
    line-height: 1.6;
    overflow-wrap: anywhere;
  }
  .content :global(p) {
    margin: 0 0 0.75rem;
  }
  .content :global(p:last-child) {
    margin-bottom: 0;
  }
  .extractions-section,
  .actions {
    border-top: 1px solid var(--dox-rule);
    padding-top: 1rem;
  }
  .extraction-result {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    margin-bottom: 1rem;
    padding: 0.75rem;
    border: 1px solid var(--dox-status-output);
    border-radius: var(--dox-radius-sm);
    background: color-mix(
      in srgb,
      var(--dox-status-output) 12%,
      var(--dox-surface)
    );
  }
  .result-item {
    display: flex;
    flex-direction: column;
    min-width: 5rem;
    color: var(--dox-text-secondary);
    font: 0.63rem var(--dox-font-mono);
    text-transform: uppercase;
  }
  .result-item strong {
    color: var(--dox-text-primary);
    font: 600 1.2rem var(--dox-font-display);
  }
  .result-item.success {
    border-bottom: 2px solid var(--dox-status-output);
  }
  .result-item.muted {
    color: var(--dox-text-muted);
  }
  .extraction-lists {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 1rem;
  }
  ul {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  li,
  .extraction-group p {
    margin: 0 0 0.35rem;
    padding: 0.55rem 0.65rem;
    background: var(--dox-surface-raised);
    border: 1px solid var(--dox-rule);
    border-radius: var(--dox-radius-sm);
    color: var(--dox-text-secondary);
    font-size: 0.84rem;
    overflow-wrap: anywhere;
  }
  a {
    color: var(--dox-text-accent);
  }
  .extraction-group p {
    color: var(--dox-text-muted);
    font-style: italic;
  }
  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: 0.75rem;
    margin-top: 1rem;
  }
  .extract-btn,
  .archive-btn {
    min-height: 38px;
    padding: 0.5rem 1rem;
    border-radius: var(--dox-radius-sm);
    cursor: pointer;
    font: 600 0.8rem var(--dox-font-mono);
  }
  .extract-btn {
    background: var(--dox-status-running);
    border: 1px solid var(--dox-status-running);
    color: var(--dox-text-on-running);
  }
  .extract-btn:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }
  .archive-btn {
    background: transparent;
    border: 1px solid var(--dox-rule-strong);
    color: var(--dox-text-secondary);
  }
  .archive-btn:hover {
    background: var(--dox-surface-raised);
  }
  @media (max-width: 768px) {
    .close-btn,
    .extract-btn,
    .archive-btn {
      min-height: var(--touch-target-min);
    }
    .close-btn {
      flex-basis: var(--touch-target-min);
      min-width: var(--touch-target-min);
    }
    .extraction-lists {
      grid-template-columns: 1fr;
    }
    li:has(a) {
      display: flex;
      align-items: center;
      min-height: var(--touch-target-min);
    }
    li:has(a) a {
      display: flex;
      align-items: center;
      width: 100%;
      min-height: var(--touch-target-min);
    }
  }
  @media (prefers-reduced-motion: reduce) {
    * {
      scroll-behavior: auto;
    }
  }
</style>
