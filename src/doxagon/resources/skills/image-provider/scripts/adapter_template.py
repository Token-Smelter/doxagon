#!/usr/bin/env python3
"""Doxagon image-provider adapter template.

Copy to ~/.doxagon/providers/<name>, make it executable, and implement
`generate`. Everything else here is the contract in docs/image-providers.md:
argument parsing, --capabilities, verbatim prompt bytes, mandates the
provider cannot honor, and output into the given directory.

Keep credentials in ~/.doxagon/providers/<name>.env; never print them.
"""

import argparse
import json
import os
import sys
from pathlib import Path

NAME = Path(__file__).name
# Narrow these to what the provider really supports. Values must be subsets of
# the platform's: resolutions 1K/2K/4K; max_references at most 14.
CAPABILITIES = {
    "schema": "doxagon.provider-capabilities/1",
    "max_references": 0,
    "resolutions": ["1K"],
    "aspect_ratios": ["1:1"],
    "model": "set-me",
    "text_rendering": False,
}


def load_env() -> None:
    env_file = Path.home() / ".doxagon" / "providers" / f"{NAME}.env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and not key.strip().startswith("#"):
                os.environ.setdefault(key.strip(), value.strip().strip('"'))


def generate(prompt: str, references: list[Path], image_size: str, aspect_ratio: str, output: Path) -> None:
    """Send `prompt` unchanged to the provider and write one image into `output`.

    Raise on any failure. If the provider's API rewrites or truncates the
    prompt, detect it and raise; do not repair it.
    """
    raise NotImplementedError("implement generate() for your provider")


def main() -> int:
    if sys.argv[1:] == ["--capabilities"]:
        print(json.dumps(CAPABILITIES))
        return 0
    parser = argparse.ArgumentParser(prog=NAME)
    parser.add_argument("--prompt-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--image-size", required=True, choices=["1K", "2K", "4K"])
    parser.add_argument("--aspect-ratio", required=True)
    parser.add_argument("--source", type=Path, action="append", default=[])
    args = parser.parse_args()

    if args.image_size not in CAPABILITIES["resolutions"]:
        print(f"{NAME}: image size {args.image_size} is not supported", file=sys.stderr)
        return 2
    if args.aspect_ratio not in CAPABILITIES["aspect_ratios"]:
        print(f"{NAME}: aspect ratio {args.aspect_ratio} is not supported", file=sys.stderr)
        return 2
    if len(args.source) > CAPABILITIES["max_references"]:
        print(f"{NAME}: {len(args.source)} references exceed the maximum", file=sys.stderr)
        return 2

    load_env()
    try:
        generate(args.prompt_file.read_text(encoding="utf-8"), args.source,
                 args.image_size, args.aspect_ratio, args.output)
    except Exception as error:  # report, never leak: the message must not contain credentials
        print(f"{NAME}: {type(error).__name__}: {str(error)[:300]}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
