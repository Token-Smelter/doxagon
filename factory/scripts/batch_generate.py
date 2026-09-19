#!/usr/bin/env python3
"""Batch generate images for all slides in a presentation.

Assembles prompts and generates images for multiple slides in parallel using
the Terminal Native style system and Vertex AI Gemini 3 Pro Image Preview.

Usage:
    python3 factory/scripts/batch_generate.py --presentation observatory
    python3 factory/scripts/batch_generate.py --presentation observatory --start 10 --end 20
    python3 factory/scripts/batch_generate.py --presentation observatory --parallel 5

Options:
    --presentation  Required. Name of the presentation (matches theses/{name}/)
    --parallel      Number of concurrent workers (default: 3, max recommended: 5)
    --start         Start from slide number (1-indexed, default: 1)
    --end           End at slide number (default: all slides)

Requirements:
    - GCP authentication: run `gcloud auth login` before use
    - Virtual environment: run from project root with venv activated

The script:
    1. Reads slide order from config.yaml
    2. For each slide, runs generate_visuals.py to assemble the prompt
    3. Runs generate_image_vertex.py to generate the image via Vertex AI
    4. Reports success/failure summary at completion
"""

import argparse
import subprocess
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import yaml


def log(message: str) -> None:
    """Print with immediate flush for real-time output."""
    print(message, flush=True)


def get_project_root() -> Path:
    """Get the project root directory."""
    return Path(__file__).parent.parent.parent


def load_presentation_config(presentation: str) -> dict:
    """Load presentation config.yaml."""
    root = get_project_root()
    config_path = root / "theses" / presentation / "outputs" / "presentation" / "config.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def assemble_slide(presentation: str, slide_num: int) -> Path | None:
    """Run assembly for a single slide, return outputs dir if successful."""
    root = get_project_root()

    result = subprocess.run(
        [
            sys.executable,
            str(root / "factory" / "scripts" / "generate_visuals.py"),
            "--presentation", presentation,
            "--slide", str(slide_num),
            "--output"
        ],
        capture_output=True,
        text=True,
        cwd=root
    )

    if result.returncode != 0:
        log(f"  Assembly failed for slide {slide_num}: {result.stderr}")
        return None

    # Parse output to find the outputs directory
    for line in result.stdout.split('\n'):
        if 'outputs/' in line or 'assembled_prompt.md' in line:
            # Extract the path
            if 'Wrote:' in line:
                path = line.split('Wrote:')[-1].strip()
                return Path(path).parent

    return None


def generate_image(outputs_dir: Path, slide_num: int) -> bool:
    """Generate image from assembled prompt."""
    root = get_project_root()
    prompt_file = outputs_dir / "assembled_prompt.md"

    if not prompt_file.exists():
        log(f"  No prompt file for slide {slide_num}")
        return False

    result = subprocess.run(
        [
            "uv", "run",
            str(root / "factory" / "scripts" / "generate_image_vertex.py"),
            "--prompt-file", str(prompt_file),
            "--output", str(outputs_dir)
        ],
        capture_output=True,
        text=True,
        cwd=root
    )

    if result.returncode != 0:
        log(f"  Generation failed for slide {slide_num}: {result.stderr}")
        return False

    return True


def process_slide(presentation: str, slide_num: int, slide_slug: str) -> tuple[int, str, bool]:
    """Process a single slide: assemble and generate."""
    log(f"[{slide_num}] {slide_slug}: Assembling...")

    root = get_project_root()
    outputs_dir = root / "theses" / presentation / "outputs" / "presentation" / "slides" / slide_slug / "images" / "main" / "outputs"

    # Ensure outputs directory exists
    outputs_dir.mkdir(parents=True, exist_ok=True)

    # Run assembly - use slug name, not number
    result = subprocess.run(
        [
            sys.executable,
            str(root / "factory" / "scripts" / "generate_visuals.py"),
            "--presentation", presentation,
            "--slide", slide_slug,
            "--output"
        ],
        capture_output=True,
        text=True,
        cwd=root
    )

    if result.returncode != 0:
        log(f"[{slide_num}] {slide_slug}: Assembly FAILED")
        return (slide_num, slide_slug, False)

    log(f"[{slide_num}] {slide_slug}: Generating image...")

    prompt_file = outputs_dir / "assembled_prompt.md"
    if not prompt_file.exists():
        log(f"[{slide_num}] {slide_slug}: No prompt file found")
        return (slide_num, slide_slug, False)

    # Run generation
    result = subprocess.run(
        [
            "uv", "run",
            str(root / "factory" / "scripts" / "generate_image_vertex.py"),
            "--prompt-file", str(prompt_file),
            "--output", str(outputs_dir)
        ],
        capture_output=True,
        text=True,
        cwd=root
    )

    if result.returncode != 0:
        log(f"[{slide_num}] {slide_slug}: Generation FAILED - {result.stderr[:200]}")
        return (slide_num, slide_slug, False)

    log(f"[{slide_num}] {slide_slug}: SUCCESS")
    return (slide_num, slide_slug, True)


def main():
    parser = argparse.ArgumentParser(description="Batch generate images for presentation slides")
    parser.add_argument("--presentation", required=True, help="Presentation name")
    parser.add_argument("--parallel", type=int, default=3, help="Number of parallel workers (default: 3)")
    parser.add_argument("--start", type=int, default=1, help="Start from slide number")
    parser.add_argument("--end", type=int, default=None, help="End at slide number")
    args = parser.parse_args()

    config = load_presentation_config(args.presentation)
    slides = config.get("slide_order", config.get("slides", []))

    if not slides:
        log("No slides found in config")
        return 1

    # Filter slides by range
    end = args.end or len(slides)
    slide_range = [(i+1, slug) for i, slug in enumerate(slides) if args.start <= i+1 <= end]

    log(f"Processing {len(slide_range)} slides with {args.parallel} workers...")
    log("")

    results = []

    with ThreadPoolExecutor(max_workers=args.parallel) as executor:
        futures = {
            executor.submit(process_slide, args.presentation, num, slug): (num, slug)
            for num, slug in slide_range
        }

        for future in as_completed(futures):
            result = future.result()
            results.append(result)

    # Summary
    log("")
    log("=" * 50)
    log("SUMMARY")
    log("=" * 50)

    successes = [r for r in results if r[2]]
    failures = [r for r in results if not r[2]]

    log(f"Successful: {len(successes)}/{len(results)}")
    if failures:
        log("Failed slides:")
        for num, slug, _ in sorted(failures):
            log(f"  [{num}] {slug}")

    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
