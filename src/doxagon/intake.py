"""Import functionality for Doxagon knowledge graph.

Counterpart to doxagon.export — reads any export format (zip, yaml, json),
validates, detects conflicts, and merges into the local library.

Module named 'intake' to avoid collision with Python's 'import' keyword.
"""

import json
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Literal

import frontmatter
import yaml

from doxagon.config import (
    DOXAI_DIR,
    DIEGESES_DIR,
    EVIDENCE_DIR,
    SCHEMA_FILE,
)
from doxagon.export import _write_markdown_file
from doxagon.graph import invalidate_cache
from doxagon.storage import read_logos, write_logos


# =============================================================================
# Data Structures
# =============================================================================

Strategy = Literal["skip", "overwrite", "newer"]


@dataclass
class ImportBundle:
    """Normalized in-memory representation of any export format."""

    manifest: dict = field(default_factory=dict)
    doxai: dict[str, dict] = field(default_factory=dict)
    evidence: dict[str, dict] = field(default_factory=dict)
    diegeses: dict[str, dict] = field(default_factory=dict)
    edges: list[dict] = field(default_factory=list)


@dataclass
class Conflict:
    """A single entity that exists both locally and in the import."""

    entity_type: str  # "doxa" | "evidence" | "diegesis" | "edge"
    slug: str
    local: dict = field(default_factory=dict)
    incoming: dict = field(default_factory=dict)


@dataclass
class ConflictReport:
    """Full comparison between bundle and local library."""

    conflicts: list[Conflict] = field(default_factory=list)
    new_doxai: set[str] = field(default_factory=set)
    new_evidence: set[str] = field(default_factory=set)
    new_diegeses: set[str] = field(default_factory=set)
    new_edges: list[dict] = field(default_factory=list)
    identical: dict[str, int] = field(default_factory=dict)


@dataclass
class ImportResult:
    """Outcome of an import operation."""

    created: dict[str, int] = field(default_factory=dict)
    updated: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


# =============================================================================
# Bundle Loading
# =============================================================================


def load_bundle(path: Path) -> ImportBundle:
    """Read zip, yaml, or json export into normalized ImportBundle.

    Format detection by extension:
    - .zip → archive with library/ directory structure
    - .yaml/.yml → single-file YAML bundle
    - .json → single-file JSON bundle

    Raises ValueError if format unrecognized or structure invalid.
    """
    path = Path(path)
    if not path.exists():
        raise ValueError(f"File not found: {path}")

    suffix = path.suffix.lower()
    if suffix == ".zip":
        return _load_from_zip(path)
    elif suffix in (".yaml", ".yml"):
        return _load_from_yaml(path)
    elif suffix == ".json":
        return _load_from_json(path)
    else:
        raise ValueError(f"Unrecognized format: {suffix}. Expected .zip, .yaml, .yml, or .json")


