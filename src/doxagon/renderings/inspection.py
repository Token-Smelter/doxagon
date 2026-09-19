"""Bounded HTML source inspection without execution, fetching, or vault access.

This is an intake inventory, not a browser parser, sanitizer, dependency-closure
proof, or epistemic assessment. Structural candidates and lexical hints guide
an author's adaptation; they never become inferred checkpoints or permissions.
"""

from __future__ import annotations

import hashlib
from html.parser import HTMLParser
import os
from pathlib import Path
import re
import stat
from typing import Any

from doxagon.presentations.javascript import code_projection, module_specifiers

REPORT_SCHEMA = "doxagon.html-intake-report/1"
MAX_HTML_BYTES = 16 * 1024 * 1024
MAX_ELEMENTS = 20000
MAX_ITEMS = 4096
MAX_VALUE_CHARS = 512
_VOID_ELEMENTS = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"})
_JS_TYPES = frozenset({"", "module", "text/javascript", "application/javascript", "text/ecmascript", "application/ecmascript"})
_CSS_REFERENCE = re.compile(r"url\s*\(|@import\s+(?=[\"'])", re.IGNORECASE)
_HINTS = {
    "animation_frames": r"\brequestAnimationFrame\b",
    "scroll_input": r"\b(?:scrollY|scrollX|scrollTop|scrollLeft|IntersectionObserver)\b",
    "viewport_geometry": r"\b(?:innerHeight|innerWidth|devicePixelRatio|getBoundingClientRect)\b",
    "time_input": r"\bperformance\s*\.\s*now\b|\bDate\s*\.\s*now\b|\b(?:setTimeout|setInterval)\b",
    "dom_events": r"\baddEventListener\b",
    "network": r"\b(?:fetch|XMLHttpRequest|WebSocket|EventSource)\b",
    "storage": r"\b(?:localStorage|sessionStorage|indexedDB)\b",
    "dynamic_code": r"\beval\s*\(|\bFunction\s*\(|\bimport\s*\(",
}


class HtmlInspectionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _reference_value(value: str) -> dict[str, Any]:
    embedded = value.lower().startswith("data:")
    return {
        "value": "data:[embedded; inspect original source]" if embedded else value[:MAX_VALUE_CHARS],
        "bytes": len(value.encode("utf-8")),
        "sha256": _sha(value.encode("utf-8")),
        "abridged": embedded or len(value) > MAX_VALUE_CHARS,
    }


def _reference_kind(value: str) -> str:
    value = value.strip().lower()
    if value.startswith("#"):
        return "fragment"
    if value.startswith("data:"):
        return "embedded"
    if value.startswith(("http:", "https:", "//")):
        return "network"
    if re.match(r"[a-z][a-z0-9+.-]*:", value):
        return "other-scheme"
    return "relative"


