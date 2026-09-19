#!/usr/bin/env python3
"""
Populate a PowerPoint presentation with full-screen images and speaker notes.

Takes a template PPTX and fills it with:
- Full-screen images for each slide (from slide.md and images/{id}/)
- Speaker notes from slide.md

Slide structure:
    slides/{slug}/
    ├── slide.md                 # Content + image relationships
    └── images/{id}/
        └── outputs/             # Generated images

Usage:
    python factory/scripts/populate_pptx.py --presentation observatory
    python factory/scripts/populate_pptx.py --output my-presentation.pptx
"""

import argparse
import re
import sys
import yaml
from pathlib import Path
from PIL import Image
from pptx import Presentation
from pptx.util import Emu

from utils import (
    get_presentation_path,
    get_presentation_output_paths,
    load_output_config,
    natural_sort_key,
    parse_frontmatter,
    get_slide_order,
    find_slide_dir,
)


def load_slide_frontmatter(slide_dir: Path) -> dict:
    """Load frontmatter from slide.md."""
    slide_md = slide_dir / "slide.md"
    if not slide_md.exists():
        return {}

    content = slide_md.read_text()
    frontmatter, _ = parse_frontmatter(content)
    return frontmatter


def get_slide_title(slide_dir: Path) -> str | None:
    """Extract slide title from slide.md."""
    frontmatter = load_slide_frontmatter(slide_dir)
    text_data = frontmatter.get('text', {})
    return text_data.get('title')


def get_slide_subtitle(slide_dir: Path) -> str | None:
    """Extract slide subtitle from slide.md (if present in text.body)."""
    frontmatter = load_slide_frontmatter(slide_dir)
    text_data = frontmatter.get('text', {})
    body = text_data.get('body', '')
    # Look for subtitle pattern in body
    for line in body.split('\n'):
        if line.startswith('**Subtitle:**'):
            return line.replace('**Subtitle:**', '').strip()
    return None


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


def get_slide_image(slide_dir: Path) -> Path | None:
    """Get the image path for a slide.

    Reads slide.md to find the primary image's selected path.
    """
    frontmatter = load_slide_frontmatter(slide_dir)

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


def get_speaker_notes(slide_dir: Path) -> str:
    """Get speaker notes content from slide.md."""
    frontmatter = load_slide_frontmatter(slide_dir)
    notes = frontmatter.get('speaker_notes', '')
    # Clean up any header if present
    if notes.startswith('# Speaker Notes'):
        lines = notes.split('\n')[1:]
        notes = '\n'.join(lines)
    return notes.strip()


def add_full_screen_image(slide, image_path: Path, prs: Presentation):
    """Add an image to a slide, preserving aspect ratio and centering. Sends to back."""
    slide_width = prs.slide_width
    slide_height = prs.slide_height

    with Image.open(image_path) as img:
        img_width, img_height = img.size

    img_aspect = img_width / img_height
    slide_aspect = slide_width / slide_height

    if img_aspect > slide_aspect:
        width = slide_width
        height = int(slide_width / img_aspect)
    else:
        height = slide_height
        width = int(slide_height * img_aspect)

    left = (slide_width - width) // 2
    top = (slide_height - height) // 2

    picture = slide.shapes.add_picture(
        str(image_path),
        Emu(left),
        Emu(top),
        width=Emu(width),
        height=Emu(height)
    )

    # Send image to back
    sp_tree = picture._element.getparent()
    sp_tree.remove(picture._element)
    sp_tree.insert(2, picture._element)


def add_speaker_notes(slide, notes_text: str):
    """Add speaker notes to a slide."""
    notes_slide = slide.notes_slide
    notes_frame = notes_slide.notes_text_frame
    notes_frame.text = notes_text


def get_title_only_layout(prs: Presentation):
    """Find the 'Title Only' layout from the slide master."""
    for layout in prs.slide_layouts:
        if layout.name == 'Title Only':
            print(f"Found 'Title Only' layout")
            return layout

    for layout in prs.slide_layouts:
        placeholders = list(layout.placeholders)
        if len(placeholders) == 1:
            print(f"Using layout '{layout.name}' with single placeholder as Title Only")
            return layout

    for layout in prs.slide_layouts:
        if layout.name == 'Blank':
            print(f"Falling back to 'Blank' layout")
            return layout

    return prs.slide_layouts[0]


