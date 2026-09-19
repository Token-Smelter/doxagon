"""FastAPI dependency injection."""

from functools import lru_cache
from doxagon.graph import load_graph, compute_hash
import networkx as nx


@lru_cache()
def get_graph() -> nx.MultiDiGraph:
    """Cached graph dependency."""
    return load_graph()


def get_fresh_graph() -> nx.MultiDiGraph:
    """Force fresh graph load (cache invalidation)."""
    get_graph.cache_clear()
    return get_graph()


def get_version() -> str:
    """Get current graph version hash."""
    return compute_hash()
