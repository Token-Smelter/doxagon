<script lang="ts">
  import { onMount } from "svelte";
  import { page } from "$app/stores";
  import { goto } from "$app/navigation";
  import {
    pipelineStats,
    phantasiai,
    evidence,
    selectedPhantasia,
    selectedEvidence,
  } from "$lib/stores/pipeline";
  import { fetchPipelineStats, fetchPhantasiai, fetchEvidence } from "$lib/api";
  import PipelineStats from "$lib/components/pipeline/PipelineStats.svelte";
  import PhantasiaList from "$lib/components/pipeline/PhantasiaList.svelte";
  import PhantasiaDetail from "$lib/components/pipeline/PhantasiaDetail.svelte";
  import CreatePhantasia from "$lib/components/pipeline/CreatePhantasia.svelte";

  type View = "dashboard" | "phantasiai" | "evidence" | "inbox" | "doxai";
  const views: View[] = [
    "dashboard",
    "phantasiai",
    "evidence",
    "inbox",
    "doxai",
  ];
  let currentView: View = "dashboard";
  let loading = true;
  let showCreateModal = false;
  let showingDetail = false;
  $: if (
    $selectedPhantasia &&
    typeof window !== "undefined" &&
    window.innerWidth <= 768
  )
    showingDetail = true;
  $: urlView = $page.url.searchParams.get("view") as View | null;
  $: if (urlView && views.includes(urlView)) currentView = urlView;
  function backToList() {
    showingDetail = false;
    selectedPhantasia.set(null);
  }
  onMount(async () => {
    await loadData();
    loading = false;
  });
  async function loadData() {
    try {
      const [stats, p, e] = await Promise.all([
        fetchPipelineStats(),
        fetchPhantasiai(),
        fetchEvidence(),
      ]);
      pipelineStats.set(stats);
      phantasiai.set(p);
      evidence.set(e);
    } catch (err) {
      console.error("Failed to load pipeline data:", err);
    }
  }
  function navigate(view: View) {
    currentView = view;
    const url = new URL(window.location.href);
    if (view === "dashboard") url.searchParams.delete("view");
    else url.searchParams.set("view", view);
    goto(url.toString(), { replaceState: true, noScroll: true });
  }
  function handleStatsNavigate(
    event: CustomEvent<{ view: "phantasiai" | "evidence" | "inbox" | "doxai" }>,
  ) {
    navigate(event.detail.view);
  }
  function closePhantasiaDetail() {
    showingDetail = false;
    selectedPhantasia.set(null);
  }
  function closeEvidenceDetail() {
    selectedEvidence.set(null);
  }
  async function handleExtracted() {
    await loadData();
  }
  async function handlePhantasiaCreated() {
    showCreateModal = false;
    await loadData();
  }
</script>

