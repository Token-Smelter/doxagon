#!/usr/bin/env python3
"""
Essay Compiler

Compiles essay sections into a unified markdown document with optional images.

Section structure:
    outputs/essay/sections/{slug}/
    ├── section.md               # Content (frontmatter + prose)
    └── images/{id}/
        ├── definition.md        # Visual description + styles
        ├── sources/             # Reference images
        └── outputs/             # Generated images

Outputs to timestamped build directories.

Usage:
    python factory/scripts/compile_essay.py --presentation sample-blueprint
    python factory/scripts/compile_essay.py --validate-only
    python factory/scripts/compile_essay.py --verbose
"""

import argparse
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

import sys
sys.path.insert(0, str(Path(__file__).parent))

from utils import (
    get_presentation_path,
    get_essay_output_paths,
    get_section_order,
    find_section_dir,
    load_section,
    load_output_config,
    find_best_image_in_dir,
)


class SectionContent(NamedTuple):
    """Container for section content."""
    slug: str
    title: str
    level: int
    body: str
    doxai: list[str]
    derived_from: list[str]
    images: list[dict]


def load_section_content(section_dir: Path, section_meta: dict) -> SectionContent | None:
    """Load content from a section directory.

    Args:
        section_dir: Path to section directory
        section_meta: Metadata from config (slug, level, title override)

    Returns:
        SectionContent or None if invalid
    """
    result = load_section(section_dir)
    if not result:
        return None

    frontmatter, body = result

    slug = section_meta.get('slug', section_dir.name)
    title = section_meta.get('title') or frontmatter.get('title', 'Untitled')
    level = section_meta.get('level', frontmatter.get('level', 1))
    doxai = frontmatter.get('doxai', [])
    derived_from = frontmatter.get('derived_from', [])
    images = frontmatter.get('images', [])

    return SectionContent(
        slug=slug,
        title=title,
        level=level,
        body=body,
        doxai=doxai,
        derived_from=derived_from,
        images=images,
    )


def find_section_image(section_dir: Path, image_id: str = 'main') -> Path | None:
    """Find an image in a section's images directory.

    Handles both:
    - Symlinked images from slides: images/{slug}/selected.{ext}
    - Native essay images: images/{id}/outputs/
    """
    img_dir = section_dir / "images" / image_id

    if not img_dir.exists():
        return None

    # Check for selected.* (symlinked from slides)
    for ext in ['png', 'jpg', 'jpeg']:
        selected = img_dir / f"selected.{ext}"
        if selected.exists():
            return selected

    # Fall back to outputs directory (native essay images)
    outputs_dir = img_dir / "outputs"
    return find_best_image_in_dir(outputs_dir)


def resolve_image_refs(body: str, section_dir: Path, build_img_dir: Path) -> tuple[str, list[Path]]:
    """Resolve ![[image-id]] references in body text.

    Args:
        body: Section body text
        section_dir: Path to section directory
        build_img_dir: Path to build images directory

    Returns:
        Tuple of (resolved body text, list of copied image paths)
    """
    copied_images = []
    image_pattern = re.compile(r'!\[\[([^\]]+)\]\]')

    def replace_image(match):
        image_id = match.group(1)
        image_path = find_section_image(section_dir, image_id)

        if image_path and image_path.exists():
            dest_name = f"{section_dir.name}-{image_id}{image_path.suffix}"
            dest_path = build_img_dir / dest_name
            copied_images.append((image_path, dest_path))
            return f"![{image_id}](img/{dest_name})"
        else:
            return f"[Image not found: {image_id}]"

    resolved = image_pattern.sub(replace_image, body)
    return resolved, copied_images


def resolve_section_refs(body: str, section_slugs: list[str]) -> str:
    """Resolve [[slug]] cross-references to section anchors.

    Args:
        body: Section body text
        section_slugs: List of valid section slugs

    Returns:
        Body with resolved cross-references
    """
    # Negative lookbehind to avoid matching ![[image]] refs
    ref_pattern = re.compile(r'(?<!!)\[\[([^\]]+)\]\]')

    def replace_ref(match):
        slug = match.group(1)
        if slug in section_slugs:
            return f"[{slug}](#{slug})"
        else:
            return f"[Unknown section: {slug}]"

    return ref_pattern.sub(replace_ref, body)


def resolve_citations(body: str, bib_keys: set[str]) -> str:
    """Resolve [@key] citations.

    Args:
        body: Section body text
        bib_keys: Set of valid bibliography keys

    Returns:
        Body with resolved citations (or warnings for invalid keys)
    """
    cite_pattern = re.compile(r'\[@([^\]]+)\]')

    def replace_cite(match):
        key = match.group(1)
        if key in bib_keys:
            return f"[{key}]"
        else:
            return f"[Citation not found: {key}]"

    return cite_pattern.sub(replace_cite, body)


