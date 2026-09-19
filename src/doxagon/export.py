"""Export functionality for Doxagon knowledge graph.

Supports three export modes:
- Platform: Share framework without personal content
- Library: Full backup/migration
- Subgraph: Share specific arguments
"""

import json
import shutil
import tarfile
import tempfile
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional


class DateTimeEncoder(json.JSONEncoder):
    """JSON encoder that handles date and datetime objects."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, date):
            return obj.isoformat()
        return super().default(obj)

import frontmatter
import yaml

from doxagon.config import (
    ROOT_DIR,
    LIBRARY_DIR,
    THESES_DIR,
    DOXAI_DIR,
    EVIDENCE_DIR,
    DIEGESES_DIR,
    PHANTASIAI_DIR,
    KATALEPSEIS_DIR,
    EXPLORATIONS_DIR,
    INBOX_DIR,
    LOGOS_FILE,
    SCHEMA_FILE,
)
from doxagon.graph import load_graph
from doxagon.storage import read_doxa, read_diegesis, read_logos


# =============================================================================
# Archive Utilities
# =============================================================================


def _create_archive(tmp_path: Path, output_path: Path) -> None:
    """Create archive from temp directory, format based on output_path extension.

    Supports .tar.gz (best compression), .tar.xz, .tar.bz2, and .zip.
    """
    suffix = "".join(output_path.suffixes).lower()

    if suffix in (".tar.gz", ".tgz"):
        with tarfile.open(output_path, "w:gz") as tf:
            for file_path in tmp_path.rglob("*"):
                if file_path.is_file():
                    arcname = file_path.relative_to(tmp_path)
                    tf.add(file_path, arcname)
    elif suffix == ".tar.xz":
        with tarfile.open(output_path, "w:xz") as tf:
            for file_path in tmp_path.rglob("*"):
                if file_path.is_file():
                    arcname = file_path.relative_to(tmp_path)
                    tf.add(file_path, arcname)
    elif suffix == ".tar.bz2":
        with tarfile.open(output_path, "w:bz2") as tf:
            for file_path in tmp_path.rglob("*"):
                if file_path.is_file():
                    arcname = file_path.relative_to(tmp_path)
                    tf.add(file_path, arcname)
    elif suffix == ".zip":
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in tmp_path.rglob("*"):
                if file_path.is_file():
                    arcname = file_path.relative_to(tmp_path)
                    zf.write(file_path, arcname)
    else:
        # Default to tar.gz
        with tarfile.open(output_path, "w:gz") as tf:
            for file_path in tmp_path.rglob("*"):
                if file_path.is_file():
                    arcname = file_path.relative_to(tmp_path)
                    tf.add(file_path, arcname)


# =============================================================================
# Subgraph Extraction
# =============================================================================


def extract_diegesis_subgraph(
    diegesis_slug: str,
    walk_name: Optional[str] = None,
) -> set[str]:
    """Extract doxa IDs from a diegesis, optionally filtered by walk.

    Args:
        diegesis_slug: Diegesis identifier (with or without n- prefix)
        walk_name: Optional walk name to filter sections

    Returns:
        Set of doxa slugs included in the diegesis/walk
    """
    # Normalize slug
    if not diegesis_slug.startswith("n-"):
        diegesis_slug = f"n-{diegesis_slug}"

    diegesis = read_diegesis(diegesis_slug)
    metadata = diegesis["metadata"]

    sections = metadata.get("sections", {})
    walks = metadata.get("walks", {})

    # If walk specified, get only those sections
    if walk_name:
        if walk_name not in walks:
            available = list(walks.keys())
            raise ValueError(f"Walk '{walk_name}' not found. Available: {available}")
        section_order = walks[walk_name]
    else:
        # All sections
        section_order = list(sections.keys())

    # Collect doxai from sections
    doxa_ids = set()
    for section_key in section_order:
        if section_key in sections:
            section_doxai = sections[section_key].get("doxai", [])
            doxa_ids.update(section_doxai)

    return doxa_ids


def extract_neighborhood_subgraph(
    root_id: str,
    hops: int = 2,
) -> set[str]:
    """Extract doxa IDs within N hops of a root node.

    Args:
        root_id: Root doxa identifier
        hops: Number of hops to traverse (default 2)

    Returns:
        Set of doxa slugs within hop distance
    """
    G = load_graph()

    if root_id not in G:
        raise ValueError(f"Root doxa not found: {root_id}")

    neighborhood = {root_id}
    frontier = {root_id}

    for _ in range(hops):
        next_frontier = set()
        for node in frontier:
            # Both directions
            next_frontier.update(G.predecessors(node))
            next_frontier.update(G.successors(node))
        neighborhood.update(next_frontier)
        frontier = next_frontier

    return neighborhood


def extract_tag_subgraph(tags: list[str]) -> set[str]:
    """Extract doxa IDs matching any of the given tags.

    Args:
        tags: List of tags to match (union semantics)

    Returns:
        Set of doxa slugs with at least one matching tag
    """
    G = load_graph()

    matching = set()
    for node_id, data in G.nodes(data=True):
        node_tags = data.get("tags", [])
        if any(tag in node_tags for tag in tags):
            matching.add(node_id)

    return matching


# =============================================================================
# Dependency Resolution
# =============================================================================


def collect_referenced_evidence(doxa_ids: set[str]) -> set[str]:
    """Collect evidence slugs referenced by a set of doxai.

    Args:
        doxa_ids: Set of doxa slugs

    Returns:
        Set of evidence slugs referenced in doxa evidence fields
    """
    evidence_ids = set()

    for doxa_id in doxa_ids:
        try:
            doxa = read_doxa(doxa_id)
            evidence_list = doxa["metadata"].get("evidence", [])
            for ev in evidence_list:
                if isinstance(ev, dict):
                    source = ev.get("source", "")
                    if source:
                        evidence_ids.add(source)
        except FileNotFoundError:
            continue

    return evidence_ids


def filter_edges_to_subgraph(node_ids: set[str]) -> list[dict]:
    """Filter logos edges to only those within a subgraph.

    Args:
        node_ids: Set of node IDs defining the subgraph

    Returns:
        List of edge dicts where both endpoints are in node_ids
    """
    logos = read_logos()
    edges = logos.get("edges", [])

    filtered = []
    for edge in edges:
        source = edge.get("source", "")
        target = edge.get("target", "")
        if source in node_ids and target in node_ids:
            filtered.append(edge)

    return filtered


def collect_diegeses_containing(doxa_ids: set[str]) -> set[str]:
    """Find diegeses that reference any of the given doxai.

    Args:
        doxa_ids: Set of doxa slugs

    Returns:
        Set of diegesis slugs
    """
    diegesis_ids = set()

    if not DIEGESES_DIR.exists():
        return diegesis_ids

    for path in DIEGESES_DIR.glob("n-*.md"):
        try:
            doc = frontmatter.load(path)
            sections = doc.get("sections", {})

            for section in sections.values():
                if isinstance(section, dict):
                    section_doxai = section.get("doxai", [])
                    if any(d in doxa_ids for d in section_doxai):
                        diegesis_ids.add(path.stem)
                        break
        except Exception:
            continue

    return diegesis_ids


# =============================================================================
# Content Loading
# =============================================================================


def load_doxa_content(doxa_id: str) -> dict:
    """Load full doxa content including metadata and body."""
    try:
        doxa = read_doxa(doxa_id)
        return {
            "id": doxa_id,
            "metadata": doxa["metadata"],
            "content": doxa["content"],
        }
    except FileNotFoundError:
        return None


def load_evidence_content(evidence_id: str) -> dict:
    """Load full evidence content including metadata and body."""
    path = EVIDENCE_DIR / f"{evidence_id}.md"
    if not path.exists():
        return None

    try:
        doc = frontmatter.load(path)
        return {
            "id": evidence_id,
            "metadata": dict(doc.metadata),
            "content": doc.content,
        }
    except Exception:
        return None


def load_diegesis_content(diegesis_id: str) -> dict:
    """Load full diegesis content including metadata and body."""
    try:
        diegesis = read_diegesis(diegesis_id)
        return {
            "id": diegesis_id,
            "metadata": diegesis["metadata"],
            "content": diegesis["content"],
        }
    except FileNotFoundError:
        return None


# =============================================================================
# Export Format Writers
# =============================================================================


def _build_manifest(
    export_type: str,
    selection: dict,
    counts: dict,
) -> dict:
    """Build export manifest with metadata."""
    return {
        "_meta": {
            "export_type": export_type,
            "exported_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "selection": selection,
            "counts": counts,
            "format_version": "1.0",
        }
    }


def export_as_yaml(
    doxai: dict[str, dict],
    evidence: dict[str, dict],
    diegeses: dict[str, dict],
    edges: list[dict],
    output_path: Path,
    manifest: dict,
) -> None:
    """Export subgraph as a single YAML bundle.

    Args:
        doxai: Dict of doxa_id -> doxa content
        evidence: Dict of evidence_id -> evidence content
        diegeses: Dict of diegesis_id -> diegesis content
        edges: List of edge dicts
        output_path: Output file path
        manifest: Export metadata
    """
    bundle = {
        **manifest,
        "doxai": doxai,
        "evidence": evidence,
        "diegeses": diegeses,
        "edges": edges,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        yaml.dump(bundle, default_flow_style=False, allow_unicode=True, sort_keys=False)
    )


def export_as_json(
    doxai: dict[str, dict],
    evidence: dict[str, dict],
    diegeses: dict[str, dict],
    edges: list[dict],
    output_path: Path,
    manifest: dict,
) -> None:
    """Export subgraph as a single JSON bundle.

    Args:
        doxai: Dict of doxa_id -> doxa content
        evidence: Dict of evidence_id -> evidence content
        diegeses: Dict of diegesis_id -> diegesis content
        edges: List of edge dicts
        output_path: Output file path
        manifest: Export metadata
    """
    bundle = {
        **manifest,
        "doxai": doxai,
        "evidence": evidence,
        "diegeses": diegeses,
        "edges": edges,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(bundle, indent=2, ensure_ascii=False, cls=DateTimeEncoder))


def export_as_zip(
    doxai: dict[str, dict],
    evidence: dict[str, dict],
    diegeses: dict[str, dict],
    edges: list[dict],
    output_path: Path,
    manifest: dict,
    include_schema: bool = True,
) -> None:
    """Export subgraph as a ZIP archive with directory structure.

    Args:
        doxai: Dict of doxa_id -> doxa content
        evidence: Dict of evidence_id -> evidence content
        diegeses: Dict of diegesis_id -> diegesis content
        edges: List of edge dicts
        output_path: Output ZIP file path
        manifest: Export metadata
        include_schema: Whether to include schema.yaml
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        # Create directory structure
        (tmp_path / "library" / "doxai").mkdir(parents=True)
        (tmp_path / "library" / "evidence").mkdir(parents=True)
        (tmp_path / "library" / "diegeses").mkdir(parents=True)

        # Write manifest
        (tmp_path / "manifest.yaml").write_text(
            yaml.dump(manifest, default_flow_style=False, allow_unicode=True)
        )

        # Write doxai files
        for doxa_id, doxa_data in doxai.items():
            _write_markdown_file(
                tmp_path / "library" / "doxai" / f"{doxa_id}.md",
                doxa_data["metadata"],
                doxa_data["content"],
            )

        # Write evidence files
        for ev_id, ev_data in evidence.items():
            _write_markdown_file(
                tmp_path / "library" / "evidence" / f"{ev_id}.md",
                ev_data["metadata"],
                ev_data["content"],
            )

        # Write diegesis files
        for dieg_id, dieg_data in diegeses.items():
            _write_markdown_file(
                tmp_path / "library" / "diegeses" / f"{dieg_id}.md",
                dieg_data["metadata"],
                dieg_data["content"],
            )

        # Write edges
        (tmp_path / "library" / "logos.yaml").write_text(
            yaml.dump({"edges": edges}, default_flow_style=False, allow_unicode=True)
        )

        # Include schema if requested
        if include_schema and SCHEMA_FILE.exists():
            shutil.copy(SCHEMA_FILE, tmp_path / "library" / "schema.yaml")

        # Write README
        readme = _generate_export_readme(manifest)
        (tmp_path / "README.md").write_text(readme)

        # Create archive
        _create_archive(tmp_path, output_path)


