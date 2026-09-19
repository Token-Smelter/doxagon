from fastapi import APIRouter, Query, HTTPException
import networkx as nx
from doxagon.graph import load_graph, graph_to_model, compute_hash
from doxagon.models import Graph
from doxagon.config import DIEGESES_DIR
import frontmatter

router = APIRouter(prefix="/graph", tags=["graph"])


def get_diegesis_doxai(slug: str, walk: str | None = None) -> list[str]:
    """Get all doxai slugs from a diegesis, optionally filtered by walk."""
    path = DIEGESES_DIR / f"{slug}.md"
    if not path.exists():
         path = DIEGESES_DIR / f"n-{slug}.md"

    if not path.exists():
        raise HTTPException(status_code=404, detail="Diegesis not found")

    doc = frontmatter.load(path)
    sections = doc.get('sections', {})
    walks = doc.get('walks', {})

    if sections:
        # New format: sections contain doxai
        if walk and walk in walks:
            # Filter to sections in this walk only
            walk_sections = walks[walk]
            doxai = []
            for section_key in walk_sections:
                section = sections.get(section_key, {})
                if isinstance(section, dict):
                    doxai.extend(section.get('doxai', []))
            return doxai
        else:
            # Return all doxai from all sections
            doxai = []
            for section in sections.values():
                if isinstance(section, dict):
                    doxai.extend(section.get('doxai', []))
            return doxai
    elif isinstance(walks, list):
        # Old format: walks is a flat list of doxa slugs
        return walks
    else:
        return []


@router.get("", response_model=Graph)
def get_full_graph() -> Graph:
    """Return full graph."""
    G = load_graph()
    version = compute_hash()
    return graph_to_model(G, version)


@router.get("/version")
def get_version() -> dict:
    """Return current graph version hash."""
    return {"version": compute_hash()}


@router.get("/scoped", response_model=Graph)
def get_scoped_graph(
    diegesis: str | None = Query(None),
    walk: str | None = Query(None),
    root: str | None = Query(None),
    hops: int = Query(2, ge=1, le=3)
) -> Graph:
    """Return filtered subgraph.

    Args:
        diegesis: Filter to nodes in this diegesis
        walk: Filter to nodes in this named walk (requires diegesis)
        root: Center on this node and show N-hop neighborhood
        hops: Number of hops for neighborhood (1-3)
    """
    G = load_graph()
    version = compute_hash()

    if diegesis:
        try:
            doxai = get_diegesis_doxai(diegesis, walk)
            nodes = set(doxai)
            # Add 1-hop neighbors
            for n in doxai:
                if n in G:
                    nodes.update(G.predecessors(n))
                    nodes.update(G.successors(n))
            # Filter valid nodes
            nodes = {n for n in nodes if n in G}
            subgraph = G.subgraph(nodes).copy()
        except HTTPException:
            subgraph = nx.MultiDiGraph()
    elif root:
        if root not in G:
             raise HTTPException(status_code=404, detail="Root node not found")
        # N-hop neighborhood
        nodes = set(nx.single_source_shortest_path_length(
            G.to_undirected(), root, cutoff=hops
        ).keys())
        subgraph = G.subgraph(nodes).copy()
    else:
        subgraph = G

    return graph_to_model(subgraph, version)
