"""Independent structural inspector for a compiled Edition."""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
import json
from pathlib import Path
import re

from .contracts import EDITION_SCHEMA, MODES, sha256
from .errors import HtmlEditionError


@dataclass(frozen=True)
class InspectionReport:
    edition_id: str
    compile_input_hash: str
    file_sha256: str
    section_ids: tuple[str, ...]


class _EditionParser(HTMLParser):
    _VOID_ELEMENTS = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.main_depth: int | None = None
        self.depth = 0
        self.sections: list[str] = []
        self.metadata_parts: list[str] = []
        self.in_metadata = False
        self.bad = False
        self.csp: str | None = None
        self.has_header = False
        self.has_footer = False

    def _start(self, tag: str, attrs: list[tuple[str, str | None]], *, opens_element: bool) -> None:
        attributes = dict(attrs)
        if opens_element:
            self.depth += 1
        if tag in {"iframe", "frame", "object", "embed", "base"}:
            self.bad = True
        for name, value in attrs:
            if name.lower().startswith("on") or (name.lower() in {"src", "href"} and value and re.match(r"(?:https?:)?//|file:|javascript:", value, re.I)):
                self.bad = True
        if tag == "meta" and attributes.get("http-equiv", "").lower() == "content-security-policy":
            self.csp = attributes.get("content")
        if tag == "main" and attributes.get("id") == "dox-content":
            self.main_depth = self.depth
        if tag == "section":
            if self.main_depth != self.depth - 1:
                self.bad = True
            else:
                section_id = attributes.get("id", "")
                if not section_id.startswith("section-"):
                    self.bad = True
                self.sections.append(section_id.removeprefix("section-"))
        if tag == "header":
            self.has_header = True
        if tag == "footer":
            self.has_footer = True
        if tag == "script" and attributes.get("id") == "dox-edition-metadata" and attributes.get("type") == "application/json":
            self.in_metadata = True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._start(tag, attrs, opens_element=tag not in self._VOID_ELEMENTS)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in self._VOID_ELEMENTS:
            self.bad = True
        self._start(tag, attrs, opens_element=False)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self.in_metadata = False
        if tag in self._VOID_ELEMENTS or self.depth == 0:
            self.bad = True
            return
        if tag == "main" and self.main_depth == self.depth:
            self.main_depth = None
        self.depth -= 1

    def handle_data(self, data: str) -> None:
        if self.in_metadata:
            self.metadata_parts.append(data)


def inspect_edition_bytes(data: bytes) -> InspectionReport:
    try:
        decoded = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise HtmlEditionError("HTML_EDITION_INSPECTION_FAILED", "edition is not UTF-8") from error
    parser = _EditionParser()
    try:
        parser.feed(decoded)
        parser.close()
        metadata = json.loads("".join(parser.metadata_parts))
    except (ValueError, json.JSONDecodeError) as error:
        raise HtmlEditionError("HTML_EDITION_INSPECTION_FAILED", "edition metadata is invalid") from error
    if parser.bad or not parser.has_header or not parser.has_footer or not parser.sections:
        raise HtmlEditionError("HTML_EDITION_INSPECTION_FAILED", "edition violates offline structure")
    if parser.csp is None or "default-src 'none'" not in parser.csp or "connect-src 'none'" not in parser.csp or "frame-src 'none'" not in parser.csp:
        raise HtmlEditionError("HTML_EDITION_INSPECTION_FAILED", "edition CSP is incomplete")
    if not isinstance(metadata, dict) or metadata.get("schema") != EDITION_SCHEMA or metadata.get("mode") not in MODES:
        raise HtmlEditionError("HTML_EDITION_INSPECTION_FAILED", "edition metadata contract is invalid")
    edition_id, compile_hash = metadata.get("editionId"), metadata.get("compileInputHash")
    if not isinstance(edition_id, str) or not re.fullmatch(r"[a-f0-9]{64}", edition_id) or not isinstance(compile_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", compile_hash):
        raise HtmlEditionError("HTML_EDITION_INSPECTION_FAILED", "edition identities are invalid")
    if len(parser.sections) != len(set(parser.sections)):
        raise HtmlEditionError("HTML_EDITION_INSPECTION_FAILED", "edition section identities are duplicated")
    return InspectionReport(edition_id, compile_hash, sha256(data), tuple(parser.sections))


def inspect_edition(path: Path) -> InspectionReport:
    try:
        if path.is_symlink() or not path.is_file():
            raise HtmlEditionError("HTML_EDITION_INSPECTION_FAILED", "edition is not a regular file")
        return inspect_edition_bytes(path.read_bytes())
    except OSError as error:
        raise HtmlEditionError("HTML_EDITION_INSPECTION_FAILED", "edition is unavailable") from error
