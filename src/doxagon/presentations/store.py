"""Immutable revision trees behind one atomically replaced HEAD pointer.

A promoted revision is never edited in place. Every mutation stages a complete
private candidate, validates it, and lands it under its own calculated digest;
HEAD is a single file replaced by rename, so a reader sees either the whole
previous revision or the whole next one. A candidate that fails validation is
discarded, which is what makes "a failed validation changes no source or blob"
a property of the storage layout rather than a promise in a comment.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
import fcntl
import json
import os
from pathlib import Path
import shutil
from typing import Any, Iterator
from uuid import uuid4

from doxagon.html_editions.contracts import canonical_json

from .contracts import ASSET_ROOT, DEFAULT_VALIDATION_POLICY, MANIFEST_KEY, RECEIPT_ROOT, ValidationPolicy
from .errors import WorkspaceError
from .validator import validate_presentation

HEAD_SCHEMA = "doxagon.presentation-head/2"
HEAD_KEY = "HEAD"
LOCK_KEY = "lock"
REVISIONS_DIR = "revisions"
STAGING_DIR = "staging"
DERIVED_DIR = "derived"
JOBS_DIR = "jobs"

_STORE_DIRECTORIES = (REVISIONS_DIR, STAGING_DIR, DERIVED_DIR, JOBS_DIR)


def now() -> str:
    """An RFC 3339 UTC timestamp in the exact form the manifest accepts."""

    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def revision_directory(revision: str) -> str:
    """The filesystem name for a revision; ``sha256:`` is not a path segment."""

    return revision.split(":", 1)[1]


def write_bytes(path: Path, payload: bytes) -> None:
    """Replace one file by rename so a reader never observes a partial write."""

    temporary = path.parent / f".{path.name}.{uuid4().hex}.tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        offset = 0
        while offset < len(payload):
            offset += os.write(descriptor, payload[offset:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)


def write_json(path: Path, payload: Any) -> None:
    write_bytes(path, canonical_json(payload))


def read_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_bytes())
    except FileNotFoundError:
        return None
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise WorkspaceError("PRES_STORE_CORRUPT", f"stored record is not valid JSON: {path.name}", status=500) from error


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _clone(source: str, destination: str) -> None:
    """Hardlink content-addressed blobs; give every editable file its own inode.

    Writing through a link shared with a promoted tree would rewrite history,
    so only ``assets/`` — whose bytes are immutable by digest — is linked.
    """

    if f"{os.sep}{ASSET_ROOT}{os.sep}" in source:
        os.link(source, destination)
        return
    shutil.copy2(source, destination)


@dataclass(frozen=True)
class Promotion:
    """The revision a candidate landed as, with its recomputable receipt."""

    revision: str
    receipt: dict[str, Any]


class RevisionStore:
    """Append-only revision trees plus the single HEAD pointer that selects one."""

    def __init__(self, root: Path, *, policy: ValidationPolicy = DEFAULT_VALIDATION_POLICY) -> None:
        self.root = root
        # The store carries the policy so every later promotion, receipt
        # verification, and export of this workspace validates against the same
        # budget the deck was admitted under.
        self.policy = policy

    @classmethod
    def create(cls, root: Path, *, policy: ValidationPolicy = DEFAULT_VALIDATION_POLICY) -> "RevisionStore":
        for name in _STORE_DIRECTORIES:
            (root / name).mkdir(parents=True, exist_ok=True)
        (root / LOCK_KEY).touch()
        return cls(root, policy=policy)

    @classmethod
    def open(cls, root: Path, *, policy: ValidationPolicy = DEFAULT_VALIDATION_POLICY) -> "RevisionStore":
        if not all((root / name).is_dir() for name in _STORE_DIRECTORIES):
            raise WorkspaceError("PRES_WORKSPACE_NOT_FOUND", "no presentation workspace at this root", status=404)
        return cls(root, policy=policy)

    @property
    def head(self) -> str | None:
        """The promoted revision, read without touching a single stored byte."""

        payload = read_json(self.root / HEAD_KEY)
        if payload is None:
            return None
        if not isinstance(payload, dict) or payload.get("schema") != HEAD_SCHEMA:
            raise WorkspaceError("PRES_STORE_CORRUPT", "HEAD is not a presentation head record", status=500)
        revision = payload.get("revision")
        if not isinstance(revision, str) or not self.revision_root(revision).is_dir():
            raise WorkspaceError("PRES_STORE_CORRUPT", "HEAD names no promoted revision", status=500)
        return revision

    @property
    def revision(self) -> str:
        revision = self.head
        if revision is None:
            raise WorkspaceError("PRES_WORKSPACE_EMPTY", "this workspace has no promoted revision", status=409)
        return revision

    def revision_root(self, revision: str) -> Path:
        return self.root / REVISIONS_DIR / revision_directory(revision)

    @property
    def head_root(self) -> Path:
        return self.revision_root(self.revision)

    def read_manifest(self, revision: str | None = None) -> dict[str, Any]:
        root = self.revision_root(revision) if revision else self.head_root
        manifest = read_json(root / MANIFEST_KEY)
        if not isinstance(manifest, dict):
            raise WorkspaceError("PRES_STORE_CORRUPT", "promoted manifest is unreadable", status=500)
        return manifest

    def read_receipt(self, revision: str | None = None) -> dict[str, Any]:
        target = revision or self.revision
        receipt = read_json(self.revision_root(target) / RECEIPT_ROOT / f"{revision_directory(target)}.validation.json")
        if not isinstance(receipt, dict):
            raise WorkspaceError("PRES_STORE_CORRUPT", "promoted receipt is unreadable", status=500)
        return receipt

    @contextmanager
    def exclusive(self) -> Iterator[None]:
        """Serialize promotion so two matching writers cannot both land."""

        descriptor = os.open(self.root / LOCK_KEY, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            os.close(descriptor)

    @contextmanager
    def candidate(self) -> Iterator[Path]:
        """Stage a complete private copy of HEAD and discard it unless promoted."""

        path = self.root / STAGING_DIR / uuid4().hex
        try:
            head = self.head
            if head is None:
                path.mkdir(parents=True)
            else:
                # symlinks are copied as symlinks so validation refuses them at
                # the syscall boundary instead of silently absorbing their target.
                shutil.copytree(self.head_root, path, symlinks=True, copy_function=_clone)
                shutil.rmtree(path / RECEIPT_ROOT, ignore_errors=True)
            yield path
        finally:
            shutil.rmtree(path, ignore_errors=True)

    def promote(self, candidate: Path) -> Promotion:
        """Validate a complete candidate, then land it and HEAD atomically."""

        result = validate_presentation(candidate, policy=self.policy)
        if not result.ok:
            raise WorkspaceError(
                "PRES_VALIDATION_FAILED",
                "candidate revision failed validation",
                status=422,
                diagnostics=result.diagnostics,
            )
        revision = result.revision
        manifest = self._candidate_manifest(candidate)
        # `revision` is calculated, never chosen: it is pinned into the manifest
        # only after the validator derived it, and it is excluded from its own
        # digest, so re-validating the pinned tree must reproduce it exactly.
        manifest["revision"] = revision
        write_json(candidate / MANIFEST_KEY, manifest)
        confirmed = validate_presentation(candidate, policy=self.policy)
        if not confirmed.ok or confirmed.revision != revision:
            raise WorkspaceError(
                "PRES_REVISION_UNSTABLE",
                "the calculated revision did not reproduce",
                status=500,
                diagnostics=confirmed.diagnostics,
            )
        receipt = confirmed.receipt
        receipt_root = candidate / RECEIPT_ROOT
        receipt_root.mkdir(parents=True, exist_ok=True)
        write_bytes(receipt_root / f"{revision_directory(revision)}.validation.json", receipt.canonical_bytes())

        target = self.revision_root(revision)
        if target.exists():
            # An identical revision is already promoted; a revision is its
            # content, so re-landing it would be the same bytes under the same name.
            shutil.rmtree(candidate)
        else:
            os.rename(candidate, target)
            fsync_directory(target.parent)
        self._set_head(revision)
        return Promotion(revision, receipt.as_dict())

    def _candidate_manifest(self, candidate: Path) -> dict[str, Any]:
        manifest = read_json(candidate / MANIFEST_KEY)
        if not isinstance(manifest, dict):
            raise WorkspaceError("PRES_MANIFEST_INVALID_JSON", "candidate manifest is unreadable", status=422)
        return manifest

    def _set_head(self, revision: str) -> None:
        write_json(self.root / HEAD_KEY, {"schema": HEAD_SCHEMA, "revision": revision, "promoted_at": now()})
        fsync_directory(self.root)
