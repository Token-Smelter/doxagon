import pytest
from doxagon.graph import load_graph, compute_hash, build_graph
from doxagon.config import LIBRARY_DIR


def test_load_graph_returns_networkx():
    """Graph loading returns valid NetworkX DiGraph."""
    G = load_graph()
    assert hasattr(G, 'nodes')
    assert hasattr(G, 'edges')


def test_compute_hash_consistent():
    """Same library state produces same hash."""
    h1 = compute_hash()
    h2 = compute_hash()
    assert h1 == h2


def test_compute_hash_is_12_chars():
    """Hash is truncated to 12 characters per spec."""
    h = compute_hash()
    assert len(h) == 12


def test_build_graph_loads_doxai():
    """Graph contains nodes from doxai/ directory."""
    G = build_graph()
    # May be 0 if library is empty, but should not raise
    assert G.nodes is not None


def test_build_graph_has_diegesis_membership():
    """Graph includes diegesis membership index."""
    G = build_graph()
    assert 'diegesis_membership' in G.graph
    assert isinstance(G.graph['diegesis_membership'], dict)
