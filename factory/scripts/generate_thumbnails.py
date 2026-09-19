#!/usr/bin/env python3
"""
Generate Thumbnails for Web UI and LLM Feedback

Creates low-resolution thumbnails for slide images. Two modes:
1. Inline mode (default): Creates .thumb_* files next to originals for web UI
2. Lowres mode (--lowres): Creates separate directory for LLM feedback

Usage:
    python factory/scripts/generate_thumbnails.py --presentation NAME  # Inline thumbs for web UI
    python factory/scripts/generate_thumbnails.py --presentation NAME --lowres             # Separate dir for LLM
    python factory/scripts/generate_thumbnails.py --presentation NAME --max-dim 256        # Smaller thumbnails
"""

import argparse
from pathlib import Path

from utils import get_presentation_path

try:
    from PIL import Image
except ImportError:
    print("Error: Pillow is required. Install with: uv pip install Pillow")
    exit(1)


def generate_thumbnail(
    image_path: Path,
    output_path: Path,
    max_dimension: int = 800,
    quality: int = 70,
) -> Path | None:
    """
    Generate a low-resolution JPG thumbnail from an image.

    Args:
        image_path: Path to source image
        output_path: Path for output JPG
        max_dimension: Maximum width or height in pixels
        quality: JPEG quality (1-100)

    Returns:
        Path to generated thumbnail, or None if failed
    """
    try:
        with Image.open(image_path) as img:
            # Convert to RGB if necessary (for PNG with alpha)
            if img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')

            # Calculate new dimensions maintaining aspect ratio
            width, height = img.size
            if width > height:
                if width > max_dimension:
                    new_width = max_dimension
                    new_height = int(height * (max_dimension / width))
                else:
                    new_width, new_height = width, height
            else:
                if height > max_dimension:
                    new_height = max_dimension
                    new_width = int(width * (max_dimension / height))
                else:
                    new_width, new_height = width, height

            # Resize using high-quality downsampling
            resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

            # Ensure output directory exists
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # Save as JPEG
            resized.save(output_path, "JPEG", quality=quality, optimize=True)

            return output_path

    except Exception as e:
        print(f"  Error processing {image_path.name}: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(
        description="Generate thumbnails for web UI and LLM feedback",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--presentation", "-p",
        required=True,
        help="Presentation name",
    )
    parser.add_argument(
        "--max-dim", "-d",
        type=int,
        default=256,
        help="Maximum dimension (width or height) in pixels (default: 256 for inline, 800 for lowres)",
    )
    parser.add_argument(
        "--quality", "-q",
        type=int,
        default=70,
        help="JPEG quality 1-100 (default: 70)",
    )
    parser.add_argument(
        "--lowres",
        action="store_true",
        help="Output to separate lowres directory instead of inline",
    )
    parser.add_argument(
        "--output-dir",
        default="output/lowres",
        help="Output directory for lowres mode (default: output/lowres)",
    )

    args = parser.parse_args()

    # Resolve paths
    project_root = Path(__file__).parent.parent.parent  # doxagon/

    if args.lowres:
        # Legacy lowres mode - output to separate directory
        max_dim = args.max_dim if args.max_dim != 256 else 800
        slides_dir = get_presentation_path(args.presentation) / "outputs" / "presentation" / "slides"
        output_dir = project_root / args.output_dir

        if not slides_dir.exists():
            print(f"Error: Slides directory not found: {slides_dir}")
            return 1

        output_dir.mkdir(parents=True, exist_ok=True)

        # Find images - look in images/*/outputs/
        images = list(slides_dir.glob("**/images/*/outputs/*.png"))
        images = [p for p in images if not p.name.startswith(".thumb_")]
        print(f"Found {len(images)} images")

        total_generated = 0
        for image_path in sorted(images):
            slide_name = image_path.parent.parent.parent.parent.name
            output_filename = f"{slide_name}_{image_path.stem}.jpg"
            output_path = output_dir / output_filename

            if generate_thumbnail(image_path, output_path, max_dim, args.quality):
                total_generated += 1
                print(f"  {slide_name}/{image_path.name} -> {output_filename}")

        print(f"\nGenerated {total_generated} thumbnails in {output_dir}")
    else:
        # Inline mode - create .thumb_* files next to originals
        slides_dir = get_presentation_path(args.presentation) / "outputs" / "presentation" / "slides"

        if not slides_dir.exists():
            print(f"Error: Slides directory not found: {slides_dir}")
            return 1

        # Find images in images/*/outputs/
        images = list(slides_dir.glob("**/images/*/outputs/*.png"))
        images = [p for p in images if not p.name.startswith(".thumb_")]
        print(f"Found {len(images)} images in {args.presentation}")

        total_generated = 0
        total_skipped = 0

        for image_path in sorted(images):
            # Create inline thumbnail: .thumb_filename.jpg
            thumb_name = f".thumb_{image_path.stem}.jpg"
            thumb_path = image_path.parent / thumb_name

            # Skip if thumb exists and is newer than original
            if thumb_path.exists() and thumb_path.stat().st_mtime >= image_path.stat().st_mtime:
                total_skipped += 1
                continue

            if generate_thumbnail(image_path, thumb_path, args.max_dim, args.quality):
                total_generated += 1
                slide_name = image_path.parent.parent.parent.parent.name
                orig_kb = image_path.stat().st_size / 1024
                thumb_kb = thumb_path.stat().st_size / 1024
                print(f"  {slide_name}: {image_path.name} ({orig_kb:.0f}KB -> {thumb_kb:.0f}KB)")

        print(f"\nGenerated {total_generated} inline thumbnails ({total_skipped} skipped)")

    return 0


if __name__ == "__main__":
    exit(main())
