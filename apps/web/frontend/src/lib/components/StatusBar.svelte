<script lang="ts">
    import { graph } from '../stores/graph';

    $: nodeCount = $graph?.nodes.length ?? 0;
    $: edgeCount = $graph?.edges.length ?? 0;

    // Calculate orphan nodes (no incoming or outgoing edges)
    $: orphanCount = (() => {
        if (!$graph) return 0;
        const connected = new Set<string>();
        $graph.edges.forEach(e => {
            connected.add(e.source);
            connected.add(e.target);
        });
        return $graph.nodes.filter(n => !connected.has(n.slug)).length;
    })();

    // Calculate evidence coverage
    $: evidenceCoverage = (() => {
        if (!$graph || $graph.nodes.length === 0) return 0;
        const withEvidence = $graph.nodes.filter(n => (n.evidence?.length ?? 0) > 0).length;
        return Math.round((withEvidence / $graph.nodes.length) * 100);
    })();

    // Calculate average degree
    $: avgDegree = (() => {
        if (!$graph || $graph.nodes.length === 0) return 0;
        return (($graph.edges.length * 2) / $graph.nodes.length).toFixed(1);
    })();
</script>

<div class="status-bar">
    <div class="stat" title="Total nodes in graph">
        <span class="label">Nodes</span>
        <span class="value">{nodeCount}</span>
    </div>
    <div class="stat" title="Total edges in graph">
        <span class="label">Edges</span>
        <span class="value">{edgeCount}</span>
    </div>
    <div class="stat" title="Average connections per node">
        <span class="label">Avg Degree</span>
        <span class="value">{avgDegree}</span>
    </div>
    <div class="stat" title="Nodes with no connections">
        <span class="label">Orphans</span>
        <span class="value" class:warning={orphanCount > 0}>{orphanCount}{orphanCount > 0 ? ' ⚠' : ''}</span>
    </div>
    <div class="stat" title="Percentage of nodes with evidence">
        <span class="label">Evidence</span>
        <span class="value" class:low={evidenceCoverage < 50}>{evidenceCoverage}%{evidenceCoverage < 50 ? ' low' : ''}</span>
    </div>
</div>

<style>
    .status-bar {
        position: fixed;
        bottom: 0;
        left: 0;
        right: 0;
        height: 24px;
        background: var(--dox-frame-ground);
        border-top: 1px solid var(--dox-frame-rule);
        display: flex;
        align-items: center;
        padding: 0 1rem;
        gap: 1.5rem;
        font-size: 0.75rem;
        color: var(--dox-frame-text-muted);
        z-index: 100;
        font-family: var(--dox-font-mono);
    }

    .stat {
        display: flex;
        align-items: center;
        gap: 0.35rem;
    }

    .label {
        color: var(--dox-frame-text-muted);
    }

    .value {
        color: var(--dox-frame-text);
        font-weight: 500;
    }

    .value.warning {
        color: var(--dox-status-warning);
    }

    .value.low {
        color: var(--dox-brand-paper-2);
        text-decoration: underline;
        text-underline-offset: 0.15em;
    }
</style>
