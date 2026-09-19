"""Pure deterministic compiler for one offline HTML Edition."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from importlib import resources
import base64
import csv
import hashlib
import io
import json
import mimetypes
import os
from pathlib import Path
import re
import stat
from typing import Callable, Mapping

from .contracts import (
    MAX_BODY_BYTES,
    MAX_DOCUMENT_BODY_BYTES,
    MAX_RAW_BYTES,
    MEDIA_TYPES,
    ContentDocument,
    Resource,
    Section,
    _stat_identity,
    canonical_json,
    sha256,
)
from .css import is_stylesheet
from .errors import HtmlEditionError

_RESOURCE_CAPS = {
    "image/png": 16 * 1024 * 1024,
    "image/jpeg": 16 * 1024 * 1024,
    "image/svg+xml": 2 * 1024 * 1024,
    "font/woff2": 2 * 1024 * 1024,
    "application/json": 5 * 1024 * 1024,
    "text/csv": 5 * 1024 * 1024,
    "text/css": 100 * 1024,
}
# Bytes that positively identify a binary media type, and control bytes no
# admitted text media type may contain.
_MEDIA_SIGNATURES: Mapping[str, bytes] = {
    "image/png": b"\x89PNG\r\n\x1a\n",
    "image/jpeg": b"\xff\xd8\xff",
    "font/woff2": b"wOF2",
}
_TEXT_CONTROL = re.compile(rb"[\x00-\x08\x0b\x0e-\x1f\x7f]")
_FORBIDDEN_MARKUP = re.compile(r"<\s*/?\s*(?:script|style|iframe|frame|object|embed|portal|base|form|input|button|video|audio)\b|\bon\w+\s*=|\b(?:javascript|file|data|blob)\s*:", re.I)
_FORBIDDEN_CSS = re.compile(r"@(?:import|namespace)|url\s*\(|\b(?:position|z-index|transform|filter|backdrop-filter|clip-path|pointer-events|behavior)\s*:", re.I)
_CSS_PROPERTY = re.compile(
    r"(?:color|background-color|font-(?:family|size|style|weight)|line-height|letter-spacing|text-align|"
    r"margin(?:-(?:top|right|bottom|left))?|padding(?:-(?:top|right|bottom|left))?|"
    r"border(?:-(?:color|style|width))?|border-radius|max-width)"
    r"\Z",
    re.I,
)
_CSS_VALUE = re.compile(r"[a-zA-Z0-9 #(),.%+/_-]+\Z")


@dataclass(frozen=True)
class EditionIdentity:
    """The four non-interchangeable Edition identities."""

    authoring_revision: str
    compile_input_hash: str
    edition_id: str
    file_sha256: str


@dataclass(frozen=True)
class EditionReceipt:
    """Closed public receipt; it deliberately excludes workspace authority data."""

    schema: str
    identity: EditionIdentity
    target_ids: tuple[dict[str, str], ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "authoring_revision": self.identity.authoring_revision,
            "compile_input_hash": self.identity.compile_input_hash,
            "edition_id": self.identity.edition_id,
            "file_sha256": self.identity.file_sha256,
            "targets": list(self.target_ids),
        }


@dataclass(frozen=True)
class BuildResult:
    html: bytes
    authoring_revision: str
    compile_input_hash: str
    edition_id: str
    file_sha256: str
    target_ids: tuple[dict[str, str], ...]

    @property
    def receipt(self) -> EditionReceipt:
        return EditionReceipt(
            "doxagon.html-edition-receipt/1",
            EditionIdentity(self.authoring_revision, self.compile_input_hash, self.edition_id, self.file_sha256),
            self.target_ids,
        )


def _asset(name: str) -> bytes:
    return resources.files("doxagon.html_editions.resources").joinpath(name).read_bytes()


def _csp_hash(value: bytes) -> str:
    return base64.b64encode(hashlib.sha256(value).digest()).decode("ascii")


def _open_contained_file(root: Path | int, key: str, subject: str) -> int:
    """Open a regular source using descriptors retained for every path component."""

    directory_fd: int | None = None
    try:
        directory_fd = os.dup(root) if isinstance(root, int) else os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        components = key.split("/")
        for component in components[:-1]:
            child_fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = child_fd
        fd = os.open(components[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
    except OSError as error:
        raise HtmlEditionError("HTML_EDITION_SOURCE_CONTAINMENT", f"{subject} is unavailable or not contained") from error
    finally:
        if directory_fd is not None:
            os.close(directory_fd)
    return fd


def _read_regular(root: Path | int, key: str, declared_size: int | None, subject: str, *, maximum_size: int | None = None) -> bytes:
    fd: int | None = None
    try:
        fd = _open_contained_file(root, key, subject)
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise HtmlEditionError("HTML_EDITION_SOURCE_SIZE_MISMATCH", f"{subject} size mismatch")
        if declared_size is None:
            declared_size = before.st_size
        if before.st_size != declared_size:
            raise HtmlEditionError("HTML_EDITION_SOURCE_SIZE_MISMATCH", f"{subject} size mismatch")
        if maximum_size is not None and declared_size > maximum_size:
            raise HtmlEditionError("HTML_EDITION_BODY_LIMIT", "body exceeds size limit")
        chunks: list[bytes] = []
        remaining = declared_size
        while remaining:
            chunk = os.read(fd, min(65536, remaining))
            if not chunk:
                raise HtmlEditionError("HTML_EDITION_SOURCE_SIZE_MISMATCH", f"{subject} was truncated")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(fd, 1):
            raise HtmlEditionError("HTML_EDITION_SOURCE_SIZE_MISMATCH", f"{subject} grew while reading")
        after = os.fstat(fd)
    except HtmlEditionError:
        raise
    except OSError as error:
        raise HtmlEditionError("HTML_EDITION_SOURCE_NOT_FOUND", f"{subject} is unavailable") from error
    finally:
        if fd is not None:
            os.close(fd)
    if _stat_identity(after) != _stat_identity(before):
        raise HtmlEditionError("HTML_EDITION_SOURCE_RACE", f"{subject} changed while reading")
    return b"".join(chunks)


def _read_body(root: Path | int, key: str) -> bytes:
    return _read_regular(root, key, None, "body", maximum_size=MAX_BODY_BYTES)


def _utf8_text(data: bytes) -> str | None:
    """Decode strictly and refuse control bytes no text media type may carry."""

    if _TEXT_CONTROL.search(data):
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _is_svg_document(text: str) -> bool:
    remainder = text.lstrip("\ufeff \t\r\n")
    # Skip an XML declaration, doctype, or comment prologue before the root.
    while remainder.startswith(("<?", "<!")):
        end = remainder.find(">")
        if end < 0:
            return False
        remainder = remainder[end + 1 :].lstrip()
    return remainder.startswith("<svg") and (len(remainder) == 4 or remainder[4] in " \t\r\n/>")


def _is_json_document(text: str) -> bool:
    try:
        json.loads(text)
    except ValueError:
        return False
    return True


def _is_csv_document(text: str) -> bool:
    try:
        rows = [row for row in csv.reader(io.StringIO(text, newline="")) if row]
    except csv.Error:
        return False
    # RFC 4180 §2.4: every record carries the same field count.
    return bool(rows) and len({len(row) for row in rows}) == 1


_MEDIA_PARSERS: Mapping[str, Callable[[str], bool]] = {
    "image/svg+xml": _is_svg_document,
    "application/json": _is_json_document,
    "text/csv": _is_csv_document,
    "text/css": is_stylesheet,
}


def _matches_declared_media(media_type: str, data: bytes) -> bool:
    """Require bytes to positively match the declared type, never merely fail to contradict it."""

    signature = _MEDIA_SIGNATURES.get(media_type)
    if signature is not None:
        return data.startswith(signature)
    text = _utf8_text(data)
    if text is None:
        return False
    parser = _MEDIA_PARSERS.get(media_type)
    return parser is not None and parser(text)


def verify_media_bytes(media_type: str, key: str, data: bytes) -> None:
    """Verify declared media type against a positive byte match, the extension, and SVG safety."""

    key = key.lower()
    # Content-addressed storage keys are extensionless, so an extension check
    # alone admits arbitrary bytes; every admitted type must match positively.
    if media_type not in MEDIA_TYPES:
        raise HtmlEditionError("HTML_EDITION_RESOURCE_MIME_MISMATCH", "resource media type is not supported")
    if not _matches_declared_media(media_type, data):
        raise HtmlEditionError("HTML_EDITION_RESOURCE_MIME_MISMATCH", "resource MIME mismatch")
    expected_extension = mimetypes.guess_type(key)[0]
    if media_type == "text/csv":
        expected_extension = "text/csv" if key.endswith(".csv") else expected_extension
    if media_type == "text/css":
        expected_extension = "text/css" if key.endswith(".css") else expected_extension
    if expected_extension is not None and expected_extension != media_type:
        raise HtmlEditionError("HTML_EDITION_RESOURCE_MIME_MISMATCH", "resource extension mismatch")
    if media_type == "image/svg+xml" and re.search(rb"<\s*(?:script|foreignObject|animate)\b|\bon\w+\s*=|(?:href|xlink:href)\s*=\s*['\"](?:https?:|data:)", data, re.I):
        raise HtmlEditionError("HTML_EDITION_RESOURCE_UNSAFE", "resource contains executable SVG")


def _resource_mime(resource: Resource, data: bytes) -> None:
    verify_media_bytes(resource.source.media_type, resource.source.key, data)


def _markdown(body: str, resources: Mapping[str, str]) -> str:
    if _FORBIDDEN_MARKUP.search(body):
        raise HtmlEditionError("HTML_EDITION_SANITIZER_REJECTED", "body contains executable or remote content")
    output: list[str] = []
    for raw_line in body.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        image = re.fullmatch(r"!\[([^]]*)\]\(resource:([a-z][a-z0-9-]{0,63})\)", line)
        if image:
            logical_id = image.group(2)
            if logical_id not in resources:
                raise HtmlEditionError("HTML_EDITION_SANITIZER_REJECTED", "body references undeclared resource")
            output.append(f'<img alt="{escape(image.group(1))}" src="{resources[logical_id]}">')
        elif line.startswith("### "):
            output.append(f"<h3>{escape(line[4:])}</h3>")
        elif line.startswith("## "):
            output.append(f"<h2>{escape(line[3:])}</h2>")
        elif line.startswith("# "):
            output.append(f"<h1>{escape(line[2:])}</h1>")
        elif line.startswith("- "):
            output.append(f"<ul><li>{escape(line[2:])}</li></ul>")
        else:
            output.append(f"<p>{escape(line)}</p>")
    return "".join(output)


def _section_css(section: Section) -> str:
    if section.css is None:
        return ""
    css = section.css.strip()
    if (
        len(css.encode()) > 100 * 1024
        or _FORBIDDEN_CSS.search(css)
        or any(character in css for character in "{}<>\\\"'\\\\")
        or "/*" in css
        or "*/" in css
    ):
        raise HtmlEditionError("HTML_EDITION_CSS_REJECTED", "section CSS is not contained")
    declarations: list[str] = []
    for declaration in css.split(";"):
        if not declaration.strip():
            continue
        property_name, separator, value = declaration.partition(":")
        if not separator or not _CSS_PROPERTY.fullmatch(property_name.strip()) or not _CSS_VALUE.fullmatch(value.strip()):
            raise HtmlEditionError("HTML_EDITION_CSS_REJECTED", "section CSS must use safe declarations")
        declarations.append(f"{property_name.strip().lower()}:{value.strip()}")
    if css and not declarations:
        raise HtmlEditionError("HTML_EDITION_CSS_REJECTED", "section CSS must use safe declarations")
    return ";".join(declarations)


class HtmlEditionCompiler:
    """Resolve a document directory and render deterministic bytes without I/O elsewhere."""

    def compile(self, document: ContentDocument, document_root: Path | int) -> BuildResult:
        resolved_bodies: dict[str, str] = {}
        total_body_bytes = 0
        for section in document.sections:
            if isinstance(section.body, str):
                body = section.body
            else:
                raw = _read_body(document_root, f"bodies/{section.body.key}")
                if sha256(raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")) != section.body.sha256:
                    raise HtmlEditionError("HTML_EDITION_BODY_HASH_MISMATCH", "body hash mismatch")
                try:
                    body = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
                except UnicodeDecodeError as error:
                    raise HtmlEditionError("HTML_EDITION_BODY_ENCODING", "body is not UTF-8") from error
            total_body_bytes += len(body.encode("utf-8"))
            if total_body_bytes > MAX_DOCUMENT_BODY_BYTES:
                raise HtmlEditionError("HTML_EDITION_BODY_LIMIT", "document bodies exceed size limit")
            resolved_bodies[section.section_id] = body
        resolved_resources: dict[str, bytes] = {}
        total = 0
        for resource in document.resources:
            if resource.source.size > _RESOURCE_CAPS[resource.source.media_type] or resource.source.size + total > MAX_RAW_BYTES:
                raise HtmlEditionError("HTML_EDITION_RESOURCE_LIMIT", "resource declaration exceeds limit")
            raw = _read_regular(document_root, f"resources/{resource.source.key}", resource.source.size, "resource")
            if sha256(raw) != resource.source.sha256:
                raise HtmlEditionError("HTML_EDITION_RESOURCE_HASH_MISMATCH", "resource hash mismatch")
            _resource_mime(resource, raw)
            resolved_resources[resource.logical_id] = raw
            total += len(raw)
        runtime = _asset("runtime.js")
        platform_css = _asset("style.css")
        manifest = {
            "document": document.source,
            "bodies": resolved_bodies,
            "resources": [{"logical_id": item.logical_id, "source": item.source.__dict__, "sha256": sha256(resolved_resources[item.logical_id])} for item in document.resources],
            "runtime": sha256(runtime),
            "css": sha256(platform_css),
            "sanitizer": "doxagon-html-sanitizer/1",
        }
        compile_input_hash = sha256(b"doxagon-html-edition-compile-v1\0" + canonical_json(manifest))
        edition_id = sha256(("doxagon-html-edition-id-v1\0" + compile_input_hash + "\0doxagon.html-edition/1\0doxagon-html-edition-runtime/1").encode())
        data_urls = {key: f"data:{next(item.source.media_type for item in document.resources if item.logical_id == key)};base64,{base64.b64encode(value).decode('ascii')}" for key, value in resolved_resources.items()}
        target_ids: list[dict[str, str]] = []
        section_html: list[str] = []
        author_css: list[str] = []
        for section in document.sections:
            aliases = "".join(f'<a id="section-{section.section_id}~step={number}" aria-hidden="true"></a>' for number in range(1, len(section.steps) + 1))
            targets = "".join(
                f'<span id="target-{section.section_id}-{key}" data-target-section="{section.section_id}"></span>' for key in section.targets
            )
            target_ids.extend({"sectionId": section.section_id, "targetKey": key, "generatedId": f"target-{section.section_id}-{key}"} for key in section.targets)
            heading = f"<h{section.level}>{escape(section.title or section.aria_label or '')}</h{section.level}>" if section.title else ""
            section_html.append(
                f'<section id="section-{section.section_id}" data-section-id="{section.section_id}" aria-label="{escape(section.aria_label or section.title or "")}">{aliases}{heading}{targets}{_markdown(resolved_bodies[section.section_id], {key: data_urls[key] for key in section.resources})}</section>'
            )
            if section.css:
                author_css.append(f"#section-{section.section_id}{{{_section_css(section)}}}")
        combined_css = platform_css.decode("utf-8") + "".join(author_css)
        csp = "default-src 'none'; script-src 'sha256-" + _csp_hash(runtime) + "'; style-src 'sha256-" + _csp_hash(combined_css.encode()) + "'; img-src data:; font-src data:; connect-src 'none'; object-src 'none'; frame-src 'none'; worker-src 'none'; base-uri 'none'; form-action 'none'"
        public_metadata = canonical_json({"schema": "doxagon.html-edition/1", "editionId": edition_id, "compileInputHash": compile_input_hash, "authoringRevision": document.authoring_revision, "mode": document.mode, "targets": target_ids}).decode().replace("</", "<\\/")
        title = escape(str(document.metadata["title"]))
        html = (
            "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<meta http-equiv=\"Content-Security-Policy\" content=\"{csp}\"><title>{title}</title><style>{combined_css}</style></head>"
            f"<body data-mode=\"{document.mode}\"><header><h1>{title}</h1></header><main id=\"dox-content\">{''.join(section_html)}</main>"
            f"<footer>Generated by Doxagon HTML Editions</footer><script type=\"application/json\" id=\"dox-edition-metadata\">{public_metadata}</script><script>{runtime.decode('utf-8')}</script></body></html>"
        ).encode("utf-8")
        return BuildResult(html, document.authoring_revision, compile_input_hash, edition_id, sha256(html), tuple(target_ids))