<svelte:head><title>Pipeline | Doxagon</title></svelte:head>
<div class="pipeline-page">
  <header class="page-header">
    <a href="/" class="back-link"><span aria-hidden="true">←</span> Graph</a>
    <h1>Intake pipeline</h1>
    <nav class="nav-tabs" aria-label="Pipeline views">
      <button
        class="nav-tab"
        class:active={currentView === "dashboard"}
        aria-current={currentView === "dashboard" ? "page" : undefined}
        on:click={() => navigate("dashboard")}>Dashboard</button
      ><button
        class="nav-tab"
        class:active={currentView === "phantasiai"}
        aria-current={currentView === "phantasiai" ? "page" : undefined}
        on:click={() => navigate("phantasiai")}>Phantasiai</button
      ><button
        class="nav-tab"
        class:active={currentView === "evidence"}
        aria-current={currentView === "evidence" ? "page" : undefined}
        on:click={() => navigate("evidence")}>Evidence</button
      >
    </nav>
  </header>
  <main class="content">
    {#if loading}<div class="loading" role="status">
        <span aria-hidden="true">◌</span>Loading pipeline data…
      </div>
    {:else if currentView === "dashboard"}<div class="dashboard">
        <PipelineStats on:navigate={handleStatsNavigate} />
      </div>
    {:else if currentView === "phantasiai"}<div class="split-view">
        <div class="list-panel" class:hidden-mobile={showingDetail}>
          <PhantasiaList on:create={() => (showCreateModal = true)} />
        </div>
        <div
          class="detail-panel"
          class:hidden-mobile={!showingDetail && !$selectedPhantasia}
        >
          {#if $selectedPhantasia}<button
              class="mobile-back-btn"
              on:click={backToList}>← Back to list</button
            ><PhantasiaDetail
              on:close={closePhantasiaDetail}
              on:extracted={handleExtracted}
            />{:else}<div class="empty-detail">
              <span aria-hidden="true">○</span>
              <p>Select a phantasia to view details</p>
            </div>{/if}
        </div>
      </div>
    {:else if currentView === "evidence"}<div class="placeholder">
        <span class="placeholder-mark" aria-hidden="true">○</span>
        <h2>Evidence</h2>
        <p>Evidence list view coming soon.</p>
        <p class="stat">
          {$pipelineStats?.evidence_count ?? 0} artifacts recorded
        </p>
      </div>
    {:else if currentView === "inbox"}<div class="placeholder">
        <span class="placeholder-mark" aria-hidden="true">↓</span>
        <h2>Inbox</h2>
        <p>File upload interface coming soon.</p>
      </div>
    {:else if currentView === "doxai"}<div class="placeholder">
        <span class="placeholder-mark stone" aria-hidden="true">□</span><a
          href="/"
          class="link-btn">View Doxai graph <span aria-hidden="true">→</span></a
        >
      </div>{/if}
  </main>
</div>
{#if showCreateModal}<CreatePhantasia
    on:close={() => (showCreateModal = false)}
    on:created={handlePhantasiaCreated}
  />{/if}

<style>
  .pipeline-page {
    display: flex;
    flex-direction: column;
    min-height: 100vh;
    min-width: 0;
    background: var(--dox-ground);
    color: var(--dox-text-primary);
  }
  .page-header {
    display: flex;
    align-items: center;
    gap: 1.25rem;
    padding: 0.9rem clamp(1rem, 3vw, 1.5rem);
    background: var(--dox-surface);
    border-bottom: 1px solid var(--dox-rule);
  }
  .back-link {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    color: var(--dox-text-accent);
    font: 0.78rem var(--dox-font-mono);
    text-decoration: none;
  }
  .back-link:hover {
    text-decoration: underline;
  }
  h1 {
    margin: 0;
    color: var(--dox-text-primary);
    font: 600 1.3rem var(--dox-font-display);
  }
  .nav-tabs {
    display: flex;
    gap: 0.25rem;
    margin-left: auto;
  }
  button {
    font: inherit;
  }
  .nav-tab {
    min-height: 36px;
    padding: 0.45rem 0.8rem;
    background: transparent;
    border: 1px solid transparent;
    border-radius: var(--dox-radius-sm);
    color: var(--dox-text-secondary);
    cursor: pointer;
    font: 0.76rem var(--dox-font-mono);
  }
  .nav-tab:hover {
    background: var(--dox-surface-raised);
  }
  .nav-tab.active {
    border-color: var(--dox-status-running);
    color: var(--dox-text-on-running);
    background: var(--dox-status-running);
  }
  .nav-tab.active::before {
    content: "◆";
    margin-right: 0.35rem;
    color: currentColor;
    font-size: 0.65rem;
  }
  .content {
    flex: 1;
    min-height: 0;
    padding: clamp(0.75rem, 3vw, 1.5rem);
    overflow: hidden;
  }
  .loading,
  .empty-detail,
  .placeholder {
    display: grid;
    place-content: center;
    justify-items: center;
    min-height: 16rem;
    height: 100%;
    color: var(--dox-text-muted);
    text-align: center;
  }
  .loading span,
  .placeholder-mark,
  .empty-detail span {
    display: grid;
    place-items: center;
    width: 2rem;
    height: 2rem;
    margin-bottom: 0.5rem;
    border: 1px solid currentColor;
    border-radius: 50%;
    font: 1.25rem var(--dox-font-display);
  }
  .placeholder-mark.stone {
    border-radius: 0;
    color: var(--dox-text-accent);
  }
  .dashboard {
    max-width: 75rem;
    margin: 0 auto;
  }
  .split-view {
    display: grid;
    grid-template-columns: minmax(16rem, 25rem) minmax(0, 1fr);
    gap: clamp(0.75rem, 3vw, 1.5rem);
    height: 100%;
  }
  .list-panel,
  .detail-panel {
    min-width: 0;
    min-height: 0;
    overflow: hidden;
  }
  .empty-detail {
    background: var(--dox-surface);
    border: 1px solid var(--dox-rule);
    border-radius: var(--dox-radius);
  }
  .placeholder h2 {
    margin: 0;
    color: var(--dox-text-primary);
    font: 600 1.2rem var(--dox-font-display);
  }
  .placeholder p {
    margin: 0.4rem 0;
  }
  .stat {
    color: var(--dox-text-secondary);
    font-family: var(--dox-font-mono);
  }
  .link-btn {
    min-height: 44px;
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    margin-top: 0.75rem;
    padding: 0.6rem 0.9rem;
    background: var(--dox-status-output);
    border: 1px solid var(--dox-status-output);
    border-radius: var(--dox-radius-sm);
    color: var(--dox-text-on-output);
    font: 600 0.8rem var(--dox-font-mono);
    text-decoration: none;
  }
  .mobile-back-btn {
    display: none;
  }
  @media (max-width: 900px) {
    .split-view {
      grid-template-columns: 1fr;
    }
  }
  @media (max-width: 768px) {
    .page-header {
      flex-wrap: wrap;
      gap: 0.7rem;
    }
    .back-link {
      min-height: var(--touch-target-min);
    }
    h1 {
      font-size: 1.15rem;
    }
    .nav-tabs {
      width: 100%;
      margin-left: 0;
    }
    .nav-tab {
      flex: 1;
      min-height: var(--touch-target-min);
      display: flex;
      align-items: center;
      justify-content: center;
      padding-inline: 0.35rem;
    }
    .content {
      min-height: 0;
      overflow: auto;
    }
    .split-view {
      height: auto;
      min-height: calc(100vh - 11rem);
    }
    .list-panel,
    .detail-panel {
      overflow: visible;
    }
    .hidden-mobile {
      display: none;
    }
    .mobile-back-btn {
      display: inline-flex;
      min-height: var(--touch-target-min);
      align-items: center;
      margin-bottom: 0.75rem;
      padding: 0.5rem 0.75rem;
      background: var(--dox-surface-raised);
      border: 1px solid var(--dox-rule-strong);
      border-radius: var(--dox-radius-sm);
      color: var(--dox-text-accent);
      cursor: pointer;
      font: 0.78rem var(--dox-font-mono);
    }
  }
  @media (max-width: 350px) {
    .page-header {
      padding-inline: 0.75rem;
    }
    .nav-tab {
      font-size: 0.68rem;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    * {
      scroll-behavior: auto;
    }
  }
</style>
