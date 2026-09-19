"""File operations for Doxagon library management."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import frontmatter
import yaml

from doxagon import config
from doxagon.validation import GraphIntegrityError, ValidationIssue, ValidationReport, validate_edge_records

LIBRARY_DIR = config.LIBRARY_DIR
DOXAI_DIR = config.DOXAI_DIR
DIEGESES_DIR = config.DIEGESES_DIR
LOGOS_FILE = config.LOGOS_FILE
SCHEMA_FILE = config.SCHEMA_FILE


def read_doxa(slug: str) -> dict:
    """Load a single doxa file."""
    path = DOXAI_DIR / f"{slug}.md"
    if not path.exists():
        raise FileNotFoundError(f"Doxa not found: {slug}")
    doc = frontmatter.load(path)
    return {"metadata": dict(doc.metadata), "content": doc.content}


def read_diegesis(slug: str) -> dict:
    """Load a single diegesis file."""
    for variant in [f"{slug}.md", f"n-{slug}.md"]:
        path = DIEGESES_DIR / variant
        if path.exists():
            doc = frontmatter.load(path)
            return {"metadata": dict(doc.metadata), "content": doc.content}
    raise FileNotFoundError(f"Diegesis not found: {slug}")


def read_logos(path: Path | None = None) -> dict[str, Any]:
    """Load logos.yaml without treating parse failure as an empty graph."""
    logos_path = path or LOGOS_FILE
    if not logos_path.exists():
        return {"edges": []}
    data = yaml.safe_load(logos_path.read_text())
    if data is None:
        return {"edges": []}
    if not isinstance(data, dict) or "edges" not in data or not isinstance(data["edges"], list):
        report = ValidationReport([ValidationIssue("malformed_logos", "logos.yaml must contain an edges list")])
        raise GraphIntegrityError(report)
    return data


def _schema_values(schema_file: Path) -> set[str]:
    schema = yaml.safe_load(schema_file.read_text()) or {}
    return set(schema.get("edge_types", {}))


def write_logos(
    data: dict[str, Any],
    *,
    path: Path | None = None,
    doxai_dir: Path | None = None,
    schema_file: Path | None = None,
) -> None:
    """Validate and atomically replace logos.yaml."""
    logos_path = path or LOGOS_FILE
    nodes_path = doxai_dir or DOXAI_DIR
    schema_path = schema_file or SCHEMA_FILE
    edges = data.get("edges") if isinstance(data, dict) else None
    if not isinstance(edges, list):
        raise GraphIntegrityError(
            ValidationReport([ValidationIssue("malformed_logos", "logos.yaml must contain an edges list")])
        )

    doxa_ids = {
        item.stem
        for item in nodes_path.glob("**/*.md")
        if item.stem.upper() != "README"
    } if nodes_path.exists() else set()
    report = validate_edge_records(edges, doxa_ids=doxa_ids, valid_edge_types=_schema_values(schema_path))
    if not report.valid:
        raise GraphIntegrityError(report)

    logos_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = yaml.safe_dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=logos_path.parent,
            prefix=f".{logos_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
            temporary_path = Path(handle.name)
        os.replace(temporary_path, logos_path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def list_doxai() -> list[str]:
    """List all doxa slugs."""
    if not DOXAI_DIR.exists():
        return []
    return [p.stem for p in DOXAI_DIR.glob("*.md")]


def list_diegeses() -> list[str]:
    """List all diegesis slugs."""
    if not DIEGESES_DIR.exists():
        return []
    return [p.stem.removeprefix("n-") for p in DIEGESES_DIR.glob("*.md")]
