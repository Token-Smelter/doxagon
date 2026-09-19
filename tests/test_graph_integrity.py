from __future__ import annotations

from itertools import islice, product
from pathlib import Path

import networkx as nx
import pytest
import yaml
from click.testing import CliRunner

import doxagon.graph as graph_module
from apps.web.backend.routers import edges as edge_router
from doxagon.models import EdgeCreate
from doxagon.storage import write_logos
from doxagon.validation import GraphIntegrityError, validate_edge_records, validate_library
from scripts import dox as dox_cli

EDGE_TYPES = ["supports", "contradicts", "requires", "elaborates", "grounds", "causes", "resolves"]


def _write_doxa(path: Path, slug: str, *, belief: str | None = None, tags: list[str] | None = None) -> None:
    metadata = {
        "status": "canonical",
        "tags": tags or ["domain:verification"],
        "evidence": [],
    }
    if belief is not None:
        metadata["belief"] = belief
    body = yaml.safe_dump(metadata, sort_keys=False).strip()
    (path / f"{slug}.md").write_text(f"---\n{body}\n---\n")


def _configure_graph(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, node_count: int = 3) -> dict[str, Path]:
    library = tmp_path / "library"
    doxai = library / "doxai"
    evidence = library / "evidence"
    diegeses = library / "diegeses"
    cache = tmp_path / ".cache"
    for directory in (doxai, evidence, diegeses):
        directory.mkdir(parents=True)
    for index in range(node_count):
        _write_doxa(doxai, f"d-{index}", belief=f"Belief {index}")

    schema = library / "schema.yaml"
    schema.write_text(
        yaml.safe_dump(
            {
                "edge_types": {edge_type: {} for edge_type in EDGE_TYPES},
                "tag_prefixes": {"domain": {"values": ["verification"]}},
            },
            sort_keys=False,
        )
    )
    paths = {
        "doxai": doxai,
        "evidence": evidence,
        "diegeses": diegeses,
        "logos": library / "logos.yaml",
        "schema": schema,
        "cache": cache,
    }
    for name, value in {
        "DOXAI_DIR": doxai,
        "EVIDENCE_DIR": evidence,
        "DIEGESES_DIR": diegeses,
        "LOGOS_FILE": paths["logos"],
        "SCHEMA_FILE": schema,
        "CACHE_DIR": cache,
        "CACHE_FILE": cache / "graph.pkl",
        "HASH_FILE": cache / "hash.txt",
    }.items():
        monkeypatch.setattr(graph_module, name, value)
    return paths


def _metadata_edge(source: str, target: str, edge_type: str, index: int) -> dict:
    return {
        "source": source,
        "target": target,
        "type": edge_type,
        "alias": f"alias-{index}",
        "rationale": f"rationale-{index}",
        "provenance": {"method": "test", "audit": "2026-07-11", "batch": index},
        "confidence": "high",
        "annotation": f"annotation-{index}",
        "strength": "strong",
        "disputed": False,
        "reviewer_notes": f"review-{index}",
        "created": "2026-07-11",
    }


def test_pre_migration_1078_edges_round_trip_without_metadata_loss(monkeypatch, tmp_path):
    paths = _configure_graph(monkeypatch, tmp_path, node_count=20)
    identities = (
        (f"d-{source}", f"d-{target}", edge_type)
        for source, target, edge_type in product(range(20), range(20), EDGE_TYPES)
        if source != target
    )
    source_edges = [
        _metadata_edge(source, target, edge_type, index)
        for index, (source, target, edge_type) in enumerate(islice(identities, 1078))
    ]
    paths["logos"].write_text(yaml.safe_dump({"edges": source_edges}, sort_keys=False))

    graph = graph_module.build_graph()
    assert isinstance(graph, nx.MultiDiGraph)
    assert graph.number_of_edges() == 1078
    assert len(graph_module.graph_to_model(graph, "version").edges) == 1078

    graph_module.save_logos(graph)
    saved_edges = yaml.safe_load(paths["logos"].read_text())["edges"]
    assert len(saved_edges) == 1078
    def identity(edge):
        return edge["source"], edge["target"], edge["type"]

    assert sorted(saved_edges, key=identity) == sorted(source_edges, key=identity)


