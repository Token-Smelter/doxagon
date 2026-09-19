"""Server-issued presentation cursors.

One session owns one cursor. Presenter, audience, and preview clients send
actions and receive snapshots; none of them may originate a position. A
snapshot names `{session_id, deck_revision, epoch, sequence, checkpoint_id}`,
so a client can reject a foreign revision, a stale pair, or a forked pair
without asking anyone what the truth is. Browser broadcast may relay a snapshot
it received, but it can never mint one.
"""

from __future__ import annotations

from dataclasses import dataclass
import fcntl
import os
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import uuid4

from .contracts import CURSOR_SCHEMA
from .errors import WorkspaceError
from .store import RevisionStore, now, read_json, write_json

SNAPSHOT_SCHEMA = "doxagon.presentation-snapshot/2"
SESSION_SCHEMA = "doxagon.presentation-session/2"
SESSIONS_DIR = "sessions"

ACTIONS = frozenset({"SEEK", "NEXT", "PREVIOUS", "HOME", "END"})
_MAX_SEQUENCE = 2**53 - 1


@dataclass(frozen=True)
class Snapshot:
    """The only cursor record a client is allowed to believe."""

    session_id: str
    deck_revision: str
    epoch: int
    sequence: int
    checkpoint_id: str
    issued_at: str
    navigation: Mapping[str, str] | None = None
    #: Where inside a document-mode checkpoint the cursor rests. A stage
    #: checkpoint has no interior, so it is always None there.
    cue: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": SNAPSHOT_SCHEMA,
            "session_id": self.session_id,
            "deck_revision": self.deck_revision,
            "epoch": self.epoch,
            "sequence": self.sequence,
            "checkpoint_id": self.checkpoint_id,
            "cue": self.cue,
            "issued_at": self.issued_at,
            "navigation": None if self.navigation is None else dict(self.navigation),
        }

    @property
    def cursor(self) -> dict[str, Any]:
        return {
            "schema": CURSOR_SCHEMA,
            "deckRevision": self.deck_revision,
            "sequence": self.sequence,
            "checkpointId": self.checkpoint_id,
            "cue": self.cue,
        }

    def accepts(self, candidate: "Snapshot") -> bool:
        """Whether a client holding this snapshot may adopt ``candidate``."""

        if candidate.session_id != self.session_id or candidate.deck_revision != self.deck_revision:
            return False
        if candidate.epoch != self.epoch:
            return candidate.epoch > self.epoch
        if candidate.sequence == self.sequence:
            # Equal (epoch, sequence) with a different position is a fork, and a
            # cue is part of the position a client renders.
            return candidate.checkpoint_id == self.checkpoint_id and candidate.cue == self.cue
        return candidate.sequence > self.sequence


