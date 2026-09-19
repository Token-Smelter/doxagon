"""Deep integration pass for the doxai knowledge graph.

This module handles:
1. Loading the complete library (all doxai + edges)
2. Calling Gemini for deep analysis (single-pass or batched by cluster)
3. Parsing integration findings (edges, tensions, gaps, clusters)
4. Optionally applying proposed edges
"""

import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime

import frontmatter
import networkx as nx
import yaml

from doxagon.config import DOXAI_DIR, LOGOS_FILE
from doxagon.graph import build_graph, invalidate_cache
from doxagon.prompts import load_prompt
from doxagon.storage import write_logos


@dataclass
class ProposedEdge:
    """A proposed relationship between beliefs."""
    source: str
    target: str
    edge_type: str
    strength: str
    confidence: str = "medium"  # high | medium | low
    rationale: str = ""  # WHY this relationship exists
    annotation: str = ""  # Legacy field, prefer rationale


@dataclass
class Tension:
    """A tension between beliefs."""
    beliefs: list[str]
    severity: str
    description: str
    resolution_options: list[str]


@dataclass
class EvidenceGap:
    """An evidence gap in a belief."""
    belief: str
    gap_type: str
    description: str
    suggested_research: str


@dataclass
class ClusterOpportunity:
    """A potential diegesis from related beliefs."""
    name: str
    beliefs: list[str]
    narrative: str


@dataclass
class IntegrationResult:
    """Result of integration analysis."""
    proposed_edges: list[ProposedEdge] = field(default_factory=list)
    tensions: list[Tension] = field(default_factory=list)
    gaps: list[EvidenceGap] = field(default_factory=list)
    clusters: list[ClusterOpportunity] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def load_all_doxai() -> str:
    """Load all doxai content for integration context."""
    content_parts = []
    for f in sorted(DOXAI_DIR.glob("d-*.md")):
        try:
            text = f.read_text()
            content_parts.append(f"### {f.stem}\n\n{text}\n")
        except Exception:
            continue
    return "\n---\n\n".join(content_parts) if content_parts else "(No doxai found)"


def load_existing_edges() -> str:
    """Load existing edges from logos.yaml."""
    if not LOGOS_FILE.exists():
        return "(No edges defined)"

    try:
        data = yaml.safe_load(LOGOS_FILE.read_text())
        edges = data.get('edges', [])
        if not edges:
            return "(No edges defined)"

        lines = []
        for edge in edges:
            if isinstance(edge, list):
                # Legacy format
                lines.append(f"- {edge[0]} --[{edge[2] if len(edge) > 2 else 'unknown'}]--> {edge[1]}")
            else:
                # New format
                lines.append(f"- {edge.get('source', '?')} --[{edge.get('type', '?')}]--> {edge.get('target', '?')}")
        return "\n".join(lines)
    except Exception:
        return "(Error loading edges)"


def call_gemini(prompt: str, model: str = "gemini-2.5-pro") -> str:
    """Call gemini CLI with a prompt and return the response.

    Uses stdin to pass the prompt to avoid command line length limits.
    """
    result = subprocess.run(
        ["gemini", "-m", model],
        input=prompt,
        capture_output=True,
        text=True,
        timeout=300,  # 5 minutes for deep analysis
    )
    if result.returncode != 0:
        raise RuntimeError(f"Gemini CLI error: {result.stderr}")
    return result.stdout.strip()


def parse_integration_response(response: str) -> IntegrationResult:
    """Parse integration analysis response into structured findings."""
    result = IntegrationResult()

    # Parse EDGE blocks
    edge_pattern = r'===EDGE===(.*?)===END_EDGE==='
    for match in re.finditer(edge_pattern, response, re.DOTALL):
        content = match.group(1).strip()
        edge = _parse_yaml_block(content)
        if edge and 'source' in edge and 'target' in edge:
            result.proposed_edges.append(ProposedEdge(
                source=edge.get('source', ''),
                target=edge.get('target', ''),
                edge_type=edge.get('type', 'supports'),
                strength=edge.get('strength', 'moderate'),
                confidence=edge.get('confidence', 'medium'),
                rationale=edge.get('rationale', ''),
                annotation=edge.get('annotation', ''),  # Legacy fallback
            ))

    # Parse TENSION blocks
    tension_pattern = r'===TENSION===(.*?)===END_TENSION==='
    for match in re.finditer(tension_pattern, response, re.DOTALL):
        content = match.group(1).strip()
        tension = _parse_yaml_block(content)
        if tension and 'beliefs' in tension:
            result.tensions.append(Tension(
                beliefs=tension.get('beliefs', []),
                severity=tension.get('severity', 'medium'),
                description=tension.get('description', ''),
                resolution_options=tension.get('resolution_options', []),
            ))

    # Parse GAP blocks
    gap_pattern = r'===GAP===(.*?)===END_GAP==='
    for match in re.finditer(gap_pattern, response, re.DOTALL):
        content = match.group(1).strip()
        gap = _parse_yaml_block(content)
        if gap and 'belief' in gap:
            result.gaps.append(EvidenceGap(
                belief=gap.get('belief', ''),
                gap_type=gap.get('gap_type', 'missing_evidence'),
                description=gap.get('description', ''),
                suggested_research=gap.get('suggested_research', ''),
            ))

    # Parse CLUSTER blocks
    cluster_pattern = r'===CLUSTER===(.*?)===END_CLUSTER==='
    for match in re.finditer(cluster_pattern, response, re.DOTALL):
        content = match.group(1).strip()
        cluster = _parse_yaml_block(content)
        if cluster and 'beliefs' in cluster:
            result.clusters.append(ClusterOpportunity(
                name=cluster.get('name', 'Unnamed cluster'),
                beliefs=cluster.get('beliefs', []),
                narrative=cluster.get('narrative', ''),
            ))

    return result


