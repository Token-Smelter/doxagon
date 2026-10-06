#!/usr/bin/env python3
"""Synthetic-vault conformance fixture. No image model and no prompt interpretation.

The prompt hash only selects which code-drawn component to emit, so N requests
yield distinguishable test images without pretending to follow instructions.
"""

import argparse
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import sys

from PIL import Image

from build_sample import COMPONENTS, ROOT, fixture

if sys.argv[1:] == ["--capabilities"]:
    print(
        json.dumps(
            {
                "schema": "doxagon.provider-capabilities/1",
                "max_references": 2,
                "resolutions": ["1K"],
                "aspect_ratios": ["1:1"],
                "model": "motion-fixture-no-generation",
                "text_rendering": False,
            }
        )
    )
    raise SystemExit(0)
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--prompt-file", required=True, type=Path)
parser.add_argument("--output", required=True, type=Path)
parser.add_argument("--image-size", choices=["1K"], required=True)
parser.add_argument("--aspect-ratio", choices=["1:1"], required=True)
parser.add_argument("--source", type=Path, action="append", default=[])
args = parser.parse_args()
digest = sha256(args.prompt_file.read_bytes()).digest()
if len(args.source) > 2:
    parser.error("At most two references")
for source in args.source:
    source.read_bytes()
profile = json.loads((ROOT / "samples/profiles.json").read_text())["studio"]
component = COMPONENTS[digest[0] % len(COMPONENTS)]
image = Image.open(BytesIO(fixture(profile, component))).resize((1024, 1024), Image.Resampling.LANCZOS)
image.save(args.output / "synthetic-fixture.png")
print(f"Synthetic {component} fixture; no image generation performed.", file=sys.stderr)
