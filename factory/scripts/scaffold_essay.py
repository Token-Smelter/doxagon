#!/usr/bin/env python3
"""
Scaffold essay sections from presentation speaker notes.

Generates essay section structure from an existing presentation,
using speaker notes as the initial prose content.
"""

import argparse
import sys
from pathlib import Path

# Add parent to path for utils import
sys.path.insert(0, str(Path(__file__).parent))

from utils import (
    get_presentation_path,
    get_presentation_output_paths,
    get_essay_output_paths,
    load_output_config,
    find_slide_dir,
    parse_frontmatter,
)


# Mapping from presentation acts to essay sections
# Based on presentation config.yaml slides: list with act comments
ACT_TO_SECTION = {
    'introduction': {
        'title': 'Introduction',
        'level': 1,
        'slides': ['title', 'cheap-action-verification-scarce'],
    },
    'symptoms-and-lens': {
        'title': 'Symptoms and the McLuhan Lens',
        'level': 1,
        'slides': ['next-step', 'medium-shift', 'bottleneck-moves'],
    },
    'substrate': {
        'title': 'The Organizational Substrate',
        'level': 1,
        'slides': [
            'binding-acts',
            'what-makes-work-real',
            'six-requirements',
            'self-as-wrapper',
            'six-primitives-preview',
        ],
    },
    'the-challenge': {
        'title': 'The Challenge',
        'level': 1,
        'slides': [
            'discretion-not-just-delegation',
            'ai-native-definition',
            'delegated-authority-sentence',
            'velocity-ceiling',
            'drinking-bird-backdoor-delegation',
        ],
    },
    'the-solution': {
        'title': 'The Delegation Control Plane',
        'level': 1,
        'slides': [
            'delegation-control-plane',
            'binding-act-request',
            'worked-example-deploy',
            'earned-autonomy',
            'what-this-enables',
        ],
    },
    'conclusion': {
        'title': 'Conclusion',
        'level': 1,
        'slides': [],  # New content, not derived from slides
    },
}


def find_slide_image_path(slide_dir: Path) -> Path | None:
    """Find the selected image for a slide."""
    slide_md = slide_dir / "slide.md"
    if not slide_md.exists():
        return None

    content = slide_md.read_text()
    frontmatter, _ = parse_frontmatter(content)

    images = frontmatter.get('images', [])
    if not images:
        return None

    # Find primary image
    primary = None
    for img in images:
        if img.get('is_primary', False):
            primary = img
            break
    if not primary:
        primary = images[0]

    # Get selected path
    image_id = primary.get('id', 'main')
    selected = primary.get('selected')
    if selected:
        selected_path = slide_dir / "images" / image_id / selected
        if selected_path.exists():
            return selected_path

    # Fallback: find best image in outputs
    outputs_dir = slide_dir / "images" / image_id / "outputs"
    if outputs_dir.exists():
        for ext in ['png', 'jpg', 'jpeg']:
            selected = outputs_dir / f"selected.{ext}"
            if selected.exists():
                return selected
        # Most recent generated
        images = sorted(outputs_dir.glob("generated_*.*"), reverse=True)
        if images:
            return images[0]

    return None


def collect_slide_content(slides_dir: Path, slide_slugs: list[str]) -> dict:
    """Collect speaker notes, doxai, and images from slides."""
    slide_content = []  # List of (slug, notes, image_path) tuples
    all_doxai = []
    derived_from = []

    for slug in slide_slugs:
        slide_dir = find_slide_dir(slides_dir, slug)
        if not slide_dir:
            print(f"  Warning: Slide '{slug}' not found")
            continue

        slide_md = slide_dir / "slide.md"
        if not slide_md.exists():
            continue

        content = slide_md.read_text()
        frontmatter, _ = parse_frontmatter(content)

        # Collect speaker notes
        notes = frontmatter.get('speaker_notes', '')

        # Find slide image
        image_path = find_slide_image_path(slide_dir)

        slide_content.append({
            'slug': slug,
            'notes': notes.strip() if notes else '',
            'image_path': image_path,
        })

        # Collect doxai references
        doxai = frontmatter.get('doxai', [])
        if doxai:
            for d in doxai:
                if d not in all_doxai:
                    all_doxai.append(d)

        # Track derived_from
        derived_from.append(slug)

    return {
        'slide_content': slide_content,
        'doxai': all_doxai,
        'derived_from': derived_from,
    }