def reduce_action(
    checkpoint_order: Sequence[str],
    edges: Sequence[Mapping[str, Any]],
    current: str,
    action: Mapping[str, Any],
    *,
    cues: Mapping[str, Sequence[str]] | None = None,
    cue: str | None = None,
) -> tuple[str, str | None]:
    """Resolve one action to an absolute position: a checkpoint and its cue.

    NEXT and PREVIOUS preserve traversal intent while resolving the halves of a
    registered edge, so a checkpoint with no registered forward edge simply has
    no Next — it does not fall through to an index, a slide, or a counter.

    A document-mode checkpoint has an interior. Next walks its declared cues
    first and only then crosses a registered edge, so one command reads as one
    move whether the next position is a scroll away or a whole new document.
    """

    kind = action.get("type")
    interiors = {key: tuple(value) for key, value in (cues or {}).items()}
    if kind not in ACTIONS:
        raise WorkspaceError("PRES_ACTION_UNKNOWN", f"action {kind!r} is not a deck action", status=422)
    if current not in checkpoint_order:
        raise WorkspaceError("PRES_CHECKPOINT_UNKNOWN", f"no checkpoint {current!r} in this revision", status=409)

    def entry(checkpoint_id: str, *, last: bool = False) -> tuple[str, str | None]:
        interior = interiors.get(checkpoint_id, ())
        if not interior:
            return checkpoint_id, None
        return checkpoint_id, interior[-1] if last else interior[0]

    if kind == "SEEK":
        target = action.get("checkpointId")
        if target not in checkpoint_order:
            raise WorkspaceError("PRES_CHECKPOINT_UNKNOWN", f"no checkpoint {target!r} in this revision", status=404)
        requested = action.get("cue")
        if requested is None:
            return entry(str(target))
        if requested not in interiors.get(str(target), ()):
            raise WorkspaceError("PRES_CUE_UNKNOWN", f"no cue {requested!r} in checkpoint {target!r}", status=404)
        return str(target), str(requested)
    if kind == "HOME":
        return entry(str(checkpoint_order[0]))
    if kind == "END":
        return entry(str(checkpoint_order[-1]), last=True)

    interior = interiors.get(current, ())
    if interior and cue in interior:
        step = 1 if kind == "NEXT" else -1
        position = interior.index(cue) + step
        if 0 <= position < len(interior):
            return current, interior[position]

    key, other = ("from", "to") if kind == "NEXT" else ("to", "from")
    for edge in edges:
        if edge.get(key) == current:
            # Entering a document backwards lands on its last cue, so Back out of
            # one document and forward again returns to where the reader was.
            return entry(str(edge[other]), last=kind == "PREVIOUS")
    raise WorkspaceError(
        "PRES_EDGE_ABSENT",
        f"checkpoint {current!r} registers no {'forward' if kind == 'NEXT' else 'reverse'} edge",
        status=409,
    )