def test_invalid_or_collapsing_saves_are_atomic(monkeypatch, tmp_path):
    paths = _configure_graph(monkeypatch, tmp_path, node_count=2)
    original = {"edges": [_metadata_edge("d-0", "d-1", "supports", 0)]}
    paths["logos"].write_text(yaml.safe_dump(original, sort_keys=False))
    original_bytes = paths["logos"].read_bytes()

    graph = graph_module.build_graph()
    graph.add_edge("d-0", "d-missing", key="supports", type="supports")
    with pytest.raises(GraphIntegrityError):
        graph_module.save_logos(graph)
    assert paths["logos"].read_bytes() == original_bytes

    with pytest.raises(GraphIntegrityError):
        graph_module.save_logos(nx.DiGraph())
    assert paths["logos"].read_bytes() == original_bytes

    duplicate = {"edges": [original["edges"][0], dict(original["edges"][0])]}
    with pytest.raises(GraphIntegrityError):
        write_logos(duplicate, path=paths["logos"], doxai_dir=paths["doxai"], schema_file=paths["schema"])
    assert paths["logos"].read_bytes() == original_bytes


def test_malformed_logos_load_and_cli_validation_fail_closed(monkeypatch, tmp_path):
    paths = _configure_graph(monkeypatch, tmp_path, node_count=2)
    paths["logos"].write_text("not_edges: []\n")

    with pytest.raises(GraphIntegrityError) as error:
        graph_module.build_graph()
    assert [issue.code for issue in error.value.report.errors] == ["malformed_logos"]

    monkeypatch.setattr(dox_cli, "LOGOS_FILE", paths["logos"])
    result = CliRunner().invoke(dox_cli.cli, ["validate"])
    assert result.exit_code == 1
    assert "ERROR [malformed_logos]" in result.output


def test_build_fails_closed_instead_of_creating_phantom_nodes(monkeypatch, tmp_path):
    paths = _configure_graph(monkeypatch, tmp_path, node_count=2)
    paths["logos"].write_text(
        yaml.safe_dump({"edges": [{"source": "d-0", "target": "NEW:1", "type": "supports"}]})
    )
    with pytest.raises(GraphIntegrityError) as error:
        graph_module.build_graph()
    codes = {issue.code for issue in error.value.report.errors}
    assert {"placeholder_endpoint", "dangling_endpoint"} <= codes


def test_validation_detects_all_integrity_conditions_and_allows_distinct_parallel_types(tmp_path):
    doxai = tmp_path / "doxai"
    doxai.mkdir()
    _write_doxa(doxai, "d-a", belief=None, tags=["domain:not-registered"])
    _write_doxa(doxai, "d-b", belief="B")
    edges = [
        {"source": "d-a", "target": "d-b", "type": "supports"},
        {"source": "d-a", "target": "d-b", "type": "supports"},
        {"source": "d-a", "target": "d-b", "type": "grounds"},
        {"source": "NEW:1", "target": "d-b", "type": "supports"},
        {"source": "STALE:1", "target": "d-b", "type": "supports"},
        {"source": "e-source", "target": "d-b", "type": "supports"},
        {"source": "d-missing", "target": "d-b", "type": "supports"},
        {"source": "d-a", "target": "d-b", "type": "free-text"},
    ]
    report = validate_library(
        edges=edges,
        doxai_dir=doxai,
        valid_edge_types=set(EDGE_TYPES),
        valid_domains={"verification"},
    )
    codes = {issue.code for issue in report.issues}
    assert {
        "placeholder_endpoint",
        "evidence_endpoint",
        "dangling_endpoint",
        "noncanonical_type",
        "malformed_domain",
        "missing_belief",
        "exact_duplicate",
        "parallel_typed_pair",
    } <= codes

    parallel_only = validate_edge_records(
        [
            {"source": "d-a", "target": "d-b", "type": "supports"},
            {"source": "d-a", "target": "d-b", "type": "grounds"},
        ],
        doxa_ids={"d-a", "d-b"},
        valid_edge_types=set(EDGE_TYPES),
    )
    assert parallel_only.valid
    assert [issue.code for issue in parallel_only.warnings] == ["parallel_typed_pair"]


