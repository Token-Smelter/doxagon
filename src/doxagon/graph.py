from __future__ import annotations

import hashlib
import pickle
from collections import defaultdict
from typing import Any, Iterator

import frontmatter
import networkx as nx
import yaml

from doxagon.config import (
    CACHE_DIR,
    CACHE_FILE,
    DIEGESES_DIR,
    DOXAI_DIR,
    EVIDENCE_DIR,
    HASH_FILE,
    LOGOS_FILE,
    SCHEMA_FILE,
)
from doxagon.models import DoxaNode, Edge, Graph
from doxagon.storage import read_logos, write_logos
from doxagon.validation import GraphIntegrityError, ValidationIssue, ValidationReport, normalize_edge, validate_edge_records


def compute_hash() -> str:
    """Compute a fingerprint of every authoritative graph input."""
    hasher = hashlib.sha256()
    for directory in (DOXAI_DIR, EVIDENCE_DIR, DIEGESES_DIR):
        if directory.exists():
            for path in sorted(directory.glob("**/*.md")):
                hasher.update(str(path.relative_to(directory)).encode())
                hasher.update(path.read_bytes())
    if LOGOS_FILE.exists():
        hasher.update(LOGOS_FILE.read_bytes())
    return hasher.hexdigest()[:12]


def _valid_edge_types() -> set[str]:
    """Return the declared edge-type vocabulary, or none when no schema exists.

    Every other authoritative read on this path checks existence first, so an
    absent corpus degrades to an empty graph. This one did not, which turned a
    missing schema into a FileNotFoundError from deep inside a graph build.
    Matches FilesystemEdgeRepository.edge_types on the converted path.
    """

    if not SCHEMA_FILE.exists():
        return set()
    schema = yaml.safe_load(SCHEMA_FILE.read_text()) or {}
    return set(schema.get("edge_types", {}))


def edge_records_between(graph: nx.MultiDiGraph, source: str, target: str) -> list[tuple[str, dict[str, Any]]]:
    """Return every typed edge for an ordered node pair in deterministic order."""
    records = graph.get_edge_data(source, target, default={})
    return [(str(key), data) for key, data in sorted(records.items(), key=lambda item: str(item[0]))]


def iter_edges(graph: nx.MultiDiGraph) -> Iterator[tuple[str, str, str, dict[str, Any]]]:
    """Iterate all edges with deterministic typed keys."""
    yield from graph.edges(keys=True, data=True)


def build_graph() -> nx.MultiDiGraph:
    """Build a parallel-edge-safe graph from authoritative library files."""
    graph = nx.MultiDiGraph()

    if DOXAI_DIR.exists():
        for doxa_file in DOXAI_DIR.glob("**/*.md"):
            if doxa_file.stem.upper() == "README":
                continue
            try:
                post = frontmatter.load(doxa_file)
            except Exception as exc:
                raise GraphIntegrityError(
                    ValidationReport([ValidationIssue("invalid_frontmatter", f"{doxa_file}: {exc}")])
                ) from exc
            graph.add_node(
                doxa_file.stem,
                belief=post.get("belief", ""),
                tags=post.get("tags", []),
                evidence=post.get("evidence", []),
                path=str(doxa_file),
                content=post.content,
            )

    logos = read_logos(LOGOS_FILE)
    report = validate_edge_records(
        logos.get("edges", []),
        doxa_ids=set(graph.nodes),
        valid_edge_types=_valid_edge_types(),
    )
    if not report.valid:
        raise GraphIntegrityError(report)

    for raw_edge in logos.get("edges", []):
        edge = normalize_edge(raw_edge)
        if edge is None:
            continue
        source = edge.pop("source")
        target = edge.pop("target")
        edge_type = edge.get("type")
        graph.add_edge(source, target, key=edge_type, **edge)

    diegesis_membership: defaultdict[str, list[str]] = defaultdict(list)
    if DIEGESES_DIR.exists():
        for path in DIEGESES_DIR.glob("*.md"):
            try:
                doc = frontmatter.load(path)
            except Exception as exc:
                raise GraphIntegrityError(
                    ValidationReport([ValidationIssue("invalid_frontmatter", f"{path}: {exc}")])
                ) from exc
            diegesis_slug = path.stem.removeprefix("n-")
            sections = doc.get("sections", {})
            walks = doc.get("walks", {})
            if sections:
                for section in sections.values():
                    if isinstance(section, dict):
                        for doxa_slug in section.get("doxai", []):
                            if diegesis_slug not in diegesis_membership[doxa_slug]:
                                diegesis_membership[doxa_slug].append(diegesis_slug)
            elif isinstance(walks, list):
                for doxa_slug in walks:
                    if diegesis_slug not in diegesis_membership[doxa_slug]:
                        diegesis_membership[doxa_slug].append(diegesis_slug)

    graph.graph["diegesis_membership"] = dict(diegesis_membership)
    return graph


def load_graph(force_refresh: bool = False) -> nx.MultiDiGraph:
    """Load graph from cache or rebuild from authoritative files."""
    current_hash = compute_hash()
    if not force_refresh and CACHE_FILE.exists() and HASH_FILE.exists():
        try:
            cached = pickle.loads(CACHE_FILE.read_bytes())
            if HASH_FILE.read_text().strip() == current_hash and isinstance(cached, nx.MultiDiGraph):
                return cached
        except Exception:
            pass

    graph = build_graph()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_bytes(pickle.dumps(graph))
    HASH_FILE.write_text(current_hash)
    return graph


def graph_to_model(graph: nx.MultiDiGraph, version: str) -> Graph:
    """Convert every node and typed edge to the API model."""
    nodes = []
    for slug, data in graph.nodes(data=True):
        node_data = {key: value for key, value in data.items() if key in DoxaNode.model_fields}
        node_data.setdefault("title", slug)
        nodes.append(DoxaNode(slug=slug, **node_data))

    edges = []
    for source, target, _, data in iter_edges(graph):
        edges.append(Edge(source=source, target=target, **dict(data)))
    return Graph(nodes=nodes, edges=edges, version=version)


def save_logos(graph: nx.MultiDiGraph) -> None:
    """Validate and atomically persist every edge and all attached metadata."""
    if not isinstance(graph, nx.MultiDiGraph):
        raise GraphIntegrityError(
            ValidationReport(
                [ValidationIssue("collapsing_graph", "Refusing to save a graph without parallel-edge support")]
            )
        )

    edges: list[dict[str, Any]] = []
    for source, target, _, data in iter_edges(graph):
        edge = {"source": source, "target": target, **dict(data)}
        edges.append(edge)
    edges.sort(key=lambda edge: (edge["source"], edge["target"], edge.get("type", "")))

    existing = read_logos(LOGOS_FILE)
    output = {**existing, "edges": edges}
    write_logos(output, path=LOGOS_FILE, doxai_dir=DOXAI_DIR, schema_file=SCHEMA_FILE)


def invalidate_cache() -> None:
    """Remove cache files to force rebuild."""
    if CACHE_FILE.exists():
        CACHE_FILE.unlink()
    if HASH_FILE.exists():
        HASH_FILE.unlink()