def load_bib_keys(bib_path: Path) -> set[str]:
    """Extract citation keys from a .bib file."""
    keys = set()
    if not bib_path.exists():
        return keys

    content = bib_path.read_text()
    key_pattern = re.compile(r'@\w+\{([^,]+),')
    for match in key_pattern.finditer(content):
        keys.add(match.group(1))

    return keys


def parse_bib_entries(bib_path: Path) -> list[dict]:
    """Parse .bib file into structured entries for rendering.

    Returns list of dicts with: key, type, author, title, year, and other fields.
    """
    if not bib_path.exists():
        return []

    content = bib_path.read_text()
    entries = []

    # Match each @type{key, ... } block
    entry_pattern = re.compile(r'@(\w+)\{([^,]+),([^@]*)\}', re.MULTILINE | re.DOTALL)

    for match in entry_pattern.finditer(content):
        entry_type = match.group(1).lower()
        key = match.group(2).strip()
        fields_text = match.group(3)

        entry = {'key': key, 'type': entry_type}

        # Parse fields - handle multi-line values and braces
        field_pattern = re.compile(r'(\w+)\s*=\s*(?:\{([^}]*)\}|"([^"]*)")', re.MULTILINE | re.DOTALL)
        for field_match in field_pattern.finditer(fields_text):
            field_name = field_match.group(1).lower()
            field_value = (field_match.group(2) or field_match.group(3) or '').strip()
            # Clean up whitespace in multi-line values
            field_value = ' '.join(field_value.split())
            entry[field_name] = field_value

        entries.append(entry)

    return entries


def render_bibliography(bib_path: Path) -> str:
    """Render .bib file as markdown bibliography.

    Format: Author (Year). *Title*. Publisher/Journal.
    """
    entries = parse_bib_entries(bib_path)
    if not entries:
        return ""

    # Sort by author last name, then year
    def sort_key(e):
        author = e.get('author', 'ZZZ')
        # Extract last name (before comma or first word)
        if ',' in author:
            last_name = author.split(',')[0].strip()
        else:
            last_name = author.split()[0] if author.split() else 'ZZZ'
        # Handle institutional authors in {{}}
        last_name = last_name.strip('{}')
        year = e.get('year', '9999')
        return (last_name.lower(), year)

    entries.sort(key=sort_key)

    lines = []
    for entry in entries:
        author = entry.get('author', 'Unknown')
        # Clean up institutional authors
        author = author.strip('{}')
        year = entry.get('year', 'n.d.')
        title = entry.get('title', 'Untitled')

        # Format based on entry type
        if entry['type'] == 'book':
            publisher = entry.get('publisher', '')
            if publisher:
                lines.append(f"- {author} ({year}). *{title}*. {publisher}.")
            else:
                lines.append(f"- {author} ({year}). *{title}*.")

        elif entry['type'] == 'article':
            journal = entry.get('journal', '')
            volume = entry.get('volume', '')
            number = entry.get('number', '')
            pages = entry.get('pages', '')

            cite = f"- {author} ({year}). {title}."
            if journal:
                cite += f" *{journal}*"
                if volume:
                    cite += f", {volume}"
                    if number:
                        cite += f"({number})"
                if pages:
                    cite += f", {pages}"
            cite += "."
            lines.append(cite)

        elif entry['type'] == 'techreport':
            institution = entry.get('institution', '')
            number = entry.get('number', '')
            cite = f"- {author} ({year}). *{title}*."
            if number:
                cite += f" {number}."
            if institution:
                cite += f" {institution}."
            lines.append(cite)

        elif entry['type'] == 'misc':
            note = entry.get('note', '')
            cite = f"- {author} ({year}). {title}."
            if note:
                cite += f" {note}"
            lines.append(cite)

        else:
            # Generic fallback
            lines.append(f"- {author} ({year}). *{title}*.")

    return '\n'.join(lines)


def generate_toc(sections: list[SectionContent], heading_offset: int = 0) -> str:
    """Generate table of contents from sections."""
    lines = ["## Contents\n"]

    for section in sections:
        indent = "  " * (section.level - 1)
        lines.append(f"{indent}- [{section.title}](#{section.slug})")

    lines.append("")
    return '\n'.join(lines)


