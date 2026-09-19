"""Unit tests for doxagon.export module."""

import json
import os
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from doxagon import export


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def fixtures_dir():
    """Path to test fixtures directory."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_library(fixtures_dir, monkeypatch):
    """Configure doxagon to use fixtures library."""
    lib_path = fixtures_dir / "library"
    monkeypatch.setattr("doxagon.config.LIBRARY_DIR", lib_path)
    monkeypatch.setattr("doxagon.config.DOXAI_DIR", lib_path / "doxai")
    monkeypatch.setattr("doxagon.config.EVIDENCE_DIR", lib_path / "evidence")
    monkeypatch.setattr("doxagon.config.DIEGESES_DIR", lib_path / "diegeses")
    monkeypatch.setattr("doxagon.config.LOGOS_FILE", lib_path / "logos.yaml")
    monkeypatch.setattr("doxagon.config.SCHEMA_FILE", lib_path / "schema.yaml")
    # Also patch in storage module
    monkeypatch.setattr("doxagon.storage.LIBRARY_DIR", lib_path)
    monkeypatch.setattr("doxagon.storage.DOXAI_DIR", lib_path / "doxai")
    monkeypatch.setattr("doxagon.storage.DIEGESES_DIR", lib_path / "diegeses")
    monkeypatch.setattr("doxagon.storage.LOGOS_FILE", lib_path / "logos.yaml")
    # Patch graph module
    monkeypatch.setattr("doxagon.graph.DOXAI_DIR", lib_path / "doxai")
    monkeypatch.setattr("doxagon.graph.DIEGESES_DIR", lib_path / "diegeses")
    monkeypatch.setattr("doxagon.graph.LOGOS_FILE", lib_path / "logos.yaml")
    # Without this the graph module validates these fixtures' edges against the
    # real corpus schema, so the suite only passed where a corpus happened to
    # sit beside the checkout and happened to declare the same edge types.
    monkeypatch.setattr("doxagon.graph.SCHEMA_FILE", lib_path / "schema.yaml")
    monkeypatch.setattr("doxagon.graph.CACHE_DIR", lib_path / ".cache")
    monkeypatch.setattr("doxagon.graph.CACHE_FILE", lib_path / ".cache" / "graph.pkl")
    monkeypatch.setattr("doxagon.graph.HASH_FILE", lib_path / ".cache" / "hash.txt")
    # Patch export module
    monkeypatch.setattr("doxagon.export.LIBRARY_DIR", lib_path)
    monkeypatch.setattr("doxagon.export.DOXAI_DIR", lib_path / "doxai")
    monkeypatch.setattr("doxagon.export.EVIDENCE_DIR", lib_path / "evidence")
    monkeypatch.setattr("doxagon.export.DIEGESES_DIR", lib_path / "diegeses")
    monkeypatch.setattr("doxagon.export.LOGOS_FILE", lib_path / "logos.yaml")
    monkeypatch.setattr("doxagon.export.SCHEMA_FILE", lib_path / "schema.yaml")
    # Invalidate any existing cache
    from doxagon.graph import invalidate_cache
    invalidate_cache()
    return lib_path


# =============================================================================
# Subgraph Extraction Tests
# =============================================================================


def test_extract_diegesis_subgraph_returns_walk_doxai(fixtures_library):
    """Diegesis extraction returns only doxai in walk."""
    result = export.extract_diegesis_subgraph("n-test-narrative", "canonical")
    assert "d-root" in result
    assert "d-child-a" in result
    assert "d-orphan" not in result


def test_extract_diegesis_subgraph_respects_walk_filter(fixtures_library):
    """Different walks return different subsets."""
    canonical = export.extract_diegesis_subgraph("n-test-narrative", "canonical")
    short = export.extract_diegesis_subgraph("n-test-narrative", "short")

    assert "d-child-a" in canonical
    assert "d-child-a" not in short
    assert "d-root" in short


def test_extract_diegesis_subgraph_invalid_walk_raises(fixtures_library):
    """Invalid walk name raises ValueError."""
    with pytest.raises(ValueError) as exc_info:
        export.extract_diegesis_subgraph("n-test-narrative", "nonexistent")
    assert "not found" in str(exc_info.value)


def test_extract_neighborhood_subgraph_respects_hop_limit(fixtures_library):
    """N-hop extraction stops at specified depth."""
    # d-orphan is not connected, so shouldn't appear
    result = export.extract_neighborhood_subgraph("d-root", hops=1)
    assert "d-root" in result
    assert "d-child-a" in result
    assert "d-child-b" in result
    assert "d-orphan" not in result


def test_extract_neighborhood_subgraph_handles_isolated_node(fixtures_library):
    """Orphan node returns only itself."""
    result = export.extract_neighborhood_subgraph("d-orphan", hops=2)
    assert result == {"d-orphan"}


def test_extract_tag_subgraph_matches_any_tag(fixtures_library):
    """Tag filter returns union of matching nodes."""
    result = export.extract_tag_subgraph(["domain:test"])
    assert "d-root" in result
    assert "d-child-a" in result
    assert "d-child-b" in result
    assert "d-orphan" not in result  # has domain:orphan, not domain:test


def test_extract_tag_subgraph_multiple_tags(fixtures_library):
    """Multiple tags return union of matches."""
    result = export.extract_tag_subgraph(["domain:orphan", "domain:secondary"])
    assert "d-orphan" in result  # matches domain:orphan
    assert "d-child-b" in result  # matches domain:secondary
    assert "d-child-a" not in result


# =============================================================================
# Evidence Collection Tests
# =============================================================================


def test_collect_referenced_evidence_follows_links(fixtures_library):
    """Evidence referenced in doxa frontmatter is collected."""
    doxa_ids = {"d-root"}
    result = export.collect_referenced_evidence(doxa_ids)
    assert "e-test-source" in result


def test_collect_referenced_evidence_ignores_missing(fixtures_library):
    """Missing evidence files don't crash collection."""
    # d-child-a has empty evidence list
    doxa_ids = {"d-child-a", "d-nonexistent"}
    result = export.collect_referenced_evidence(doxa_ids)
    assert isinstance(result, set)


