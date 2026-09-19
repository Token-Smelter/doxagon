#!/usr/bin/env python3
"""
Visual Prompt Generator

Assembles image generation prompts for slides using the bundle structure.

Slide structure:
    slides/{slug}/
    ├── slide.md                 # Content + image relationships
    └── images/{id}/
        ├── definition.md        # Visual description + styles
        ├── sources/             # Reference images
        └── outputs/             # Generated images

Usage:
    python factory/scripts/generate_visuals.py --presentation observatory --trace
    python factory/scripts/generate_visuals.py --presentation observatory --slide 14 --output
    python factory/scripts/generate_visuals.py --slide 14 --image main --output
"""

import argparse
import sys
from pathlib import Path

from utils import (
    get_presentation_path,
    get_presentation_output_paths,
    parse_frontmatter,
    load_file_content,
    normalize_slug,
)


def resolve_style_dependencies(style_path: str, styles_dir: Path, resolved: set = None) -> list[str]:
    """
    Recursively resolve style dependencies from frontmatter 'requires' field.
    Returns list of style paths in dependency order (dependencies first).
    """
    if resolved is None:
        resolved = set()

    if style_path in resolved:
        return []

    bundle_dir = styles_dir / style_path
    definition_file = bundle_dir / "definition.md"

    result = []

    if definition_file.exists():
        content = load_file_content(definition_file)
        frontmatter, _ = parse_frontmatter(content)
        requires = frontmatter.get('requires', [])

        # Resolve dependencies first (recursive)
        for req in requires:
            result.extend(resolve_style_dependencies(req, styles_dir, resolved))

    # Add self after dependencies
    if style_path not in resolved:
        result.append(style_path)
        resolved.add(style_path)

    return result


def load_style_bundle(style_path: str, styles_dir: Path) -> tuple[str, list[Path]]:
    """
    Load a style bundle (definition.md body + sources/ images).
    Frontmatter is parsed separately for dependency resolution.
    Returns (text_content, list_of_image_paths)
    """
    bundle_dir = styles_dir / style_path
    definition_file = bundle_dir / "definition.md"

    text_content = ""
    image_paths = []

    if definition_file.exists():
        content = load_file_content(definition_file)
        # Parse frontmatter but only use body for content
        _, body = parse_frontmatter(content)
        text_content = body
    else:
        print(f"Warning: Style definition not found: {definition_file}", file=sys.stderr)

    # Collect source images
    sources_dir = bundle_dir / "sources"
    if sources_dir.exists():
        for img in sources_dir.iterdir():
            if img.suffix.lower() in ['.png', '.jpg', '.jpeg', '.webp']:
                image_paths.append(img)

    return text_content, image_paths


def get_image_dirs(slide_dir: Path) -> list[tuple[str, Path]]:
    """
    Get all image directories for a slide.
    Returns list of (image_id, image_dir) tuples.
    """
    images_dir = slide_dir / "images"
    if not images_dir.exists() or not images_dir.is_dir():
        return []

    result = []
    for img_dir in sorted(images_dir.iterdir()):
        if img_dir.is_dir() and (img_dir / "definition.md").exists():
            result.append((img_dir.name, img_dir))
    return result