def generate_section_md(
    title: str,
    level: int,
    derived_from: list[str],
    doxai: list[str],
    slide_content: list[dict],
    image_ids: list[str],
) -> str:
    """Generate section.md content with inline image references."""
    import yaml

    frontmatter = {
        'title': title,
        'level': level,
    }

    if derived_from:
        frontmatter['derived_from'] = derived_from

    if doxai:
        frontmatter['doxai'] = doxai

    frontmatter['images'] = []

    # Build the markdown content
    yaml_str = yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True, sort_keys=False)

    # Build body with image references before each section's notes
    body_parts = []
    for item in slide_content:
        slug = item['slug']
        notes = item['notes']
        has_image = slug in image_ids

        if has_image:
            body_parts.append(f"![[{slug}]]")

        if notes:
            body_parts.append(notes)

    body = '\n\n'.join(body_parts) if body_parts else '[Content to be written]'

    return f"""---
{yaml_str.strip()}
---

{body}
"""


def scaffold_section(
    section_slug: str,
    section_info: dict,
    slides_dir: Path,
    sections_dir: Path,
    force: bool = False,
) -> bool:
    """Scaffold a single essay section."""
    section_dir = sections_dir / section_slug
    section_md = section_dir / "section.md"

    # Check if section already exists
    if section_md.exists() and not force:
        print(f"  Skipping '{section_slug}' (already exists, use --force to overwrite)")
        return False

    # Create section directory
    section_dir.mkdir(parents=True, exist_ok=True)

    # Collect content from slides
    content = collect_slide_content(slides_dir, section_info.get('slides', []))

    # Create images directory and symlink images from slides
    images_dir = section_dir / "images"
    images_dir.mkdir(exist_ok=True)

    image_ids = []
    for item in content['slide_content']:
        slug = item['slug']
        image_path = item['image_path']

        if image_path and image_path.exists():
            # Create directory for this image
            img_subdir = images_dir / slug
            img_subdir.mkdir(exist_ok=True)

            # Symlink the image
            link_path = img_subdir / f"selected{image_path.suffix}"
            if link_path.exists() or link_path.is_symlink():
                link_path.unlink()
            link_path.symlink_to(image_path)

            image_ids.append(slug)
            print(f"    Linked image: {slug}")

    # Generate section.md
    md_content = generate_section_md(
        title=section_info['title'],
        level=section_info['level'],
        derived_from=content['derived_from'],
        doxai=content['doxai'],
        slide_content=content['slide_content'],
        image_ids=image_ids,
    )

    section_md.write_text(md_content)
    print(f"  Created '{section_slug}/section.md'")

    return True


def main():
    parser = argparse.ArgumentParser(
        description='Scaffold essay sections from presentation speaker notes'
    )
    parser.add_argument(
        '--presentation', '-p',
        help='Presentation name'
    )
    parser.add_argument(
        '--force', '-f',
        action='store_true',
        help='Overwrite existing sections'
    )
    parser.add_argument(
        '--section', '-s',
        help='Scaffold only this section (by slug)'
    )
    parser.add_argument(
        '--dry-run', '-n',
        action='store_true',
        help='Show what would be created without writing files'
    )

    args = parser.parse_args()

    # Get presentation
    presentation = args.presentation
    if not presentation:
        print("Error: No presentation specified. Use --presentation NAME")
        return 1

    print(f"Scaffolding essay for: {presentation}")

    # Get paths
    presentation_path = get_presentation_path(presentation)
    pres_paths = get_presentation_output_paths(presentation_path)
    essay_paths = get_essay_output_paths(presentation_path)

    slides_dir = pres_paths['slides_dir']
    sections_dir = essay_paths['sections_dir']

    if not slides_dir.exists():
        print(f"Error: Slides directory not found: {slides_dir}")
        return 1

    # Ensure sections directory exists
    sections_dir.mkdir(parents=True, exist_ok=True)

    # Determine which sections to scaffold
    if args.section:
        if args.section not in ACT_TO_SECTION:
            print(f"Error: Unknown section '{args.section}'")
            print(f"Available: {', '.join(ACT_TO_SECTION.keys())}")
            return 1
        sections_to_scaffold = {args.section: ACT_TO_SECTION[args.section]}
    else:
        sections_to_scaffold = ACT_TO_SECTION

    # Scaffold each section
    created = 0
    for section_slug, section_info in sections_to_scaffold.items():
        print(f"\nSection: {section_slug}")

        if args.dry_run:
            print(f"  Would create: {sections_dir / section_slug}/section.md")
            print(f"  From slides: {section_info.get('slides', [])}")
            continue

        if scaffold_section(section_slug, section_info, slides_dir, sections_dir, args.force):
            created += 1

    if not args.dry_run:
        print(f"\nScaffolded {created} sections in {sections_dir}")

    return 0


if __name__ == '__main__':
    sys.exit(main())
