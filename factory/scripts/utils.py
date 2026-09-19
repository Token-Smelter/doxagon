#!/usr/bin/env python3
"""
Shared utilities for presentation factory scripts.
"""

import os
import re
import yaml
from pathlib import Path


def vault_root() -> Path:
    """The content root these scripts operate on.

    Presentations live in the vault, not beside this file. Resolving from
    `__file__` pointed at the platform checkout, so every path built from it
    missed even when the caller named a real project.
    """
    configured = os.environ.get("DOXAGON_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    raise SystemExit(
        "Set DOXAGON_ROOT to the vault (e.g. ~/development/doxagon-vault).\n"
        "These scripts read presentation content, which does not live in this repository."
    )


PROJECT_ROOT = Path(__file__).parent.parent.parent


def get_presentation_path(presentation: str) -> Path:
    """Get path to presentation directory"""
    return vault_root() / "projects" / presentation


def get_presentation_output_paths(presentation_path: Path) -> dict:
    """Get paths to presentation output components.

    Returns dict with:
        slides_dir: Path to slides
        styles_dir: Path to styles
        build_dir: Path to build output
        templates_dir: Path to templates

    Supports both new structure (outputs/presentation/) and legacy (flat).
    """
    # New structure: outputs/presentation/
    new_slides = presentation_path / "outputs" / "presentation" / "slides"
    if new_slides.exists():
        return {
            'slides_dir': new_slides,
            'styles_dir': presentation_path / "outputs" / "presentation" / "styles",
            'build_dir': presentation_path / "outputs" / "presentation" / "build",
            'templates_dir': presentation_path / "templates",
        }

    # Legacy structure: flat
    return {
        'slides_dir': presentation_path / "slides",
        'styles_dir': presentation_path / "styles",
        'build_dir': presentation_path / "build",
        'templates_dir': presentation_path / "templates",
    }


def get_essay_output_paths(presentation_path: Path) -> dict:
    """Get paths to essay output components.

    Returns dict with:
        essay_dir: Path to essay output root
        sections_dir: Path to sections
        styles_dir: Path to styles
        build_dir: Path to build output
        references_bib: Path to bibliography file
    """
    essay_dir = presentation_path / "outputs" / "essay"
    return {
        'essay_dir': essay_dir,
        'sections_dir': essay_dir / "sections",
        'styles_dir': essay_dir / "styles",
        'build_dir': essay_dir / "build",
        'references_bib': essay_dir / "references.bib",
    }


def natural_sort_key(s: str) -> tuple:
    """Sort key for natural ordering (00, 00-5, 01, 02, etc.)."""
    match = re.match(r'^(\d+)(?:-(\d+))?-(.+)$', s)
    if match:
        major = int(match.group(1))
        minor = int(match.group(2)) if match.group(2) else 0
        return (major, minor, match.group(3))
    return (999, 0, s)


def normalize_slug(dirname: str) -> str:
    """Extract semantic slug from directory name.

    Examples:
        '05-mcluhan-medium-environment' -> 'mcluhan-medium-environment'
        '05-5-extensions-of-man' -> 'extensions-of-man'
        'title' -> 'title'
    """
    match = re.match(r'^\d+(?:-\d+)?-(.+)$', dirname)
    return match.group(1) if match else dirname


def get_slide_order(slides_dir: Path, config: dict) -> list[str]:
    """Get ordered list of slide slugs.

    Priority:
    1. config['slide_order'] or config['slides'] if present - canonical order
    2. Numbered directories - use natural_sort_key() (backward compat)

    Returns:
        List of slide slugs in presentation order
    """
    # Check both 'slide_order' (preferred) and 'slides' (legacy)
    if 'slide_order' in config and config['slide_order']:
        return config['slide_order']
    if 'slides' in config and config['slides']:
        return config['slides']

    # Fallback: directory-based ordering (backward compatibility)
    slide_dirs = [d for d in slides_dir.iterdir() if d.is_dir()]
    slide_dirs.sort(key=lambda d: natural_sort_key(d.name))

    slugs = []
    for d in slide_dirs:
        slug = normalize_slug(d.name)
        slugs.append(slug)

    return slugs


def find_slide_dir(slides_dir: Path, slug: str) -> Path | None:
    """Find slide directory by slug, handling both semantic and numbered names.

    Handles:
    - Exact match: "title/"
    - Numbered match: "00-title/", "05-5-extensions-of-man/"

    Args:
        slides_dir: Directory containing slides
        slug: Semantic slug to search for

    Returns:
        Path to slide directory or None if not found
    """
    # Try exact match first
    exact = slides_dir / slug
    if exact.exists():
        return exact

    # Try numbered variants
    for d in slides_dir.iterdir():
        if d.is_dir():
            if normalize_slug(d.name) == slug:
                return d

    return None


def get_section_order(sections_dir: Path, config: dict) -> list[dict]:
    """Get ordered list of section metadata from essay config.

    Priority:
    1. config['sections'] if present - canonical order
    2. Directory scan (fallback, alphabetical)

    Returns:
        List of section dicts with at least 'slug' and 'level' keys
    """
    if 'sections' in config and config['sections']:
        sections = []
        for item in config['sections']:
            if isinstance(item, str):
                sections.append({'slug': item, 'level': 1})
            elif isinstance(item, dict):
                sections.append({
                    'slug': item.get('slug', item.get('name', '')),
                    'level': item.get('level', 1),
                    **item
                })
        return sections

    # Fallback: directory-based ordering (alphabetical)
    if not sections_dir.exists():
        return []

    section_dirs = sorted([d.name for d in sections_dir.iterdir() if d.is_dir()])
    return [{'slug': slug, 'level': 1} for slug in section_dirs]