def construct_prompt(image_dir: Path, styles_dir: Path) -> tuple[str, list[Path], dict] | None:
    """
    Constructs the full generation prompt for an image directory.

    Returns (prompt_text, list_of_reference_images, generation_config) or None if no definition.md

    generation_config contains:
        - image_size: "1K", "2K", or "4K" (or None)
        - aspect_ratio: "16:9", "1:1", etc. (or None)
    """
    definition_file = image_dir / "definition.md"
    if not definition_file.exists():
        return None

    content = load_file_content(definition_file)
    frontmatter, visual_description = parse_frontmatter(content)

    styles = frontmatter.get('styles', [])
    custom_constraints = frontmatter.get('custom_constraints', '')
    config = frontmatter.get('config', {})

    # Collect all text and images
    all_text = []
    all_images = []

    # 0. Inject rendered_text rule (prevents instruction leakage into images)
    rendered_text_rule = """<rendered_text_rule>
CRITICAL: Only render text that appears inside <rendered_text> blocks.
Everything outside these blocks is instruction metadata - do NOT render it as visible text.
Do NOT add text that "seems appropriate" or render words from style descriptions.
</rendered_text_rule>"""
    all_text.append(rendered_text_rule)

    # 1. Load global constraints if they exist (including sources)
    global_constraints_dir = styles_dir / "constraints" / "layout"
    global_constraints = global_constraints_dir / "definition.md"
    if global_constraints.exists():
        content = load_file_content(global_constraints)
        _, body = parse_frontmatter(content)
        all_text.append(f"<global_constraints>\n{body}\n</global_constraints>")
        # Include source images from global constraints
        global_sources = global_constraints_dir / "sources"
        if global_sources.exists():
            for img in global_sources.iterdir():
                if img.suffix.lower() in ['.png', '.jpg', '.jpeg', '.webp']:
                    all_images.append(img)

    # 2. Load palette if diagram family is used
    if any('diagram' in s for s in styles):
        # Try palette-2025 first (observatory), then palette (observatory)
        palette_file = styles_dir / "global" / "palette-2025" / "definition.md"
        if not palette_file.exists():
            palette_file = styles_dir / "global" / "palette" / "definition.md"
        if palette_file.exists():
            content = load_file_content(palette_file)
            _, body = parse_frontmatter(content)
            all_text.append(f"<color_system>\n{body}\n</color_system>")

    # 3. Add custom constraints from image definition
    if custom_constraints:
        all_text.append(f"<image_constraints>\n{custom_constraints}\n</image_constraints>")

    # 4. Add visual description (from the image's definition.md body)
    all_text.append(f"<visual_description>\n{visual_description}\n</visual_description>")

    # 5. Load composed styles (with dependency resolution)
    # Resolve all dependencies from frontmatter 'requires' fields
    resolved_styles = []
    resolved_set = set()
    for style_path in styles:
        resolved_styles.extend(resolve_style_dependencies(style_path, styles_dir, resolved_set))

    style_texts = []
    for style_path in resolved_styles:
        bundle_dir = styles_dir / style_path
        if not (bundle_dir / "definition.md").exists():
            print(f"Error: Style not found: {style_path}", file=sys.stderr)
            print(f"  Expected: {bundle_dir / 'definition.md'}", file=sys.stderr)
            return None
        text, images = load_style_bundle(style_path, styles_dir)
        if text:
            style_texts.append(text)
        all_images.extend(images)

    if style_texts:
        style_block = "\n\n".join(style_texts)
        all_text.append(f"<style_definitions>\n{style_block}\n</style_definitions>")

    # 6. Add image-specific source images
    sources_dir = image_dir / "sources"
    if sources_dir.exists():
        for img in sources_dir.iterdir():
            if img.suffix.lower() in ['.png', '.jpg', '.jpeg', '.webp']:
                all_images.append(img)

    # 7. Add generation settings
    resolution = config.get('resolution', '2k')
    aspect_ratio = config.get('aspect_ratio', '16:9')

    # Fix YAML sexagesimal parsing (16:9 becomes 969 in YAML 1.1)
    if isinstance(aspect_ratio, int):
        # Convert back: N = a*60 + b → "a:b"
        aspect_ratio = f"{aspect_ratio // 60}:{aspect_ratio % 60}"

    all_text.append(f"""<generation_settings>
resolution: {resolution.upper()}
aspect_ratio: {aspect_ratio}
</generation_settings>""")

    # Enforce 14-image limit
    if len(all_images) > 14:
        print(f"Warning: {image_dir.name} has {len(all_images)} images, truncating to 14", file=sys.stderr)
        all_images = all_images[:14]

    full_prompt = "\n\n---\n\n".join(all_text)

    # Build generation config for API parameters
    # Convert resolution to API format (e.g., "4k" -> "4K")
    image_size = resolution.upper() if resolution else None
    generation_config = {
        "image_size": image_size,
        "aspect_ratio": aspect_ratio,
    }

    return full_prompt.strip(), all_images, generation_config