def _parse_yaml_block(content: str) -> dict:
    """Parse a YAML-like block into a dictionary."""
    try:
        return yaml.safe_load(content) or {}
    except Exception:
        # Fall back to simple key: value parsing
        result = {}
        current_key = None
        current_value = []

        for line in content.split('\n'):
            if ':' in line and not line.startswith(' ') and not line.startswith('-'):
                # Save previous key
                if current_key:
                    val = '\n'.join(current_value).strip()
                    result[current_key] = val if val else result.get(current_key, '')
                # Start new key
                key, value = line.split(':', 1)
                current_key = key.strip()
                current_value = [value.strip()] if value.strip() else []
            elif current_key:
                current_value.append(line)

        # Save last key
        if current_key:
            val = '\n'.join(current_value).strip()
            result[current_key] = val if val else result.get(current_key, '')

        return result


def apply_proposed_edges(edges: list[ProposedEdge]) -> int:
    """Apply proposed edges to logos.yaml. Returns count of edges added."""
    if not edges:
        return 0

    # Load existing
    logos = yaml.safe_load(LOGOS_FILE.read_text()) if LOGOS_FILE.exists() else {}
    existing_edges = logos.get('edges', [])

    # Build set of existing edges for dedup
    existing_set = set()
    for e in existing_edges:
        if isinstance(e, list):
            existing_set.add((e[0], e[1], e[2] if len(e) > 2 else 'unknown'))
        else:
            existing_set.add((e.get('source', ''), e.get('target', ''), e.get('type', '')))

    # Add new edges
    added = 0
    for edge in edges:
        key = (edge.source, edge.target, edge.edge_type)
        if key not in existing_set:
            new_edge = {
                'source': edge.source,
                'target': edge.target,
                'type': edge.edge_type,
                'strength': edge.strength,
                'confidence': edge.confidence,
                'provenance': {
                    'method': 'integration',
                    'pass': date.today().isoformat(),
                },
                'created': date.today().isoformat(),
            }
            # Prefer rationale over annotation
            if edge.rationale:
                new_edge['rationale'] = edge.rationale
            elif edge.annotation:
                new_edge['rationale'] = edge.annotation  # Migrate legacy annotation
            existing_edges.append(new_edge)
            existing_set.add(key)
            added += 1

    # Save only after the complete typed-edge set validates.
    logos['edges'] = existing_edges
    write_logos(logos)
    invalidate_cache()

    return added


def detect_clusters(min_cluster_size: int = 5) -> list[list[str]]:
    """Detect communities in the doxai graph using Louvain method.

    Returns list of clusters, each a list of doxa slugs.
    Small clusters are merged into the nearest larger one.
    """
    G = build_graph()

    # Louvain needs undirected graph
    U = G.to_undirected()

    # Remove isolated nodes — they'll get their own pass
    isolates = list(nx.isolates(U))
    U.remove_nodes_from(isolates)

    if len(U) == 0:
        # All nodes are isolated
        return [isolates] if isolates else []

    communities = nx.community.louvain_communities(U, seed=42)

    # Sort by size descending
    clusters = [sorted(c) for c in communities]
    clusters.sort(key=len, reverse=True)

    # Merge small clusters into the closest large one
    large = [c for c in clusters if len(c) >= min_cluster_size]
    small = [c for c in clusters if len(c) < min_cluster_size]

    for small_cluster in small:
        # Find the large cluster with the most edges to this small one
        best_target = 0
        best_count = -1
        for i, large_cluster in enumerate(large):
            large_set = set(large_cluster)
            count = sum(
                1 for node in small_cluster
                for neighbor in G.predecessors(node)
                if neighbor in large_set
            ) + sum(
                1 for node in small_cluster
                for neighbor in G.successors(node)
                if neighbor in large_set
            )
            if count > best_count:
                best_count = count
                best_target = i
        if large:
            large[best_target] = sorted(set(large[best_target]) | set(small_cluster))
        else:
            large.append(small_cluster)

    # Add isolates to the largest cluster (or their own if no clusters)
    if isolates:
        if large:
            large[0] = sorted(set(large[0]) | set(isolates))
        else:
            large.append(isolates)

    return large


