"""Repack an existing inline-image document without changing its argument or artwork.

This is not a legacy-slide converter. The input must already own its cue navigation
and emit `doxagon:position` with a chapter id. Output is a new, self-contained file;
inspect and verify it before replacing the selected document.
"""

import argparse
import base64
import hashlib
from html import escape
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path

from PIL import Image

RUNTIME = Path(__file__).resolve().parents[1] / "src/doxagon/presentations/resources/document-assets.js"


class InlineImages(HTMLParser):
    def __init__(self, source: str):
        super().__init__(convert_charrefs=True)
        self.source = source
        self.line_starts = [0]
        for line in source.splitlines(keepends=True):
            self.line_starts.append(self.line_starts[-1] + len(line))
        self.edits = []
        self.assets = {}
        self.head_ends = []
        self.body_ends = []
        self.scripts = []

    def source_position(self):
        line, column = self.getpos()
        return self.line_starts[line - 1] + column

    def handle_endtag(self, tag):
        if tag == "head":
            self.head_ends.append(self.source_position())
        elif tag == "body":
            self.body_ends.append(self.source_position())

    def handle_starttag(self, tag, attrs):
        if tag == "script" and "src" not in dict(attrs):
            self.scripts.append(self.source_position())
        if tag != "img":
            return
        attributes = dict(attrs)
        uri = attributes.get("src", "")
        if not uri.startswith("data:image/") or ";base64," not in uri:
            raise ValueError("Every image must already be embedded; resolve external images before repacking")
        media, encoded = uri.split(";base64,", 1)
        if media not in {"data:image/webp", "data:image/png", "data:image/jpeg", "data:image/gif"}:
            raise ValueError(f"Unsupported embedded image type: {media}")
        raw = base64.b64decode(encoded, validate=True)
        with Image.open(BytesIO(raw)) as image:
            width, height = image.size
        key = "asset-" + hashlib.sha256(raw).hexdigest()
        self.assets.setdefault(key, (uri, attributes.get("alt", ""), width, height))
        attributes.pop("src")
        attributes.update({"data-dox-asset": key, "width": str(width), "height": str(height), "loading": "eager"})
        replacement = "<img " + " ".join(
            escape(name, quote=True) if value is None else f'{escape(name, quote=True)}="{escape(value, quote=True)}"'
            for name, value in attributes.items()
        ) + ">"
        line, column = self.getpos()
        start = self.line_starts[line - 1] + column
        self.edits.append((start, start + len(self.get_starttag_text()), replacement))


def repack(source: str, runtime: str) -> str:
    if "data-dox-asset" in source:
        raise ValueError("This document is already packed")
    if "doxagon:position" not in source or "doxagon:connect" not in source:
        raise ValueError("The document must already implement chapter position events and the player bridge")
    parser = InlineImages(source)
    parser.feed(source)
    if len(parser.head_ends) != 1 or len(parser.body_ends) != 1:
        raise ValueError("Expected a complete HTML document with one head and body")
    if not parser.assets:
        raise ValueError("No embedded images found")
    styles = """<style>
img[data-dox-asset]:not([src]) { visibility: hidden; }
.asset-status { position: fixed; right: 1rem; bottom: calc(var(--bottom, 0px) + 1rem);
  z-index: var(--z-controls, 10); max-width: min(28rem, calc(100vw - 2rem));
  padding: .5rem .75rem; background: var(--paper, white); color: var(--ink, black);
  border: 1px solid var(--line, currentColor); font: 13px/1.4 var(--ui, sans-serif); }
.asset-status[hidden] { display: none; }
</style>
"""
    # Parse actual tags: the notes popup's JS contains its own HTML document as
    # a string. Searching for closing tags would modify that string instead.
    if not parser.scripts:
        raise ValueError("Expected the document's inline navigation runtime")
    script_at = parser.scripts[-1]
    if any(start > script_at for start, _, _ in parser.edits):
        raise ValueError("The navigation runtime must follow the complete document structure")
    bootstrap = (
        '<p id="asset-status" class="asset-status" role="status" hidden></p>\n'
        f"<script>\n{runtime}\n</script>\n"
    )
    payloads = ["""<script>
if (window.parent !== window) window.parent.postMessage({type: 'doxagon:available'}, '*');
</script>
<noscript>
<style>
  main img[data-dox-asset] { display: none; }
  #dox-asset-payloads[hidden] { display: block; padding: 2rem 5vw; }
  #dox-asset-payloads img { max-width: 100%; height: auto; }
</style>
<p class="noscript">The full text is above. Embedded plates follow in reading order.
Enable JavaScript for images in place, animation and presentation controls.</p>
</noscript>
<div id="dox-asset-payloads" hidden aria-label="Embedded plates in reading order">
"""]
    for key, (uri, alt, width, height) in parser.assets.items():
        payloads.append(
            f'<figure data-dox-source="{key}"><img src="{uri}" loading="lazy" '
            f'width="{width}" height="{height}" alt="{escape(alt, quote=True)}">'
            f'<figcaption>{escape(alt)}</figcaption></figure>\n'
            '<script>window.doxagonAssets.receive(document.currentScript.previousElementSibling);</script>\n'
        )
    payloads.append('</div>\n<script>window.doxagonAssets.complete();</script>\n')
    edits = parser.edits + [
        (parser.head_ends[0], parser.head_ends[0], styles),
        (script_at, script_at, bootstrap),
        (parser.body_ends[0], parser.body_ends[0], "".join(payloads)),
    ]
    for start, end, replacement in sorted(edits, reverse=True):
        source = source[:start] + replacement + source[end:]
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path, help="New output file; existing files are never overwritten")
    args = parser.parse_args()
    result = repack(args.source.read_text(encoding="utf-8"), RUNTIME.read_text(encoding="utf-8"))
    with args.output.open("x", encoding="utf-8") as output:
        output.write(result)
    print(f"Wrote {args.output}: {len(result.encode('utf-8')):,} bytes; source and selected document untouched")


if __name__ == "__main__":
    main()