def compile_essay(
    sections_dir: Path,
    config: dict,
    build_dir: Path,
    verbose: bool = False,
    include_images: bool = True,
    include_toc: bool = True,
    include_bibliography: bool = True,
    references_bib: Path | None = None,
) -> tuple[str, list[tuple[Path, Path]]]:
    """Compile all sections into a single markdown document.

    Returns:
        Tuple of (markdown content, list of (source, dest) image pairs to copy)
    """
    build_img_dir = build_dir / "img"
    output_lines = []
    all_images = []

    # Title block
    title = config.get('title', 'Untitled Essay')
    subtitle = config.get('subtitle')
    author = config.get('author')
    date = config.get('date')

    output_lines.append(f"# {title}\n")
    if subtitle:
        output_lines.append(f"*{subtitle}*\n")
    if author:
        output_lines.append(f"**{author}**")
    if date:
        output_lines.append(f"  \n{date}\n")
    output_lines.append("\n---\n")

    # Abstract
    abstract = config.get('abstract')
    if abstract:
        output_lines.append("## Abstract\n")
        output_lines.append(f"{abstract.strip()}\n")
        output_lines.append("\n---\n")

    # Load bibliography keys for citation resolution
    bib_keys = set()
    if references_bib:
        bib_keys = load_bib_keys(references_bib)
        if verbose:
            print(f"  Loaded {len(bib_keys)} bibliography keys")

    # Get ordered sections
    section_order = get_section_order(sections_dir, config)
    section_slugs = [s.get('slug', s) if isinstance(s, dict) else s for s in section_order]

    # Load all sections first (for TOC and cross-ref validation)
    loaded_sections = []
    for section_meta in section_order:
        if isinstance(section_meta, str):
            section_meta = {'slug': section_meta, 'level': 1}

        slug = section_meta.get('slug')
        section_dir = find_section_dir(sections_dir, slug)

        if not section_dir:
            if verbose:
                print(f"  WARNING: Section '{slug}' not found, skipping")
            continue

        section = load_section_content(section_dir, section_meta)
        if section:
            loaded_sections.append((section, section_dir))

    # Generate TOC
    if include_toc and loaded_sections:
        toc = generate_toc([s for s, _ in loaded_sections])
        output_lines.append(toc)
        output_lines.append("\n---\n")

    # Heading offset from config
    heading_offset = config.get('build', {}).get('heading_offset', 0)

    # Compile each section
    for section, section_dir in loaded_sections:
        if verbose:
            print(f"  Processing section: {section.title}")

        # Section heading with anchor and source marker
        heading_level = '#' * (section.level + heading_offset + 1)
        output_lines.append(f"\n<!-- section: {section.slug} -->")
        output_lines.append(f"{heading_level} {section.title} {{#{section.slug}}}\n")

        # Process body
        body = section.body

        # Resolve cross-references
        body = resolve_section_refs(body, section_slugs)

        # Resolve citations
        if bib_keys:
            body = resolve_citations(body, bib_keys)

        # Resolve images
        if include_images:
            body, images = resolve_image_refs(body, section_dir, build_img_dir)
            all_images.extend(images)

        output_lines.append(f"{body}\n")

    # Bibliography
    if include_bibliography and references_bib and references_bib.exists():
        output_lines.append("\n---\n")
        output_lines.append("## References\n")
        bib_content = render_bibliography(references_bib)
        if bib_content:
            output_lines.append(bib_content + "\n")
        else:
            output_lines.append(f"*See {references_bib.name} for full bibliography*\n")

    return '\n'.join(output_lines), all_images


