"""Closed public graph/evidence projections; raw producer objects never pass through."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any
from urllib.parse import urlsplit

from .contracts import PUBLIC_GRAPH_SCHEMA
from .errors import HtmlEditionError

_PATHLIKE = re.compile(r"(?:^|[\s:])(?:/|~[/\\]|[A-Za-z]:[\\/]|file:|\.\./)", re.I)


def _closed(record: Any, allowed: set[str], subject: str, *, url_fields: frozenset[str] = frozenset()) -> dict[str, Any]:
    if not isinstance(record, dict) or set(record).difference(allowed):
        raise HtmlEditionError("HTML_EDITION_PUBLIC_PROJECTION_REJECTED", f"{subject} is not closed")
    for key, value in record.items():
        if key not in url_fields:
            _safe_value(value, subject)
    return record


def _https_url(value: Any) -> str:
    if not isinstance(value, str) or any(character.isspace() or ord(character) < 32 for character in value):
        raise HtmlEditionError("HTML_EDITION_PUBLIC_PROJECTION_REJECTED", "public evidence URL is invalid")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise HtmlEditionError("HTML_EDITION_PUBLIC_PROJECTION_REJECTED", "public evidence URL is invalid") from error
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment or "\\" in value or port is not None and not 0 < port < 65536:
        raise HtmlEditionError("HTML_EDITION_PUBLIC_PROJECTION_REJECTED", "public evidence URL is invalid")
    return value


def _safe_value(value: Any, subject: str) -> None:
    if value is None or isinstance(value, bool) or isinstance(value, int):
        return
    if isinstance(value, float):
        if math.isfinite(value):
            return
    elif isinstance(value, str):
        if _PATHLIKE.search(value):
            raise HtmlEditionError("HTML_EDITION_PUBLIC_PROJECTION_REJECTED", f"{subject} contains private path-like data")
        return
    elif isinstance(value, list):
        for nested in value:
            _safe_value(nested, subject)
        return
    elif isinstance(value, dict) and all(isinstance(key, str) for key in value):
        for nested in value.values():
            _safe_value(nested, subject)
        return
    raise HtmlEditionError("HTML_EDITION_PUBLIC_PROJECTION_REJECTED", f"{subject} is not JSON-compatible")


@dataclass(frozen=True)
class PublicEvidenceV1:
    value: dict[str, Any]

    @classmethod
    def parse(cls, value: Any) -> "PublicEvidenceV1":
        record = _closed(
            value,
            {"id", "assertion", "source_label", "source_url", "type", "strength", "status", "summary_or_quote", "annotations", "gaps", "content_excerpt", "corrections"},
            "public evidence",
            url_fields=frozenset({"source_url"}),
        )
        if not all(isinstance(record.get(key), str) for key in ("id", "assertion", "source_label", "type", "strength", "status", "summary_or_quote")):
            raise HtmlEditionError("HTML_EDITION_PUBLIC_PROJECTION_REJECTED", "public evidence is incomplete")
        if record.get("status") not in {"provisional", "validated", "retracted", "superseded"}:
            raise HtmlEditionError("HTML_EDITION_PUBLIC_PROJECTION_REJECTED", "public evidence status is invalid")
        if "source_url" in record:
            _https_url(record["source_url"])
        return cls(record)


@dataclass(frozen=True)
class PublicEdgeV1:
    value: dict[str, Any]

    @classmethod
    def parse(cls, value: Any) -> "PublicEdgeV1":
        record = _closed(
            value,
            {"source_id", "target_id", "type", "alias", "rationale", "annotation", "strength", "confidence", "disputed", "reviewer_notes", "created", "corrections", "provenance"},
            "public edge",
        )
        if not all(isinstance(record.get(key), str) for key in ("source_id", "target_id", "type")):
            raise HtmlEditionError("HTML_EDITION_PUBLIC_PROJECTION_REJECTED", "public edge is incomplete")
        return cls(record)


@dataclass(frozen=True)
class PublicNodeV1:
    value: dict[str, Any]

    @classmethod
    def parse(cls, value: Any) -> "PublicNodeV1":
        record = _closed(value, {"id", "title", "belief", "tags"}, "public node")
        if not isinstance(record.get("id"), str) or not isinstance(record.get("belief"), str) or ("tags" in record and (not isinstance(record["tags"], list) or record["tags"] != sorted(record["tags"]))):
            raise HtmlEditionError("HTML_EDITION_PUBLIC_PROJECTION_REJECTED", "public node is invalid")
        return cls(record)


@dataclass(frozen=True)
class PublicGraphExcerptV1:
    nodes: tuple[PublicNodeV1, ...]
    edges: tuple[PublicEdgeV1, ...]
    evidence: tuple[PublicEvidenceV1, ...]
    scope: dict[str, Any]

    @classmethod
    def parse(cls, value: Any) -> "PublicGraphExcerptV1":
        record = _closed(value, {"schema", "nodes", "edges", "evidence", "scope", "truncated", "disclosure", "diegesis_binding"}, "public graph")
        if record.get("schema") != PUBLIC_GRAPH_SCHEMA or not isinstance(record.get("nodes"), list) or not isinstance(record.get("edges"), list) or not isinstance(record.get("evidence"), list) or not isinstance(record.get("scope"), dict):
            raise HtmlEditionError("HTML_EDITION_PUBLIC_PROJECTION_REJECTED", "public graph is invalid")
        return cls(tuple(PublicNodeV1.parse(item) for item in record["nodes"]), tuple(PublicEdgeV1.parse(item) for item in record["edges"]), tuple(PublicEvidenceV1.parse(item) for item in record["evidence"]), record["scope"])
