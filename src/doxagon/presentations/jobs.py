"""Durable lifecycle records for generation and thumbnail work.

Every job is a file, not a process-local dictionary entry: a reader in a new
process sees the same status, request, and outputs a crashed writer left
behind, and a retry is a first-class record that names the attempt it replaces.
Nothing here mutates a revision; a job only records what was asked, what
happened, and which immutable assets resulted.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
import fcntl
import os
from pathlib import Path
from typing import Any, Iterable, Iterator
from uuid import uuid4

from doxagon.html_editions.contracts import canonical_json, sha256

from .errors import WorkspaceError
from .store import JOBS_DIR, now, read_json, write_json

JOB_SCHEMA = "doxagon.presentation-job/1"

GENERATION_KIND = "generation"
THUMBNAIL_KIND = "thumbnail"
JOB_KINDS = frozenset({GENERATION_KIND, THUMBNAIL_KIND})

PENDING = "pending"
RUNNING = "running"
SUCCEEDED = "succeeded"
FAILED = "failed"
TERMINAL = frozenset({SUCCEEDED, FAILED})

_KEYS_DIR = "keys"
_KEYS_LOCK = "lock"
_MAX_KEY_CHARS = 200


@dataclass(frozen=True)
class JobRecord:
    """One durable unit of asynchronous work and everything it produced."""

    job_id: str
    kind: str
    status: str
    idempotency_key: str
    fingerprint: str
    base_revision: str
    request: dict[str, Any]
    outputs: tuple[dict[str, Any], ...] = ()
    failures: tuple[dict[str, Any], ...] = ()
    error: dict[str, Any] | None = None
    revision: str | None = None
    retry_of: str | None = None
    attempt: int = 1
    created_at: str = ""
    updated_at: str = ""
    lineage: str = ""

    @property
    def lineage_id(self) -> str:
        """The originating job every retry of this request descends from.

        Generated asset identity is bound to this value, so a retry must keep
        the lineage it replaces while an independently submitted job — even one
        asking for byte-identical work — must not borrow it.
        """

        return self.lineage or self.job_id

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": JOB_SCHEMA,
            "job_id": self.job_id,
            "kind": self.kind,
            "status": self.status,
            "idempotency_key": self.idempotency_key,
            "fingerprint": self.fingerprint,
            "base_revision": self.base_revision,
            "request": dict(self.request),
            "outputs": [dict(item) for item in self.outputs],
            "failures": [dict(item) for item in self.failures],
            "error": None if self.error is None else dict(self.error),
            "revision": self.revision,
            "retry_of": self.retry_of,
            "attempt": self.attempt,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "lineage": self.lineage_id,
        }

    @classmethod
    def parse(cls, payload: Any) -> "JobRecord":
        if not isinstance(payload, dict) or payload.get("schema") != JOB_SCHEMA:
            raise WorkspaceError("PRES_STORE_CORRUPT", "stored job is not a job record", status=500)
        return cls(
            payload["job_id"],
            payload["kind"],
            payload["status"],
            payload["idempotency_key"],
            payload["fingerprint"],
            payload["base_revision"],
            dict(payload.get("request") or {}),
            tuple(payload.get("outputs") or ()),
            tuple(payload.get("failures") or ()),
            payload.get("error"),
            payload.get("revision"),
            payload.get("retry_of"),
            int(payload.get("attempt", 1)),
            payload.get("created_at", ""),
            payload.get("updated_at", ""),
            str(payload.get("lineage") or payload["job_id"]),
        )

    @property
    def asset_ids(self) -> tuple[str, ...]:
        return tuple(str(item["asset_id"]) for item in self.outputs if "asset_id" in item)


def fingerprint_of(kind: str, request: Any, base_revision: str) -> str:
    return sha256(
        b"doxagon-presentation-job/v1\0"
        + canonical_json({"kind": kind, "request": request, "base_revision": base_revision})
    )


def _chronological(record: JobRecord) -> tuple[str, str, int, str]:
    """Order one listing: by time, and inside one second by attempt.

    ``now()`` has one-second resolution, so a retry submitted immediately after
    the attempt it replaces carries the identical ``created_at``. Breaking that
    tie on the random job id would order attempt 2 before attempt 1 about half
    the time. The lineage groups every attempt of one request and ``attempt``
    orders them within it, so a retry always follows what it retries; two
    independent requests fall back to their durable lineage and job ids, which
    are fixed on disk and give every reader the same order.
    """

    return (record.created_at, record.lineage_id, record.attempt, record.job_id)


class JobStore:
    """File-backed job records; every read reloads from durable storage."""

    def __init__(self, root: Path) -> None:
        self.root = root / JOBS_DIR
        self.keys = self.root / _KEYS_DIR

    def _path(self, job_id: str) -> Path:
        if not job_id or len(job_id) != 32 or any(character not in "0123456789abcdef" for character in job_id):
            raise WorkspaceError("PRES_JOB_NOT_FOUND", "no such job", status=404)
        return self.root / f"{job_id}.json"

    def get(self, job_id: str) -> JobRecord:
        payload = read_json(self._path(job_id))
        if payload is None:
            raise WorkspaceError("PRES_JOB_NOT_FOUND", "no such job", status=404)
        return JobRecord.parse(payload)

    def lookup(self, idempotency_key: str) -> JobRecord | None:
        """Read an existing keyed request without creating a job or directory."""
        return self._existing(idempotency_key)

    def list(self, *, kind: str | None = None) -> tuple[JobRecord, ...]:
        records = [JobRecord.parse(read_json(path)) for path in sorted(self.root.glob("*.json"))]
        selected = [record for record in records if kind is None or record.kind == kind]
        return tuple(sorted(selected, key=_chronological))

    def submit(self, kind: str, idempotency_key: str, request: Any, base_revision: str) -> JobRecord:
        """Create a job, or replay the one this idempotency key already made."""

        if kind not in JOB_KINDS:
            raise WorkspaceError("PRES_JOB_KIND_UNSUPPORTED", f"job kind {kind!r} is not supported")
        if not isinstance(idempotency_key, str) or not 0 < len(idempotency_key) <= _MAX_KEY_CHARS:
            raise WorkspaceError("PRES_JOB_KEY_INVALID", "idempotency key must be a bounded non-empty string")
        fingerprint = fingerprint_of(kind, request, base_revision)
        with self._keyed():
            existing = self._existing(idempotency_key)
            if existing is not None:
                if existing.fingerprint != fingerprint:
                    # Replaying one key with different work would silently discard
                    # one of the two requests; the caller must choose a new key.
                    raise WorkspaceError(
                        "PRES_JOB_KEY_CONFLICT",
                        "this idempotency key already names different work",
                        status=409,
                        revision=existing.base_revision,
                    )
                return existing
            moment = now()
            job_id = uuid4().hex
            record = JobRecord(
                job_id,
                kind,
                PENDING,
                idempotency_key,
                fingerprint,
                base_revision,
                dict(request) if isinstance(request, dict) else {"value": request},
                created_at=moment,
                updated_at=moment,
                lineage=job_id,
            )
            self._write(record)
            write_json(self._key_path(idempotency_key), {"job_id": record.job_id})
            return record

    def start(self, job_id: str) -> JobRecord:
        record = self.get(job_id)
        if record.status != PENDING:
            raise WorkspaceError("PRES_JOB_NOT_PENDING", f"job is {record.status}, not pending", status=409)
        return self._update(record, status=RUNNING)

    def succeed(
        self,
        job_id: str,
        *,
        outputs: Iterable[dict[str, Any]] = (),
        failures: Iterable[dict[str, Any]] = (),
        revision: str | None = None,
    ) -> JobRecord:
        return self._update(
            self.get(job_id), status=SUCCEEDED, outputs=tuple(outputs), failures=tuple(failures), revision=revision
        )

    def progress(self, job_id: str, *, outputs=(), failures=()) -> JobRecord:
        """Persist partial results before the next external operation."""
        record = self.get(job_id)
        if record.status != RUNNING:
            raise WorkspaceError("PRES_JOB_NOT_RUNNING", "Only a running job can report progress", status=409)
        return self._update(record, outputs=tuple(outputs), failures=tuple(failures))

    def fail(
        self,
        job_id: str,
        code: str,
        message: str,
        *,
        outputs: Iterable[dict[str, Any]] = (),
        failures: Iterable[dict[str, Any]] = (),
    ) -> JobRecord:
        return self._update(
            self.get(job_id),
            status=FAILED,
            outputs=tuple(outputs),
            failures=tuple(failures),
            error={"code": code, "message": message},
        )

    def retry(self, job_id: str, base_revision: str) -> JobRecord:
        """Re-submit failed work against the revision that is current now."""

        record = self.get(job_id)
        if record.status != FAILED:
            raise WorkspaceError("PRES_JOB_NOT_RETRYABLE", f"a {record.status} job is not retryable", status=409)
        attempt = record.attempt + 1
        key = f"{record.idempotency_key}#retry-{attempt}"
        with self._keyed():
            existing = self._existing(key)
            if existing is not None:
                # Two callers retrying the same failed attempt asked for one
                # retry, so they receive the one retry that attempt has.
                return existing
            moment = now()
            retry = JobRecord(
                uuid4().hex,
                record.kind,
                PENDING,
                key,
                fingerprint_of(record.kind, record.request, base_revision),
                base_revision,
                dict(record.request),
                retry_of=record.job_id,
                attempt=attempt,
                created_at=moment,
                updated_at=moment,
                lineage=record.lineage_id,
            )
            self._write(retry)
            write_json(self._key_path(key), {"job_id": retry.job_id})
            return retry

    @contextmanager
    def _keyed(self) -> Iterator[None]:
        """Serialize keyed creation: one idempotency key, one durable job.

        Resolving a key and writing the job it names are two steps. Two
        submissions that interleave between them would each read "no job yet"
        and each persist one, leaving a key that points at a job whose twin is
        already running.
        """

        self.keys.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.keys / _KEYS_LOCK, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            os.close(descriptor)

    def _existing(self, idempotency_key: str) -> JobRecord | None:
        pointer = read_json(self._key_path(idempotency_key))
        if pointer is None:
            return None
        return self.get(str(pointer["job_id"]))

    def _key_path(self, idempotency_key: str) -> Path:
        return self.keys / f"{sha256(idempotency_key.encode('utf-8'))}.json"

    def _update(self, record: JobRecord, **changes: Any) -> JobRecord:
        if record.status in TERMINAL:
            raise WorkspaceError("PRES_JOB_TERMINAL", f"job is already {record.status}", status=409)
        updated = replace(record, updated_at=now(), **changes)
        self._write(updated)
        return updated

    def _write(self, record: JobRecord) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        write_json(self._path(record.job_id), record.as_dict())