class _Inventory(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.elements: dict[str, int] = {}
        self.sections: list[dict[str, Any]] = []
        self.cues: list[dict[str, Any]] = []
        self.anchors: list[dict[str, Any]] = []
        self.blocks: list[dict[str, Any]] = []
        self.references: list[dict[str, Any]] = []
        self.hints: list[dict[str, Any]] = []
        self.findings: list[dict[str, Any]] = []
        self.title_parts: list[str] = []
        self.title_chars = 0
        self.stack: list[tuple[str, int | None]] = []
        self.ids: set[str] = set()
        self.block: dict[str, Any] | None = None
        self.block_parts: list[str] = []
        self.item_count = 0
        self.element_count = 0

    def add(self, collection: list[dict[str, Any]], record: dict[str, Any]) -> None:
        self.item_count += 1
        if self.item_count > MAX_ITEMS:
            raise HtmlInspectionError("HTML_INTAKE_LIMIT", f"inspection exceeds the {MAX_ITEMS}-item report limit")
        collection.append(record)

    def finding(self, code: str, line: int, message: str) -> None:
        self.add(self.findings, {"code": code, "line": line, "message": message})

    def reference(self, tag: str, attribute: str, value: str, line: int) -> None:
        self.add(self.references, {
            "tag": tag, "attribute": attribute, "line": line,
            "kind": "compound" if attribute == "srcset" else _reference_kind(value),
            **_reference_value(value),
        })

    def handle_starttag(self, tag: str, attributes: list[tuple[str, str | None]]) -> None:
        self.element_count += 1
        if self.element_count > MAX_ELEMENTS:
            raise HtmlInspectionError("HTML_INTAKE_LIMIT", f"source exceeds the {MAX_ELEMENTS}-element limit")
        self.elements[tag] = self.elements.get(tag, 0) + 1
        attrs = dict(attributes)
        line = self.getpos()[0]
        if len(attrs) != len(attributes):
            self.finding("HTML_INTAKE_DUPLICATE_ATTRIBUTE", line, "Duplicate attributes require browser/author review.")
        identifier = attrs.get("id")
        if identifier:
            self.add(self.anchors, {"tag": tag, "id": identifier[:MAX_VALUE_CHARS], "line": line})
            if identifier in self.ids:
                self.finding("HTML_INTAKE_DUPLICATE_ID", line, "Duplicate ID cannot identify a unique cue target.")
            self.ids.add(identifier)
        section = self.stack[-1][1] if self.stack else None
        if tag == "section":
            section = len(self.sections)
            self.add(self.sections, {"id": (identifier or "")[:MAX_VALUE_CHARS] or None, "line": line, "cue_candidates": 0})
        classes = (attrs.get("class") or "").split()
        if "step" in classes or "data-step" in attrs or "data-cue" in attrs:
            self.add(self.cues, {"id": (identifier or "")[:MAX_VALUE_CHARS] or None, "line": line, "section_index": section})
            if section is not None:
                self.sections[section]["cue_candidates"] += 1
        for key, value in attributes:
            if value is not None and key in {"src", "href", "poster", "srcset", "data"}:
                self.reference(tag, key, value, line)
            if key.startswith("on"):
                self.finding("HTML_INTAKE_EVENT_HANDLER", line, "Inline event handler requires explicit lifecycle adaptation.")
            if key == "srcdoc":
                self.finding("HTML_INTAKE_NESTED_DOCUMENT", line, "Embedded document was not inspected.")
            if key == "style" and value:
                self.css_references(value, line)
        if tag in {"base", "iframe", "object", "embed", "form"}:
            self.finding("HTML_INTAKE_HOST_BEHAVIOR", line, f"The {tag} element needs explicit containment review.")
        if tag in {"script", "style"}:
            declared_type = (attrs.get("type") or "").strip().lower()
            if tag == "style":
                kind = "css"
            elif declared_type == "module":
                kind = "module"
            else:
                kind = "classic" if declared_type in _JS_TYPES else "data"
            self.block = {
                "tag": tag, "line": line, "content_line": line + (self.get_starttag_text() or "").count("\n"),
                "kind": kind,
                "external": bool(attrs.get("src")), "closed": False, "bytes": None, "sha256": None,
            }
            self.block_parts = []
            self.add(self.blocks, self.block)
        if tag not in _VOID_ELEMENTS:
            self.stack.append((tag, section))

    def handle_startendtag(self, tag: str, attributes: list[tuple[str, str | None]]) -> None:
        foreign = tag in {"svg", "math"}
        for ancestor, _ in reversed(self.stack):
            if ancestor in {"foreignobject", "annotation-xml"}:
                break
            if ancestor in {"svg", "math"}:
                foreign = True
                break
        self.handle_starttag(tag, attributes)
        if tag not in _VOID_ELEMENTS:
            self.handle_endtag(tag)
            if not foreign:
                self.finding("HTML_INTAKE_NONVOID_SELF_CLOSE", self.getpos()[0], "Self-closing nonvoid HTML requires browser parsing review.")

    def handle_endtag(self, tag: str) -> None:
        if self.block is not None and tag == self.block["tag"]:
            self.finish_block()
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        if self.block is not None:
            self.block_parts.append(data)
        elif self.stack and self.stack[-1][0] == "title":
            self.title_parts.append(data[:max(0, MAX_VALUE_CHARS - self.title_chars)])
            self.title_chars += len(data)

    def finish_block(self) -> None:
        block = self.block
        assert block is not None
        text = "".join(self.block_parts)
        block.update(closed=True, bytes=len(text.encode("utf-8")), sha256=_sha(text.encode("utf-8")))
        if block["tag"] == "style":
            self.css_references(text, block["content_line"])
        elif block["kind"] != "data":
            self.finding("HTML_INTAKE_SCRIPT_ADAPTATION", block["line"], "Script requires authored lifecycle/cue adaptation; a file split is not a conversion.")
            if not block["external"]:
                projection = code_projection(text)
                for hint, expression in _HINTS.items():
                    match = re.search(expression, projection)
                    if match:
                        self.add(self.hints, {"hint": hint, "line": block["content_line"] + text.count("\n", 0, match.start())})
                for offset, specifier in module_specifiers(text):
                    if specifier is not None:
                        self.reference("script", "module-specifier", specifier, block["content_line"] + text.count("\n", 0, offset))
        self.block = None
        self.block_parts = []

    def css_references(self, text: str, line: int) -> None:
        # Literal candidates only: escaped URLs, comments, imports, and generated
        # styles still need a CSS-aware adaptation. Never infer a closed graph.
        cursor = 0
        while match := _CSS_REFERENCE.search(text, cursor):
            start = match.end()
            while start < len(text) and text[start].isspace():
                start += 1
            if start >= len(text):
                break
            quote = text[start] if text[start] in "\"'" else None
            if quote:
                start += 1
            end = start
            while end < len(text):
                if text[end] == "\\":
                    end += 2
                elif text[end] == (quote or ")"):
                    break
                else:
                    end += 1
            if end >= len(text):
                break
            self.reference("style", "literal-url", text[start:end].strip(), line + text.count("\n", 0, match.start()))
            cursor = end + 1


def inspect_html_bytes(data: bytes) -> dict[str, Any]:
    if len(data) > MAX_HTML_BYTES:
        raise HtmlInspectionError("HTML_INTAKE_LIMIT", f"HTML source exceeds {MAX_HTML_BYTES} bytes")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise HtmlInspectionError("HTML_INTAKE_ENCODING", "HTML source must be UTF-8") from error
    if "\x00" in text:
        raise HtmlInspectionError("HTML_INTAKE_ENCODING", "HTML source contains NUL")
    inventory = _Inventory()
    try:
        inventory.feed(text)
        inventory.close()
    except (AssertionError, RecursionError) as error:
        raise HtmlInspectionError("HTML_INTAKE_PARSE", "HTML or embedded syntax could not be inspected; author review required") from error
    if inventory.block is not None:
        inventory.finding("HTML_INTAKE_UNCLOSED_BLOCK", inventory.block["line"], "Unclosed script/style; block inventory is incomplete.")
    return {
        "schema": REPORT_SCHEMA,
        "status": "inspected",
        "source": {"sha256": _sha(data), "bytes": len(data), "encoding": "utf-8"},
        "assurance": {"executed": False, "resources_read": False, "network_used": False, "vault_changed": False,
                      "admission": "not-assessed", "dependency_closure": "not-proven"},
        "title": " ".join("".join(inventory.title_parts).split()),
        "title_abridged": inventory.title_chars > MAX_VALUE_CHARS,
        "elements": dict(sorted(inventory.elements.items())),
        "sections": inventory.sections,
        "cue_candidates": inventory.cues,
        "anchors": inventory.anchors,
        "blocks": inventory.blocks,
        "references": inventory.references,
        "lexical_hints": inventory.hints,
        "findings": inventory.findings,
        "limitations": [
            "Source inventory is not HTML5 DOM/layout validation, a sanitizer, or a permission grant.",
            "Structural cues and lexical hints do not infer scenes, behavior, or claim support.",
            "CSS candidates may include inert literals; dynamic, escaped and external dependencies require review.",
            "Reference values and titles may be abridged; original source bytes remain authoritative.",
        ],
    }


def inspect_html_file(path: Path) -> dict[str, Any]:
    """Read only the explicitly selected regular file; reject unstable reads."""

    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as source:
            before = os.fstat(source.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise HtmlInspectionError("HTML_INTAKE_SOURCE", "HTML source must be a regular file")
            if before.st_size > MAX_HTML_BYTES:
                raise HtmlInspectionError("HTML_INTAKE_LIMIT", f"HTML source exceeds {MAX_HTML_BYTES} bytes")
            data = source.read(MAX_HTML_BYTES + 1)
            after = os.fstat(source.fileno())
        def identity(item: os.stat_result) -> tuple[int, ...]:
            return (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns)

        if identity(before) != identity(after) or len(data) != before.st_size:
            raise HtmlInspectionError("HTML_INTAKE_SOURCE_CHANGED", "HTML source changed during inspection; retry")
    except OSError as error:
        raise HtmlInspectionError("HTML_INTAKE_SOURCE", "HTML source could not be opened as a regular, non-symlink file") from error
    return inspect_html_bytes(data)