def _write_markdown_file(path: Path, metadata: dict, content: str) -> None:
    """Write a frontmatter markdown file."""
    post = frontmatter.Post(content, **metadata)
    path.write_text(frontmatter.dumps(post))


def _generate_export_readme(manifest: dict) -> str:
    """Generate README for export archive."""
    meta = manifest.get("_meta", {})
    export_type = meta.get("export_type", "unknown")
    exported_at = meta.get("exported_at", "unknown")
    counts = meta.get("counts", {})

    return f"""# Doxagon Export

## Export Info

- **Type**: {export_type}
- **Exported**: {exported_at}
- **Doxai**: {counts.get('doxai', 0)}
- **Evidence**: {counts.get('evidence', 0)}
- **Diegeses**: {counts.get('diegeses', 0)}
- **Edges**: {counts.get('edges', 0)}

## Structure

```
library/
├── doxai/       # Belief files (d-*.md)
├── evidence/    # Evidence files (e-*.md)
├── diegeses/    # Narrative files (n-*.md)
├── logos.yaml   # Edge definitions
└── schema.yaml  # Schema (if included)
```

## Import Instructions

1. Copy contents to your Doxagon library directory
2. Run `dox validate` to check for issues
3. Merge logos.yaml edges with existing edges

## Generated by Doxagon

https://github.com/Token-Smelter/doxagon
"""