def load_cluster_doxai(slugs: list[str]) -> str:
    """Load doxai content for a specific set of slugs."""
    content_parts = []
    for slug in sorted(slugs):
        path = DOXAI_DIR / f"{slug}.md"
        if path.exists():
            try:
                text = path.read_text()
                content_parts.append(f"### {slug}\n\n{text}\n")
            except Exception:
                continue
    return "\n---\n\n".join(content_parts) if content_parts else "(No doxai found)"


def load_cluster_edges(slugs: list[str]) -> str:
    """Load existing edges that involve any of the given slugs."""
    if not LOGOS_FILE.exists():
        return "(No edges defined)"

    slug_set = set(slugs)
    try:
        data = yaml.safe_load(LOGOS_FILE.read_text())
        edges = data.get('edges', [])
        if not edges:
            return "(No edges defined)"

        lines = []
        for edge in edges:
            if isinstance(edge, list):
                source, target = edge[0], edge[1]
                edge_type = edge[2] if len(edge) > 2 else 'unknown'
            else:
                source = edge.get('source', '?')
                target = edge.get('target', '?')
                edge_type = edge.get('type', '?')

            if source in slug_set or target in slug_set:
                lines.append(f"- {source} --[{edge_type}]--> {target}")

        return "\n".join(lines) if lines else "(No edges for this cluster)"
    except Exception:
        return "(Error loading edges)"


def summarize_cluster(slugs: list[str], cluster_index: int) -> str:
    """Build a short summary of a cluster for cross-cluster context."""
    G = build_graph()
    beliefs = []
    for slug in slugs[:10]:  # Sample up to 10 for summary
        data = G.nodes.get(slug, {})
        belief = data.get('belief', slug)
        beliefs.append(f"  - {slug}: {belief}")

    summary = f"Cluster {cluster_index + 1} ({len(slugs)} beliefs):\n"
    summary += "\n".join(beliefs)
    if len(slugs) > 10:
        summary += f"\n  ... and {len(slugs) - 10} more"
    return summary


def rank_clusters_by_recency(clusters: list[list[str]]) -> list[tuple[int, int, list[str]]]:
    """Rank clusters by how many recently-added doxai they contain.

    Returns list of (recent_count, cluster_index, cluster) sorted by recent_count desc.
    """
    cutoff = date.today().replace(day=1).isoformat()  # First of current month

    def get_created(slug: str) -> str:
        path = DOXAI_DIR / f"{slug}.md"
        if not path.exists():
            return "2000-01-01"
        try:
            post = frontmatter.load(path)
            created = post.get('created')
            if created:
                return str(created)
            return datetime.fromtimestamp(path.stat().st_mtime).strftime('%Y-%m-%d')
        except Exception:
            return "2000-01-01"

    ranked = []
    for i, cluster in enumerate(clusters):
        recent = sum(1 for s in cluster if get_created(s) >= cutoff)
        ranked.append((recent, i, cluster))

    ranked.sort(key=lambda x: x[0], reverse=True)
    return ranked


def merge_results(results: list[IntegrationResult]) -> IntegrationResult:
    """Merge multiple integration results, deduplicating edges."""
    merged = IntegrationResult()
    seen_edges = set()

    for result in results:
        for edge in result.proposed_edges:
            key = (edge.source, edge.target, edge.edge_type)
            if key not in seen_edges:
                merged.proposed_edges.append(edge)
                seen_edges.add(key)
        merged.tensions.extend(result.tensions)
        merged.gaps.extend(result.gaps)
        merged.clusters.extend(result.clusters)
        merged.errors.extend(result.errors)

    return merged