def main():
    parser = argparse.ArgumentParser(description="Generate visual prompts for slides.")
    parser.add_argument("--presentation", type=str, help="Presentation name (default: active)")
    parser.add_argument("--trace", action="store_true", help="Print the assembled prompts without generating.")
    parser.add_argument("--slide", type=str, help="Filter by slide number (e.g., '14')")
    parser.add_argument("--image", type=str, help="Filter by image ID (e.g., 'main', 'comparison')")
    parser.add_argument("--output", action="store_true", help="Write prompt to image's outputs directory")

    args = parser.parse_args()

    # Determine presentation
    presentation = args.presentation
    if not presentation:
        print("Error: No presentation specified and no active presentation set", file=sys.stderr)
        print("Use --presentation NAME", file=sys.stderr)
        sys.exit(1)

    presentation_path = get_presentation_path(presentation)
    if not presentation_path.exists():
        print(f"Error: Presentation not found: {presentation_path}", file=sys.stderr)
        sys.exit(1)

    # Get output paths (supports both new and legacy structure)
    paths = get_presentation_output_paths(presentation_path)
    slides_dir = paths['slides_dir']
    styles_dir = paths['styles_dir']

    # Find all slide directories
    slide_dirs = sorted([d for d in slides_dir.iterdir() if d.is_dir()])

    # Filter by slide if specified
    if args.slide:
        matched = None
        for d in slide_dirs:
            # Try number match: "14" -> "14-*" or exact position
            if d.name.startswith(f"{args.slide.zfill(2)}-"):
                matched = d
                break

            # Try slug match (both numbered and semantic)
            slug = normalize_slug(d.name)
            if slug == args.slide:
                matched = d
                break

        if matched:
            slide_dirs = [matched]
        else:
            print(f"No slide found matching '{args.slide}'")
            return

    for slide_dir in slide_dirs:
        # Get all images for this slide
        image_dirs = get_image_dirs(slide_dir)

        for image_id, image_dir in image_dirs:
            # Filter by image ID if specified
            if args.image and image_id != args.image:
                continue

            result = construct_prompt(image_dir, styles_dir)
            if result:
                prompt, images, gen_config = result

                # Determine display name
                display_name = f"{slide_dir.name}"
                if len(image_dirs) > 1 or image_id != 'main':
                    display_name = f"{slide_dir.name}/{image_id}"

                if args.output:
                    # Write to outputs directory
                    outputs_dir = image_dir / "outputs"
                    outputs_dir.mkdir(exist_ok=True)

                    # Write assembled prompt
                    prompt_file = outputs_dir / "assembled_prompt.md"
                    prompt_file.write_text(prompt)
                    print(f"Wrote prompt to: {prompt_file}")

                    # Write generation config JSON (for API parameters)
                    import json
                    config_data = {
                        "image_size": gen_config.get("image_size"),
                        "aspect_ratio": gen_config.get("aspect_ratio"),
                        "source_images": [str(img) for img in images],
                    }
                    config_file = outputs_dir / "generation_config.json"
                    config_file.write_text(json.dumps(config_data, indent=2))

                    if images:
                        print(f"  Reference images ({len(images)}): {', '.join(img.name for img in images)}")
                    if gen_config.get("image_size"):
                        print(f"  Image size: {gen_config['image_size']}, Aspect ratio: {gen_config.get('aspect_ratio', '16:9')}")
                else:
                    print(f"--- PROMPT FOR: {display_name} ---")
                    print(prompt)
                    if images:
                        print(f"\nReference images ({len(images)}): {', '.join(img.name for img in images)}")
                    if gen_config.get("image_size"):
                        print(f"Generation config: {gen_config}")
                    print("\n" + "="*60 + "\n")


if __name__ == "__main__":
    main()