def test_path_direction_is_explicit_and_tree_labels_actual_types(monkeypatch):
    graph = nx.MultiDiGraph()
    graph.add_node("d-a", belief="A")
    graph.add_node("d-b", belief="B")
    graph.add_edge("d-b", "d-a", key="supports", type="supports")
    graph.add_edge("d-a", "d-b", key="grounds", type="grounds", alias="specific grounding")
    graph.add_edge("d-a", "d-b", key="contradicts", type="contradicts")
    monkeypatch.setattr(dox_cli, "load_graph", lambda: graph)

    runner = CliRunner()
    directed = runner.invoke(dox_cli.cli, ["path", "d-b", "d-a"])
    assert directed.exit_code == 0
    assert "Directed paths" in directed.output

    no_fallback = runner.invoke(dox_cli.cli, ["path", "d-a", "d-b", "--direction", "directed"])
    assert no_fallback.exit_code == 0
    assert "Directed paths" in no_fallback.output

    reverse_only = nx.MultiDiGraph()
    reverse_only.add_nodes_from(graph.nodes(data=True))
    reverse_only.add_edge("d-b", "d-a", key="supports", type="supports")
    monkeypatch.setattr(dox_cli, "load_graph", lambda: reverse_only)
    assert "No directed path" in runner.invoke(dox_cli.cli, ["path", "d-a", "d-b"]).output
    assert "Undirected paths" in runner.invoke(
        dox_cli.cli, ["path", "d-a", "d-b", "--direction", "undirected"]
    ).output

    monkeypatch.setattr(dox_cli, "load_graph", lambda: graph)
    tree = runner.invoke(dox_cli.cli, ["tree", "d-a", "--depth", "1"])
    assert tree.exit_code == 0
    assert "[grounds] specific grounding" in tree.output
    assert "[contradicts]" in tree.output
    assert "↓ Grounds" not in tree.output


def test_evidence_changes_cache_fingerprint(monkeypatch, tmp_path):
    paths = _configure_graph(monkeypatch, tmp_path, node_count=1)
    paths["logos"].write_text("edges: []\n")
    evidence = paths["evidence"] / "e-source.md"
    evidence.write_text("first")
    before = graph_module.compute_hash()
    evidence.write_text("second")
    assert graph_module.compute_hash() != before


def test_edge_api_preserves_metadata_and_parallel_types(monkeypatch, tmp_path):
    paths = _configure_graph(monkeypatch, tmp_path, node_count=2)
    paths["logos"].write_text("edges: []\n")
    monkeypatch.setattr(edge_router, "LOGOS_FILE", paths["logos"])
    monkeypatch.setattr(edge_router, "DOXAI_DIR", paths["doxai"])
    monkeypatch.setattr(edge_router, "SCHEMA_FILE", paths["schema"])
    monkeypatch.setattr(edge_router, "invalidate_cache", lambda: None)

    for edge_type in ("supports", "grounds"):
        edge_router.create_edge(
            EdgeCreate(
                source="d-0",
                target="d-1",
                type=edge_type,
                rationale=f"why-{edge_type}",
                provenance={"method": "manual", "ticket": "GATE-0"},
                confidence="high",
                annotation="legacy note",
                strength="strong",
            )
        )
    saved = edge_router._load_logos()["edges"]
    assert len(saved) == 2
    supports = edge_router.get_edge("d-0", "d-1", "supports")
    assert supports.rationale == "why-supports"
    assert supports.provenance.model_extra["ticket"] == "GATE-0"
    assert supports.annotation == "legacy note"


def test_live_logos_has_clean_endpoints_types_and_preserved_parallel_pairs():
    """Assert corpus integrity, not a frozen corpus size.

    The exact counts this previously asserted (1,009 edges, 19 warnings) were a
    snapshot of one day's private corpus. They broke the moment the corpus grew
    and proved nothing about integrity in the meantime. Per the separation
    design, exact live counts belong to a private-CI baseline, never to a public
    assertion; the public tree keeps the property that actually matters, and
    skips once no corpus is co-located with the checkout.
    """

    library = Path(__file__).parents[1] / "library"
    if not library.is_dir():
        pytest.skip("no co-located private corpus in this checkout")
    schema = yaml.safe_load((library / "schema.yaml").read_text())
    edges = yaml.safe_load((library / "logos.yaml").read_text())["edges"]
    doxa_ids = {path.stem for path in (library / "doxai").rglob("*.md") if path.stem.upper() != "README"}
    report = validate_edge_records(edges, doxa_ids=doxa_ids, valid_edge_types=set(schema["edge_types"]))
    assert report.valid
    assert edges, "a present corpus must not be empty"