def run_integration(
    focus: str | None = None,
    apply_edges: bool = False,
    batch: bool = False,
    recent: int | None = None,
    progress_callback=None,
) -> IntegrationResult:
    """Run deep integration pass on the doxai library.

    Args:
        focus: Optional focus area (e.g., "AI economics", "tensions only")
        apply_edges: If True, automatically add proposed edges to logos.yaml
        batch: If True, partition into clusters and run per-cluster passes
        recent: If set, select the N clusters with the most recently-added doxai (implies batch)
        progress_callback: Optional callable(message: str) for progress updates

    Returns:
        IntegrationResult with findings
    """
    def _progress(msg: str):
        if progress_callback:
            progress_callback(msg)

    if not batch and not recent:
        return _run_single_pass(focus=focus, apply_edges=apply_edges)

    # Batched mode: detect clusters, run per-cluster, then cross-cluster
    _progress("Detecting communities...")
    all_clusters = detect_clusters()
    _progress(f"Found {len(all_clusters)} clusters: {[len(c) for c in all_clusters]}")

    # Filter to most recent clusters if requested
    if recent:
        ranked = rank_clusters_by_recency(all_clusters)
        selected = ranked[:recent]
        clusters = [cluster for _, _, cluster in selected]
        for count, idx, cluster in selected:
            _progress(f"  Selected cluster {idx + 1} ({len(cluster)} beliefs, {count} recent)")
    else:
        clusters = all_clusters

    results = []

    # Phase 1: intra-cluster passes
    for i, cluster in enumerate(clusters):
        _progress(f"Pass {i + 1}/{len(clusters)}: {len(cluster)} beliefs...")
        doxai_content = load_cluster_doxai(cluster)
        edges_content = load_cluster_edges(cluster)

        focus_instructions = f"You are analyzing cluster {i + 1} of {len(clusters)}. "
        focus_instructions += f"This cluster contains {len(cluster)} beliefs. "
        focus_instructions += "Focus on finding ALL missing edges within this group."
        if focus:
            focus_instructions += f"\nAdditional focus: {focus}"

        prompt = load_prompt(
            "integrate",
            doxai_content=doxai_content,
            edges_content=edges_content,
            focus_instructions=focus_instructions,
        )

        try:
            response = call_gemini(prompt)
            result = parse_integration_response(response)
            results.append(result)
            _progress(f"  → {len(result.proposed_edges)} edges found")
        except Exception as e:
            _progress(f"  → ERROR: {e}")
            results.append(IntegrationResult(errors=[f"Cluster {i + 1} failed: {e}"]))

    # Phase 2: cross-cluster pass using summaries
    if len(clusters) > 1:
        _progress("Running cross-cluster pass...")
        cluster_summaries = "\n\n".join(
            summarize_cluster(c, i) for i, c in enumerate(clusters)
        )

        # Load ALL doxai but with cross-cluster instructions
        all_doxai = load_all_doxai()
        all_edges = load_existing_edges()

        cross_focus = (
            "You are looking for CROSS-CLUSTER connections only. "
            "The graph has been partitioned into these clusters:\n\n"
            f"{cluster_summaries}\n\n"
            "Focus on finding edges that BRIDGE between clusters — "
            "connections that link beliefs from different topic areas. "
            "Intra-cluster edges have already been found. "
            "Prioritize non-obvious cross-domain relationships."
        )
        if focus:
            cross_focus += f"\nAdditional focus: {focus}"

        prompt = load_prompt(
            "integrate",
            doxai_content=all_doxai,
            edges_content=all_edges,
            focus_instructions=cross_focus,
        )

        try:
            response = call_gemini(prompt)
            cross_result = parse_integration_response(response)
            results.append(cross_result)
            _progress(f"  → {len(cross_result.proposed_edges)} cross-cluster edges found")
        except Exception as e:
            _progress(f"  → Cross-cluster ERROR: {e}")
            results.append(IntegrationResult(errors=[f"Cross-cluster pass failed: {e}"]))

    # Merge all results
    merged = merge_results(results)

    # Apply edges if requested
    if apply_edges and merged.proposed_edges:
        added = apply_proposed_edges(merged.proposed_edges)
        if added < len(merged.proposed_edges):
            merged.errors.append(
                f"Applied {added}/{len(merged.proposed_edges)} edges (rest were duplicates)"
            )
        else:
            merged.errors.append(f"Applied {added} edges")

    return merged


def _run_single_pass(
    focus: str | None = None,
    apply_edges: bool = False,
) -> IntegrationResult:
    """Original single-pass integration."""
    # Load full library
    doxai_content = load_all_doxai()
    edges_content = load_existing_edges()

    # Build focus instructions
    focus_instructions = ""
    if focus:
        focus_instructions = f"Focus your analysis on: {focus}"

    # Build prompt
    prompt = load_prompt(
        "integrate",
        doxai_content=doxai_content,
        edges_content=edges_content,
        focus_instructions=focus_instructions,
    )

    # Call Gemini
    response = call_gemini(prompt)

    # Parse response
    result = parse_integration_response(response)

    # Optionally apply edges
    if apply_edges and result.proposed_edges:
        added = apply_proposed_edges(result.proposed_edges)
        if added < len(result.proposed_edges):
            result.errors.append(
                f"Applied {added}/{len(result.proposed_edges)} edges (rest were duplicates)"
            )

    return result
