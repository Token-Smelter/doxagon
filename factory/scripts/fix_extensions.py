#!/usr/bin/env python3
"""
Fix image file extensions based on actual file content.

Renames .png files that are actually JPEGs to .jpg
"""

import subprocess
from pathlib import Path


def get_actual_type(filepath: Path) -> str:
    """Use `file` command to determine actual image type."""
    result = subprocess.run(
        ["file", "-b", str(filepath)],
        capture_output=True,
        text=True
    )
    output = result.stdout.strip()
    if output.startswith("JPEG"):
        return "jpg"
    elif output.startswith("PNG"):
        return "png"
    return "unknown"


def main():
    project_root = Path(__file__).parent.parent
    slides_dir = project_root / "slides"

    renamed = 0

    for png_file in slides_dir.glob("**/output/*.png"):
        actual_type = get_actual_type(png_file)

        if actual_type == "jpg":
            new_path = png_file.with_suffix(".jpg")
            print(f"Renaming: {png_file.relative_to(project_root)} -> {new_path.name}")
            png_file.rename(new_path)
            renamed += 1
        elif actual_type == "unknown":
            print(f"Warning: Unknown type for {png_file}")

    print(f"\nRenamed {renamed} files")


if __name__ == "__main__":
    main()
