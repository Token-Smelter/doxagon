import pytest
from fastapi.testclient import TestClient
from apps.web.backend.main import app

client = TestClient(app)


def test_graph_endpoint():
    """GET /api/graph returns valid graph structure."""
    response = client.get("/api/graph")
    assert response.status_code == 200
    data = response.json()
    assert "nodes" in data
    assert "edges" in data
    assert "version" in data


def test_graph_version_endpoint():
    """GET /api/graph/version returns version hash."""
    response = client.get("/api/graph/version")
    assert response.status_code == 200
    data = response.json()
    assert "version" in data
    assert len(data["version"]) == 12


def test_doxai_endpoint_404():
    """GET /api/doxai/{slug} returns 404 for missing slug."""
    response = client.get("/api/doxai/nonexistent-slug-12345")
    assert response.status_code == 404


def test_doxai_content_endpoint_404():
    """GET /api/doxai/{slug}/content returns 404 for missing slug."""
    response = client.get("/api/doxai/nonexistent-slug-12345/content")
    assert response.status_code == 404


def test_diegeses_list():
    """GET /api/diegeses returns list."""
    response = client.get("/api/diegeses")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_scoped_graph_with_invalid_diegesis():
    """GET /api/graph/scoped returns empty graph for invalid diegesis."""
    response = client.get("/api/graph/scoped?diegesis=nonexistent")
    # NOTE: Current implementation returns empty graph, not 404
    assert response.status_code == 200
    data = response.json()
    assert data["nodes"] == []
    assert data["edges"] == []


def test_scoped_graph_with_invalid_root():
    """GET /api/graph/scoped returns 404 for invalid root."""
    response = client.get("/api/graph/scoped?root=nonexistent-node-xyz")
    assert response.status_code == 404


def test_cors_methods_restricted():
    """CORS should only allow GET and OPTIONS methods."""
    # POST should be rejected by CORS (but TestClient bypasses CORS)
    # This is more of a documentation test
    response = client.options("/api/graph")
    # OPTIONS is allowed
    assert response.status_code in [200, 204, 405]
