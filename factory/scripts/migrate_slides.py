#!/usr/bin/env python3
"""
Slide Migration Script

Migrates slides from v1 structure (separate files) to v2 structure (consolidated slide.md + image bundles).

v1 structure:
    slides/{slug}/
    ├── text.md
    ├── speaker-notes.md
    ├── definition.md
    ├── sources/
    └── outputs/

v2 structure:
    slides/{slug}/
    ├── slide.md
    └── images/
        └── main/
            ├── definition.md
            ├── sources/
            └── outputs/

Usage:
    python factory/scripts/migrate_slides.py --presentation observatory
    python factory/scripts/migrate_slides.py --presentation observatory --slide 07 --dry-run
"""

import argparse
import re
import shutil
import sys
import yaml
from pathlib import Path

from utils import (
    get_presentation_path,
    get_presentation_output_paths,
    parse_frontmatter,
)


def extract_title(text_content: str) -> str:
    """Extract title from text.md content."""
    for line in text_content.split('\n'):
        line = line.strip()
        if line.startswith('# '):
            return line[2:].strip()
    return "Untitled"


def extract_body(text_content: str) -> str:
    """Extract body (everything after first heading) from text.md."""
    lines = text_content.split('\n')
    body_lines = []
    found_title = False

    for line in lines:
        if line.strip().startswith('# ') and not found_title:
            found_title = True
            continue
        if found_title:
            body_lines.append(line)

    return '\n'.join(body_lines).strip()


def is_v1_slide(slide_dir: Path) -> bool:
    """Check if slide uses v1 structure."""
    return (slide_dir / "definition.md").exists() and not (slide_dir / "slide.md").exists()


def is_v2_slide(slide_dir: Path) -> bool:
    """Check if slide uses v2 structure."""
    return (slide_dir / "slide.md").exists()


def migrate_slide(slide_dir: Path, dry_run: bool = False) -> bool:
    """
    Migrate a single slide from v1 to v2 structure.

    Returns True if migration was performed, False if skipped.
    """
    if not is_v1_slide(slide_dir):
        if is_v2_slide(slide_dir):
            print(f"  Skipping {slide_dir.name}: already v2")
        else:
            print(f"  Skipping {slide_dir.name}: no definition.md found")
        return False

    print(f"  Migrating {slide_dir.name}...")

    # Read existing files
    text_file = slide_dir / "text.md"
    notes_file = slide_dir / "speaker-notes.md"
    definition_file = slide_dir / "definition.md"
    sources_dir = slide_dir / "sources"
    outputs_dir = slide_dir / "outputs"

    text_content = text_file.read_text() if text_file.exists() else ""
    notes_content = notes_file.read_text() if notes_file.exists() else ""
    definition_content = definition_file.read_text() if definition_file.exists() else ""

    # Parse definition.md
    def_frontmatter, def_body = parse_frontmatter(definition_content)

    # Extract slide metadata
    title = extract_title(text_content)
    body = extract_body(text_content)

    # Clean speaker notes (remove header if present)
    notes_lines = []
    for line in notes_content.split('\n'):
        if line.strip().startswith('# Speaker Notes'):
            continue
        notes_lines.append(line)
    speaker_notes = '\n'.join(notes_lines).strip()

    # Get selected image path (already relative to outputs/)
    selected = def_frontmatter.get('selected', '')

    # Build slide.md content
    slide_yaml = {
        'text': {
            'title': title,
            'body': body if body else None,
        },
        'speaker_notes': speaker_notes if speaker_notes else None,
        'images': [
            {
                'id': 'main',
                'selected': selected if selected else None,
                'placement': 'full-bleed',
                'purpose': f"Visual representation for {title}",
            }
        ]
    }

    # Remove None values
    if not slide_yaml['text'].get('body'):
        del slide_yaml['text']['body']
    if not slide_yaml.get('speaker_notes'):
        del slide_yaml['speaker_notes']
    if not slide_yaml['images'][0].get('selected'):
        del slide_yaml['images'][0]['selected']

    # Build image definition.md content (preserve original)
    # Just keep the original definition.md as-is for the image

    if dry_run:
        print(f"    Would create: slide.md")
        print(f"    Would create: images/main/definition.md")
        if sources_dir.exists():
            print(f"    Would move: sources/ -> images/main/sources/")
        if outputs_dir.exists():
            print(f"    Would move: outputs/ -> images/main/outputs/")
        print(f"    Would remove: text.md, speaker-notes.md, definition.md")
        return True

    # Create new structure
    images_main_dir = slide_dir / "images" / "main"
    images_main_dir.mkdir(parents=True, exist_ok=True)

    # Write slide.md
    slide_md_content = "---\n"
    slide_md_content += yaml.dump(slide_yaml, default_flow_style=False, allow_unicode=True, sort_keys=False)
    slide_md_content += "---\n"
    (slide_dir / "slide.md").write_text(slide_md_content)

    # Move definition.md to images/main/
    shutil.copy2(definition_file, images_main_dir / "definition.md")

    # Move sources/ if exists
    if sources_dir.exists() and sources_dir.is_dir():
        dest_sources = images_main_dir / "sources"
        if dest_sources.exists():
            shutil.rmtree(dest_sources)
        shutil.move(str(sources_dir), str(dest_sources))

    # Move outputs/ if exists
    if outputs_dir.exists() and outputs_dir.is_dir():
        dest_outputs = images_main_dir / "outputs"
        if dest_outputs.exists():
            shutil.rmtree(dest_outputs)
        shutil.move(str(outputs_dir), str(dest_outputs))

    # Remove old files
    if text_file.exists():
        text_file.unlink()
    if notes_file.exists():
        notes_file.unlink()
    if definition_file.exists():
        definition_file.unlink()

    print(f"    Created: slide.md")
    print(f"    Created: images/main/definition.md")

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Migrate slides from v1 to v2 structure",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument("--presentation", type=str, help="Presentation name (default: active)")
    parser.add_argument("--slide", type=str, help="Migrate only this slide number (e.g., '07')")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without making changes")

    args = parser.parse_args()

    # Determine presentation
    presentation = args.presentation
    if not presentation:
        print("Error: No presentation specified and no active presentation set")
        sys.exit(1)

    presentation_path = get_presentation_path(presentation)
    if not presentation_path.exists():
        print(f"Error: Presentation not found: {presentation_path}")
        sys.exit(1)

    # Get output paths (supports both new and legacy structure)
    paths = get_presentation_output_paths(presentation_path)
    slides_dir = paths['slides_dir']
    if not slides_dir.exists():
        print(f"Error: Slides directory not found: {slides_dir}")
        sys.exit(1)

    print(f"Migrating slides for '{presentation}'")
    if args.dry_run:
        print("(DRY RUN - no changes will be made)")
    print()

    # Find slide directories
    slide_dirs = sorted([d for d in slides_dir.iterdir() if d.is_dir()])

    migrated = 0
    skipped = 0

    for slide_dir in slide_dirs:
        # Filter by slide number (must match XX- prefix exactly)
        if args.slide:
            slide_prefix = f"{args.slide.zfill(2)}-"
            if not slide_dir.name.startswith(slide_prefix):
                continue

        if migrate_slide(slide_dir, dry_run=args.dry_run):
            migrated += 1
        else:
            skipped += 1

    print()
    print(f"Done. Migrated: {migrated}, Skipped: {skipped}")


if __name__ == "__main__":
    main()
