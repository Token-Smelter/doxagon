"""Vault-anchored writer fence and roll-forward write-ahead log.

Stage 1 converts one vertical slice at a time.  This module owns the durability
half of the graph-write slice: exclusive write ownership for one canonical vault
root, an even/odd authority generation that readers can observe, and a
``replace`` operation that converges by roll-forward after interruption.

Version 1 records replace one file. Version 2 records replace a bounded group
of files under the same reader barrier; both recover by rolling forward.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4
import errno
import hashlib
import json
import os
import time
import re
import stat
from typing import Mapping

try:  # pragma: no cover - exercised by platform, not by branch
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX platforms
    fcntl = None


CONTROL_DIRECTORY = ".doxagon"
LOCK_FILENAME = "write.lock"
WAL_DIRECTORY = "wal"
GENERATION_FILENAME = "authority-generation.json"
STAGE_DIRECTORY = ".doxagon-stage"

DEFAULT_FENCE_WAIT_SECONDS = 5.0
_FENCE_POLL_SECONDS = 0.05


class WriterFenceUnsupported(RuntimeError):
    """The filesystem cannot prove exclusive write ownership."""


class WriterFenceUnavailable(RuntimeError):
    """Another live writer holds the fence for this vault."""


class RecoveryUnresolved(RuntimeError):
    """A prepared transaction cannot be proven to converge."""


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    """Durably install ``payload`` at ``path`` through a same-directory rename."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{uuid4().hex}.tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    _fsync_directory(path.parent)


def _generation_path(vault_root: Path) -> Path:
    return vault_root / CONTROL_DIRECTORY / GENERATION_FILENAME