def find_section_dir(sections_dir: Path, slug: str) -> Path | None:
    """Find section directory by slug.

    Args:
        sections_dir: Directory containing sections
        slug: Section slug to search for

    Returns:
        Path to section directory or None if not found
    """
    section_path = sections_dir / slug
    if section_path.exists() and section_path.is_dir():
        return section_path
    return None


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """
    Parse YAML frontmatter from markdown content.
    Returns (frontmatter_dict, body_content)
    """
    if not content.startswith('---'):
        return {}, content

    # Look for closing --- (followed by newline or end of file)
    end_match = re.search(r'\n---(?:\n|$)', content[3:])
    if not end_match:
        return {}, content

    end_idx = end_match.start() + 3
    frontmatter_str = content[3:end_idx]

    # Calculate body start - skip past the closing --- and any newline
    body_start = end_idx + 4  # +3 for initial offset, +4 for '\n---'
    if body_start < len(content) and content[body_start] == '\n':
        body_start += 1
    body = content[body_start:].strip() if body_start < len(content) else ''

    try:
        frontmatter = yaml.safe_load(frontmatter_str) or {}
    except yaml.YAMLError as e:
        print(f"Warning: Failed to parse frontmatter: {e}")
        frontmatter = {}

    return frontmatter, body


def load_file_content(path: Path, warn_missing: bool = False) -> str:
    """Reads a file and returns its content, handling missing files gracefully."""
    if not path.exists():
        if warn_missing:
            import sys
            print(f"Warning: File not found: {path}", file=sys.stderr)
        return ""
    return path.read_text().strip()


def load_config(presentation_path: Path) -> dict:
    """Load presentation config.yaml with error handling."""
    config_file = presentation_path / "config.yaml"
    if not config_file.exists():
        return {}

    try:
        return yaml.safe_load(config_file.read_text()) or {}
    except yaml.YAMLError as e:
        print(f"Error: Invalid YAML in {config_file}: {e}")
        return {}


def load_output_config(presentation_path: Path, output_type: str = "presentation") -> dict:
    """Load output-specific config.yaml, merged with root config.

    Looks for config in outputs/{output_type}/config.yaml first,
    falls back to root config.yaml for shared fields (name, title, audience).
    """
    root_config = load_config(presentation_path)

    # Try new structure first
    output_config_file = presentation_path / "outputs" / output_type / "config.yaml"
    if output_config_file.exists():
        try:
            output_config = yaml.safe_load(output_config_file.read_text()) or {}
            # Merge: output config overrides root config
            merged = {**root_config, **output_config}
            return merged
        except yaml.YAMLError as e:
            print(f"Error: Invalid YAML in {output_config_file}: {e}")
            return root_config

    # Fall back to root config (legacy structure)
    return root_config


def find_best_image_in_dir(outputs_dir: Path) -> Path | None:
    """Find best image in an outputs directory."""
    if not outputs_dir or not outputs_dir.exists():
        return None

    # Priority 1: selected.* images
    for ext in ['jpg', 'jpeg', 'png']:
        selected = outputs_dir / f"selected.{ext}"
        if selected.exists():
            return selected

    # Priority 2: Most recent generated image
    images = list(outputs_dir.glob("generated_*.*"))
    images = [p for p in images if p.suffix.lower() in ['.jpg', '.jpeg', '.png']]
    if images:
        images.sort(key=lambda p: p.name, reverse=True)
        return images[0]

    return None


def find_slide_image(slide_dir: Path) -> Path | None:
    """Find the primary image for a slide.

    Reads slide.md to find the primary image's selected path.
    """
    slide_md = slide_dir / "slide.md"
    if not slide_md.exists():
        return None

    content = slide_md.read_text()
    frontmatter, _ = parse_frontmatter(content)

    images = frontmatter.get('images', [])
    if not images:
        return None

    # Find primary image (first one with is_primary or just first one)
    primary = None
    for img in images:
        if img.get('is_primary', False):
            primary = img
            break
    if not primary:
        primary = images[0]

    # Get selected path
    selected = primary.get('selected')
    if selected:
        image_id = primary.get('id', 'main')
        selected_path = slide_dir / "images" / image_id / selected
        if selected_path.exists():
            return selected_path

    # Fall back to searching outputs
    image_id = primary.get('id', 'main')
    outputs_dir = slide_dir / "images" / image_id / "outputs"
    return find_best_image_in_dir(outputs_dir)


def load_slide(slide_dir: Path) -> dict | None:
    """Load slide.md frontmatter."""
    slide_md = slide_dir / "slide.md"
    if not slide_md.exists():
        return None

    content = slide_md.read_text()
    frontmatter, _ = parse_frontmatter(content)
    return frontmatter


def load_section(section_dir: Path) -> tuple[dict, str] | None:
    """Load section.md frontmatter and body.

    Returns:
        Tuple of (frontmatter_dict, body_content) or None if not found
    """
    section_md = section_dir / "section.md"
    if not section_md.exists():
        return None

    content = section_md.read_text()
    return parse_frontmatter(content)