# =============================================================================
# High-Level Export Functions
# =============================================================================


def export_subgraph(
    output_path: Path,
    format: str = "zip",
    diegesis: Optional[str] = None,
    walk: Optional[str] = None,
    root: Optional[str] = None,
    hops: int = 2,
    tags: Optional[list[str]] = None,
    include_evidence: bool = True,
    include_diegeses: bool = True,
) -> dict:
    """Export a subgraph of the knowledge graph.

    Args:
        output_path: Output file path
        format: Export format (zip, yaml, json)
        diegesis: Diegesis slug for diegesis-based selection
        walk: Walk name within diegesis
        root: Root doxa for neighborhood-based selection
        hops: Hop distance for neighborhood selection
        tags: Tags for tag-based selection
        include_evidence: Whether to include referenced evidence
        include_diegeses: Whether to include containing diegeses

    Returns:
        Export statistics dict
    """
    # Determine selection mode and extract doxa IDs
    if diegesis:
        doxa_ids = extract_diegesis_subgraph(diegesis, walk)
        selection = {"mode": "diegesis", "diegesis": diegesis, "walk": walk}
    elif root:
        doxa_ids = extract_neighborhood_subgraph(root, hops)
        selection = {"mode": "neighborhood", "root": root, "hops": hops}
    elif tags:
        doxa_ids = extract_tag_subgraph(tags)
        selection = {"mode": "tags", "tags": tags}
    else:
        raise ValueError("Must specify diegesis, root, or tags for subgraph export")

    # Load doxa content
    doxai = {}
    for doxa_id in doxa_ids:
        content = load_doxa_content(doxa_id)
        if content:
            doxai[doxa_id] = content

    # Collect evidence
    evidence = {}
    if include_evidence:
        evidence_ids = collect_referenced_evidence(doxa_ids)
        for ev_id in evidence_ids:
            content = load_evidence_content(ev_id)
            if content:
                evidence[ev_id] = content

    # Collect diegeses
    diegeses = {}
    if include_diegeses:
        diegesis_ids = collect_diegeses_containing(doxa_ids)
        for dieg_id in diegesis_ids:
            content = load_diegesis_content(dieg_id)
            if content:
                diegeses[dieg_id] = content

    # Filter edges
    edges = filter_edges_to_subgraph(doxa_ids)

    # Build manifest
    counts = {
        "doxai": len(doxai),
        "evidence": len(evidence),
        "diegeses": len(diegeses),
        "edges": len(edges),
    }
    manifest = _build_manifest("subgraph", selection, counts)

    # Export
    if format == "yaml":
        export_as_yaml(doxai, evidence, diegeses, edges, output_path, manifest)
    elif format == "json":
        export_as_json(doxai, evidence, diegeses, edges, output_path, manifest)
    else:  # zip
        export_as_zip(doxai, evidence, diegeses, edges, output_path, manifest)

    return counts