def read_authority_generation(vault_root: Path) -> tuple[int, str | None]:
    """Return the vault's ``(generation, active_txid)`` reader barrier.

    An even generation with no active transaction means the authoritative state
    is at rest and safe to read.  An odd generation means a write is in flight.
    """

    try:
        record = json.loads(_generation_path(vault_root).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RecoveryUnresolved("authority generation is unreadable") from error
    generation = record.get("generation")
    active = record.get("active_txid")
    if not isinstance(generation, int) or isinstance(generation, bool) or generation < 0:
        raise RecoveryUnresolved("authority generation is malformed")
    if active is not None and not isinstance(active, str):
        raise RecoveryUnresolved("authority generation is malformed")
    return generation, active


def _write_authority_generation(vault_root: Path, generation: int, active_txid: str | None) -> None:
    payload = json.dumps(
        {"format": 1, "generation": generation, "active_txid": active_txid}, separators=(",", ":")
    )
    _atomic_write_bytes(_generation_path(vault_root), (payload + "\n").encode())


def has_pending_transaction(vault_root: Path) -> bool:
    """Report whether this vault needs bounded recovery before it can serve."""

    try:
        generation, active = read_authority_generation(vault_root)
    except RecoveryUnresolved:
        return True
    if generation % 2 or active is not None:
        return True
    wal_root = vault_root / CONTROL_DIRECTORY / WAL_DIRECTORY
    return wal_root.is_dir() and any(wal_root.glob("*.json"))


class WriterFence:
    """Exclusive, lifetime-scoped write ownership for one canonical vault root.

    Presence of the lock file is never ownership; only a held ``flock`` is.  A
    stale lock file left by a killed writer is reacquired by the next owner
    without cleanup, because the kernel released the lock when the process died.
    """

    def __init__(self, vault_root: Path, *, wait_seconds: float | None = None) -> None:
        self._vault_root = vault_root
        self._wait_seconds = wait_seconds
        self._descriptor: int | None = None

    @property
    def held(self) -> bool:
        return self._descriptor is not None

    def acquire(self) -> None:
        if fcntl is None:
            raise WriterFenceUnsupported("writer_fence_unsupported: flock is unavailable")
        if self._descriptor is not None:
            return

        control = self._vault_root / CONTROL_DIRECTORY
        if not control.resolve().is_relative_to(self._vault_root.resolve()):
            raise WriterFenceUnsupported('vault control directory resolves outside the vault')
        control.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(control / LOCK_FILENAME, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        wait_seconds = DEFAULT_FENCE_WAIT_SECONDS if self._wait_seconds is None else self._wait_seconds
        deadline = time.monotonic() + wait_seconds
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                if error.errno not in {errno.EACCES, errno.EAGAIN}:
                    os.close(descriptor)
                    raise WriterFenceUnsupported("writer_fence_unsupported: flock failed") from error
                if time.monotonic() >= deadline:
                    os.close(descriptor)
                    raise WriterFenceUnavailable("writer fence is held by another writer")
                time.sleep(_FENCE_POLL_SECONDS)
            else:
                self._descriptor = descriptor
                return

    def release(self) -> None:
        if self._descriptor is None:
            return
        try:
            fcntl.flock(self._descriptor, fcntl.LOCK_UN)
        finally:
            os.close(self._descriptor)
            self._descriptor = None


@dataclass(frozen=True)
class PreparedReplace:
    """One durably prepared single-file replacement."""

    txid: str
    target: Path
    postimage: Path
    digest: str


@dataclass(frozen=True)
class PreparedReplaceMany:
    txid: str
    targets: tuple[PreparedReplace, ...]


class WriteAheadLog:
    """Roll-forward log for authoritative single- and multi-file replacement.

    Recovery only ever rolls forward.  It never reconstructs a preimage and
    never invents a rollback, so an unprovable transaction stops the vault
    rather than silently choosing a state.
    """

    def __init__(self, vault_root: Path, fence: WriterFence) -> None:
        self._vault_root = vault_root
        self._fence = fence

    @property
    def _wal_root(self) -> Path:
        return self._contained(str(Path(CONTROL_DIRECTORY) / WAL_DIRECTORY))

    def _record_path(self, txid: str) -> Path:
        return self._wal_root / f"{txid}.json"

    def _require_fence(self) -> None:
        if not self._fence.held:
            raise WriterFenceUnavailable("refusing to mutate the vault without a held writer fence")

    def commit_replace(self, target: Path, payload: bytes) -> str:
        """Durably replace ``target`` with ``payload`` and return its transaction id."""

        self._require_fence()
        generation, active = read_authority_generation(self._vault_root)
        if active is not None or generation % 2:
            raise RecoveryUnresolved("a prepared transaction is still in flight")

        txid = uuid4().hex
        prepared = self._prepare(txid, target, payload)
        _write_authority_generation(self._vault_root, generation + 1, txid)
        self._install(prepared)
        _write_authority_generation(self._vault_root, generation + 2, None)
        self._discard_record(txid)
        return txid

    def initialize(self) -> None:
        """Explicitly provision a missing barrier under the writer fence."""
        self._require_fence()
        if _generation_path(self._vault_root).exists():
            generation, active = read_authority_generation(self._vault_root)
            if generation % 2 or active is not None:
                raise RecoveryUnresolved('a prepared transaction is still in flight')
            return
        if self._wal_root.exists() and any(self._wal_root.glob('*.json')):
            raise RecoveryUnresolved('journal records exist without an authority generation')
        _write_authority_generation(self._vault_root, 0, None)

    def commit_replace_many(self, replacements: Mapping[Path, bytes]) -> str:
        """Promote one prevalidated authored change under one generation bump."""
        self._require_fence()
        if not replacements or len(replacements) > 512:
            raise ValueError('a transaction requires 1..512 targets')
        generation, active = read_authority_generation(self._vault_root)
        if active is not None or generation % 2:
            raise RecoveryUnresolved('a prepared transaction is still in flight')
        normalized = {self._contained(os.path.relpath(path, self._vault_root)): data for path, data in replacements.items()}
        if len(normalized) != len(replacements):
            raise ValueError('transaction targets must be distinct')
        txid = uuid4().hex
        prepared = self._prepare_many(txid, normalized)
        _write_authority_generation(self._vault_root, generation + 1, txid)
        self._install_many(prepared)
        _write_authority_generation(self._vault_root, generation + 2, None)
        self._discard_record(txid)
        return txid

    def _prepare_many(self, txid: str, replacements: Mapping[Path, bytes]) -> PreparedReplaceMany:
        targets = []
        for index, (target, payload) in enumerate(replacements.items()):
            target.parent.mkdir(parents=True, exist_ok=True)
            stage_root = target.parent / STAGE_DIRECTORY
            stage_root.mkdir(exist_ok=True)
            self._contained(os.path.relpath(stage_root, self._vault_root))
            if os.stat(stage_root).st_dev != os.stat(target.parent).st_dev:
                raise WriterFenceUnsupported('staging area is on another filesystem')
            postimage = stage_root / f'{txid}-{index}.postimage'
            _atomic_write_bytes(postimage, payload)
            self._preserve_target_mode(postimage, target)
            targets.append(PreparedReplace(txid, target, postimage, hashlib.sha256(payload).hexdigest()))
        prepared = PreparedReplaceMany(txid, tuple(targets))
        record = {'format': 2, 'kind': 'replace_many', 'txid': txid, 'targets': [
            {'target': os.path.relpath(item.target, self._vault_root),
             'postimage': os.path.relpath(item.postimage, self._vault_root), 'sha256': item.digest}
            for item in targets
        ]}
        _atomic_write_bytes(self._record_path(txid), (json.dumps(record, separators=(',', ':')) + '\n').encode())
        return prepared

    def _install_many(self, prepared: PreparedReplaceMany) -> None:
        # Prove all remaining staged bytes before promoting any more targets.
        for item in prepared.targets:
            if item.postimage.exists():
                self._verify_postimage(item)
            elif not self._target_matches(item):
                raise RecoveryUnresolved('a transaction target has neither a valid postimage nor converged bytes')
        for item in prepared.targets:
            if item.postimage.exists():
                self._install(item)

    def recover(self) -> str | None:
        """Converge any prepared transaction and return the recovered id."""

        self._require_fence()
        generation, active = read_authority_generation(self._vault_root)

        if generation % 2 == 0 and active is None:
            # A crash between the commit bump and record cleanup leaves an
            # already-installed transaction behind an even generation.
            self._discard_all_records()
            return None
        if generation % 2 == 0 or active is None:
            raise RecoveryUnresolved("authority generation and transaction marker disagree")

        prepared = self._load_record(active)
        if isinstance(prepared, PreparedReplaceMany):
            self._install_many(prepared)
        elif prepared.postimage.is_file():
            self._install(prepared)
        elif not self._target_matches(prepared):
            raise RecoveryUnresolved("prepared postimage is unavailable and the target did not converge")
        _write_authority_generation(self._vault_root, generation + 1, None)
        self._discard_record(active)
        return active

    def _prepare(self, txid: str, target: Path, payload: bytes) -> PreparedReplace:
        target = self._contained(os.path.relpath(target, self._vault_root))
        parent = target.parent
        parent.mkdir(parents=True, exist_ok=True)
        stage_root = parent / STAGE_DIRECTORY
        self._contained(os.path.relpath(stage_root, self._vault_root))
        stage_root.mkdir(parents=True, exist_ok=True)
        if os.stat(stage_root).st_dev != os.stat(parent).st_dev:
            raise WriterFenceUnsupported("writer_fence_unsupported: staging area is on another filesystem")

        postimage = stage_root / f"{txid}.postimage"
        _atomic_write_bytes(postimage, payload)
        self._preserve_target_mode(postimage, target)
        digest = hashlib.sha256(payload).hexdigest()
        record = {
            "format": 1,
            "txid": txid,
            "kind": "replace",
            "target": os.path.relpath(target, self._vault_root),
            "postimage": os.path.relpath(postimage, self._vault_root),
            "sha256": digest,
        }
        _atomic_write_bytes(self._record_path(txid), (json.dumps(record, separators=(",", ":")) + "\n").encode())
        return PreparedReplace(txid=txid, target=target, postimage=postimage, digest=digest)

    def _install(self, prepared: PreparedReplace) -> None:
        self._verify_postimage(prepared)
        os.replace(prepared.postimage, prepared.target)
        _fsync_directory(prepared.target.parent)

    @staticmethod
    def _preserve_target_mode(postimage: Path, target: Path) -> None:
        try:
            mode = stat.S_IMODE(target.stat().st_mode)
        except FileNotFoundError:
            mode = 0o644
        os.chmod(postimage, mode)
        descriptor = os.open(postimage, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _verify_postimage(self, prepared: PreparedReplace) -> None:
        self._contained(os.path.relpath(prepared.target, self._vault_root))
        self._contained(os.path.relpath(prepared.postimage, self._vault_root))
        try:
            digest = hashlib.sha256(prepared.postimage.read_bytes()).hexdigest()
        except OSError as error:
            raise RecoveryUnresolved('prepared postimage is unreadable') from error
        if digest != prepared.digest:
            raise RecoveryUnresolved('prepared postimage hash disagrees with the journal')

    def _target_matches(self, prepared: PreparedReplace) -> bool:
        try:
            return hashlib.sha256(prepared.target.read_bytes()).hexdigest() == prepared.digest
        except OSError:
            return False

    def _contained(self, relative: str) -> Path:
        if not isinstance(relative, str) or Path(relative).is_absolute() or '..' in Path(relative).parts:
            raise RecoveryUnresolved('journal path must be relative to the vault')
        try:
            path = (self._vault_root / relative).resolve()
        except (OSError, RuntimeError):
            raise RecoveryUnresolved('journal path cannot be resolved safely') from None
        if not path.is_relative_to(self._vault_root.resolve()):
            raise RecoveryUnresolved('journal path escapes the vault')
        return path

    def _load_record(self, txid: str) -> PreparedReplace | PreparedReplaceMany:
        if re.fullmatch(r'[a-f0-9]{32}', txid) is None:
            raise RecoveryUnresolved('invalid transaction identifier')
        try:
            with self._record_path(txid).open('rb') as stream:
                raw = stream.read(8 * 1024 * 1024 + 1)
            if len(raw) > 8 * 1024 * 1024:
                raise RecoveryUnresolved('journal record exceeds its size limit')
            record = json.loads(raw)
        except (OSError, ValueError, UnicodeError) as error:
            raise RecoveryUnresolved("prepared transaction record is unreadable") from error
        if not isinstance(record, dict) or record.get('txid') != txid:
            raise RecoveryUnresolved('prepared transaction identity disagrees')
        if record.get('kind') == 'replace_many' and record.get('format') == 2:
            entries = record.get('targets')
            if not isinstance(entries, list) or not 1 <= len(entries) <= 512:
                raise RecoveryUnresolved('invalid multi-target journal record')
            targets = tuple(self._record_target(txid, item) for item in entries)
            if len({item.target for item in targets}) != len(targets):
                raise RecoveryUnresolved('duplicate transaction targets')
            return PreparedReplaceMany(txid, targets)
        if record.get("kind") != "replace" or record.get('format') != 1:
            raise RecoveryUnresolved(f"unsupported prepared operation kind: {record.get('kind')!r}")
        return self._record_target(txid, record)

    def _record_target(self, txid: str, record: dict) -> PreparedReplace:
        try:
            digest = record['sha256']
            if not isinstance(digest, str) or re.fullmatch(r'[a-f0-9]{64}', digest) is None:
                raise RecoveryUnresolved('invalid postimage digest')
            target = self._contained(record['target'])
            postimage = self._contained(record['postimage'])
            stage = self._contained(os.path.relpath(target.parent / STAGE_DIRECTORY, self._vault_root))
            if postimage.parent != stage or not re.fullmatch(txid + r'(?:-\d+)?\.postimage', postimage.name):
                raise RecoveryUnresolved('postimage is outside the transaction staging directory')
            return PreparedReplace(txid, target, postimage, digest)
        except (KeyError, TypeError) as error:
            raise RecoveryUnresolved("prepared transaction record is incomplete") from error

    def _discard_record(self, txid: str) -> None:
        self._record_path(txid).unlink(missing_ok=True)

    def _discard_all_records(self) -> None:
        if not self._wal_root.is_dir():
            return
        for record in self._wal_root.glob("*.json"):
            record.unlink(missing_ok=True)