# =============================================================================
# Edge Filtering Tests
# =============================================================================


def test_filter_edges_includes_internal_only(fixtures_library):
    """Only edges where both endpoints are in subgraph."""
    node_ids = {"d-root", "d-child-a"}
    edges = export.filter_edges_to_subgraph(node_ids)

    # Should include d-child-a -> d-root and d-root -> d-child-a
    sources = {e["source"] for e in edges}
    targets = {e["target"] for e in edges}
    assert sources <= node_ids
    assert targets <= node_ids


def test_filter_edges_excludes_external(fixtures_library):
    """Edges to/from nodes outside subgraph are excluded."""
    # Only d-root - edges to children should be excluded
    node_ids = {"d-root"}
    edges = export.filter_edges_to_subgraph(node_ids)

    # No edges should remain since all edges involve d-root + children
    # Actually d-child-a -> d-root has d-root as target but d-child-a not in set
    for edge in edges:
        assert edge["source"] in node_ids
        assert edge["target"] in node_ids


# =============================================================================
# Format Export Tests
# =============================================================================


def test_export_as_zip_creates_valid_archive():
    """ZIP export produces extractable archive."""
    doxai = {"d-test": {"id": "d-test", "metadata": {"belief": "test"}, "content": "body"}}
    evidence = {}
    diegeses = {}
    edges = []
    manifest = {"_meta": {"export_type": "test"}}

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "test.zip"
        export.export_as_zip(doxai, evidence, diegeses, edges, output_path, manifest)

        assert output_path.exists()
        with zipfile.ZipFile(output_path, "r") as zf:
            assert "manifest.yaml" in zf.namelist()
            assert "README.md" in zf.namelist()


def test_export_as_zip_contains_manifest():
    """ZIP contains manifest.yaml with metadata."""
    doxai = {"d-test": {"id": "d-test", "metadata": {"belief": "test"}, "content": "body"}}
    manifest = {"_meta": {"export_type": "test", "counts": {"doxai": 1}}}

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "test.zip"
        export.export_as_zip(doxai, {}, {}, [], output_path, manifest)

        with zipfile.ZipFile(output_path, "r") as zf:
            manifest_content = yaml.safe_load(zf.read("manifest.yaml"))
            assert manifest_content["_meta"]["export_type"] == "test"


