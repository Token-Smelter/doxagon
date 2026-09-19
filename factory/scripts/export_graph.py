#!/usr/bin/env python3
"""
Export a diegesis walk as JSON for D3.js visualization.

Exports only titles, relationships, and metadata - not full content.
Output is suitable for force-directed graph on GitHub Pages.

Usage:
    python factory/scripts/export_graph.py --diegesis n-sample-editorial --walk canonical
    python factory/scripts/export_graph.py -d n-sample-editorial -w executive -o publish/assets/data/
"""

import json
import re
from pathlib import Path

import yaml


def parse_diegesis(diegesis_path: Path) -> dict:
    """Parse a diegesis markdown file and extract frontmatter."""
    content = diegesis_path.read_text()

    if not content.startswith("---"):
        raise ValueError(f"No frontmatter found in {diegesis_path}")

    _, frontmatter, _ = content.split("---", 2)
    return yaml.safe_load(frontmatter)


def get_walk_doxai(diegesis: dict, walk_name: str) -> list[str]:
    """Extract ordered list of doxai IDs for a given walk."""
    if walk_name not in diegesis.get("walks", {}):
        available = list(diegesis.get("walks", {}).keys())
        raise ValueError(f"Walk '{walk_name}' not found. Available: {available}")

    section_order = diegesis["walks"][walk_name]
    sections = diegesis.get("sections", {})

    doxai_list = []
    for section_key in section_order:
        if section_key not in sections:
            print(f"Warning: Section '{section_key}' not found in sections")
            continue
        section_doxai = sections[section_key].get("doxai", [])
        doxai_list.extend(section_doxai)

    return doxai_list


def load_doxa(doxa_path: Path) -> dict | None:
    """Load a single doxa file and extract public fields."""
    if not doxa_path.exists():
        print(f"Warning: Doxa file not found: {doxa_path}")
        return None

    content = doxa_path.read_text()

    if not content.startswith("---"):
        return None

    _, frontmatter, _ = content.split("---", 2)
    data = yaml.safe_load(frontmatter)

    belief = data.get("belief", "")
    tags = data.get("tags", [])

    return {
        "id": doxa_path.stem,
        "title": belief,
        "tags": tags
    }


def load_edges(logos_path: Path, doxai_set: set[str]) -> list[dict]:
    """Load edges from logos.yaml, filtered to only include edges within the doxai set."""
    with open(logos_path) as f:
        data = yaml.safe_load(f)

    edges = []
    for edge in data.get("edges", []):
        source = edge.get("source", "")
        target = edge.get("target", "")

        # Only include edges where both endpoints are in our walk
        if source in doxai_set and target in doxai_set:
            edges.append({
                "source": source,
                "target": target,
                "type": edge.get("type", "unknown"),
                "label": edge.get("alias", edge.get("type", "unknown")),
                "confidence": edge.get("confidence", "unknown")
            })

    return edges


def export_graph(
    library_path: Path,
    diegesis_name: str,
    walk_name: str,
    output_path: Path
):
    """Export a diegesis walk as JSON for visualization."""

    # Load diegesis
    diegesis_path = library_path / "diegeses" / f"{diegesis_name}.md"
    if not diegesis_path.exists():
        raise FileNotFoundError(f"Diegesis not found: {diegesis_path}")

    diegesis = parse_diegesis(diegesis_path)

    # Get ordered doxai for this walk
    doxai_ids = get_walk_doxai(diegesis, walk_name)
    doxai_set = set(doxai_ids)

    print(f"Walk '{walk_name}' contains {len(doxai_ids)} doxai")

    # Load each doxa
    nodes = []
    doxai_path = library_path / "doxai"
    for doxa_id in doxai_ids:
        doxa_file = doxai_path / f"{doxa_id}.md"
        doxa = load_doxa(doxa_file)
        if doxa:
            nodes.append(doxa)

    print(f"Loaded {len(nodes)} doxa files")

    # Load and filter edges
    logos_path = library_path / "logos.yaml"
    edges = load_edges(logos_path, doxai_set)

    print(f"Found {len(edges)} edges within this walk")

    # Extract domains from tags
    domains = set()
    for node in nodes:
        for tag in node.get("tags", []):
            if tag.startswith("domain:"):
                domains.add(tag.replace("domain:", ""))

    # Build output
    graph = {
        "meta": {
            "diegesis": diegesis_name,
            "walk": walk_name,
            "title": diegesis.get("title", ""),
            "subtitle": diegesis.get("subtitle", ""),
            "node_count": len(nodes),
            "edge_count": len(edges),
            "edge_types": sorted(set(e["type"] for e in edges)),
            "domains": sorted(domains)
        },
        "nodes": nodes,
        "edges": edges
    }

    # Write output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(graph, f, indent=2)

    print(f"\nExported to: {output_path}")
    print(f"  Nodes: {len(nodes)}")
    print(f"  Edges: {len(edges)}")
    print(f"  Edge types: {', '.join(graph['meta']['edge_types'])}")
    print(f"  Domains: {', '.join(graph['meta']['domains'])}")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Export a diegesis walk as JSON for D3 visualization"
    )
    parser.add_argument(
        "--diegesis", "-d",
        required=True,
        help="Diegesis name (e.g., n-sample-editorial)"
    )
    parser.add_argument(
        "--walk", "-w",
        required=True,
        help="Walk name (e.g., canonical, executive, technical)"
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        help="Output directory (default: publish/assets/data/)"
    )
    parser.add_argument(
        "--library", "-l",
        type=Path,
        default=Path("library"),
        help="Path to library directory"
    )

    args = parser.parse_args()

    # Resolve paths relative to project root
    project_root = Path(__file__).parent.parent.parent
    library_path = project_root / args.library

    # Default output path
    if args.output:
        output_dir = project_root / args.output
    else:
        output_dir = project_root / "publish" / "assets" / "data"

    # Output filename based on diegesis and walk
    # Strip n- prefix for cleaner filenames
    diegesis_slug = args.diegesis.removeprefix("n-")
    output_file = output_dir / f"{diegesis_slug}-{args.walk}.json"

    export_graph(library_path, args.diegesis, args.walk, output_file)


if __name__ == "__main__":
    main()
