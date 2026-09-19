"""Instance-scoped graph reads for an opened vault."""

from __future__ import annotations

from collections import defaultdict
import hashlib
from typing import Iterator

import networkx as nx

from doxagon.models import DoxaNode, Edge, Graph
from doxagon.repositories import FilesystemEdgeRepository, FilesystemKnowledgeRepository


class GraphService:
    """Build and cache one vault's graph without consulting process-global paths."""

    def __init__(self, knowledge: FilesystemKnowledgeRepository, edges: FilesystemEdgeRepository) -> None:
        self._knowledge = knowledge
        self._edges = edges
        self._cached_hash: str | None = None
        self._cached_graph: nx.MultiDiGraph | None = None

    def authority_hash(self) -> str:
        hasher = hashlib.sha256()
        root = self._knowledge.knowledge_root
        for path in self._knowledge.authority_files():
            hasher.update(path.relative_to(root).as_posix().encode())
            hasher.update(path.read_bytes())
        return hasher.hexdigest()[:12]

    def read_graph(self) -> nx.MultiDiGraph:
        version = self.authority_hash()
        if self._cached_hash == version and self._cached_graph is not None:
            return self._cached_graph

        graph = nx.MultiDiGraph()
        for slug, metadata, content in self._knowledge.doxai():
            graph.add_node(
                slug,
                belief=metadata.get("belief", ""),
                tags=metadata.get("tags", []),
                evidence=metadata.get("evidence", []),
                content=content,
            )

        for edge in self._edges.edge_records(set(graph.nodes)):
            source = edge.pop("source")
            target = edge.pop("target")
            graph.add_edge(source, target, key=edge.get("type"), **edge)

        membership: defaultdict[str, list[str]] = defaultdict(list)
        for diegesis_slug, metadata in self._knowledge.diegeses():
            sections = metadata.get("sections", {})
            walks = metadata.get("walks", {})
            if isinstance(sections, dict) and sections:
                for section in sections.values():
                    if isinstance(section, dict):
                        for slug in section.get("doxai", []):
                            if diegesis_slug not in membership[slug]:
                                membership[slug].append(diegesis_slug)
            elif isinstance(walks, list):
                for slug in walks:
                    if diegesis_slug not in membership[slug]:
                        membership[slug].append(diegesis_slug)
        graph.graph["diegesis_membership"] = dict(membership)
        self._cached_hash = version
        self._cached_graph = graph
        return graph

    def graph_model(self) -> Graph:
        graph = self.read_graph()
        nodes = []
        for slug, data in graph.nodes(data=True):
            node_data = {key: value for key, value in data.items() if key in DoxaNode.model_fields}
            node_data.setdefault("title", slug)
            nodes.append(DoxaNode(slug=slug, **node_data))
        edges = [Edge(source=source, target=target, **dict(data)) for source, target, _, data in iter_edges(graph)]
        return Graph(nodes=nodes, edges=edges, version=self.authority_hash())

    def close(self) -> None:
        self._cached_graph = None
        self._cached_hash = None


def iter_edges(graph: nx.MultiDiGraph) -> Iterator[tuple[str, str, str, dict]]:
    """Iterate typed edges in deterministic order."""

    yield from graph.edges(keys=True, data=True)