def test_export_as_yaml_is_valid_yaml():
    """YAML export is parseable."""
    doxai = {"d-test": {"id": "d-test", "metadata": {"belief": "test"}, "content": "body"}}
    manifest = {"_meta": {"export_type": "test"}}

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "test.yaml"
        export.export_as_yaml(doxai, {}, {}, [], output_path, manifest)

        content = yaml.safe_load(output_path.read_text())
        assert "_meta" in content
        assert "doxai" in content


def test_export_as_yaml_contains_all_sections():
    """YAML has _meta, doxai, evidence, edges sections."""
    doxai = {"d-test": {"id": "d-test", "metadata": {}, "content": ""}}
    evidence = {"e-test": {"id": "e-test", "metadata": {}, "content": ""}}
    diegeses = {"n-test": {"id": "n-test", "metadata": {}, "content": ""}}
    edges = [{"source": "d-a", "target": "d-b", "type": "supports"}]
    manifest = {"_meta": {"export_type": "test"}}

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "test.yaml"
        export.export_as_yaml(doxai, evidence, diegeses, edges, output_path, manifest)

        content = yaml.safe_load(output_path.read_text())
        assert "doxai" in content
        assert "evidence" in content
        assert "diegeses" in content
        assert "edges" in content


def test_export_as_json_is_valid_json():
    """JSON export is parseable."""
    doxai = {"d-test": {"id": "d-test", "metadata": {"belief": "test"}, "content": "body"}}
    manifest = {"_meta": {"export_type": "test"}}

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "test.json"
        export.export_as_json(doxai, {}, {}, [], output_path, manifest)

        content = json.loads(output_path.read_text())
        assert "_meta" in content
        assert "doxai" in content


def test_export_as_json_handles_dates():
    """JSON export handles date objects in metadata."""
    from datetime import date, datetime

    doxai = {
        "d-test": {
            "id": "d-test",
            "metadata": {
                "belief": "test",
                "created": date(2025, 1, 1),
                "updated": datetime(2025, 1, 15, 10, 30),
            },
            "content": "body",
        }
    }
    manifest = {"_meta": {"export_type": "test"}}

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "test.json"
        export.export_as_json(doxai, {}, {}, [], output_path, manifest)

        content = json.loads(output_path.read_text())
        assert content["doxai"]["d-test"]["metadata"]["created"] == "2025-01-01"


# =============================================================================
# High-Level Export Tests
# =============================================================================


def test_export_subgraph_diegesis_mode(fixtures_library):
    """Subgraph export by diegesis works."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "test.json"
        result = export.export_subgraph(
            output_path,
            format="json",
            diegesis="n-test-narrative",
            walk="canonical",
        )

        assert result["doxai"] == 2  # d-root and d-child-a
        content = json.loads(output_path.read_text())
        assert "d-root" in content["doxai"]


def test_export_subgraph_root_mode(fixtures_library):
    """Subgraph export by root node works."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "test.json"
        result = export.export_subgraph(
            output_path,
            format="json",
            root="d-root",
            hops=1,
        )

        assert result["doxai"] >= 1
        content = json.loads(output_path.read_text())
        assert "d-root" in content["doxai"]


def test_export_subgraph_tag_mode(fixtures_library):
    """Subgraph export by tag works."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "test.json"
        result = export.export_subgraph(
            output_path,
            format="json",
            tags=["domain:orphan"],
        )

        assert result["doxai"] == 1
        content = json.loads(output_path.read_text())
        assert "d-orphan" in content["doxai"]


def test_export_full_library(fixtures_library):
    """Library export includes all content."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "test.yaml"
        result = export.export_full_library(output_path, format="yaml")

        assert result["doxai"] == 4  # 4 fixture doxai
        assert result["evidence"] == 1  # 1 fixture evidence
        assert result["diegeses"] == 1  # 1 fixture diegesis
