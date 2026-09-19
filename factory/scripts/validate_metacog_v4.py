#!/usr/bin/env python3
"""Validate canonical Metacog v4 deck structure and bridge contracts."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
PRESENTATION = ROOT / "theses/metacog/outputs/presentation"
SLIDES_DIR = PRESENTATION / "slides"
EXPECTED_STEPS = [4, 3, 6, 6, 5, 7, 4, 4, 6, 5, 4, 5, 4, 4, 6, 8, 4, 5, 3, 4, 4, 0, 4, 5]
RETIRED = [
    "volcano",
    "eruption",
    "lava-lamp",
    "rivers uphill",
    "execution is free",
    "execution is zero",
    "molten makes the mold",
    "notes from the token smelter",
]


def frontmatter(path: Path) -> dict:
    parts = path.read_text().split("---", 2)
    if len(parts) != 3:
        raise AssertionError(f"missing YAML frontmatter: {path}")
    return yaml.safe_load(parts[1])


def main() -> None:
    config = yaml.safe_load((PRESENTATION / "config.yaml").read_text())
    slugs = config["slides"]
    physical = sorted(path.name for path in SLIDES_DIR.iterdir() if path.is_dir())
    assert len(slugs) == 24, f"expected 24 configured slides, got {len(slugs)}"
    assert len(set(slugs)) == 24, "configured slide slugs are not unique"
    assert sorted(slugs) == physical, "config slugs and physical directories differ"
    assert len(config["acts"]) == 6, "expected six acts"

    # Retired-material scan covers audience-facing slide content, not the config's
    # explicit prohibition list.
    all_text = ""
    image_refs = 0
    for index, (slug, expected_steps) in enumerate(zip(slugs, EXPECTED_STEPS, strict=True), 1):
        directory = SLIDES_DIR / slug
        assert slug.startswith(f"{index:02d}-"), f"wrong numeric prefix: {slug}"
        metadata = frontmatter(directory / "slide.md")
        html = (directory / "slide.html").read_text()
        all_text += "\n" + html.lower() + "\n" + (directory / "slide.md").read_text().lower()

        assert metadata["layout"] == "html", f"{slug}: layout must be html"
        assert metadata["animation"] == "manual", f"{slug}: presenter beats must be manual"
        assert metadata.get("speaker_notes", "").strip(), f"{slug}: missing speaker notes"
        assert html.strip().lower().startswith("<!doctype html>"), f"{slug}: not standalone HTML"

        declaration = re.search(r"const total=(\d+);\s*dox\.slide\.steps\(total\)", html)
        assert declaration, f"{slug}: missing dox.slide.steps declaration"
        declared = int(declaration.group(1))
        assert declared == expected_steps, f"{slug}: expected {expected_steps} steps, got {declared}"
        data_steps = [int(value) for value in re.findall(r'data-step="(\d+)"', html)]
        assert not data_steps or max(data_steps) <= declared, f"{slug}: reveal exceeds declared steps"

        images = {image["id"]: image for image in metadata.get("images", [])}
        for image_id in re.findall(r'data-image-id="([^"]+)"', html):
            image_refs += 1
            assert image_id in images, f"{slug}: unregistered image ID {image_id}"
            selected = images[image_id].get("selected")
            assert selected, f"{slug}/{image_id}: no selected asset"
            assert (directory / "images" / image_id / selected).is_file(), (
                f"{slug}/{image_id}: selected asset does not exist"
            )
        if index == 22:
            assert "data-image-id" not in html, "slide 22 must remain clean and dead"
        else:
            assert 'data-image-id="ink"' in html, f"{slug}: missing registered real ink texture"

    for phrase in RETIRED:
        assert phrase not in all_text, f"retired material found: {phrase}"

    critical = {
        "14-pour-reversal": ["COGNITION:", "SCARCE", "ABUNDANT / CHEAP", "MIND CARVES THE MOLD"],
        "16-deep-research": ["TARGET", "EVIDENCE", "LIE", "DONE", "INK / CITRINITAS"],
        "18-play": ["FIRE ISN’T WHAT NEVER FEELS HARD", "IT’S WHAT GIVES SOMETHING BACK"],
        "20-essay-judge": ["GOOD ≠ WORTH DOING"],
        "21-wanter": ["THAT’S THE WANTER", "THAT’S THE GOLD"],
    }
    for slug, phrases in critical.items():
        html = (SLIDES_DIR / slug / "slide.html").read_text()
        for phrase in phrases:
            assert phrase in html, f"{slug}: missing critical beat {phrase}"

    print(f"PASS: 24 unique HTML slides / 6 acts / {image_refs} resolved image references")
    print("PASS: bridge steps match storyboard (slide 14 = 4; slide 22 = 0)")
    print("PASS: critical v4 beats, real ink texture, and retired-material exclusions")


if __name__ == "__main__":
    main()