def export_full_library(
    output_path: Path,
    format: str = "zip",
    include_inbox: bool = False,
) -> dict:
    """Export the complete knowledge graph for backup/migration.

    Args:
        output_path: Output file path
        format: Export format (zip, yaml, json)
        include_inbox: Whether to include inbox items

    Returns:
        Export statistics dict
    """
    # Collect all doxai
    doxai = {}
    if DOXAI_DIR.exists():
        for path in DOXAI_DIR.glob("d-*.md"):
            doxa_id = path.stem
            content = load_doxa_content(doxa_id)
            if content:
                doxai[doxa_id] = content

    # Collect all evidence
    evidence = {}
    if EVIDENCE_DIR.exists():
        for path in EVIDENCE_DIR.glob("e-*.md"):
            ev_id = path.stem
            content = load_evidence_content(ev_id)
            if content:
                evidence[ev_id] = content

    # Collect all diegeses
    diegeses = {}
    if DIEGESES_DIR.exists():
        for path in DIEGESES_DIR.glob("n-*.md"):
            dieg_id = path.stem
            content = load_diegesis_content(dieg_id)
            if content:
                diegeses[dieg_id] = content

    # Get all edges
    logos = read_logos()
    edges = logos.get("edges", [])

    # Build manifest
    counts = {
        "doxai": len(doxai),
        "evidence": len(evidence),
        "diegeses": len(diegeses),
        "edges": len(edges),
    }
    selection = {"mode": "full", "include_inbox": include_inbox}
    manifest = _build_manifest("library", selection, counts)

    # Export
    if format == "yaml":
        export_as_yaml(doxai, evidence, diegeses, edges, output_path, manifest)
    elif format == "json":
        export_as_json(doxai, evidence, diegeses, edges, output_path, manifest)
    else:  # zip
        export_as_zip(doxai, evidence, diegeses, edges, output_path, manifest)

    return counts