def validate_essay(
    sections_dir: Path,
    config: dict,
    references_bib: Path | None = None,
    verbose: bool = False,
) -> dict:
    """Validate essay structure without compiling.

    Returns:
        Dict with validation results
    """
    results = {
        'sections': [],
        'missing_sections': [],
        'total_words': 0,
        'images': [],
        'missing_images': [],
        'citations': [],
        'missing_citations': [],
        'cross_refs': [],
        'invalid_cross_refs': [],
    }

    # Load bibliography keys
    bib_keys = set()
    if references_bib:
        bib_keys = load_bib_keys(references_bib)

    # Get ordered sections
    section_order = get_section_order(sections_dir, config)
    section_slugs = [s.get('slug', s) if isinstance(s, dict) else s for s in section_order]

    for section_meta in section_order:
        if isinstance(section_meta, str):
            section_meta = {'slug': section_meta, 'level': 1}

        slug = section_meta.get('slug')
        section_dir = find_section_dir(sections_dir, slug)

        if not section_dir:
            results['missing_sections'].append(slug)
            continue

        section = load_section_content(section_dir, section_meta)
        if not section:
            results['missing_sections'].append(slug)
            continue

        word_count = len(section.body.split())
        results['sections'].append({
            'slug': slug,
            'title': section.title,
            'words': word_count,
            'level': section.level,
            'doxai': len(section.doxai),
        })
        results['total_words'] += word_count

        # Check images
        image_pattern = re.compile(r'!\[\[([^\]]+)\]\]')
        for match in image_pattern.finditer(section.body):
            image_id = match.group(1)
            image_path = find_section_image(section_dir, image_id)
            if image_path:
                results['images'].append(f"{slug}/{image_id}")
            else:
                results['missing_images'].append(f"{slug}/{image_id}")

        # Check citations
        cite_pattern = re.compile(r'\[@([^\]]+)\]')
        for match in cite_pattern.finditer(section.body):
            key = match.group(1)
            if key in bib_keys:
                results['citations'].append(key)
            else:
                results['missing_citations'].append(key)

        # Check cross-refs (negative lookbehind to avoid ![[image]] refs)
        ref_pattern = re.compile(r'(?<!!)\[\[([^\]]+)\]\]')
        for match in ref_pattern.finditer(section.body):
            ref_slug = match.group(1)
            if ref_slug in section_slugs:
                results['cross_refs'].append(f"{slug} -> {ref_slug}")
            else:
                results['invalid_cross_refs'].append(f"{slug} -> {ref_slug}")

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Compile essay sections to timestamped build directory",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        "--presentation", "-p",
        type=str,
        help="Presentation/thesis name (default: active)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output"
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate structure without building"
    )
    parser.add_argument(
        "--no-images",
        action="store_true",
        help="Skip image processing"
    )
    parser.add_argument(
        "--no-toc",
        action="store_true",
        help="Skip table of contents"
    )
    parser.add_argument(
        "--no-bibliography",
        action="store_true",
        help="Skip bibliography section"
    )

    args = parser.parse_args()

    # Determine presentation
    presentation = args.presentation
    if not presentation:
        print("Error: No presentation specified")
        print("Use --presentation NAME")
        return 1

    presentation_path = get_presentation_path(presentation)
    if not presentation_path.exists():
        print(f"Error: Presentation not found: {presentation_path}")
        return 1

    # Get essay paths
    essay_paths = get_essay_output_paths(presentation_path)
    sections_dir = essay_paths['sections_dir']
    build_base = essay_paths['build_dir']
    references_bib = essay_paths['references_bib']

    if not sections_dir.exists():
        print(f"Error: Sections directory not found: {sections_dir}")
        print("Run scaffold_essay.py first to generate sections")
        return 1

    # Load essay config
    config = load_output_config(presentation_path, "essay")

    # Validate mode
    if args.validate_only:
        print(f"Validating essay for: {presentation}")
        results = validate_essay(sections_dir, config, references_bib, args.verbose)

        print(f"\nSections ({len(results['sections'])} found):")
        for s in results['sections']:
            print(f"  {s['slug']}: {s['words']} words, {s['doxai']} doxai")

        if results['missing_sections']:
            print(f"\nMissing sections: {', '.join(results['missing_sections'])}")

        print(f"\nTotal words: {results['total_words']}")

        if results['images']:
            print(f"Images: {len(results['images'])}")
        if results['missing_images']:
            print(f"Missing images: {', '.join(results['missing_images'])}")

        if results['citations']:
            print(f"Citations: {len(set(results['citations']))}")
        if results['missing_citations']:
            print(f"Missing citations: {', '.join(set(results['missing_citations']))}")

        if results['cross_refs']:
            print(f"Cross-references: {len(results['cross_refs'])}")
        if results['invalid_cross_refs']:
            print(f"Invalid cross-refs: {', '.join(results['invalid_cross_refs'])}")

        return 0

    # Build mode
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    build_dir = build_base / timestamp

    print(f"Building essay for: {presentation}")
    print(f"Output: {build_dir}")

    # Compile
    include_images = not args.no_images
    include_toc = not args.no_toc
    include_bibliography = not args.no_bibliography

    content, images = compile_essay(
        sections_dir=sections_dir,
        config=config,
        build_dir=build_dir,
        verbose=args.verbose,
        include_images=include_images,
        include_toc=include_toc,
        include_bibliography=include_bibliography,
        references_bib=references_bib,
    )

    # Write markdown
    build_dir.mkdir(parents=True, exist_ok=True)
    output_path = build_dir / "essay.md"
    output_path.write_text(content)

    # Copy images
    if include_images and images:
        img_dir = build_dir / "img"
        img_dir.mkdir(exist_ok=True)
        for src, dest in images:
            shutil.copy2(src, dest)
            if args.verbose:
                print(f"  Image: {src.name} -> {dest.name}")

    # Summary
    section_count = len(get_section_order(sections_dir, config))
    print(f"\nEssay: {output_path}")
    print(f"Sections: {section_count}")
    if images:
        print(f"Images: {len(images)}")

    return 0


if __name__ == "__main__":
    exit(main())
