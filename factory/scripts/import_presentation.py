#!/usr/bin/env python3
"""Import a presentation export into the doxagon system.

This script imports a presentation zip created by export_presentation.py.
It handles:
- Thesis structure (config, slides, styles, images)
- Library content (diegesis, doxai, evidence, edges)
- Conflict detection and resolution

Usage:
    python factory/scripts/import_presentation.py <export.zip> [--dry-run] [--force]
"""

import os
import shutil
import tempfile
import yaml
import zipfile
from pathlib import Path
from datetime import date


def detect_conflicts(staging: Path, project_root: Path) -> dict:
    """Detect files that would be overwritten by import."""
    conflicts = {
        'thesis': [],
        'doxai': [],
        'evidence': [],
        'diegesis': [],
        'edges': False
    }

    # Check thesis
    theses_dir = staging / 'theses'
    if theses_dir.exists():
        for thesis_dir in theses_dir.iterdir():
            if thesis_dir.is_dir():
                existing = project_root / 'theses' / thesis_dir.name
                if existing.exists():
                    conflicts['thesis'].append(thesis_dir.name)

    # Check doxai
    doxai_dir = staging / 'library' / 'doxai'
    if doxai_dir.exists():
        for doxa_file in doxai_dir.glob('*.md'):
            existing = project_root / 'library' / 'doxai' / doxa_file.name
            if existing.exists():
                conflicts['doxai'].append(doxa_file.stem)

    # Check evidence
    evidence_dir = staging / 'library' / 'evidence'
    if evidence_dir.exists():
        for ev_file in evidence_dir.glob('*.md'):
            existing = project_root / 'library' / 'evidence' / ev_file.name
            if existing.exists():
                conflicts['evidence'].append(ev_file.stem)

    # Check diegesis
    diegesis_dir = staging / 'library' / 'diegeses'
    if diegesis_dir.exists():
        for dieg_file in diegesis_dir.glob('*.md'):
            existing = project_root / 'library' / 'diegeses' / dieg_file.name
            if existing.exists():
                conflicts['diegesis'].append(dieg_file.stem)

    # Check if logos.yaml has edges to merge
    logos_file = staging / 'library' / 'logos.yaml'
    if logos_file.exists():
        conflicts['edges'] = True

    return conflicts


def merge_edges(staging_logos: Path, project_logos: Path):
    """Merge edges from export into existing logos.yaml."""
    # Load export edges
    with open(staging_logos) as f:
        export_data = yaml.safe_load(f)

    export_edges = export_data.get('edges', [])
    if not export_edges:
        return 0

    # Load existing logos
    with open(project_logos) as f:
        project_data = yaml.safe_load(f)

    existing_edges = project_data.get('edges', [])

    # Create set of existing edge keys for dedup
    existing_keys = {
        (e.get('source'), e.get('target'), e.get('type'))
        for e in existing_edges
    }

    # Add new edges
    added = 0
    for edge in export_edges:
        key = (edge.get('source'), edge.get('target'), edge.get('type'))
        if key not in existing_keys:
            existing_edges.append(edge)
            added += 1

    # Write back
    project_data['edges'] = existing_edges
    with open(project_logos, 'w') as f:
        yaml.dump(project_data, default_flow_style=False, sort_keys=False, allow_unicode=True)

    return added


def strip_export_tag(content: str) -> str:
    """Remove export tag from doxai frontmatter."""
    lines = content.split('\n')
    result = []
    skip_export = False

    for i, line in enumerate(lines):
        if line.strip() == 'export:':
            skip_export = True
            continue
        if skip_export and line.startswith('  '):
            continue
        skip_export = False
        result.append(line)

    return '\n'.join(result)