def _load_from_zip(path: Path) -> ImportBundle:
    """Extract zip archive into ImportBundle."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        with zipfile.ZipFile(path, "r") as zf:
            zf.extractall(tmp_path)

        # Load manifest
        manifest = {}
        manifest_path = tmp_path / "manifest.yaml"
        if manifest_path.exists():
            manifest = yaml.safe_load(manifest_path.read_text()) or {}

        lib_dir = tmp_path / "library"
        if not lib_dir.exists():
            raise ValueError("ZIP archive missing library/ directory")

        # Load doxai
        doxai = {}
        doxai_dir = lib_dir / "doxai"
        if doxai_dir.exists():
            for md_file in doxai_dir.glob("*.md"):
                slug = md_file.stem
                doc = frontmatter.load(md_file)
                doxai[slug] = {
                    "id": slug,
                    "metadata": dict(doc.metadata),
                    "content": doc.content,
                }

        # Load evidence
        evidence = {}
        evidence_dir = lib_dir / "evidence"
        if evidence_dir.exists():
            for md_file in evidence_dir.glob("*.md"):
                slug = md_file.stem
                doc = frontmatter.load(md_file)
                evidence[slug] = {
                    "id": slug,
                    "metadata": dict(doc.metadata),
                    "content": doc.content,
                }

        # Load diegeses
        diegeses = {}
        diegeses_dir = lib_dir / "diegeses"
        if diegeses_dir.exists():
            for md_file in diegeses_dir.glob("*.md"):
                slug = md_file.stem
                doc = frontmatter.load(md_file)
                diegeses[slug] = {
                    "id": slug,
                    "metadata": dict(doc.metadata),
                    "content": doc.content,
                }

        # Load edges
        edges = []
        logos_path = lib_dir / "logos.yaml"
        if logos_path.exists():
            logos_data = yaml.safe_load(logos_path.read_text()) or {}
            edges = logos_data.get("edges", [])

        return ImportBundle(
            manifest=manifest,
            doxai=doxai,
            evidence=evidence,
            diegeses=diegeses,
            edges=edges,
        )


def _load_from_yaml(path: Path) -> ImportBundle:
    """Parse single-file YAML bundle."""
    data = yaml.safe_load(path.read_text()) or {}
    return _parse_flat_bundle(data)


def _load_from_json(path: Path) -> ImportBundle:
    """Parse single-file JSON bundle."""
    data = json.loads(path.read_text())
    return _parse_flat_bundle(data)


def _parse_flat_bundle(data: dict) -> ImportBundle:
    """Parse a flat dict (from YAML or JSON) into ImportBundle."""
    return ImportBundle(
        manifest=data.get("_meta", {}),
        doxai=data.get("doxai", {}),
        evidence=data.get("evidence", {}),
        diegeses=data.get("diegeses", {}),
        edges=data.get("edges", []),
    )


# =============================================================================
# Validation
# =============================================================================


def validate_bundle(bundle: ImportBundle) -> list[str]:
    """Validate bundle against schema conventions and referential integrity.

    Returns list of warning strings. Empty list means clean.
    Validation is advisory — warnings don't block import.
    """
    warnings = []

    # Load schema for edge type validation
    valid_edge_types = set()
    if SCHEMA_FILE.exists():
        schema = yaml.safe_load(SCHEMA_FILE.read_text()) or {}
        valid_edge_types = set(schema.get("edge_types", {}).keys())

    # Collect all known doxa slugs (bundle + local)
    bundle_doxa_slugs = set(bundle.doxai.keys())
    local_doxa_slugs = set()
    if DOXAI_DIR.exists():
        local_doxa_slugs = {p.stem for p in DOXAI_DIR.glob("*.md")}
    all_known_doxai = bundle_doxa_slugs | local_doxa_slugs

    # Check doxa slug prefixes
    for slug in bundle.doxai:
        if not slug.startswith("d-"):
            warnings.append(f"Doxa '{slug}' missing d- prefix")

    # Check evidence slug prefixes
    for slug in bundle.evidence:
        if not slug.startswith("e-"):
            warnings.append(f"Evidence '{slug}' missing e- prefix")

    # Check diegesis slug prefixes
    for slug in bundle.diegeses:
        if not slug.startswith("n-"):
            warnings.append(f"Diegesis '{slug}' missing n- prefix")

    # Validate edges
    for edge in bundle.edges:
        source = edge.get("source", "")
        target = edge.get("target", "")
        edge_type = edge.get("type", "")

        if valid_edge_types and edge_type not in valid_edge_types:
            warnings.append(f"Edge {source}→{target}: unknown type '{edge_type}'")

        if source and source not in all_known_doxai:
            warnings.append(f"Edge source '{source}' not found in bundle or local library")

        if target and target not in all_known_doxai:
            warnings.append(f"Edge target '{target}' not found in bundle or local library")

    # Validate diegesis section references
    for slug, diegesis in bundle.diegeses.items():
        metadata = diegesis.get("metadata", {})
        sections = metadata.get("sections", {})
        for section_key, section in sections.items():
            if isinstance(section, dict):
                for doxa_ref in section.get("doxai", []):
                    if doxa_ref not in all_known_doxai:
                        warnings.append(
                            f"Diegesis '{slug}' section '{section_key}' "
                            f"references unknown doxa '{doxa_ref}'"
                        )

    return warnings


# =============================================================================
# Conflict Detection
# =============================================================================


def detect_conflicts(bundle: ImportBundle) -> ConflictReport:
    """Compare bundle against local library, identify overlaps.

    Entities that exist locally with identical content are tracked
    in the 'identical' count and silently skipped — not reported as conflicts.
    """
    report = ConflictReport()

    # Doxai conflicts
    identical_doxai = 0
    for slug, incoming in bundle.doxai.items():
        path = DOXAI_DIR / f"{slug}.md"
        if path.exists():
            local = _load_local_entity(path)
            if _entities_equal(local, incoming):
                identical_doxai += 1
            else:
                report.conflicts.append(Conflict(
                    entity_type="doxa",
                    slug=slug,
                    local=local,
                    incoming=incoming,
                ))
        else:
            report.new_doxai.add(slug)
    if identical_doxai:
        report.identical["doxai"] = identical_doxai

    # Evidence conflicts
    identical_evidence = 0
    for slug, incoming in bundle.evidence.items():
        path = EVIDENCE_DIR / f"{slug}.md"
        if path.exists():
            local = _load_local_entity(path)
            if _entities_equal(local, incoming):
                identical_evidence += 1
            else:
                report.conflicts.append(Conflict(
                    entity_type="evidence",
                    slug=slug,
                    local=local,
                    incoming=incoming,
                ))
        else:
            report.new_evidence.add(slug)
    if identical_evidence:
        report.identical["evidence"] = identical_evidence

    # Diegesis conflicts
    identical_diegeses = 0
    for slug, incoming in bundle.diegeses.items():
        path = DIEGESES_DIR / f"{slug}.md"
        if path.exists():
            local = _load_local_entity(path)
            if _entities_equal(local, incoming):
                identical_diegeses += 1
            else:
                report.conflicts.append(Conflict(
                    entity_type="diegesis",
                    slug=slug,
                    local=local,
                    incoming=incoming,
                ))
        else:
            report.new_diegeses.add(slug)
    if identical_diegeses:
        report.identical["diegeses"] = identical_diegeses

    # Edge conflicts
    existing_logos = read_logos()
    existing_edges = existing_logos.get("edges", [])
    existing_edge_map = _build_edge_map(existing_edges)

    identical_edges = 0
    for incoming_edge in bundle.edges:
        key = _edge_key(incoming_edge)
        if key in existing_edge_map:
            local_edge = existing_edge_map[key]
            if _edges_equal(local_edge, incoming_edge):
                identical_edges += 1
            else:
                report.conflicts.append(Conflict(
                    entity_type="edge",
                    slug=f"{key[0]}→{key[1]}",
                    local=local_edge,
                    incoming=incoming_edge,
                ))
        else:
            report.new_edges.append(incoming_edge)
    if identical_edges:
        report.identical["edges"] = identical_edges

    return report


# =============================================================================
# Import Application
# =============================================================================


def apply_import(
    bundle: ImportBundle,
    conflicts: ConflictReport,
    strategy: Strategy = "skip",
    dry_run: bool = False,
) -> ImportResult:
    """Write bundle contents to local library.

    For each entity:
    1. If new → write file
    2. If conflict → apply strategy (skip, overwrite, newer)
    3. If identical → skip silently

    dry_run=True returns what WOULD happen without writing anything.
    """
    result = ImportResult(
        created={"doxai": 0, "evidence": 0, "diegeses": 0, "edges": 0},
        updated={"doxai": 0, "evidence": 0, "diegeses": 0, "edges": 0},
        skipped={"doxai": 0, "evidence": 0, "diegeses": 0, "edges": 0},
    )

    # Build conflict lookup for quick access
    conflict_map: dict[tuple[str, str], Conflict] = {}
    for c in conflicts.conflicts:
        conflict_map[(c.entity_type, c.slug)] = c

    # --- Write new entities ---

    for slug in conflicts.new_doxai:
        data = bundle.doxai[slug]
        if not dry_run:
            _write_entity(DOXAI_DIR, slug, data)
        result.created["doxai"] += 1

    for slug in conflicts.new_evidence:
        data = bundle.evidence[slug]
        if not dry_run:
            _write_entity(EVIDENCE_DIR, slug, data)
        result.created["evidence"] += 1

    for slug in conflicts.new_diegeses:
        data = bundle.diegeses[slug]
        if not dry_run:
            _write_entity(DIEGESES_DIR, slug, data)
        result.created["diegeses"] += 1

    # --- Resolve conflicts ---

    for conflict in conflicts.conflicts:
        if conflict.entity_type == "edge":
            continue  # Edges handled separately below

        should_write = _resolve_conflict(conflict, strategy)

        if should_write:
            if not dry_run:
                target_dir = {
                    "doxa": DOXAI_DIR,
                    "evidence": EVIDENCE_DIR,
                    "diegesis": DIEGESES_DIR,
                }[conflict.entity_type]
                _write_entity(target_dir, conflict.slug, conflict.incoming)
            entity_key = _entity_type_to_key(conflict.entity_type)
            result.updated[entity_key] += 1
        else:
            entity_key = _entity_type_to_key(conflict.entity_type)
            result.skipped[entity_key] += 1

    # --- Merge edges ---

    edge_conflicts = [c for c in conflicts.conflicts if c.entity_type == "edge"]

    if conflicts.new_edges or edge_conflicts:
        if not dry_run:
            existing_logos = read_logos()
            existing_edges = existing_logos.get("edges", [])
            existing_edge_map = _build_edge_map(existing_edges)

            # Add new edges
            for edge in conflicts.new_edges:
                key = _edge_key(edge)
                existing_edge_map[key] = edge

            # Resolve edge conflicts
            for conflict in edge_conflicts:
                key = (_edge_source_target(conflict.slug))
                if _resolve_conflict(conflict, strategy):
                    existing_edge_map[key] = conflict.incoming
                # else: keep existing (already in map)

            merged_edges = list(existing_edge_map.values())
            merged_edges.sort(key=lambda e: (e.get("source", ""), e.get("target", "")))
            write_logos({"edges": merged_edges})

        result.created["edges"] += len(conflicts.new_edges)
        for conflict in edge_conflicts:
            if _resolve_conflict(conflict, strategy):
                result.updated["edges"] += 1
            else:
                result.skipped["edges"] += 1

    # Invalidate graph cache so next load_graph() rebuilds
    if not dry_run:
        invalidate_cache()

    return result


# =============================================================================
# High-Level Orchestrators
# =============================================================================


def import_subgraph(
    path: Path,
    strategy: Strategy = "skip",
    dry_run: bool = False,
    validate: bool = True,
) -> tuple[ImportResult, list[str]]:
    """Import a subgraph export.

    Pipeline: load → validate → detect conflicts → apply.
    Default strategy is 'skip' (additive merge — only add what's new).

    Returns (ImportResult, validation_warnings).
    """
    bundle = load_bundle(path)
    warnings = validate_bundle(bundle) if validate else []
    conflicts = detect_conflicts(bundle)
    result = apply_import(bundle, conflicts, strategy=strategy, dry_run=dry_run)
    return result, warnings


def import_library(
    path: Path,
    strategy: Strategy = "overwrite",
    dry_run: bool = False,
    validate: bool = True,
) -> tuple[ImportResult, list[str]]:
    """Import a full library backup.

    Default strategy is 'overwrite' for restore semantics.

    Returns (ImportResult, validation_warnings).
    """
    bundle = load_bundle(path)
    warnings = validate_bundle(bundle) if validate else []
    conflicts = detect_conflicts(bundle)
    result = apply_import(bundle, conflicts, strategy=strategy, dry_run=dry_run)
    return result, warnings


# =============================================================================
# Internal Helpers
# =============================================================================


def _load_local_entity(path: Path) -> dict:
    """Load a local frontmatter markdown file into the same format as exports."""
    doc = frontmatter.load(path)
    return {
        "id": path.stem,
        "metadata": dict(doc.metadata),
        "content": doc.content,
    }


def _entities_equal(local: dict, incoming: dict) -> bool:
    """Check if two entities have equivalent content.

    Compares metadata and body content. Normalizes whitespace on body
    and date types to avoid false positives from serialization differences.
    """
    local_meta = _normalize_metadata(local.get("metadata", {}))
    incoming_meta = _normalize_metadata(incoming.get("metadata", {}))

    local_content = local.get("content", "").strip()
    incoming_content = incoming.get("content", "").strip()

    return local_meta == incoming_meta and local_content == incoming_content


def _normalize_metadata(metadata: dict) -> dict:
    """Normalize metadata values for comparison.

    Converts date objects to ISO strings so that JSON round-trips
    (which lose date typing) compare equal to frontmatter-loaded data.
    """
    normalized = {}
    for key, value in metadata.items():
        if isinstance(value, date):
            normalized[key] = value.isoformat()
        elif isinstance(value, list):
            normalized[key] = [
                v.isoformat() if isinstance(v, date) else _normalize_value(v)
                for v in value
            ]
        elif isinstance(value, dict):
            normalized[key] = _normalize_metadata(value)
        else:
            normalized[key] = value
    return normalized


def _normalize_value(value: Any) -> Any:
    """Normalize a single value, handling nested dicts."""
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return _normalize_metadata(value)
    return value


def _edges_equal(local: dict, incoming: dict) -> bool:
    """Check if two edges are equivalent beyond their identity key."""
    compare_fields = ["type", "alias", "rationale", "confidence", "strength", "annotation"]
    for f in compare_fields:
        if local.get(f) != incoming.get(f):
            return False
    return True


def _edge_key(edge: dict) -> tuple[str, str]:
    """Identity key for an edge: (source, target)."""
    return (edge.get("source", ""), edge.get("target", ""))


def _edge_source_target(slug: str) -> tuple[str, str]:
    """Parse an edge conflict slug like 'd-foo→d-bar' back to (source, target)."""
    parts = slug.split("→", 1)
    if len(parts) == 2:
        return (parts[0], parts[1])
    return (slug, "")


def _build_edge_map(edges: list[dict]) -> dict[tuple[str, str], dict]:
    """Build a lookup map from edge list, keyed by (source, target)."""
    return {_edge_key(e): e for e in edges}


def _resolve_conflict(conflict: Conflict, strategy: Strategy) -> bool:
    """Decide whether to write incoming content for a conflict.

    Returns True if incoming should replace local, False to keep local.
    """
    if strategy == "overwrite":
        return True
    elif strategy == "skip":
        return False
    elif strategy == "newer":
        if conflict.entity_type == "edge":
            return False  # Edges have no timestamp, fall back to skip

        local_date = _extract_updated_date(conflict.local)
        incoming_date = _extract_updated_date(conflict.incoming)

        if incoming_date and local_date:
            return incoming_date > local_date
        elif incoming_date and not local_date:
            return True  # Incoming has date, local doesn't — prefer incoming
        else:
            return False  # No incoming date or tie — keep local
    return False


def _extract_updated_date(entity: dict) -> date | None:
    """Extract the 'updated' date from entity metadata."""
    metadata = entity.get("metadata", {})
    updated = metadata.get("updated")
    if updated is None:
        return None
    if isinstance(updated, date):
        return updated
    if isinstance(updated, str):
        try:
            return date.fromisoformat(updated)
        except ValueError:
            return None
    return None


def _write_entity(directory: Path, slug: str, data: dict) -> None:
    """Write a frontmatter markdown file to the library."""
    directory.mkdir(parents=True, exist_ok=True)
    _write_markdown_file(
        directory / f"{slug}.md",
        data.get("metadata", {}),
        data.get("content", ""),
    )


def _entity_type_to_key(entity_type: str) -> str:
    """Map singular entity type to plural result dict key."""
    return {
        "doxa": "doxai",
        "evidence": "evidence",
        "diegesis": "diegeses",
    }.get(entity_type, entity_type)