def export_platform(
    output_path: Path,
    include_skills: bool = True,
    include_docs: bool = True,
) -> dict:
    """Export framework as a starter kit without personal content.

    Args:
        output_path: Output ZIP file path
        include_skills: Whether to include .claude/skills/
        include_docs: Whether to include docs/

    Returns:
        Export statistics dict
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Directories to include
    include_dirs = [
        "src",
        "factory",
        "scripts",
        "apps",
        "bin",
        "tests",
        "design",
        ".dev",
    ]

    if include_skills:
        include_dirs.append(".claude/skills")

    if include_docs:
        include_dirs.append("docs")

    # Files to include at root
    include_files = [
        "pyproject.toml",
        "docker-compose.yaml",
        "Dockerfile",
        "README.md",
        "CLAUDE.md",
    ]

    # Library items to include (templates + schema only)
    library_include = [
        "schema.yaml",
        "logos-template.yaml",
    ]

    # Track what we export
    file_count = 0

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        # Copy directories
        for dir_name in include_dirs:
            src_dir = ROOT_DIR / dir_name
            if src_dir.exists():
                dst_dir = tmp_path / dir_name
                shutil.copytree(
                    src_dir,
                    dst_dir,
                    ignore=shutil.ignore_patterns(
                        "__pycache__",
                        "*.pyc",
                        ".pytest_cache",
                        "*.egg-info",
                        "node_modules",
                        ".venv",
                        "venv",
                        "build",
                    ),
                )
                file_count += sum(1 for _ in dst_dir.rglob("*") if _.is_file())

        # Copy root files
        for file_name in include_files:
            src_file = ROOT_DIR / file_name
            if src_file.exists():
                shutil.copy(src_file, tmp_path / file_name)
                file_count += 1

        # Create library structure with templates only
        lib_path = tmp_path / "library"
        lib_path.mkdir()

        # Copy schema and template
        for item in library_include:
            src = LIBRARY_DIR / item
            if src.exists():
                shutil.copy(src, lib_path / item)
                file_count += 1

        # Create empty directories with README/templates
        for subdir in ["doxai", "evidence", "diegeses", "phantasiai", "katalepseis", "explorations", "inbox"]:
            subdir_path = lib_path / subdir
            subdir_path.mkdir()

            # Copy _template.md if exists
            template_src = LIBRARY_DIR / subdir / "_template.md"
            if template_src.exists():
                shutil.copy(template_src, subdir_path / "_template.md")
                file_count += 1

            # Copy README.md if exists
            readme_src = LIBRARY_DIR / subdir / "README.md"
            if readme_src.exists():
                shutil.copy(readme_src, subdir_path / "README.md")
                file_count += 1

        # Write manifest
        manifest = _build_manifest(
            "platform",
            {"mode": "platform", "include_skills": include_skills, "include_docs": include_docs},
            {"files": file_count},
        )
        (tmp_path / "manifest.yaml").write_text(
            yaml.dump(manifest, default_flow_style=False, allow_unicode=True)
        )

        # Write platform README
        readme = """# Doxagon Platform

