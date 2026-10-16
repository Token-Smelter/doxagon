"""Integration: find edges the graph is missing, judged by the calling agent.

`integration_overview` partitions the graph into clusters so the work splits
into units one agent (or sub-agent) can hold. `integration_context` returns one
unit. `apply_integration` validates proposed edges against the whole graph
before writing any of them.
"""

from __future__ import annotations

from datetime import date

import frontmatter
import networkx as nx

from doxagon import agent_context
from doxagon.config import DOXAI_DIR
from doxagon.graph import build_graph, invalidate_cache
from doxagon.storage import check_logos, write_logos
from doxagon.validation import GraphIntegrityError, ValidationIssue, ValidationReport

EDGE_FIELDS = ("source", "target", "type", "rationale")


def detect_clusters(min_cluster_size: int = 5) -> list[list[str]]:
    """Partition doxai into communities (Louvain), merging small ones into their best neighbor."""
    graph = build_graph()
    undirected = graph.to_undirected()
    isolates = list(nx.isolates(undirected))
    undirected.remove_nodes_from(isolates)
    if len(undirected) == 0:
        return [sorted(isolates)] if isolates else []

    clusters = sorted((sorted(c) for c in nx.community.louvain_communities(undirected, seed=42)),
                      key=len, reverse=True)
    large = [c for c in clusters if len(c) >= min_cluster_size]
    for small in (c for c in clusters if len(c) < min_cluster_size):
        if not large:
            large.append(small)
            continue
        links = [sum(1 for node in small for neighbor in (*graph.predecessors(node), *graph.successors(node))
                     if neighbor in set(cluster)) for cluster in large]
        best = links.index(max(links))
        large[best] = sorted(set(large[best]) | set(small))
    if isolates:
        large[0] = sorted(set(large[0]) | set(isolates))
    return large


def _created(slug: str) -> str:
    path = DOXAI_DIR / f"{slug}.md"
    created = frontmatter.load(path).get('created') if path.exists() else None
    return str(created) if created else "0000-00-00"


def integration_overview() -> dict:
    """List clusters with size, recent additions and a sample, so the agent can pick units."""
    beliefs = {b['slug']: b['belief'] for b in agent_context.beliefs()}
    cutoff = date.today().replace(day=1).isoformat()
    clusters = []
    for index, cluster in enumerate(detect_clusters(), start=1):
        clusters.append({
            'cluster': index,
            'size': len(cluster),
            'added_this_month': sum(1 for slug in cluster if _created(slug) >= cutoff),
            'sample': [{'slug': slug, 'belief': beliefs.get(slug, '')} for slug in cluster[:10]],
        })
    return {
        'schema': 'doxagon.integration-overview/1',
        'beliefs': len(beliefs),
        'edges': len(agent_context.read_logos()['edges']),
        'clusters': clusters,
        'next': 'dox integrate --context --cluster N | all | cross',
    }


def integration_context(cluster: str) -> dict:
    """Return one unit of integration work.

    `N` is one cluster with full belief bodies and its edges; `all` is the whole
    graph the same way; `cross` is every belief (statement only) labelled with
    its cluster, for finding edges that bridge clusters.
    """
    clusters = detect_clusters()
    edges = agent_context.read_logos()['edges']
    if cluster == 'cross':
        membership = {slug: index for index, members in enumerate(clusters, start=1) for slug in members}
        beliefs = [{**b, 'cluster': membership.get(b['slug'])} for b in agent_context.beliefs()]
    elif cluster == 'all':
        beliefs = agent_context.beliefs(with_body=True)
    else:
        try:
            members = clusters[int(cluster) - 1]
        except (ValueError, IndexError):
            raise ValueError(f"unknown cluster {cluster!r}; run `dox integrate --context` to list clusters") from None
        beliefs = agent_context.beliefs(members, with_body=True)
        edges = [e for e in edges if e.get('source') in members or e.get('target') in members]
    return {
        'schema': 'doxagon.integration-context/1',
        'scope': cluster,
        'beliefs': beliefs,
        'edges': [{k: e.get(k) for k in ('source', 'target', 'type', 'rationale') if e.get(k)} for e in edges],
        **agent_context.vocabulary(),
        'answer_format': 'dox-knowledge skill, references/integrate.md',
    }


def apply_integration(response: str, dry_run: bool = False) -> dict:
    """Validate proposed ===EDGE=== blocks against the whole graph, then write them."""
    blocks = agent_context.parse_blocks(response, 'EDGE')
    if not blocks:
        raise ValueError("Response has no ===EDGE=== blocks")
    report = ValidationReport()
    logos = agent_context.read_logos()
    existing = {agent_context.edge_key(e) for e in logos['edges']}
    added, skipped = [], []
    today = date.today().isoformat()
    for index, block in enumerate(blocks, start=1):
        missing = [name for name in EDGE_FIELDS if not str(block.get(name) or '').strip()]
        if '_invalid' in block or missing:
            report.issues.append(ValidationIssue(
                "invalid_block", f"EDGE {index}: " + ("not a YAML mapping" if '_invalid' in block
                                                      else f"missing {', '.join(missing)}")))
            continue
        edge = {'source': block['source'], 'target': block['target'], 'type': block['type'],
                'strength': block.get('strength', 'moderate'), 'confidence': block.get('confidence', 'medium'),
                'rationale': str(block['rationale']).strip()}
        if block.get('alias'):
            edge['alias'] = block['alias']
        edge['provenance'] = {'method': 'integration'}
        edge['created'] = today
        key = agent_context.edge_key(edge)
        if key in existing:
            skipped.append(key)
            continue
        existing.add(key)
        logos['edges'].append(edge)
        added.append(key)
    report.extend(check_logos(logos))
    if not report.valid:
        raise GraphIntegrityError(report)
    if added and not dry_run:
        write_logos(logos)
        invalidate_cache()
    return {'added': added, 'skipped_existing': skipped}
