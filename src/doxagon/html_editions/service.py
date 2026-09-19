"""Fence-owned durable coordination for HTML Edition publication."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
import secrets
import sqlite3
import stat
import time
from threading import RLock
from typing import Any, Iterator
from uuid import uuid4

from doxagon.wal import RecoveryUnresolved, read_authority_generation
from doxagon.workspace import Capability, Ready, WorkspaceOpenRequest, open_workspace

from .cli import _document_location
from .compiler import BuildResult, HtmlEditionCompiler, _read_regular, _resource_mime
from .contracts import ContentDocument, _stat_identity, canonical_json, load_content_document_from_fd, sha256
from .errors import HtmlEditionError
from .inspector import inspect_edition_bytes

_IDENTIFIER = "abcdefghijklmnopqrstuvwxyz0123456789-"
_TERMINAL = frozenset({"published", "cancelled", "failed"})
_BUILD_CAPABILITIES = frozenset(
    {Capability.JOB_RUN, Capability.PUBLICATION_BUILD, Capability.ARTIFACT_PROMOTE}
)


class HtmlEditionServiceError(HtmlEditionError):
    """A deliberately path-free coordinator diagnostic."""


@dataclass(frozen=True)
class Job:
    job_id: str
    state: str
    idempotency_key: str
    project: str
    document: str
    retry_of: str | None
    edition_id: str | None
    file_sha256: str | None
    error: str | None
    created_at: str
    updated_at: str

    def public(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "state": self.state,
            "project": self.project,
            "document": self.document,
            "retry_of": self.retry_of,
            "edition_id": self.edition_id,
            "file_sha256": self.file_sha256,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _safe_identifier(value: str, subject: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 64 or any(character not in _IDENTIFIER for character in value):
        raise HtmlEditionServiceError("HTML_EDITION_REQUEST_INVALID", f"invalid {subject}")
    return value


def _open_private_directory(parent_fd: int, name: str, *, create: bool = False) -> int:
    """Open one retained, no-follow child directory."""

    if create:
        try:
            os.mkdir(name, 0o700, dir_fd=parent_fd)
        except FileExistsError:
            pass
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
    except OSError as error:
        raise HtmlEditionServiceError("HTML_EDITION_STORAGE_UNSAFE", "configured storage is unavailable") from error
    if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise HtmlEditionServiceError("HTML_EDITION_STORAGE_UNSAFE", "configured storage is unavailable")
    return descriptor


def _repair_interrupted_publication(directory_fd: int, name: str) -> None:
    """Remove the writer-owned temporary link left after a link/unlink crash."""

    try:
        final = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    if not stat.S_ISREG(final.st_mode) or final.st_nlink == 1:
        if stat.S_ISREG(final.st_mode):
            return
        raise HtmlEditionServiceError("HTML_EDITION_ARTIFACT_DIVERGED", "artifact identity diverged")
    if final.st_nlink != 2:
        raise HtmlEditionServiceError("HTML_EDITION_ARTIFACT_DIVERGED", "artifact identity diverged")
    prefix, suffix = f".{name}.", ".tmp"
    matches: list[str] = []
    for candidate in os.listdir(directory_fd):
        if not candidate.startswith(prefix) or not candidate.endswith(suffix):
            continue
        snapshot = os.stat(candidate, dir_fd=directory_fd, follow_symlinks=False)
        if (snapshot.st_dev, snapshot.st_ino) == (final.st_dev, final.st_ino):
            matches.append(candidate)
    if len(matches) != 1:
        raise HtmlEditionServiceError("HTML_EDITION_ARTIFACT_DIVERGED", "artifact identity diverged")
    os.unlink(matches[0], dir_fd=directory_fd)
    os.fsync(directory_fd)


def _open_private_regular(directory_fd: int, name: str) -> int:
    _repair_interrupted_publication(directory_fd, name)
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
    except FileNotFoundError:
        raise
    except OSError as error:
        raise HtmlEditionServiceError("HTML_EDITION_ARTIFACT_DIVERGED", "artifact is unavailable") from error
    snapshot = os.fstat(descriptor)
    if not stat.S_ISREG(snapshot.st_mode) or snapshot.st_nlink != 1:
        os.close(descriptor)
        raise HtmlEditionServiceError("HTML_EDITION_ARTIFACT_DIVERGED", "artifact identity diverged")
    return descriptor


def _read_private_regular(directory_fd: int, name: str) -> bytes:
    descriptor = _open_private_regular(directory_fd, name)
    try:
        before = os.fstat(descriptor)
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                raise HtmlEditionServiceError("HTML_EDITION_ARTIFACT_DIVERGED", "artifact was truncated")
            chunks.append(chunk)
            remaining -= len(chunk)
        # Reading an artifact is what bumps its access time, so st_atime must
        # stay outside the identity: _stat_identity is the same stable snapshot
        # the content-document and resource readers already compare.
        if os.read(descriptor, 1) or _stat_identity(os.fstat(descriptor)) != _stat_identity(before):
            raise HtmlEditionServiceError("HTML_EDITION_ARTIFACT_DIVERGED", "artifact changed while reading")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _atomic_private_bytes(directory_fd: int, name: str, payload: bytes) -> None:
    """Create a private regular file without replacing a concurrent entry."""

    temporary = f".{name}.{uuid4().hex}.tmp"
    descriptor: int | None = None
    linked = False
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory_fd,
        )
        offset = 0
        while offset < len(payload):
            offset += os.write(descriptor, payload[offset:])
        os.fsync(descriptor)
        snapshot = os.fstat(descriptor)
        if not stat.S_ISREG(snapshot.st_mode) or snapshot.st_nlink != 1:
            raise HtmlEditionServiceError("HTML_EDITION_STORAGE_UNSAFE", "temporary artifact is unsafe")
        os.close(descriptor)
        descriptor = None
        os.link(temporary, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd, follow_symlinks=False)
        linked = True
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except FileNotFoundError:
            # A recovery reader may have removed the exact temporary link.
            _repair_interrupted_publication(directory_fd, name)
        os.fsync(directory_fd)
    except FileExistsError:
        raise
    except OSError as error:
        raise HtmlEditionServiceError("HTML_EDITION_STORAGE_UNSAFE", "artifact publication failed") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if not linked:
            try:
                os.unlink(temporary, dir_fd=directory_fd)
            except FileNotFoundError:
                pass


class HtmlEditionCoordinator:
    """The single fence-owning lifecycle for one configured workspace."""

    def __init__(self, ready: Ready) -> None:
        self.ready = ready
        self.config = ready.config
        self._closed = False
        self._database: str | None = None
        self._state_fd: int | None = None
        self._editions_fd: int | None = None
        self._publication_lock = RLock()
        self._publish_hook: Any = None  # Test-only crash/cancellation boundary injection.
        try:
            self._ensure_build_store_if_permitted()
        except BaseException:
            self.close()
            raise

    @classmethod
    def open(cls, request: WorkspaceOpenRequest) -> "HtmlEditionCoordinator":
        result = open_workspace(request)
        if not isinstance(result, Ready):
            code = {
                "not_configured": "HTML_EDITION_NOT_CONFIGURED",
                "metadata_only": "HTML_EDITION_METADATA_ONLY",
                "schema_diagnostic": "HTML_EDITION_SCHEMA_DIAGNOSTIC",
                "recovery_diagnostic": "HTML_EDITION_RECOVERY_PENDING",
            }[result.state]
            raise HtmlEditionServiceError(code, code)
        return cls(result)

    @property
    def can_build(self) -> bool:
        return _BUILD_CAPABILITIES.issubset(self.config.capabilities)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            for descriptor in (self._editions_fd, self._state_fd):
                if descriptor is not None:
                    os.close(descriptor)
            self._editions_fd = None
            self._state_fd = None
            self.ready.services.close()

    def __enter__(self) -> "HtmlEditionCoordinator":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _require_open(self) -> None:
        if self._closed:
            raise HtmlEditionServiceError("HTML_EDITION_CLOSED", "HTML Edition coordinator is closed")

    def _require(self, capabilities: frozenset[Capability]) -> None:
        self._require_open()
        if not capabilities.issubset(self.config.capabilities):
            raise HtmlEditionServiceError("HTML_EDITION_CAPABILITY_DENIED", "required workspace capability is not granted")

    def _ensure_build_store_if_permitted(self) -> None:
        if not self.can_build:
            return
        state_root_fd: int | None = None
        artifact_root_fd: int | None = None
        try:
            state_root_fd = os.open(self.config.state_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            artifact_root_fd = os.open(self.config.artifact_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            self._state_fd = _open_private_directory(state_root_fd, "html-editions", create=True)
            artifact_fd = _open_private_directory(artifact_root_fd, "html-editions", create=True)
            try:
                self._editions_fd = _open_private_directory(artifact_fd, "editions", create=True)
            finally:
                os.close(artifact_fd)
        except OSError as error:
            raise HtmlEditionServiceError("HTML_EDITION_STORAGE_UNSAFE", "configured storage root is unavailable") from error
        finally:
            if state_root_fd is not None:
                os.close(state_root_fd)
            if artifact_root_fd is not None:
                os.close(artifact_root_fd)
        if self._state_fd is None:
            raise HtmlEditionServiceError("HTML_EDITION_STORAGE_UNSAFE", "configured state is unavailable")
        try:
            descriptor = _open_private_regular(self._state_fd, "jobs.sqlite3")
            os.close(descriptor)
        except FileNotFoundError:
            pass
        self._database = f"/proc/self/fd/{self._state_fd}/jobs.sqlite3"
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    request_fingerprint TEXT NOT NULL,
                    project TEXT NOT NULL,
                    document_name TEXT NOT NULL,
                    state TEXT NOT NULL,
                    retry_of TEXT,
                    lease_owner TEXT,
                    lease_until REAL,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    prepared_html BLOB NOT NULL,
                    receipt_json TEXT NOT NULL,
                    authority_hash TEXT NOT NULL,
                    edition_id TEXT NOT NULL,
                    file_sha256 TEXT NOT NULL,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS inventory (
                    edition_id TEXT PRIMARY KEY,
                    file_sha256 TEXT NOT NULL,
                    receipt_sha256 TEXT NOT NULL,
                    job_id TEXT NOT NULL UNIQUE,
                    published_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS preview_tokens (
                    token_hash TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    expires_at REAL NOT NULL,
                    revoked INTEGER NOT NULL DEFAULT 0
                );
                """
            )
            columns = {entry["name"] for entry in connection.execute("PRAGMA table_info(jobs)")}
            if "request_fingerprint" not in columns:
                connection.execute("ALTER TABLE jobs ADD COLUMN request_fingerprint TEXT NOT NULL DEFAULT ''")
                rows = connection.execute("SELECT job_id,project,document_name,retry_of FROM jobs").fetchall()
                for row in rows:
                    connection.execute(
                        "UPDATE jobs SET request_fingerprint=? WHERE job_id=?",
                        (self._request_fingerprint(row["project"], row["document_name"], row["retry_of"]), row["job_id"]),
                    )

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        self._require_open()
        if self._database is None:
            raise HtmlEditionServiceError("HTML_EDITION_CAPABILITY_DENIED", "publication is not granted")
        connection = sqlite3.connect(self._database, isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            yield connection
        finally:
            connection.close()

    @staticmethod
    def _row(row: sqlite3.Row) -> Job:
        return Job(
            job_id=row["job_id"], state=row["state"], idempotency_key=row["idempotency_key"],
            project=row["project"], document=row["document_name"], retry_of=row["retry_of"],
            edition_id=row["edition_id"], file_sha256=row["file_sha256"], error=row["error"],
            created_at=row["created_at"], updated_at=row["updated_at"],
        )

    @staticmethod
    def _request_fingerprint(project: str, document: str, retry_of: str | None) -> str:
        return hashlib.sha256(canonical_json({"document": document, "project": project, "retry_of": retry_of})).hexdigest()

    def _document_and_compile(self, project: str, document: str) -> tuple[ContentDocument, BuildResult]:
        self._require(frozenset({Capability.WORKSPACE_READ, Capability.CONTENT_READ, Capability.ASSET_READ}))
        root = self.config.projects_root / project / "outputs" / "content-documents" / document
        location = _document_location(root, self.ready)
        try:
            content = load_content_document_from_fd(location.source_fd, location.source_suffix)
            return content, HtmlEditionCompiler().compile(content, location.root_fd)
        finally:
            location.close()

    def _compile(self, project: str, document: str) -> BuildResult:
        return self._document_and_compile(project, document)[1]

    def read_document(self, project: str, document: str) -> dict[str, Any]:
        project, document = _safe_identifier(project, "project"), _safe_identifier(document, "document")
        content, result = self._document_and_compile(project, document)
        return {"edition": result.receipt.as_dict(), "project": project, "document": document, "content": content.source}

    def validate(self, project: str, document: str) -> dict[str, Any]:
        project, document = _safe_identifier(project, "project"), _safe_identifier(document, "document")
        result = self._compile(project, document)
        inspect_edition_bytes(result.html)
        return result.receipt.as_dict()

    def resource(self, project: str, document: str, resource_id: str) -> tuple[str, bytes]:
        self._require(frozenset({Capability.WORKSPACE_READ, Capability.CONTENT_READ, Capability.ASSET_READ}))
        project, document = _safe_identifier(project, "project"), _safe_identifier(document, "document")
        resource_id = _safe_identifier(resource_id, "resource id")
        root = self.config.projects_root / project / "outputs" / "content-documents" / document
        location = _document_location(root, self.ready)
        try:
            content = load_content_document_from_fd(location.source_fd, location.source_suffix)
            resource = next((item for item in content.resources if item.logical_id == resource_id), None)
            if resource is None:
                raise HtmlEditionServiceError("HTML_EDITION_RESOURCE_NOT_FOUND", "resource is not declared")
            raw = _read_regular(location.root_fd, f"resources/{resource.source.key}", resource.source.size, "resource")
            if sha256(raw) != resource.source.sha256:
                raise HtmlEditionServiceError("HTML_EDITION_RESOURCE_DIVERGED", "resource identity diverged")
            _resource_mime(resource, raw)
            return resource.source.media_type, raw
        finally:
            location.close()

    def _authority_hash(self) -> str:
        try:
            generation, active = read_authority_generation(self.config.vault_root)
        except RecoveryUnresolved as error:
            raise HtmlEditionServiceError(
                "HTML_EDITION_AUTHORITY_UNAVAILABLE", "workspace authority is unavailable"
            ) from error
        if generation % 2 or active is not None:
            raise HtmlEditionServiceError("HTML_EDITION_AUTHORITY_DIVERGED", "workspace authority is not at rest")
        return hashlib.sha256(canonical_json({
            "vault_id": str(self.config.vault_id), "generation": generation,
            "schema": self.config.effective_schema_digest,
        })).hexdigest()

    def _assert_authority(self, row: sqlite3.Row) -> None:
        if self._authority_hash() != row["authority_hash"]:
            raise HtmlEditionServiceError("HTML_EDITION_AUTHORITY_DIVERGED", "workspace authority changed before publication")

    def enqueue(self, project: str, document: str, idempotency_key: str, *, retry_of: str | None = None) -> Job:
        self._require(_BUILD_CAPABILITIES)
        project, document = _safe_identifier(project, "project"), _safe_identifier(document, "document")
        if not isinstance(idempotency_key, str) or not idempotency_key or len(idempotency_key) > 200:
            raise HtmlEditionServiceError("HTML_EDITION_REQUEST_INVALID", "invalid idempotency key")
        if retry_of is not None:
            _safe_identifier(retry_of, "retry job id")
        fingerprint = self._request_fingerprint(project, document, retry_of)
        with self._connection() as connection:
            existing = connection.execute("SELECT * FROM jobs WHERE idempotency_key=?", (idempotency_key,)).fetchone()
        if existing is not None:
            if existing["request_fingerprint"] != fingerprint:
                raise HtmlEditionServiceError("HTML_EDITION_IDEMPOTENCY_CONFLICT", "idempotency key is bound to another request")
            return self._row(existing)
        result = self._compile(project, document)
        inspect_edition_bytes(result.html)
        receipt = result.receipt.as_dict()
        authority_hash = self._authority_hash()
        created, job_id = _now(), uuid4().hex
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute("SELECT * FROM jobs WHERE idempotency_key=?", (idempotency_key,)).fetchone()
            if existing is not None:
                connection.execute("COMMIT")
                if existing["request_fingerprint"] != fingerprint:
                    raise HtmlEditionServiceError("HTML_EDITION_IDEMPOTENCY_CONFLICT", "idempotency key is bound to another request")
                return self._row(existing)
            connection.execute(
                """INSERT INTO jobs (job_id,idempotency_key,request_fingerprint,project,document_name,state,retry_of,prepared_html,receipt_json,authority_hash,edition_id,file_sha256,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (job_id, idempotency_key, fingerprint, project, document, "queued", retry_of, result.html,
                 json.dumps(receipt, sort_keys=True, separators=(",", ":")), authority_hash,
                 result.edition_id, result.file_sha256, created, created),
            )
            row = connection.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            connection.execute("COMMIT")
            return self._row(row)

    def status(self, job_id: str) -> Job:
        _safe_identifier(job_id, "job id")
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise HtmlEditionServiceError("HTML_EDITION_JOB_NOT_FOUND", "HTML Edition job is not found")
        return self._row(row)

    def cancel(self, job_id: str) -> Job:
        self._require(_BUILD_CAPABILITIES)
        _safe_identifier(job_id, "job id")
        # Persist a running-job cancellation without waiting for publication:
        # the publisher observes this durable flag at each boundary.  Only
        # cleanup is serialized, because it can touch a shared edition.
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if row is None:
                connection.execute("ROLLBACK")
                raise HtmlEditionServiceError("HTML_EDITION_JOB_NOT_FOUND", "HTML Edition job is not found")
            if row["state"] not in _TERMINAL:
                state = "cancelled" if row["state"] == "queued" else row["state"]
                connection.execute("UPDATE jobs SET cancel_requested=1,state=?,updated_at=? WHERE job_id=?", (state, _now(), job_id))
            row = connection.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            connection.execute("COMMIT")
        if row["state"] == "cancelled":
            with self._publication_lock:
                self._cleanup_uninventoried(row)
        return self._row(row)

    def retry(self, job_id: str, idempotency_key: str) -> Job:
        prior = self.status(job_id)
        if prior.state not in _TERMINAL:
            raise HtmlEditionServiceError("HTML_EDITION_RETRY_INVALID", "only a terminal job can be retried")
        return self.enqueue(prior.project, prior.document, idempotency_key, retry_of=prior.job_id)

    def _claim(self, owner: str, lease_seconds: float) -> sqlite3.Row | None:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            now = time.time()
            connection.execute(
                "UPDATE jobs SET state=CASE WHEN cancel_requested THEN 'cancelled' ELSE 'queued' END,lease_owner=NULL,lease_until=NULL,updated_at=? WHERE state='running' AND lease_until < ?",
                (_now(), now),
            )
            row = connection.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY created_at LIMIT 1").fetchone()
            if row is not None:
                connection.execute("UPDATE jobs SET state='running',lease_owner=?,lease_until=?,updated_at=? WHERE job_id=? AND state='queued'", (owner, now + lease_seconds, _now(), row["job_id"]))
                row = connection.execute("SELECT * FROM jobs WHERE job_id=?", (row["job_id"],)).fetchone()
            connection.execute("COMMIT")
            return row

    def _edition_directory(self, edition_id: str) -> int:
        self._require_open()
        _safe_identifier(edition_id, "edition id")
        if self._editions_fd is None:
            raise HtmlEditionServiceError("HTML_EDITION_CAPABILITY_DENIED", "publication is not granted")
        return _open_private_directory(self._editions_fd, edition_id, create=True)

    @staticmethod
    def _publish_file(directory_fd: int, name: str, payload: bytes) -> bool:
        try:
            existing = _read_private_regular(directory_fd, name)
        except FileNotFoundError:
            try:
                _atomic_private_bytes(directory_fd, name, payload)
                return True
            except FileExistsError:
                existing = _read_private_regular(directory_fd, name)
        if existing != payload:
            raise HtmlEditionServiceError("HTML_EDITION_ARTIFACT_DIVERGED", "artifact identity diverged")
        return False

    @staticmethod
    def _remove_if_matching(directory_fd: int, name: str, payload: bytes) -> bool:
        try:
            if _read_private_regular(directory_fd, name) != payload:
                return False
        except FileNotFoundError:
            return False
        os.unlink(name, dir_fd=directory_fd)
        return True

    def _cleanup_uninventoried(self, row: sqlite3.Row) -> None:
        with self._connection() as connection:
            inventoried = connection.execute("SELECT 1 FROM inventory WHERE edition_id=?", (row["edition_id"],)).fetchone()
        if inventoried is not None:
            return
        receipt_bytes = canonical_json({"receipt": json.loads(row["receipt_json"]), "authority_hash": row["authority_hash"]})
        directory_fd = self._edition_directory(row["edition_id"])
        try:
            changed = self._remove_if_matching(directory_fd, "receipt.json", receipt_bytes)
            changed = self._remove_if_matching(directory_fd, "edition.html", bytes(row["prepared_html"])) or changed
            if changed:
                os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    def _recover_cancelled_uninventoried(self) -> None:
        """Retry exact-match cleanup for durable cancelled publications."""

        with self._connection() as connection:
            rows = connection.execute("SELECT * FROM jobs WHERE state='cancelled'").fetchall()
        for row in rows:
            self._cleanup_uninventoried(row)

    def _claim_is_current(self, row: sqlite3.Row) -> bool:
        owner = row["lease_owner"]
        if not owner:
            return False
        with self._connection() as connection:
            current = connection.execute(
                "SELECT 1 FROM jobs WHERE job_id=? AND state='running' AND lease_owner=? AND lease_until>=?",
                (row["job_id"], owner, time.time()),
            ).fetchone()
        return current is not None

    def _require_claim(self, row: sqlite3.Row) -> None:
        if not self._claim_is_current(row):
            raise HtmlEditionServiceError("HTML_EDITION_LEASE_LOST", "job lease is no longer current")

    def _cancelled(self, job_id: str) -> bool:
        with self._connection() as connection:
            row = connection.execute("SELECT cancel_requested FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        return row is None or bool(row["cancel_requested"])

    def _mark_cancelled(self, row: sqlite3.Row) -> bool:
        with self._connection() as connection:
            cursor = connection.execute(
                "UPDATE jobs SET state='cancelled',lease_owner=NULL,lease_until=NULL,updated_at=? "
                "WHERE job_id=? AND state='running' AND lease_owner=? AND lease_until>=? AND cancel_requested=1",
                (_now(), row["job_id"], row["lease_owner"], time.time()),
            )
        if cursor.rowcount == 1:
            self._cleanup_uninventoried(row)
            return True
        return False

    def _fail_claim(self, row: sqlite3.Row, error: HtmlEditionServiceError) -> bool:
        with self._connection() as connection:
            cursor = connection.execute(
                "UPDATE jobs SET state='failed',error=?,lease_owner=NULL,lease_until=NULL,updated_at=? "
                "WHERE job_id=? AND state='running' AND lease_owner=? AND lease_until>=?",
                (error.code, _now(), row["job_id"], row["lease_owner"], time.time()),
            )
        return cursor.rowcount == 1

    def _publish(self, row: sqlite3.Row) -> None:
        receipt_bytes = canonical_json({"receipt": json.loads(row["receipt_json"]), "authority_hash": row["authority_hash"]})
        self._require_claim(row)
        self._assert_authority(row)
        if self._cancelled(row["job_id"]):
            self._mark_cancelled(row)
            return
        directory_fd = self._edition_directory(row["edition_id"])
        try:
            self._require_claim(row)
            self._assert_authority(row)
            self._publish_file(directory_fd, "edition.html", bytes(row["prepared_html"]))
            if self._publish_hook:
                self._publish_hook("artifact")
            self._require_claim(row)
            self._assert_authority(row)
            if self._cancelled(row["job_id"]):
                self._mark_cancelled(row)
                return
            self._publish_file(directory_fd, "receipt.json", receipt_bytes)
            if self._publish_hook:
                self._publish_hook("receipt")
        finally:
            os.close(directory_fd)
        self._require_claim(row)
        self._assert_authority(row)
        if self._publish_hook:
            self._publish_hook("before_inventory")
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT * FROM jobs WHERE job_id=? AND state='running' AND lease_owner=? AND lease_until>=?",
                (row["job_id"], row["lease_owner"], time.time()),
            ).fetchone()
            if current is None:
                connection.execute("ROLLBACK")
                return
            if current["cancel_requested"]:
                connection.execute(
                    "UPDATE jobs SET state='cancelled',lease_owner=NULL,lease_until=NULL,updated_at=? "
                    "WHERE job_id=? AND state='running' AND lease_owner=? AND lease_until>=? AND cancel_requested=1",
                    (_now(), row["job_id"], row["lease_owner"], time.time()),
                )
                connection.execute("COMMIT")
                self._cleanup_uninventoried(row)
                return
            self._assert_authority(row)
            connection.execute(
                "INSERT INTO inventory (edition_id,file_sha256,receipt_sha256,job_id,published_at) VALUES (?,?,?,?,?) ON CONFLICT(edition_id) DO UPDATE SET file_sha256=excluded.file_sha256,receipt_sha256=excluded.receipt_sha256,job_id=excluded.job_id,published_at=excluded.published_at",
                (row["edition_id"], row["file_sha256"], hashlib.sha256(receipt_bytes).hexdigest(), row["job_id"], _now()),
            )
            if self._publish_hook:
                self._publish_hook("inventory")
            cursor = connection.execute(
                "UPDATE jobs SET state='published',lease_owner=NULL,lease_until=NULL,updated_at=? "
                "WHERE job_id=? AND state='running' AND lease_owner=? AND lease_until>=?",
                (_now(), row["job_id"], row["lease_owner"], time.time()),
            )
            if cursor.rowcount != 1:
                connection.execute("ROLLBACK")
                return
            connection.execute("COMMIT")

    def run_next(self, *, lease_seconds: float = 30.0) -> Job | None:
        self._require(_BUILD_CAPABILITIES)
        with self._publication_lock:
            self._recover_cancelled_uninventoried()
            row = self._claim(uuid4().hex, lease_seconds)
            # _claim durably turns expired cancellation requests into cancelled.
            # A crash after that transaction cannot strand matching files: every
            # worker pass retries cleanup before it returns or publishes new work.
            self._recover_cancelled_uninventoried()
            if row is None:
                return None
            if row["cancel_requested"]:
                self._mark_cancelled(row)
                return self.status(row["job_id"])
            try:
                self._publish(row)
            except HtmlEditionServiceError as error:
                if self._fail_claim(row, error):
                    try:
                        self._cleanup_uninventoried(row)
                    except HtmlEditionServiceError:
                        # The terminal error remains authoritative when containment
                        # prevents cleanup of an uninventoried external effect.
                        pass
            return self.status(row["job_id"])

    def recover(self) -> list[Job]:
        """Expire leases, clean cancelled effects, and converge queued publications."""

        self._require(_BUILD_CAPABILITIES)
        with self._publication_lock:
            recovered: list[Job] = []
            while True:
                job = self.run_next()
                if job is None:
                    return recovered
                recovered.append(job)

    def _published_row(self, job_id: str) -> sqlite3.Row:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None or row["state"] != "published":
            raise HtmlEditionServiceError("HTML_EDITION_ARTIFACT_NOT_AVAILABLE", "artifact is not available")
        return row

    def download(self, job_id: str) -> bytes:
        row = self._published_row(job_id)
        directory_fd = self._edition_directory(row["edition_id"])
        try:
            payload = _read_private_regular(directory_fd, "edition.html")
        finally:
            os.close(directory_fd)
        if hashlib.sha256(payload).hexdigest() != row["file_sha256"]:
            raise HtmlEditionServiceError("HTML_EDITION_ARTIFACT_DIVERGED", "artifact identity diverged")
        return payload

    def create_preview(self, job_id: str, *, lifetime_seconds: int = 300) -> str:
        self._published_row(job_id)
        if not 1 <= lifetime_seconds <= 3600:
            raise HtmlEditionServiceError("HTML_EDITION_REQUEST_INVALID", "invalid preview lifetime")
        token = secrets.token_urlsafe(32)
        with self._connection() as connection:
            connection.execute("INSERT INTO preview_tokens (token_hash,job_id,expires_at) VALUES (?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), job_id, time.time() + lifetime_seconds))
        return token

    def revoke_preview(self, token: str) -> None:
        with self._connection() as connection:
            connection.execute("UPDATE preview_tokens SET revoked=1 WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))

    def preview(self, token: str) -> bytes:
        with self._connection() as connection:
            row = connection.execute("SELECT job_id,expires_at,revoked FROM preview_tokens WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        if row is None or row["revoked"] or row["expires_at"] < time.time():
            raise HtmlEditionServiceError("HTML_EDITION_PREVIEW_UNAVAILABLE", "preview is unavailable")
        return self.download(row["job_id"])