A personal epistemology infrastructure for managing beliefs (doxai) and their relationships.

## Quick Start

```bash
# Install dependencies
uv venv && uv pip install -e ".[dev]"

# Verify installation
dox stats

# Capture your first belief
dox capture "Your first belief statement"
```

## Documentation

- `docs/` - Architecture documentation
- `library/*/README.md` - Library structure guides
- `library/*/_template.md` - File templates

## Generated by Doxagon Export

This is a clean platform export - no personal content included.
"""
        (tmp_path / "README.md").write_text(readme)

        # Create archive
        _create_archive(tmp_path, output_path)

    return {"files": file_count}


# =============================================================================
# Presentation Export
# =============================================================================


def _generate_presentation_export_readme(
    manifest: dict,
    presentation_name: str,
    slide_count: int,
) -> str:
    """Generate README for presentation export archive."""
    meta = manifest.get("_meta", {})
    exported_at = meta.get("exported_at", "unknown")
    counts = meta.get("counts", {})

    return f"""# Presentation Export: {presentation_name}

## Export Info

- **Presentation**: {presentation_name}
- **Exported**: {exported_at}
- **Slides**: {slide_count}
- **Doxai**: {counts.get('doxai', 0)}
- **Evidence**: {counts.get('evidence', 0)}
- **Edges**: {counts.get('edges', 0)}

## Structure

```
presentation/
├── config.yaml          # Presentation metadata and slide order
└── slides/
    └── {{slug}}/
        ├── slide.md     # Content, speaker notes, image references
        └── images/
            └── {{id}}/
                ├── definition.md    # Visual prompt definition
                ├── sources/         # Reference images (if included)
                └── outputs/         # Generated images
                    ├── selected.png
                    └── .thumb_selected.jpg

styles/                  # Style definitions (if included)
├── README.md
└── ...

library/                 # Associated knowledge graph
├── doxai/d-*.md        # Beliefs referenced by slides
├── evidence/e-*.md     # Supporting evidence
└── logos.yaml          # Relationship edges
```

## Import Instructions

1. Copy `presentation/` and `styles/` to your thesis outputs directory
2. Copy `library/` contents to your Doxagon library
3. Merge `logos.yaml` edges with existing edges
4. Run `dox validate` to check for issues

## Generated by Doxagon

