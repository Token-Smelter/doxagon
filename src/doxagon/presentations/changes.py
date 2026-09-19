"""Document-scoped changes: one atomic, multi-file edit that lands as one revision.

A skill-backed agent editing a communication document often has to touch
several files at once — markup, a controller, a note, and the manifest's claim
bindings for the same cue — and needs them to land together or not at all. The
only legal write path is the store's own: stage a private candidate of HEAD,
apply every write, validate, promote atomically. Nothing here ever opens a
promoted revision directory for writing; the audit record lives beside the
store, outside revision identity.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping

from .contracts import MANIFEST_KEY, MAX_SOURCE_BYTES, RECEIPT_ROOT, _relative_key
from .errors import PresentationError, WorkspaceError
from .store import RevisionStore, now, revision_directory, write_bytes, write_json
from .validator import validate_presentation
from .workspace import require_match

CHANGE_SCHEMA = "doxagon.document-change/1"
CHANGE_RECORD_SCHEMA = "doxagon.document-change-record/1"
AUTHORING_DIR = "authoring"
MAX_CHANGE_KEYS = 256
MAX_SUMMARY_CHARS = 4096


@dataclass(frozen=True)
class DocumentChange:
    """Everything one agent edit asks for, checked before any lock is taken."""

    expected_revision: str
    writes: Mapping[str, bytes]
    deletes: tuple[str, ...]
    manifest: Mapping[str, Any] | None
    summary: str

    def __post_init__(self) -> None:
        if len(self.writes) + len(self.deletes) > MAX_CHANGE_KEYS:
            raise WorkspaceError("PRES_AUTHORING_LIMIT", f"a change may touch at most {MAX_CHANGE_KEYS} keys", status=422)
        if len(self.summary) > MAX_SUMMARY_CHARS:
            raise WorkspaceError("PRES_AUTHORING_LIMIT", "the change summary exceeds the length limit", status=422)
        for key in (*self.writes, *self.deletes):
            _checked_key(key)
        for key, data in self.writes.items():
            if not isinstance(data, (bytes, bytearray)):
                raise WorkspaceError("PRES_AUTHORING_INVALID", f"write {key!r} must carry bytes", status=422)
            if len(data) > MAX_SOURCE_BYTES:
                raise WorkspaceError("PRES_AUTHORING_LIMIT", f"write {key!r} exceeds the source size limit", status=422)
        if self.manifest is not None and not isinstance(self.manifest, Mapping):
            raise WorkspaceError("PRES_AUTHORING_INVALID", "the manifest replacement must be an object", status=422)


@dataclass(frozen=True)
class ChangeOutcome:
    before_revision: str
    after_revision: str
    receipt: dict[str, Any]
    written: tuple[str, ...]
    deleted: tuple[str, ...]
    summary: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": CHANGE_RECORD_SCHEMA,
            "before_revision": self.before_revision,
            "after_revision": self.after_revision,
            "written": list(self.written),
            "deleted": list(self.deleted),
            "summary": self.summary,
            "receipt_sha256": self.receipt.get("compose_hash"),
            "recorded_at": now(),
        }


def _checked_key(key: str) -> str:
    try:
        checked = _relative_key(key, "", "change key")
    except PresentationError as error:
        raise WorkspaceError(error.diagnostic.code, error.diagnostic.message, status=422) from error
    # The manifest changes only through the `manifest` member, and receipts are
    # minted by promotion; a raw write to either would forge revision identity.
    if checked == MANIFEST_KEY or checked.split("/", 1)[0] == RECEIPT_ROOT:
        raise WorkspaceError("PRES_AUTHORING_KEY_RESERVED", f"{checked!r} is not an authored file", status=422)
    return checked


def _stage(root: Path, change: DocumentChange) -> None:
    for key in change.deletes:
        target = root / key
        if not target.is_file():
            raise WorkspaceError("PRES_AUTHORING_KEY_ABSENT", f"{key!r} is not in this revision", status=409)
        target.unlink()
    for key, data in change.writes.items():
        target = root / key
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink():
            raise WorkspaceError("PRES_AUTHORING_KEY_RESERVED", f"{key!r} is a link, not an authored file", status=422)
        write_bytes(target, bytes(data))
    if change.manifest is not None:
        # `revision` is calculated by promotion; a caller's value is discarded so
        # a stale or forged identity cannot be smuggled through a replacement.
        write_json(root / MANIFEST_KEY, {key: value for key, value in change.manifest.items() if key != "revision"})


def plan_document_change(store: RevisionStore, change: DocumentChange) -> dict[str, Any]:
    """Stage and validate without promoting; the candidate is discarded."""

    with store.exclusive():
        current = store.revision
        require_match(f'"{change.expected_revision}"', current)
        with store.candidate() as root:
            _stage(root, change)
            result = validate_presentation(root, policy=store.policy)
    return {
        "schema": CHANGE_SCHEMA,
        "ok": result.ok,
        "before_revision": current,
        "revision_if_promoted": result.revision,
        "diagnostics": [item.as_dict() for item in result.diagnostics],
    }


def apply_document_change(store: RevisionStore, change: DocumentChange) -> ChangeOutcome:
    """Land one whole change as one revision, or refuse it whole."""

    with store.exclusive():
        current = store.revision
        require_match(f'"{change.expected_revision}"', current)
        with store.candidate() as root:
            _stage(root, change)
            promotion = store.promote(root)
    outcome = ChangeOutcome(current, promotion.revision, promotion.receipt, tuple(change.writes), change.deletes, change.summary)
    records = store.root / AUTHORING_DIR
    records.mkdir(exist_ok=True)
    write_json(records / f"{revision_directory(promotion.revision)}.json", outcome.as_dict())
    return outcome


def change_from_document(document: Mapping[str, Any]) -> DocumentChange:
    """Decode the CLI/API change file; text writes are UTF-8, binaries base64."""

    if not isinstance(document, Mapping):
        raise WorkspaceError("PRES_AUTHORING_INVALID", "a change must be an object", status=422)
    unknown = set(document) - {"schema", "expected_revision", "writes", "writes_base64", "deletes", "manifest", "summary"}
    if unknown:
        raise WorkspaceError("PRES_AUTHORING_INVALID", f"a change cannot declare {sorted(unknown)[0]!r}", status=422)
    if document.get("schema", CHANGE_SCHEMA) != CHANGE_SCHEMA:
        raise WorkspaceError("PRES_AUTHORING_INVALID", f"a change must declare schema {CHANGE_SCHEMA!r}", status=422)
    expected = document.get("expected_revision")
    if not isinstance(expected, str) or not expected:
        raise WorkspaceError("PRES_AUTHORING_INVALID", "a change must name the revision it was authored against", status=422)
    writes: dict[str, bytes] = {}
    for key, text in (document.get("writes") or {}).items():
        if not isinstance(text, str):
            raise WorkspaceError("PRES_AUTHORING_INVALID", f"write {key!r} must be text", status=422)
        writes[str(key)] = text.encode("utf-8")
    for key, encoded in (document.get("writes_base64") or {}).items():
        if key in writes:
            raise WorkspaceError("PRES_AUTHORING_INVALID", f"write {key!r} is declared twice", status=422)
        try:
            writes[str(key)] = base64.b64decode(str(encoded), validate=True)
        except (ValueError, TypeError) as error:
            raise WorkspaceError("PRES_AUTHORING_INVALID", f"write {key!r} is not valid base64", status=422) from error
    deletes = document.get("deletes") or []
    if not isinstance(deletes, list) or not all(isinstance(item, str) for item in deletes):
        raise WorkspaceError("PRES_AUTHORING_INVALID", "deletes must be a list of keys", status=422)
    summary = document.get("summary", "")
    if not isinstance(summary, str):
        raise WorkspaceError("PRES_AUTHORING_INVALID", "summary must be text", status=422)
    return DocumentChange(expected, writes, tuple(deletes), document.get("manifest"), summary)


def read_change_file(path: Path) -> DocumentChange:
    try:
        return change_from_document(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise WorkspaceError("PRES_AUTHORING_INVALID", f"change file could not be read: {error}", status=422) from error


__all__ = [
    "AUTHORING_DIR",
    "CHANGE_SCHEMA",
    "ChangeOutcome",
    "DocumentChange",
    "apply_document_change",
    "change_from_document",
    "plan_document_change",
    "read_change_file",
]
