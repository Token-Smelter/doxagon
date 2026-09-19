#!/usr/bin/env python3
"""
Presentation Compiler

Compiles individual slide folders into a unified presentation:
- Markdown with speaker notes
- PowerPoint presentation
- Standard and low-res images

Slide structure:
    slides/{slug}/
    ├── slide.md                 # Content + image relationships
    └── images/{id}/
        ├── definition.md        # Visual description + styles
        ├── sources/             # Reference images
        └── outputs/             # Generated images

Outputs to timestamped build directories.

Usage:
    python factory/scripts/compile.py --presentation observatory
    python factory/scripts/compile.py --verbose
    python factory/scripts/compile.py --no-pptx
    python factory/scripts/compile.py --no-template   # Full-bleed images, no text

The --no-template flag creates a PPTX without a template file. This generates
slides with full-bleed images (100% fill, may crop to fit 16:9) and speaker
notes only - no title text overlays.
"""

import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

from utils import (
    get_presentation_path,
    get_presentation_output_paths,
    natural_sort_key,
    normalize_slug,
    get_slide_order,
    find_slide_dir,
    parse_frontmatter,
    find_slide_image,
    find_best_image_in_dir,
    load_output_config,
)


class SlideContent(NamedTuple):
    """Container for slide content."""
    number: str
    slug: str
    title: str
    speaker_notes: str
    source_image_path: Path | None


def clean_speaker_notes(notes: str) -> str:
    """Clean speaker notes content."""
    lines = []
    for line in notes.split('\n'):
        if line.startswith('# Speaker Notes'):
            continue
        lines.append(line)
    return '\n'.join(lines).strip()


