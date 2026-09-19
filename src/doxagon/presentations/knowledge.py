"""Pinned knowledge closures: the vault records a revision relies on, frozen.

A closure is an immutable snapshot of exactly the doxai, evidence, diegeses,
and relations a rendering cites, carried inside the revision tree so that
verifying a promoted revision never reads a live vault. A doxa can change its
status tomorrow; the receipt for yesterday's revision must still recompute.

Live drift assessment — comparing a closure against the vault as it is now —
is a separate service with its own output and must not be wired into
``validate_presentation``.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import re
from typing import Any, Mapping

from doxagon.html_editions.contracts import canonical_json, sha256

from .contracts import (
    MAX_STRING_CHARS,
    _TIMESTAMP,
    _closed,
    _digest,
    _duplicate_free,
    _object,
    _string,
    _unique,
    child,
    pointer,
)
from .errors import PresentationError, fail

KNOWLEDGE_CLOSURE_SCHEMA = "doxagon.knowledge-closure/1"
CLOSURE_DOMAIN = b"doxagon-knowledge-closure/v1\0"
MAX_CLOSURE_BYTES = 4 * 1024 * 1024
MAX_CLOSURE_ITEMS = 4096
CLAIM_STATUSES = frozenset({"unassessed", "supported", "qualified", "contested"})
_INVALID = "PRES_KNOWLEDGE_CLOSURE_INVALID"

# One prefix per record kind, so an evidence id cannot masquerade as a doxa.
_DOXA_ID = re.compile(r"d-[a-z0-9][a-z0-9-]{0,127}\Z")
_EVIDENCE_ID = re.compile(r"e-[a-z0-9][a-z0-9-]{0,127}\Z")
_DIEGESIS_ID = re.compile(r"n-[a-z0-9][a-z0-9-]{0,127}\Z")


def _prefixed(value: Any, expression: re.Pattern[str], at: str, subject: str) -> str:
    text = _string(value, at, subject)
    if expression.fullmatch(text) is None:
        fail(_INVALID, f"{subject} {text!r} does not carry the required prefix", at)
    return text


def _records(value: Any, at: str, subject: str) -> list[Any]:
    if not isinstance(value, list) or len(value) > MAX_CLOSURE_ITEMS:
        fail(_INVALID, f"{subject} must be a bounded array", at)
    return value


@dataclass(frozen=True)
class ClosureDoxa:
    doxa_id: str
    belief: str
    status: str
    confidence: float | None
    sha256: str

    @classmethod
    def parse(cls, value: Any, at: str) -> "ClosureDoxa":
        record = _object(value, at, "closure doxa")
        _closed(record, {"id", "belief", "status", "confidence", "sha256"}, at, "closure doxa")
        confidence = record.get("confidence")
        if confidence is not None:
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not math.isfinite(confidence):
                fail(_INVALID, "closure doxa confidence must be a finite number", child(at, "confidence"))
            if not 0 <= confidence <= 1:
                fail(_INVALID, "closure doxa confidence must lie within [0, 1]", child(at, "confidence"))
            confidence = float(confidence)
        return cls(
            _prefixed(record.get("id"), _DOXA_ID, child(at, "id"), "closure doxa id"),
            _string(record.get("belief"), child(at, "belief"), "closure doxa belief"),
            _string(record.get("status"), child(at, "status"), "closure doxa status"),
            confidence,
            _digest(record.get("sha256"), child(at, "sha256"), "closure doxa sha256"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.doxa_id, "belief": self.belief, "status": self.status, "confidence": self.confidence, "sha256": self.sha256}


@dataclass(frozen=True)
class ClosureEvidence:
    evidence_id: str
    title: str
    sha256: str

    @classmethod
    def parse(cls, value: Any, at: str) -> "ClosureEvidence":
        record = _object(value, at, "closure evidence")
        _closed(record, {"id", "title", "sha256"}, at, "closure evidence")
        return cls(
            _prefixed(record.get("id"), _EVIDENCE_ID, child(at, "id"), "closure evidence id"),
            _string(record.get("title"), child(at, "title"), "closure evidence title"),
            _digest(record.get("sha256"), child(at, "sha256"), "closure evidence sha256"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.evidence_id, "title": self.title, "sha256": self.sha256}


@dataclass(frozen=True)
class ClosureDiegesis:
    diegesis_id: str
    title: str
    sha256: str
    walks: tuple[str, ...]

    @classmethod
    def parse(cls, value: Any, at: str) -> "ClosureDiegesis":
        record = _object(value, at, "closure diegesis")
        _closed(record, {"id", "title", "sha256", "walks"}, at, "closure diegesis")
        walks = tuple(
            _string(item, child(at, "walks", index), "closure diegesis walk")
            for index, item in enumerate(_records(record.get("walks", []), child(at, "walks"), "closure diegesis walks"))
        )
        _unique(walks, child(at, "walks"), _INVALID, "closure diegesis walks")
        return cls(
            _prefixed(record.get("id"), _DIEGESIS_ID, child(at, "id"), "closure diegesis id"),
            _string(record.get("title"), child(at, "title"), "closure diegesis title"),
            _digest(record.get("sha256"), child(at, "sha256"), "closure diegesis sha256"),
            walks,
        )

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.diegesis_id, "title": self.title, "sha256": self.sha256, "walks": list(self.walks)}


@dataclass(frozen=True)
class ClosureRelation:
    source: str
    target: str
    type: str

    @classmethod
    def parse(cls, value: Any, at: str) -> "ClosureRelation":
        record = _object(value, at, "closure relation")
        _closed(record, {"source", "target", "type"}, at, "closure relation")
        return cls(
            _prefixed(record.get("source"), _DOXA_ID, child(at, "source"), "closure relation source"),
            _prefixed(record.get("target"), _DOXA_ID, child(at, "target"), "closure relation target"),
            _string(record.get("type"), child(at, "type"), "closure relation type"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {"source": self.source, "target": self.target, "type": self.type}


@dataclass(frozen=True)
class KnowledgeClosure:
    captured_at: str
    vault_id: str | None
    generation: int | None
    doxai: dict[str, ClosureDoxa]
    evidence: dict[str, ClosureEvidence]
    diegeses: dict[str, ClosureDiegesis]
    relations: tuple[ClosureRelation, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": KNOWLEDGE_CLOSURE_SCHEMA,
            "captured_at": self.captured_at,
            "source": {"vault_id": self.vault_id, "generation": self.generation},
            "doxai": [item.as_dict() for item in self.doxai.values()],
            "evidence": [item.as_dict() for item in self.evidence.values()],
            "diegeses": [item.as_dict() for item in self.diegeses.values()],
            "relations": [item.as_dict() for item in self.relations],
        }

    @property
    def digest(self) -> str:
        return sha256(CLOSURE_DOMAIN + canonical_json(self.as_dict()))


def parse_closure(raw: bytes) -> KnowledgeClosure:
    """Decode one closure file into a closed, self-contained record."""

    if len(raw) > MAX_CLOSURE_BYTES:
        fail(_INVALID, "knowledge closure exceeds the size limit")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        fail(_INVALID, "knowledge closure is not UTF-8")
    try:
        parsed = json.loads(text, object_pairs_hook=_duplicate_free)
    except json.JSONDecodeError as error:
        fail(_INVALID, f"knowledge closure is not valid JSON: {error.msg}")
    except PresentationError as error:
        fail(_INVALID, error.diagnostic.message)
    return parse_closure_record(parsed)


def parse_closure_record(value: Any) -> KnowledgeClosure:
    record = _object(value, "", "knowledge closure")
    _closed(record, {"schema", "captured_at", "source", "doxai", "evidence", "diegeses", "relations"}, "", "knowledge closure")
    if record.get("schema") != KNOWLEDGE_CLOSURE_SCHEMA:
        fail(_INVALID, f"knowledge closure schema must be {KNOWLEDGE_CLOSURE_SCHEMA!r}", pointer("schema"))
    captured_at = _string(record.get("captured_at"), pointer("captured_at"), "closure captured_at")
    if _TIMESTAMP.fullmatch(captured_at) is None:
        fail(_INVALID, "closure captured_at must be an RFC 3339 UTC timestamp", pointer("captured_at"))
    source = _object(record.get("source", {}), pointer("source"), "closure source")
    _closed(source, {"vault_id", "generation"}, pointer("source"), "closure source")
    vault_id = source.get("vault_id")
    if vault_id is not None:
        vault_id = _string(vault_id, pointer("source", "vault_id"), "closure vault_id")
        if len(vault_id) > MAX_STRING_CHARS:
            fail(_INVALID, "closure vault_id exceeds the string length limit", pointer("source", "vault_id"))
    generation = source.get("generation")
    if generation is not None and (isinstance(generation, bool) or not isinstance(generation, int) or generation < 0):
        fail(_INVALID, "closure generation must be a non-negative integer", pointer("source", "generation"))

    doxai = _indexed(record, "doxai", ClosureDoxa, "doxa_id")
    evidence = _indexed(record, "evidence", ClosureEvidence, "evidence_id")
    diegeses = _indexed(record, "diegeses", ClosureDiegesis, "diegesis_id")
    relations = tuple(
        ClosureRelation.parse(item, pointer("relations", index))
        for index, item in enumerate(_records(record.get("relations", []), pointer("relations"), "closure relations"))
    )
    # Self-contained by construction: a relation may only join doxai this
    # closure carries, so nothing in it points at a record a verifier cannot see.
    for index, relation in enumerate(relations):
        for endpoint in ("source", "target"):
            if getattr(relation, endpoint) not in doxai:
                fail(_INVALID, f"closure relation names {getattr(relation, endpoint)!r}, which is not in this closure", pointer("relations", index, endpoint))
    return KnowledgeClosure(captured_at, vault_id, generation, doxai, evidence, diegeses, relations)


def _indexed(record: Mapping[str, Any], key: str, kind: Any, attribute: str) -> dict[str, Any]:
    items = [kind.parse(item, pointer(key, index)) for index, item in enumerate(_records(record.get(key, []), pointer(key), f"closure {key}"))]
    _unique(tuple(getattr(item, attribute) for item in items), pointer(key), _INVALID, f"closure {key}")
    return {getattr(item, attribute): item for item in items}


def closure_digest(raw: bytes) -> str:
    """Digest of a closure's canonical form, independent of source formatting."""

    return parse_closure(raw).digest
