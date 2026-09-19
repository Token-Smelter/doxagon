#!/usr/bin/env python3
"""A real image-generation backend for the browser proof, behind the real argv.

This is not a stub inside the server: it is a separate executable the server
runs through `SubprocessImageGenerator`, which builds its command line with
`generation.generator_argv` — the same argv contract the legacy generator used.
Everything on the server side of the seam is therefore exercised for real:
prompt assembly, the reference closure, the subprocess invocation, the produced
file's media type, immutable asset admission, and the durable job record.

Like a hosted backend, it can refuse: it renders 16:9 only, and any other
framing exits non-zero so the failure lands on the job record as the backend's
own diagnostic. Only the pixels are synthetic, and they are derived from the
assembled prompt so one prompt always renders the same bytes.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

from tests.synthetic_vault import png  # noqa: E402

SUPPORTED_ASPECT_RATIO = "16:9"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt-file", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--image-size", required=True)
    parser.add_argument("--aspect-ratio", required=True)
    parser.add_argument("--source", action="append", default=[])
    arguments = parser.parse_args()

    if arguments.aspect_ratio != SUPPORTED_ASPECT_RATIO:
        print(
            f"this backend renders {SUPPORTED_ASPECT_RATIO} only; {arguments.aspect_ratio} was requested",
            file=sys.stderr,
        )
        return 2

    prompt = Path(arguments.prompt_file).read_bytes()
    # The colour is a function of the prompt, so the same request renders the
    # same bytes and a different request renders different ones.
    colour = (prompt[0] % 256, len(prompt) % 256, sum(prompt) % 256)
    output = Path(arguments.output) / "generated.png"
    output.write_bytes(png(colour))
    print(str(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
