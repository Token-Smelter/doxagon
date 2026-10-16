#!/usr/bin/env python3
"""Reference Doxagon image adapter for the Gemini API. Needs a Gemini API key.

Install:   dox provider install gemini     (copies this to ~/.doxagon/providers/gemini)
Key:       GEMINI_API_KEY=... in ~/.doxagon/providers/gemini.env
           (create one at https://aistudio.google.com/apikey; generation is billed to it)
Select:    dox provider use gemini

Optional settings in the same .env file:
  GEMINI_IMAGE_MODEL  model id; image models are renamed often, so check
                      Google's current list if the default stops working
  GEMINI_API_BASE     API root, for proxies and tests

Contract: docs/image-providers.md. Standard library only; the key is sent in a
header, never in the URL, and never printed.
"""

import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

NAME = Path(__file__).name.removesuffix(".py")
DEFAULT_MODEL = "gemini-3.1-flash-image-preview"
DEFAULT_BASE = "https://generativelanguage.googleapis.com/v1beta"
RESOLUTIONS = ["1K", "2K", "4K"]
# Gemini accepts more ratios; capabilities may only name ones the platform uses.
ASPECT_RATIOS = ["1:1", "2:3", "3:2", "4:3", "9:16", "16:9"]
MAX_REFERENCES = 14
MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
SUFFIX = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}


def load_env() -> None:
    env_file = Path.home() / ".doxagon" / "providers" / f"{NAME}.env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() and not key.strip().startswith("#"):
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def fail(message: str, code: int = 1) -> int:
    print(f"{NAME}: {message}", file=sys.stderr)
    return code


def parse(argv: list[str]) -> dict:
    args: dict = {"source": []}
    flags = {"--prompt-file": "prompt_file", "--output": "output", "--image-size": "image_size",
             "--aspect-ratio": "aspect_ratio"}
    items = iter(argv)
    for arg in items:
        value = next(items, None)
        if value is None:
            raise ValueError(f"{arg} needs a value")
        if arg == "--source":
            args["source"].append(Path(value))
        elif arg in flags:
            args[flags[arg]] = value
        else:
            raise ValueError(f"unknown argument {arg}")
    missing = [flag for flag, key in flags.items() if key not in args]
    if missing:
        raise ValueError(f"missing {', '.join(missing)}")
    return args


def generate(args: dict) -> int:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        return fail(f"GEMINI_API_KEY is not set. Create a key at https://aistudio.google.com/apikey and add "
                    f"GEMINI_API_KEY=<key> to ~/.doxagon/providers/{NAME}.env")
    # Sent verbatim: the platform hashed these exact bytes.
    parts: list[dict] = [{"text": Path(args["prompt_file"]).read_text(encoding="utf-8")}]
    for source in args["source"]:
        mime = MIME.get(source.suffix.lower())
        if mime is None:
            return fail(f"unsupported reference type {source.suffix}", 2)
        parts.append({"inlineData": {"mimeType": mime, "data": base64.b64encode(source.read_bytes()).decode()}})
    body = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "responseModalities": ["TEXT", "IMAGE"],
            "imageConfig": {"aspectRatio": args["aspect_ratio"], "imageSize": args["image_size"]},
        },
    }
    model = os.environ.get("GEMINI_IMAGE_MODEL", DEFAULT_MODEL)
    base = os.environ.get("GEMINI_API_BASE", DEFAULT_BASE).rstrip("/")
    request = urllib.request.Request(f"{base}/models/{model}:generateContent", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "x-goog-api-key": key})
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            payload = json.loads(response.read())
    except urllib.error.HTTPError as error:
        try:
            detail = json.loads(error.read()).get("error", {}).get("message", "")
        except (ValueError, AttributeError):
            detail = ""
        hint = " (check GEMINI_IMAGE_MODEL against Google's current model list)" if error.code == 404 else ""
        return fail(f"HTTP {error.code} from Gemini: {detail[:200]}{hint}")
    except (urllib.error.URLError, TimeoutError) as error:
        return fail(f"could not reach Gemini: {getattr(error, 'reason', error)}")

    for candidate in payload.get("candidates") or []:
        for part in (candidate.get("content") or {}).get("parts") or []:
            data = part.get("inlineData") or part.get("inline_data")
            if data and data.get("data"):
                suffix = SUFFIX.get(data.get("mimeType") or data.get("mime_type"), ".png")
                Path(args["output"], f"image{suffix}").write_bytes(base64.b64decode(data["data"]))
                return 0
    blocked = (payload.get("promptFeedback") or {}).get("blockReason")
    finish = next((c.get("finishReason") for c in payload.get("candidates") or [] if c.get("finishReason")), None)
    return fail(f"no image returned (block reason: {blocked or 'none'}, finish reason: {finish or 'unknown'})")


def main() -> int:
    load_env()
    if sys.argv[1:] == ["--capabilities"]:
        print(json.dumps({"schema": "doxagon.provider-capabilities/1", "max_references": MAX_REFERENCES,
                          "resolutions": RESOLUTIONS, "aspect_ratios": ASPECT_RATIOS,
                          "model": os.environ.get("GEMINI_IMAGE_MODEL", DEFAULT_MODEL), "text_rendering": True}))
        return 0
    try:
        args = parse(sys.argv[1:])
    except ValueError as error:
        return fail(str(error), 2)
    if args["image_size"] not in RESOLUTIONS:
        return fail(f"image size {args['image_size']} is not supported", 2)
    if args["aspect_ratio"] not in ASPECT_RATIOS:
        return fail(f"aspect ratio {args['aspect_ratio']} is not supported", 2)
    if len(args["source"]) > MAX_REFERENCES:
        return fail(f"{len(args['source'])} references exceed {MAX_REFERENCES}", 2)
    return generate(args)


if __name__ == "__main__":
    raise SystemExit(main())