def populate_presentation(template_path: Path, output_path: Path, slides_dir: Path, config: dict):
    """Populate a presentation with images and speaker notes."""
    prs = Presentation(str(template_path))

    existing_slides = len(prs.slides)
    print(f"Template has {existing_slides} slide(s)")

    print("\nAvailable slide layouts:")
    for i, layout in enumerate(prs.slide_layouts):
        print(f"  {i}: {layout.name}")

    title_only_layout = get_title_only_layout(prs)
    title_slide_layout = prs.slides[0].slide_layout if existing_slides > 0 else title_only_layout

    # Remove all existing slides
    while len(prs.slides) > 0:
        rId = prs.slides._sldIdLst[0].rId
        prs.part.drop_rel(rId)
        del prs.slides._sldIdLst[0]

    # Get ordered slide slugs (config-based or directory-based fallback)
    slide_order = get_slide_order(slides_dir, config)

    print(f"Cleared existing slides, creating {len(slide_order)} new slides")

    # Process each slide
    for i, slug in enumerate(slide_order):
        slide_dir = find_slide_dir(slides_dir, slug)
        if not slide_dir:
            print(f"\nWARNING: Slide '{slug}' not found, skipping")
            continue

        print(f"\nProcessing slide {i}: {slide_dir.name}")

        layout = title_slide_layout if i == 0 else title_only_layout
        slide = prs.slides.add_slide(layout)

        # Get image path and add image FIRST (so it's behind title)
        image_path = get_slide_image(slide_dir)

        if image_path:
            print(f"  Adding image: {image_path.name}")
            add_full_screen_image(slide, image_path, prs)
        else:
            print(f"  WARNING: No image found for {slide_dir.name}")

        # Set slide title AFTER image
        title = get_slide_title(slide_dir)

        if i == 0:
            subtitle = get_slide_subtitle(slide_dir)
            for shape in slide.placeholders:
                if shape.placeholder_format.idx == 12 and title:
                    shape.text = title
                    print(f"  Title: {title}")
                elif shape.placeholder_format.idx == 14 and subtitle:
                    shape.text = subtitle
                    print(f"  Subtitle: {subtitle}")
        elif title and slide.shapes.title:
            slide.shapes.title.text = title
            print(f"  Title: {title}")

        # Get and add speaker notes
        notes = get_speaker_notes(slide_dir)
        if notes:
            print(f"  Adding speaker notes ({len(notes)} chars)")
            add_speaker_notes(slide, notes)
        else:
            print(f"  No speaker notes found")

    prs.save(str(output_path))
    print(f"\n✓ Saved presentation to {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Populate a PowerPoint presentation with images and speaker notes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        "--presentation",
        type=str,
        help="Presentation name (default: active presentation)"
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Output filename (default: {presentation}-populated.pptx)"
    )

    args = parser.parse_args()

    # Determine presentation
    presentation = args.presentation
    if not presentation:
        print("Error: No presentation specified")
        print("Use --presentation NAME")
        sys.exit(1)

    presentation_path = get_presentation_path(presentation)
    if not presentation_path.exists():
        print(f"Error: Presentation not found: {presentation_path}")
        sys.exit(1)

    # Get output paths (supports both new and legacy structure)
    paths = get_presentation_output_paths(presentation_path)
    slides_dir = paths['slides_dir']
    templates_dir = paths['templates_dir']

    if not slides_dir.exists():
        print(f"Error: Slides directory not found at {slides_dir}")
        sys.exit(1)

    # Load config for template name and slide ordering
    config = load_output_config(presentation_path, "presentation")
    template_name = config.get('template', 'template.pptx')
    template_path = templates_dir / template_name

    if not template_path.exists():
        print(f"Error: Template not found at {template_path}")
        sys.exit(1)

    # Determine output path
    if args.output:
        output_path = Path(args.output)
        if not output_path.is_absolute():
            output_path = presentation_path / args.output
    else:
        output_path = presentation_path / f"{presentation}-populated.pptx"

    populate_presentation(template_path, output_path, slides_dir, config)


if __name__ == "__main__":
    main()
