"""Check compositing prerequisites, not the semantic correctness of a cutout."""

import argparse
from hashlib import sha256
import json
from pathlib import Path

from PIL import Image


def inspect(path: Path, output: Path | None = None) -> dict:
    with Image.open(path) as original:
        image = original.convert("RGBA")
    alpha = image.getchannel("A")
    low, high = alpha.getextrema()
    report = {
        "path": str(path),
        "sha256": sha256(path.read_bytes()).hexdigest(),
        "size": list(image.size),
        "alpha_extrema": [low, high],
        "ink_bounds": alpha.getbbox(),
        "ok": low == 0 and high > 0,
        "requires_visual_review": True,
    }
    if output:
        output.mkdir(parents=True, exist_ok=False)
        for name, color in [("light", "#f5ecdb"), ("dark", "#0c2531")]:
            plate = Image.new("RGBA", image.size, color)
            plate.alpha_composite(image)
            plate.convert("RGB").save(output / f"{name}.png")
        (output / "alpha.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--output", type=Path, help="New directory for two contrast previews and the report")
    args = parser.parse_args()
    report = inspect(args.image, args.output)
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["ok"] else 1)