https://github.com/Token-Smelter/doxagon
"""


def export_presentation(
    presentation_name: str,
    output_path: Path,
    include_all_outputs: bool = False,
    include_sources: bool = True,
    include_styles: bool = True,
    hops: int = 1,
) -> dict:
    """Export a presentation with its associated doxai subgraph.

    Bundles all slide content, images, styles, and the knowledge graph
    subgraph referenced by slides. Creates a self-contained ZIP that can
    be imported into another doxagon instance.

    Slide Discovery:
        Slides can be specified in config.yaml under `slides:` key, or
        discovered automatically from the slides/ directory. Directory
        discovery sorts by name (numeric prefix recommended: 00-title, 01-intro).

    Doxai Collection:
        Doxai are collected from slide frontmatter (`doxai:` key). If no
        doxai are found in slides, falls back to the thesis config's
        `diegesis:` and `walk:` to get doxai from the narrative structure.
        The neighborhood is then expanded by `hops` to include related doxai.

    Args:
        presentation_name: Name of the presentation (thesis directory name)
        output_path: Output ZIP file path
        include_all_outputs: Include all generated images (not just selected)
        include_sources: Include image source/reference files
        include_styles: Include style definitions
        hops: Number of hops to expand doxai neighborhood (default: 1)

    Returns:
        Export statistics dict with keys: slides, doxai, evidence, edges

    Raises:
        ValueError: If thesis or presentation config not found, or no slides exist
    """
    thesis_dir = THESES_DIR / presentation_name
    presentation_dir = thesis_dir / "outputs" / "presentation"
    config_path = presentation_dir / "config.yaml"

    if not thesis_dir.exists():
        raise ValueError(f"Thesis not found: {presentation_name}")
    if not config_path.exists():
        raise ValueError(f"Presentation config not found: {config_path}")

    # Load presentation config
    config = yaml.safe_load(config_path.read_text())

    # Get slide order from config, or discover from directory
    slide_order = config.get("slides", [])

    if not slide_order:
        # Discover slides from directory structure (lexicographic sort, use numeric prefixes like 00-, 01-)
        slides_dir = presentation_dir / "slides"
        if slides_dir.exists():
            slide_order = sorted(
                d.name for d in slides_dir.iterdir()
                if d.is_dir() and not d.name.startswith('.') and (d / "slide.md").exists()
            )

    if not slide_order:
        raise ValueError(f"No slides found in {presentation_dir / 'slides'}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Track what we collect
    all_doxa_ids: set[str] = set()
    slide_count = 0

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        # Create directory structure
        (tmp_path / "presentation" / "slides").mkdir(parents=True)
        (tmp_path / "library" / "doxai").mkdir(parents=True)
        (tmp_path / "library" / "evidence").mkdir(parents=True)

        # Copy presentation config
        shutil.copy(config_path, tmp_path / "presentation" / "config.yaml")

        # Process each slide in order
        slides_dir = presentation_dir / "slides"
        for slide_slug in slide_order:
            slide_dir = slides_dir / slide_slug
            slide_md = slide_dir / "slide.md"

            if not slide_md.exists():
                continue

            slide_count += 1
            dest_slide_dir = tmp_path / "presentation" / "slides" / slide_slug
            dest_slide_dir.mkdir(parents=True, exist_ok=True)

            # Copy slide.md
            shutil.copy(slide_md, dest_slide_dir / "slide.md")

            # Load slide frontmatter for doxai refs and image metadata
            slide_doc = None
            try:
                slide_doc = frontmatter.load(slide_md)
                slide_doxai = slide_doc.get("doxai", [])
                if isinstance(slide_doxai, str):
                    all_doxa_ids.add(slide_doxai)
                elif isinstance(slide_doxai, list):
                    all_doxa_ids.update(slide_doxai)
            except (IOError, yaml.YAMLError):
                pass  # Malformed frontmatter, continue without doxai

            # Process images
            images_dir = slide_dir / "images"
            if images_dir.exists():
                for image_bundle in images_dir.iterdir():
                    if not image_bundle.is_dir():
                        continue

                    image_id = image_bundle.name
                    dest_image_dir = dest_slide_dir / "images" / image_id
                    dest_image_dir.mkdir(parents=True, exist_ok=True)

                    # Copy definition.md
                    definition_md = image_bundle / "definition.md"
                    if definition_md.exists():
                        shutil.copy(definition_md, dest_image_dir / "definition.md")

                    # Copy sources if requested
                    if include_sources:
                        sources_dir = image_bundle / "sources"
                        if sources_dir.exists():
                            shutil.copytree(
                                sources_dir,
                                dest_image_dir / "sources",
                                ignore=shutil.ignore_patterns("*.DS_Store"),
                            )

                    # Process outputs
                    outputs_dir = image_bundle / "outputs"
                    if outputs_dir.exists():
                        dest_outputs_dir = dest_image_dir / "outputs"
                        dest_outputs_dir.mkdir(parents=True, exist_ok=True)

                        # Get selected image from slide.md
                        selected_image = None
                        if slide_doc:
                            images_meta = slide_doc.get("images", []) or []
                            for img in images_meta:
                                if img.get("id") == image_id:
                                    selected_path = img.get("selected", "")
                                    if selected_path:
                                        selected_image = Path(selected_path).name
                                    break

                        if include_all_outputs:
                            # Copy all images and thumbnails
                            for img_file in outputs_dir.iterdir():
                                if img_file.is_file():
                                    shutil.copy(img_file, dest_outputs_dir / img_file.name)
                        else:
                            # Copy only selected image + thumbnail
                            if selected_image:
                                src_selected = outputs_dir / selected_image
                                if src_selected.exists():
                                    shutil.copy(src_selected, dest_outputs_dir / selected_image)

                                # Copy thumbnail
                                thumb_name = f".thumb_{Path(selected_image).stem}.jpg"
                                src_thumb = outputs_dir / thumb_name
                                if src_thumb.exists():
                                    shutil.copy(src_thumb, dest_outputs_dir / thumb_name)

        # Copy styles if requested
        if include_styles:
            styles_dir = presentation_dir / "styles"
            if styles_dir.exists():
                shutil.copytree(
                    styles_dir,
                    tmp_path / "styles",
                    ignore=shutil.ignore_patterns("*.DS_Store", "__pycache__"),
                )

        # If no doxai found in slides, fall back to diegesis
        if not all_doxa_ids:
            # Check thesis config for diegesis reference
            thesis_config_path = thesis_dir / "config.yaml"
            if thesis_config_path.exists():
                thesis_config = yaml.safe_load(thesis_config_path.read_text()) or {}
                diegesis_slug = thesis_config.get("diegesis")
                walk_name = thesis_config.get("walk")
                if diegesis_slug:
                    try:
                        all_doxa_ids = extract_diegesis_subgraph(diegesis_slug, walk_name)
                    except (FileNotFoundError, yaml.YAMLError, ValueError):
                        pass  # Diegesis not found or invalid

        # Expand doxai neighborhood
        expanded_doxa_ids = set()
        for doxa_id in all_doxa_ids:
            try:
                neighbors = extract_neighborhood_subgraph(doxa_id, hops)
                expanded_doxa_ids.update(neighbors)
            except ValueError:
                expanded_doxa_ids.add(doxa_id)

        # Load doxai content
        doxai = {}
        for doxa_id in expanded_doxa_ids:
            content = load_doxa_content(doxa_id)
            if content:
                doxai[doxa_id] = content

        # Collect referenced evidence
        evidence = {}
        evidence_ids = collect_referenced_evidence(expanded_doxa_ids)
        for ev_id in evidence_ids:
            content = load_evidence_content(ev_id)
            if content:
                evidence[ev_id] = content

        # Filter edges to subgraph
        edges = filter_edges_to_subgraph(expanded_doxa_ids)

        # Write doxai files
        for doxa_id, doxa_data in doxai.items():
            _write_markdown_file(
                tmp_path / "library" / "doxai" / f"{doxa_id}.md",
                doxa_data["metadata"],
                doxa_data["content"],
            )

        # Write evidence files
        for ev_id, ev_data in evidence.items():
            _write_markdown_file(
                tmp_path / "library" / "evidence" / f"{ev_id}.md",
                ev_data["metadata"],
                ev_data["content"],
            )

        # Write edges
        (tmp_path / "library" / "logos.yaml").write_text(
            yaml.dump({"edges": edges}, default_flow_style=False, allow_unicode=True)
        )

        # Build manifest
        counts = {
            "slides": slide_count,
            "doxai": len(doxai),
            "evidence": len(evidence),
            "edges": len(edges),
        }
        selection = {
            "mode": "presentation",
            "presentation": presentation_name,
            "include_all_outputs": include_all_outputs,
            "include_sources": include_sources,
            "include_styles": include_styles,
            "hops": hops,
        }
        manifest = _build_manifest("presentation", selection, counts)

        # Write manifest
        (tmp_path / "manifest.yaml").write_text(
            yaml.dump(manifest, default_flow_style=False, allow_unicode=True)
        )

        # Write README
        readme = _generate_presentation_export_readme(manifest, presentation_name, slide_count)
        (tmp_path / "README.md").write_text(readme)

        # Create archive
        _create_archive(tmp_path, output_path)

    return counts