def import_presentation(zip_path: Path, project_root: Path, dry_run: bool = False, force: bool = False):
    """Import a presentation export."""

    if not zip_path.exists():
        raise FileNotFoundError(f"Export not found: {zip_path}")

    # Extract to temp directory
    staging = Path(tempfile.mkdtemp())
    print(f"Extracting to: {staging}")

    with zipfile.ZipFile(zip_path, 'r') as zf:
        zf.extractall(staging)

    # Detect conflicts
    conflicts = detect_conflicts(staging, project_root)

    has_conflicts = (
        conflicts['thesis'] or
        conflicts['doxai'] or
        conflicts['evidence'] or
        conflicts['diegesis']
    )

    if has_conflicts:
        print("\n⚠️  Conflicts detected:")
        if conflicts['thesis']:
            print(f"  Thesis: {', '.join(conflicts['thesis'])}")
        if conflicts['doxai']:
            print(f"  Doxai ({len(conflicts['doxai'])}): {', '.join(conflicts['doxai'][:5])}{'...' if len(conflicts['doxai']) > 5 else ''}")
        if conflicts['evidence']:
            print(f"  Evidence: {', '.join(conflicts['evidence'])}")
        if conflicts['diegesis']:
            print(f"  Diegesis: {', '.join(conflicts['diegesis'])}")

        if not force:
            print("\nUse --force to overwrite existing files")
            shutil.rmtree(staging)
            return False
        else:
            print("\n--force specified, overwriting...")

    if dry_run:
        print("\n[DRY RUN] Would import:")

        # List what would be imported
        theses = list((staging / 'theses').iterdir()) if (staging / 'theses').exists() else []
        for t in theses:
            print(f"  Thesis: {t.name}")
            slides = list((t / 'outputs' / 'presentation' / 'slides').iterdir()) if (t / 'outputs' / 'presentation' / 'slides').exists() else []
            print(f"    {len(slides)} slides")

        doxai = list((staging / 'library' / 'doxai').glob('*.md')) if (staging / 'library' / 'doxai').exists() else []
        print(f"  {len(doxai)} doxai")

        evidence = list((staging / 'library' / 'evidence').glob('*.md')) if (staging / 'library' / 'evidence').exists() else []
        print(f"  {len(evidence)} evidence files")

        if conflicts['edges']:
            print(f"  Edges to merge from logos.yaml")

        shutil.rmtree(staging)
        return True

    # Perform import
    print("\nImporting...")

    # 1. Copy thesis
    src_theses = staging / 'theses'
    if src_theses.exists():
        for thesis_dir in src_theses.iterdir():
            if thesis_dir.is_dir():
                dst = project_root / 'theses' / thesis_dir.name
                if dst.exists() and force:
                    shutil.rmtree(dst)
                shutil.copytree(thesis_dir, dst)
                print(f"  ✓ Thesis: {thesis_dir.name}")

    # 2. Copy diegesis
    src_diegeses = staging / 'library' / 'diegeses'
    if src_diegeses.exists():
        dst_diegeses = project_root / 'library' / 'diegeses'
        dst_diegeses.mkdir(parents=True, exist_ok=True)
        for f in src_diegeses.glob('*.md'):
            shutil.copy2(f, dst_diegeses / f.name)
            print(f"  ✓ Diegesis: {f.stem}")

    # 3. Copy doxai (strip export tags)
    src_doxai = staging / 'library' / 'doxai'
    if src_doxai.exists():
        dst_doxai = project_root / 'library' / 'doxai'
        dst_doxai.mkdir(parents=True, exist_ok=True)
        count = 0
        for f in src_doxai.glob('*.md'):
            content = f.read_text()
            # Strip export tag before writing
            content = strip_export_tag(content)
            (dst_doxai / f.name).write_text(content)
            count += 1
        print(f"  ✓ {count} doxai (export tags stripped)")

    # 4. Copy evidence
    src_evidence = staging / 'library' / 'evidence'
    if src_evidence.exists():
        dst_evidence = project_root / 'library' / 'evidence'
        dst_evidence.mkdir(parents=True, exist_ok=True)
        count = 0
        for f in src_evidence.glob('*.md'):
            shutil.copy2(f, dst_evidence / f.name)
            count += 1
        if count:
            print(f"  ✓ {count} evidence files")

    # 5. Merge edges
    src_logos = staging / 'library' / 'logos.yaml'
    if src_logos.exists():
        dst_logos = project_root / 'library' / 'logos.yaml'
        if dst_logos.exists():
            added = merge_edges(src_logos, dst_logos)
            print(f"  ✓ Merged {added} new edges into logos.yaml")
        else:
            shutil.copy2(src_logos, dst_logos)
            print(f"  ✓ Created logos.yaml")

    # Cleanup
    shutil.rmtree(staging)

    print("\n✓ Import complete!")
    return True


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Import a presentation export')
    parser.add_argument('zip_file', type=Path, help='Path to export zip file')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be imported without doing it')
    parser.add_argument('--force', action='store_true', help='Overwrite existing files')
    parser.add_argument('--project-root', type=Path, default=None, help='Project root directory')

    args = parser.parse_args()

    project_root = args.project_root or Path(__file__).parent.parent.parent

    import_presentation(args.zip_file, project_root, args.dry_run, args.force)