def render_html_slide_image(slide_dir: Path, width: int = 1920, height: int = 1080) -> Path | None:
    """Render an HTML slide to PNG via headless Playwright. Returns path or None."""
    output_path = slide_dir / "images" / ".rendered_slide.png"
    render_script = Path(__file__).parent / "render_html_slide.py"

    if not render_script.exists():
        return None

    try:
        result = subprocess.run(
            [sys.executable, str(render_script),
             "--slide-dir", str(slide_dir),
             "--output", str(output_path),
             "--width", str(width), "--height", str(height)],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0 and output_path.exists():
            return output_path
    except (subprocess.TimeoutExpired, Exception):
        pass
    return None


def load_slide(slide_dir: Path, slide_num: int | None = None, slug: str | None = None) -> SlideContent | None:
    """Load content from a slide directory.

    Args:
        slide_dir: Path to slide directory
        slide_num: Slide number (from config position or directory name)
        slug: Semantic slug (from config or normalized directory name)

    Returns:
        SlideContent or None if invalid
    """
    if not slide_dir.is_dir():
        return None

    slide_md = slide_dir / "slide.md"
    if not slide_md.exists():
        return None

    # If number/slug not provided, extract from directory name (backward compat)
    if slide_num is None or slug is None:
        dirname = slide_dir.name
        parts = dirname.split('-', 1)
        if slide_num is None:
            number = parts[0] if parts else dirname
        else:
            number = str(slide_num)
        if slug is None:
            slug = parts[1] if len(parts) > 1 else dirname
    else:
        number = str(slide_num)

    content = slide_md.read_text()
    frontmatter, _ = parse_frontmatter(content)

    # Extract from frontmatter
    text_data = frontmatter.get('text', {})
    title = text_data.get('title', 'Untitled')
    speaker_notes = frontmatter.get('speaker_notes', '')

    # For HTML slides, try headless render first; fall back to display bundle
    if frontmatter.get('layout') == 'html':
        source_image = render_html_slide_image(slide_dir)
        if not source_image:
            source_image = find_slide_image(slide_dir)
    else:
        source_image = find_slide_image(slide_dir)

    return SlideContent(
        number=number,
        slug=slug,
        title=title,
        speaker_notes=speaker_notes,
        source_image_path=source_image,
    )


def generate_lowres_image(source: Path, dest: Path, max_width: int = 800) -> bool:
    """Generate a low-resolution version of an image using Pillow."""
    try:
        from PIL import Image
        dest.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(source) as img:
            if img.width > max_width:
                ratio = max_width / img.width
                new_height = int(img.height * ratio)
                img_resized = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
                img_resized.save(dest, quality=75, optimize=True)
            else:
                shutil.copy2(source, dest)
        return True
    except ImportError:
        shutil.copy2(source, dest)
        return True


def compile_presentation(
    slides_dir: Path,
    config: dict,
    build_dir: Path,
    verbose: bool = False,
    include_speaker_notes: bool = True,
    include_images: bool = True,
) -> str:
    """Compile all slides into a single markdown document with images."""

    if include_images:
        img_standard_dir = build_dir / "img" / "standard"
        img_lowres_dir = build_dir / "img" / "lowres"
        img_standard_dir.mkdir(parents=True, exist_ok=True)
        img_lowres_dir.mkdir(parents=True, exist_ok=True)

    output_lines = []

    # Load title from config
    title = config.get('title', 'Untitled Presentation')
    output_lines.append(f"# {title}\n")
    output_lines.append("---\n")

    # Get ordered slide slugs (config-based or directory-based fallback)
    slide_order = get_slide_order(slides_dir, config)

    for slide_num, slug in enumerate(slide_order, 1):
        slide_dir = find_slide_dir(slides_dir, slug)
        if not slide_dir:
            if verbose:
                print(f"  WARNING: Slide '{slug}' not found, skipping")
            continue

        slide = load_slide(slide_dir, slide_num=slide_num, slug=slug)
        if not slide:
            continue

        if verbose:
            print(f"  Processing slide {slide.number}: {slide.title}")

        # Slide header
        output_lines.append(f"\n## Slide {slide.number}: {slide.title}\n")

        # Annotate HTML slides
        slide_fm_content = (slide_dir / "slide.md").read_text()
        slide_fm, _ = parse_frontmatter(slide_fm_content)
        if slide_fm.get('layout') == 'html':
            images_fm = slide_fm.get('images', [])
            bundle_count = len([img for img in images_fm if isinstance(img, dict)])
            output_lines.append(f"\n*[Animated HTML slide — {bundle_count} image bundle{'s' if bundle_count != 1 else ''}]*\n")

        # Handle image
        if include_images and slide.source_image_path and slide.source_image_path.exists():
            img_filename = f"slide-{slide.number}.{slide.source_image_path.suffix.lstrip('.')}"

            # Copy standard image
            standard_dest = img_standard_dir / img_filename
            shutil.copy2(slide.source_image_path, standard_dest)

            # Generate low-res image
            lowres_dest = img_lowres_dir / img_filename
            generate_lowres_image(slide.source_image_path, lowres_dest)

            if verbose:
                print(f"    Image: {slide.source_image_path.name} -> {img_filename}")

            output_lines.append(f"\n![{slide.title}](img/standard/{img_filename})\n")
        elif include_images and verbose:
            print(f"    WARNING: No image found")

        # Speaker notes
        if include_speaker_notes and slide.speaker_notes:
            notes = clean_speaker_notes(slide.speaker_notes)
            if notes:
                quoted_notes = '\n'.join(f'> {line}' if line.strip() else '>' for line in notes.split('\n'))
                output_lines.append(f"\n{quoted_notes}\n")

        output_lines.append("\n---\n")

    return '\n'.join(output_lines)


def build_pptx(
    slides_dir: Path,
    template_path: Path | None,
    output_path: Path,
    verbose: bool = False,
) -> bool:
    """Build PowerPoint presentation from slides.

    If template_path is None, creates a presentation from scratch with
    full-bleed images and speaker notes only.
    """
    try:
        from PIL import Image
        from pptx import Presentation
        from pptx.util import Emu, Inches
    except ImportError:
        print("  WARNING: python-pptx not installed, skipping PPTX generation")
        return False

    # Create presentation from template or from scratch
    if template_path and template_path.exists():
        prs = Presentation(str(template_path))
    else:
        if template_path:
            print(f"  INFO: Template not found at {template_path}, creating from scratch")
        prs = Presentation()
        # Set 16:9 aspect ratio (default is 4:3)
        prs.slide_width = Inches(13.333)
        prs.slide_height = Inches(7.5)

    # Determine if we're in "simple" mode (no template)
    simple_mode = not (template_path and template_path.exists())

    # Get ordered slide slugs (config-based or directory-based fallback)
    presentation_path = slides_dir.parent.parent.parent  # slides_dir is outputs/presentation/slides
    config = load_output_config(presentation_path, "presentation")
    slide_order = get_slide_order(slides_dir, config)

    # Find appropriate layouts
    if simple_mode:
        # Use blank layout for all slides in simple mode
        blank_layout = None
        for layout in prs.slide_layouts:
            if layout.name == 'Blank':
                blank_layout = layout
                break
        if not blank_layout:
            blank_layout = prs.slide_layouts[6] if len(prs.slide_layouts) > 6 else prs.slide_layouts[0]
        title_only_layout = blank_layout
        title_slide_layout = blank_layout
    else:
        # Find Title Only layout
        title_only_layout = None
        for layout in prs.slide_layouts:
            if layout.name == 'Title Only':
                title_only_layout = layout
                break
        if not title_only_layout:
            title_only_layout = prs.slide_layouts[0]

        # Get title slide layout
        title_slide_layout = prs.slides[0].slide_layout if len(prs.slides) > 0 else title_only_layout

    # Clear existing slides
    while len(prs.slides) > 0:
        rId = prs.slides._sldIdLst[0].rId
        prs.part.drop_rel(rId)
        del prs.slides._sldIdLst[0]

    # Process each slide
    for slide_num, slug in enumerate(slide_order, 1):
        slide_dir = find_slide_dir(slides_dir, slug)
        if not slide_dir:
            if verbose:
                print(f"    WARNING: Slide '{slug}' not found, skipping")
            continue

        slide = load_slide(slide_dir, slide_num=slide_num, slug=slug)
        if not slide:
            continue

        i = slide_num - 1  # 0-indexed for layout selection
        if verbose:
            print(f"    PPTX slide {slide_num}: {slide.title}")

        layout = title_slide_layout if i == 0 else title_only_layout
        pptx_slide = prs.slides.add_slide(layout)

        # Add image
        if slide.source_image_path and slide.source_image_path.exists():
            with Image.open(slide.source_image_path) as img:
                img_width, img_height = img.size

            img_aspect = img_width / img_height
            slide_aspect = prs.slide_width / prs.slide_height

            if simple_mode:
                # Full bleed: scale image to cover entire slide (may crop)
                if img_aspect > slide_aspect:
                    # Image is wider - scale by height, crop width
                    height = prs.slide_height
                    width = int(prs.slide_height * img_aspect)
                else:
                    # Image is taller - scale by width, crop height
                    width = prs.slide_width
                    height = int(prs.slide_width / img_aspect)
            else:
                # Contain: scale image to fit within slide (letterbox)
                if img_aspect > slide_aspect:
                    width = prs.slide_width
                    height = int(prs.slide_width / img_aspect)
                else:
                    height = prs.slide_height
                    width = int(prs.slide_height * img_aspect)

            left = (prs.slide_width - width) // 2
            top = (prs.slide_height - height) // 2

            picture = pptx_slide.shapes.add_picture(
                str(slide.source_image_path),
                Emu(left), Emu(top),
                width=Emu(width), height=Emu(height)
            )
            # Send to back
            sp_tree = picture._element.getparent()
            sp_tree.remove(picture._element)
            sp_tree.insert(2, picture._element)

        # Set title (skip in simple mode - no text placeholders)
        if not simple_mode:
            if i == 0:
                for shape in pptx_slide.placeholders:
                    if shape.placeholder_format.idx == 12:
                        shape.text = slide.title
            elif pptx_slide.shapes.title:
                pptx_slide.shapes.title.text = slide.title

        # Add speaker notes
        if slide.speaker_notes:
            notes = clean_speaker_notes(slide.speaker_notes)
            if notes:
                notes_slide = pptx_slide.notes_slide
                notes_slide.notes_text_frame.text = notes

    prs.save(str(output_path))
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Compile presentation to timestamped build directory",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        "--presentation",
        type=str,
        help="Presentation name (default: active presentation)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output"
    )
    parser.add_argument(
        "--no-pptx",
        action="store_true",
        help="Skip PowerPoint generation"
    )
    parser.add_argument(
        "--no-speaker-notes",
        action="store_true",
        help="Exclude speaker notes from output"
    )
    parser.add_argument(
        "--no-images",
        action="store_true",
        help="Skip image copying (text-only output)"
    )
    parser.add_argument(
        "--include-style-ref",
        action="store_true",
        help="Include global style reference document in build"
    )
    parser.add_argument(
        "--no-template",
        action="store_true",
        help="Generate PPTX without a template (full-bleed images + speaker notes only)"
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

    # Get output paths (supports both new and legacy structure)
    paths = get_presentation_output_paths(presentation_path)
    slides_dir = paths['slides_dir']
    templates_dir = paths['templates_dir']
    base_build_dir = paths['build_dir']

    if not slides_dir.exists():
        print(f"Error: Slides directory not found: {slides_dir}")
        return 1

    # Load config (merges root + output-specific)
    config = load_output_config(presentation_path, "presentation")

    # Create timestamped build directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    build_dir = base_build_dir / timestamp

    print(f"Building presentation '{presentation}' to: {build_dir}")
    if args.verbose:
        print(f"Slides source: {slides_dir}")

    # Compile
    include_speaker_notes = not args.no_speaker_notes
    include_images = not args.no_images

    content = compile_presentation(
        slides_dir=slides_dir,
        config=config,
        build_dir=build_dir,
        verbose=args.verbose,
        include_speaker_notes=include_speaker_notes,
        include_images=include_images,
    )

    # Write markdown
    output_path = build_dir / "presentation.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content)

    # Write low-res markdown version (only if images included)
    if include_images:
        lowres_content = content.replace("img/standard/", "img/lowres/")
        lowres_path = build_dir / "presentation-lowres.md"
        lowres_path.write_text(lowres_content)

    # Copy global style reference if requested
    if args.include_style_ref:
        styles_dir = slides_dir.parent / "styles"
        style_readme = styles_dir / "README.md"
        if style_readme.exists():
            style_dest = build_dir / "style-reference.md"
            shutil.copy2(style_readme, style_dest)
            if args.verbose:
                print(f"  Style reference: {style_dest}")
        else:
            print(f"  WARNING: Style reference not found at {style_readme}")

    # Count slides
    slide_count = len([d for d in slides_dir.iterdir() if d.is_dir()])

    print(f"Markdown: {output_path}")
    if include_images:
        print(f"Markdown (low-res): {lowres_path}")
        print(f"Images: {build_dir / 'img'}")

    # Build PPTX
    if not args.no_pptx:
        if args.no_template:
            template_path = None
        else:
            template_name = config.get('template', 'template.pptx')
            template_path = templates_dir / template_name
        pptx_output = build_dir / "presentation.pptx"
        print(f"Building PPTX{'  (no template - full-bleed mode)' if args.no_template else ''}...")
        if build_pptx(slides_dir, template_path, pptx_output, args.verbose):
            print(f"PPTX: {pptx_output}")

    print(f"Total slides: {slide_count}")

    return 0


if __name__ == "__main__":
    exit(main())
