"""Closed v1 authoring contracts for an HTML Edition.

The contracts use JSON-compatible values so they can be authored as JSON or
YAML, but unknown fields are rejected before a body or resource is opened.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import unicodedata
from typing import Any, Mapping

import yaml

from .errors import HtmlEditionError

CONTENT_SCHEMA = "doxagon.content-document/1"
BODY_SCHEMA = "doxagon.body-source-ref/1"
RESOURCE_SCHEMA = "doxagon.resource-source-ref/1"
PUBLIC_GRAPH_SCHEMA = "doxagon.public-graph/1"
EDITION_SCHEMA = "doxagon.html-edition/1"
RECEIPT_SCHEMA = "doxagon.html-edition-receipt/1"
RUNTIME_SCHEMA = "doxagon-html-edition-runtime/1"
MODES = frozenset({"deck", "article", "interactive-essay", "report", "graph-brief"})
MEDIA_TYPES = frozenset(
    {"image/png", "image/jpeg", "image/svg+xml", "font/woff2", "application/json", "text/csv", "text/css"}
)
MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_DOCUMENT_BODY_BYTES = 8 * 1024 * 1024
MAX_SECTIONS = 256
MAX_RESOURCES = 256
MAX_RAW_BYTES = 50 * 1024 * 1024
_ID = re.compile(r"[a-z][a-z0-9-]{0,63}\Z")
_SHA = re.compile(r"[a-f0-9]{64}\Z")


def canonical_json(value: Any) -> bytes:
    """Canonical UTF-8 JSON used by every v1 identity."""

    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _reject_unknown(value: Mapping[str, Any], allowed: set[str], subject: str) -> None:
    unknown = set(value).difference(allowed)
    if unknown:
        raise HtmlEditionError("HTML_EDITION_SCHEMA_DIAGNOSTIC", f"{subject} has unknown fields")


def _object(value: Any, subject: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise HtmlEditionError("HTML_EDITION_SCHEMA_DIAGNOSTIC", f"{subject} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise HtmlEditionError("HTML_EDITION_SCHEMA_DIAGNOSTIC", f"{subject} has invalid key")
    return value


def _json_value(value: Any, subject: str) -> Any:
    """Copy one closed JSON value, rejecting YAML-only Python values."""

    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        return _string(value, subject, nonempty=False)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    if isinstance(value, list):
        return [_json_value(item, subject) for item in value]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = _string(key, subject, nonempty=False)
            if normalized_key in result:
                raise HtmlEditionError("HTML_EDITION_SCHEMA_DIAGNOSTIC", f"{subject} has duplicate key")
            result[normalized_key] = _json_value(item, subject)
        return result
    raise HtmlEditionError("HTML_EDITION_SCHEMA_DIAGNOSTIC", f"{subject} is not JSON-compatible")


def _string(value: Any, subject: str, *, nonempty: bool = True) -> str:
    if not isinstance(value, str) or (nonempty and not value):
        raise HtmlEditionError("HTML_EDITION_SCHEMA_DIAGNOSTIC", f"{subject} must be a string")
    normalized = unicodedata.normalize("NFC", value).replace("\r\n", "\n").replace("\r", "\n")
    if "\x00" in normalized:
        raise HtmlEditionError("HTML_EDITION_SCHEMA_DIAGNOSTIC", f"{subject} contains NUL")
    return normalized


def _identifier(value: Any, subject: str) -> str:
    value = _string(value, subject)
    if _ID.fullmatch(value) is None:
        raise HtmlEditionError("HTML_EDITION_SCHEMA_DIAGNOSTIC", f"{subject} is invalid")
    return value


def _relative_key(value: Any, subject: str) -> str:
    key = _string(value, subject)
    if (
        key.startswith("/")
        or "\\" in key
        or "%2f" in key.lower()
        or re.match(r"^[a-zA-Z]:", key)
        or any(part in {"", ".", ".."} for part in key.split("/"))
    ):
        raise HtmlEditionError("HTML_EDITION_SCHEMA_DIAGNOSTIC", f"{subject} is not a safe relative key")
    return key


def _hash(value: Any, subject: str) -> str:
    digest = _string(value, subject)
    if _SHA.fullmatch(digest) is None:
        raise HtmlEditionError("HTML_EDITION_SCHEMA_DIAGNOSTIC", f"{subject} is not a sha256")
    return digest


def _no_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise HtmlEditionError("HTML_EDITION_SCHEMA_DIAGNOSTIC", "duplicate JSON key")
        result[key] = value
    return result


def _parse_serialized(raw: bytes, suffix: str) -> dict[str, Any]:
    try:
        if len(raw) > MAX_BODY_BYTES:
            raise HtmlEditionError("HTML_EDITION_SCHEMA_DIAGNOSTIC", "document exceeds size limit")
        text = raw.decode("utf-8")
        if suffix.lower() == ".json":
            parsed = json.loads(text, object_pairs_hook=_no_duplicate_pairs)
        else:
            parsed = yaml.safe_load(text)
    except HtmlEditionError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, yaml.YAMLError) as error:
        raise HtmlEditionError("HTML_EDITION_SCHEMA_DIAGNOSTIC", "invalid content document") from error
    return _object(parsed, "content document")


def _load_serialized(path: Path) -> dict[str, Any]:
    try:
        return _parse_serialized(path.read_bytes(), path.suffix)
    except HtmlEditionError:
        raise
    except OSError as error:
        raise HtmlEditionError("HTML_EDITION_SCHEMA_DIAGNOSTIC", "invalid content document") from error


def _stat_identity(snapshot: os.stat_result) -> tuple[int, ...]:
    """Return every stable stat field that identifies a source snapshot."""

    return (
        snapshot.st_dev,
        snapshot.st_ino,
        snapshot.st_mode,
        snapshot.st_nlink,
        snapshot.st_uid,
        snapshot.st_gid,
        snapshot.st_rdev,
        snapshot.st_size,
        snapshot.st_mtime_ns,
        snapshot.st_ctime_ns,
    )


def _load_serialized_fd(fd: int, suffix: str) -> dict[str, Any]:
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > MAX_BODY_BYTES:
            raise HtmlEditionError("HTML_EDITION_SCHEMA_DIAGNOSTIC", "document must be a private regular file within size limit")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(fd, min(65536, remaining))
            if not chunk:
                raise HtmlEditionError("HTML_EDITION_SCHEMA_DIAGNOSTIC", "document was truncated")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(fd, 1):
            raise HtmlEditionError("HTML_EDITION_SCHEMA_DIAGNOSTIC", "document grew while reading")
        after = os.fstat(fd)
        if _stat_identity(after) != _stat_identity(before):
            raise HtmlEditionError("HTML_EDITION_SCHEMA_DIAGNOSTIC", "document changed while reading")
        return _parse_serialized(b"".join(chunks), suffix)
    except HtmlEditionError:
        raise
    except OSError as error:
        raise HtmlEditionError("HTML_EDITION_SCHEMA_DIAGNOSTIC", "invalid content document") from error


@dataclass(frozen=True)
class BodySourceRef:
    key: str
    sha256: str
    media_type: str

    @classmethod
    def parse(cls, value: Any) -> "BodySourceRef":
        record = _object(value, "body source")
        _reject_unknown(record, {"schema", "root", "key", "sha256", "media_type"}, "body source")
        if record.get("schema") != BODY_SCHEMA or record.get("root") != "document-bodies":
            raise HtmlEditionError("HTML_EDITION_SCHEMA_DIAGNOSTIC", "unsupported body source")
        if record.get("media_type") != "text/markdown":
            raise HtmlEditionError("HTML_EDITION_SCHEMA_DIAGNOSTIC", "unsupported body media type")
        return cls(_relative_key(record.get("key"), "body key"), _hash(record.get("sha256"), "body hash"), "text/markdown")


@dataclass(frozen=True)
class ResourceSourceRef:
    key: str
    sha256: str
    size: int
    media_type: str

    @classmethod
    def parse(cls, value: Any) -> "ResourceSourceRef":
        record = _object(value, "resource source")
        _reject_unknown(record, {"schema", "root", "key", "sha256", "size", "media_type"}, "resource source")
        if record.get("schema") != RESOURCE_SCHEMA or record.get("root") != "document-resources":
            raise HtmlEditionError("HTML_EDITION_SCHEMA_DIAGNOSTIC", "unsupported resource source")
        media_type = record.get("media_type")
        size = record.get("size")
        if media_type not in MEDIA_TYPES or not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise HtmlEditionError("HTML_EDITION_SCHEMA_DIAGNOSTIC", "invalid resource declaration")
        return cls(_relative_key(record.get("key"), "resource key"), _hash(record.get("sha256"), "resource hash"), size, media_type)


@dataclass(frozen=True)
class Resource:
    logical_id: str
    source: ResourceSourceRef
    purpose: str

    @classmethod
    def parse(cls, value: Any) -> "Resource":
        record = _object(value, "resource")
        _reject_unknown(record, {"logical_id", "source", "purpose"}, "resource")
        return cls(_identifier(record.get("logical_id"), "resource id"), ResourceSourceRef.parse(record.get("source")), _string(record.get("purpose"), "resource purpose"))


@dataclass(frozen=True)
class Section:
    section_id: str
    kind: str
    title: str | None
    aria_label: str | None
    level: int
    body: str | BodySourceRef
    resources: tuple[str, ...]
    targets: tuple[str, ...]
    steps: tuple[dict[str, Any], ...]
    css: str | None

    @classmethod
    def parse(cls, value: Any) -> "Section":
        record = _object(value, "section")
        _reject_unknown(
            record,
            {"section_id", "kind", "title", "aria_label", "level", "heading_level", "body", "resource_ids", "resources", "targets", "component_steps", "steps", "css", "notes", "fragments", "doxa_ids", "evidence_ids", "edge_ids", "authoring_ref"},
            "section",
        )
        section_id = _identifier(record.get("section_id"), "section id")
        kind = _identifier(record.get("kind"), "section kind")
        title = record.get("title")
        aria_label = record.get("aria_label")
        if title is None and aria_label is None:
            raise HtmlEditionError("HTML_EDITION_SCHEMA_DIAGNOSTIC", "section needs title or aria_label")
        if title is not None:
            title = _string(title, "section title")
        if aria_label is not None:
            aria_label = _string(aria_label, "section aria label")
        level = record.get("level", record.get("heading_level", 2))
        if not isinstance(level, int) or isinstance(level, bool) or not 1 <= level <= 6:
            raise HtmlEditionError("HTML_EDITION_SCHEMA_DIAGNOSTIC", "invalid heading level")
        raw_body = record.get("body")
        if isinstance(raw_body, str):
            body: str | BodySourceRef = _string(raw_body, "section body")
            if len(body.encode()) > MAX_BODY_BYTES:
                raise HtmlEditionError("HTML_EDITION_SCHEMA_DIAGNOSTIC", "body exceeds size limit")
        elif isinstance(raw_body, dict) and raw_body.get("schema") == BODY_SCHEMA:
            body = BodySourceRef.parse(raw_body)
        elif isinstance(raw_body, dict) and set(raw_body) == {"format", "value"} and raw_body.get("format") == "markdown":
            body = _string(raw_body.get("value"), "section body")
        else:
            raise HtmlEditionError("HTML_EDITION_SCHEMA_DIAGNOSTIC", "section body is invalid")
        resource_values = record.get("resource_ids", record.get("resources", []))
        if not isinstance(resource_values, list):
            raise HtmlEditionError("HTML_EDITION_SCHEMA_DIAGNOSTIC", "section resources are invalid")
        resources = tuple(_identifier(item, "section resource") for item in resource_values)
        if len(resources) != len(set(resources)):
            raise HtmlEditionError("HTML_EDITION_SCHEMA_DIAGNOSTIC", "duplicate section resource")
        targets_raw = record.get("targets", [])
        if not isinstance(targets_raw, list):
            raise HtmlEditionError("HTML_EDITION_SCHEMA_DIAGNOSTIC", "section targets are invalid")
        targets = tuple(_identifier(item.get("key") if isinstance(item, dict) else item, "target") for item in targets_raw)
        if len(targets) != len(set(targets)):
            raise HtmlEditionError("HTML_EDITION_SCHEMA_DIAGNOSTIC", "duplicate target")
        steps_raw = record.get("component_steps", record.get("steps", []))
        if not isinstance(steps_raw, list) or not all(isinstance(step, dict) for step in steps_raw):
            raise HtmlEditionError("HTML_EDITION_SCHEMA_DIAGNOSTIC", "section steps are invalid")
        steps = tuple(steps_raw)
        css = record.get("css")
        if css is not None:
            css = _string(css, "section css")
        return cls(section_id, kind, title, aria_label, level, body, resources, targets, steps, css)


@dataclass(frozen=True)
class ContentDocument:
    document_key: str
    mode: str
    metadata: dict[str, Any]
    theme_id: str
    token_overrides: dict[str, str]
    sections: tuple[Section, ...]
    resources: tuple[Resource, ...]
    features: dict[str, bool]
    graph_scope: dict[str, Any] | None
    source: dict[str, Any]

    @classmethod
    def parse(cls, value: Any) -> "ContentDocument":
        record = _object(_json_value(value, "content document"), "content document")
        _reject_unknown(record, {"schema", "document_key", "mode", "metadata", "theme_id", "theme", "token_overrides", "sections", "resources", "features", "graph_scope", "diegesis_binding"}, "content document")
        if record.get("schema") != CONTENT_SCHEMA:
            raise HtmlEditionError("HTML_EDITION_SCHEMA_DIAGNOSTIC", "unsupported content document schema")
        document_key = _identifier(record.get("document_key"), "document key")
        mode = record.get("mode")
        if mode not in MODES:
            raise HtmlEditionError("HTML_EDITION_SCHEMA_DIAGNOSTIC", "unsupported edition mode")
        metadata = _object(record.get("metadata"), "metadata")
        _reject_unknown(metadata, {"title", "description", "authors", "language", "published_date", "disclosure"}, "metadata")
        if not isinstance(metadata.get("title"), str):
            raise HtmlEditionError("HTML_EDITION_SCHEMA_DIAGNOSTIC", "metadata title is required")
        theme_id = _identifier(record.get("theme_id", record.get("theme", "default")), "theme id")
        tokens = _object(record.get("token_overrides", {}), "token overrides")
        if not all(isinstance(key, str) and isinstance(item, str) and key.startswith("--dox-") for key, item in tokens.items()):
            raise HtmlEditionError("HTML_EDITION_SCHEMA_DIAGNOSTIC", "invalid token override")
        raw_sections = record.get("sections")
        raw_resources = record.get("resources")
        features = _object(record.get("features", {}), "features")
        if not all(isinstance(key, str) and isinstance(item, bool) for key, item in features.items()):
            raise HtmlEditionError("HTML_EDITION_SCHEMA_DIAGNOSTIC", "invalid feature")
        if not isinstance(raw_sections, list) or not raw_sections or len(raw_sections) > MAX_SECTIONS:
            raise HtmlEditionError("HTML_EDITION_SCHEMA_DIAGNOSTIC", "sections are required")
        if not isinstance(raw_resources, list) or len(raw_resources) > MAX_RESOURCES:
            raise HtmlEditionError("HTML_EDITION_SCHEMA_DIAGNOSTIC", "invalid resource count")
        sections = tuple(Section.parse(item) for item in raw_sections)
        resources = tuple(Resource.parse(item) for item in raw_resources)
        if len({item.section_id for item in sections}) != len(sections) or len({item.logical_id for item in resources}) != len(resources):
            raise HtmlEditionError("HTML_EDITION_SCHEMA_DIAGNOSTIC", "duplicate document identity")
        if mode == "graph-brief" and not isinstance(record.get("graph_scope"), dict):
            raise HtmlEditionError("HTML_EDITION_SCHEMA_DIAGNOSTIC", "graph-brief requires graph scope")
        resource_ids = {item.logical_id for item in resources}
        if any(not set(section.resources).issubset(resource_ids) for section in sections):
            raise HtmlEditionError("HTML_EDITION_SCHEMA_DIAGNOSTIC", "section references undeclared resource")
        generated_target_ids = {f"target-{section.section_id}-{target}" for section in sections for target in section.targets}
        if len(generated_target_ids) != sum(len(section.targets) for section in sections):
            raise HtmlEditionError("HTML_EDITION_SCHEMA_DIAGNOSTIC", "duplicate generated target identity")
        if sum(len(section.body.encode("utf-8")) for section in sections if isinstance(section.body, str)) > MAX_DOCUMENT_BODY_BYTES:
            raise HtmlEditionError("HTML_EDITION_BODY_LIMIT", "document bodies exceed size limit")
        return cls(document_key, mode, metadata, theme_id, dict(tokens), sections, resources, dict(features), record.get("graph_scope"), record)

    @property
    def authoring_revision(self) -> str:
        return sha256(b"doxagon-html-edition-authoring-v1\0" + canonical_json(self.source))


def load_content_document(path: Path) -> ContentDocument:
    return ContentDocument.parse(_load_serialized(path))


def load_content_document_from_fd(fd: int, suffix: str) -> ContentDocument:
    """Load a Content Document through a caller-owned, no-follow descriptor."""

    return ContentDocument.parse(_load_serialized_fd(fd, suffix))