class SessionService:
    """Serializes actions per session and issues every snapshot itself."""

    def __init__(self, store: RevisionStore) -> None:
        self.store = store
        self.root = store.root / SESSIONS_DIR
        self.root.mkdir(parents=True, exist_ok=True)

    def open(self, *, revision: str | None = None, session_id: str | None = None) -> Snapshot:
        """Start (or restart) a session pinned to one revision's first checkpoint."""

        target = revision or self.store.revision
        order = self._order(target)
        identifier = session_id or f"session_{uuid4().hex}"
        with self._locked(identifier) as record:
            epoch = 0 if record is None else int(record["epoch"]) + 1
            cues = self._cues(target).get(order[0], ())
            return self._write(identifier, target, epoch, 0, order[0], cue=cues[0] if cues else None)

    def snapshot(self, session_id: str) -> Snapshot:
        record = read_json(self._path(session_id))
        if not isinstance(record, dict) or record.get("schema") != SESSION_SCHEMA:
            raise WorkspaceError("PRES_SESSION_UNKNOWN", f"no session {session_id!r}", status=404)
        return _snapshot(record)

    def apply(self, session_id: str, action: Mapping[str, Any], *, expected_revision: str | None = None) -> Snapshot:
        """Advance one session under its own lock and issue the new snapshot."""

        with self._locked(session_id) as record:
            if record is None:
                raise WorkspaceError("PRES_SESSION_UNKNOWN", f"no session {session_id!r}", status=404)
            revision = str(record["deck_revision"])
            if expected_revision is not None and expected_revision != revision:
                raise WorkspaceError(
                    "PRES_SESSION_REVISION_MISMATCH",
                    "this session presents a different revision",
                    status=409,
                    revision=revision,
                )
            order = self._order(revision)
            target, cue = reduce_action(
                order,
                self._edges(revision),
                str(record["checkpoint_id"]),
                action,
                cues=self._cues(revision),
                cue=record.get("cue"),
            )
            sequence = int(record["sequence"]) + 1
            if sequence > _MAX_SEQUENCE:
                raise WorkspaceError("PRES_SESSION_EXHAUSTED", "this session must be reopened", status=409)
            return self._write(
                session_id, revision, int(record["epoch"]), sequence, target, cue=cue,
                navigation={
                    "type": str(action["type"]),
                    "from": str(record["checkpoint_id"]),
                    **({"from_cue": str(record["cue"])} if record.get("cue") else {}),
                },
            )

    def repin(self, session_id: str, revision: str) -> Snapshot:
        """Move a live session to another revision by bumping its epoch.

        A revision change is not a cursor move: the old `(epoch, sequence)`
        line ends, so a client still holding the previous revision rejects
        every later snapshot instead of seeking inside a deck it no longer has.
        """

        order = self._order(revision)
        with self._locked(session_id) as record:
            if record is None:
                raise WorkspaceError("PRES_SESSION_UNKNOWN", f"no session {session_id!r}", status=404)
            current = str(record["checkpoint_id"])
            landing = current if current in order else order[0]
            held = record.get("cue")
            interior = self._cues(revision).get(landing, ())
            return self._write(
                session_id,
                revision,
                int(record["epoch"]) + 1,
                0,
                landing,
                # A cue only survives a repin if the new revision still declares
                # it; otherwise the document is re-entered at its start.
                cue=held if held in interior else (interior[0] if interior else None),
            )

    # --- internals ---------------------------------------------------------

    def _path(self, session_id: str) -> Path:
        if not session_id or "/" in session_id or "\\" in session_id or session_id.startswith("."):
            raise WorkspaceError("PRES_SESSION_UNKNOWN", "session id is not a stored session", status=404)
        return self.root / f"{session_id}.json"

    def _order(self, revision: str) -> tuple[str, ...]:
        order = tuple(str(item) for item in self.store.read_receipt(revision).get("checkpoint_order", ()))
        if not order:
            raise WorkspaceError("PRES_WORKSPACE_EMPTY", "this revision registers no checkpoint", status=409)
        return order

    def _edges(self, revision: str) -> tuple[Mapping[str, Any], ...]:
        return tuple(self.store.read_receipt(revision).get("edges", ()))

    def _cues(self, revision: str) -> dict[str, tuple[str, ...]]:
        """Each document checkpoint's declared interior, in authored order."""

        return {
            str(item["id"]): tuple(str(cue) for cue in item.get("cues", ()))
            for item in self.store.read_receipt(revision).get("checkpoints", ())
            if item.get("cues")
        }

    def _write(
        self, session_id: str, revision: str, epoch: int, sequence: int, checkpoint_id: str,
        *, navigation: Mapping[str, str] | None = None, cue: str | None = None,
    ) -> Snapshot:
        snapshot = Snapshot(session_id, revision, epoch, sequence, checkpoint_id, now(), navigation, cue)
        # The stored record and the issued snapshot are different documents:
        # one is this service's state, the other is what a client may believe.
        write_json(self._path(session_id), {**snapshot.as_dict(), "schema": SESSION_SCHEMA})
        return snapshot

    class _Lock:
        def __init__(self, service: "SessionService", session_id: str) -> None:
            self.path = service._path(session_id)
            self.descriptor = -1

        def __enter__(self) -> dict[str, Any] | None:
            self.descriptor = os.open(f"{self.path}.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            fcntl.flock(self.descriptor, fcntl.LOCK_EX)
            record = read_json(self.path)
            return record if isinstance(record, dict) else None

        def __exit__(self, *exception: Any) -> None:
            os.close(self.descriptor)

    def _locked(self, session_id: str) -> "SessionService._Lock":
        return SessionService._Lock(self, session_id)


def _snapshot(record: Mapping[str, Any]) -> Snapshot:
    return Snapshot(
        str(record["session_id"]),
        str(record["deck_revision"]),
        int(record["epoch"]),
        int(record["sequence"]),
        str(record["checkpoint_id"]),
        str(record["issued_at"]),
        record.get("navigation"),
        record.get("cue"),
    )
