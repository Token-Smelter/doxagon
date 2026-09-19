"""The v2 cursor and order model.

A cursor names exactly one stable checkpoint id inside one revision. There is
no slide id, step counter, or bundle index anywhere in this model: every
control, synchronization snapshot, management selection, and deterministic
export identifies its position by ``checkpoint_id`` alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .contracts import CURSOR_SCHEMA, LEGACY_FIELDS, _identifier, _object, _string, child, pointer
from .errors import fail

_MAX_SEQUENCE = 2**53 - 1


@dataclass(frozen=True)
class DeckCursor:
    """`{deckRevision, sequence, checkpointId}` — the only position record."""

    deck_revision: str
    sequence: int
    checkpoint_id: str

    @classmethod
    def parse(cls, value: Any, at: str = "") -> "DeckCursor":
        record = _object(value, at, "cursor")
        legacy = sorted(set(record) & (LEGACY_FIELDS | {"slideId", "stepIndex", "slideIndex"}))
        if legacy:
            fail("PRES_LEGACY_FIELD", f"cursor declares legacy field {legacy[0]!r}", child(at, legacy[0]))
        unknown = sorted(set(record) - {"schema", "deckRevision", "sequence", "checkpointId"})
        if unknown:
            fail("PRES_UNKNOWN_FIELD", f"cursor declares unknown field {unknown[0]!r}", child(at, unknown[0]))
        if record.get("schema") != CURSOR_SCHEMA:
            fail("PRES_SCHEMA_UNSUPPORTED", f"cursor schema must be {CURSOR_SCHEMA!r}", child(at, "schema"))
        sequence = record.get("sequence")
        if not isinstance(sequence, int) or isinstance(sequence, bool) or not 0 <= sequence <= _MAX_SEQUENCE:
            fail("PRES_FIELD_INVALID", "cursor sequence must be a bounded non-negative integer", child(at, "sequence"))
        return cls(
            _string(record.get("deckRevision"), child(at, "deckRevision"), "cursor deckRevision"),
            sequence,
            _identifier(record.get("checkpointId"), child(at, "checkpointId"), "cursor checkpointId"),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": CURSOR_SCHEMA,
            "deckRevision": self.deck_revision,
            "sequence": self.sequence,
            "checkpointId": self.checkpoint_id,
        }


@dataclass(frozen=True)
class CheckpointOrder:
    """`checkpoint_order` bound to one revision; the only navigation order."""

    revision: str
    checkpoint_ids: tuple[str, ...]

    @classmethod
    def build(cls, revision: str, checkpoint_ids: Iterable[str]) -> "CheckpointOrder":
        ordered = tuple(checkpoint_ids)
        if not ordered:
            fail("PRES_FIELD_INVALID", "checkpoint_order must not be empty", pointer("checkpoint_order"))
        if len(set(ordered)) != len(ordered):
            fail("PRES_CHECKPOINT_ID_DUPLICATE", "checkpoint_order repeats a checkpoint id", pointer("checkpoint_order"))
        return cls(revision, ordered)

    def __contains__(self, checkpoint_id: object) -> bool:
        return checkpoint_id in self.checkpoint_ids

    def __len__(self) -> int:
        return len(self.checkpoint_ids)

    def index_of(self, checkpoint_id: str) -> int:
        if checkpoint_id not in self.checkpoint_ids:
            fail("PRES_CHECKPOINT_UNKNOWN", f"checkpoint {checkpoint_id!r} is not in this revision")
        return self.checkpoint_ids.index(checkpoint_id)

    @property
    def first(self) -> str:
        return self.checkpoint_ids[0]

    @property
    def last(self) -> str:
        return self.checkpoint_ids[-1]

    def seek(self, checkpoint_id: str, sequence: int) -> DeckCursor:
        """Absolute seek: the target is named, never derived from a counter."""

        self.index_of(checkpoint_id)
        if not isinstance(sequence, int) or isinstance(sequence, bool) or not 0 <= sequence <= _MAX_SEQUENCE:
            fail("PRES_FIELD_INVALID", "cursor sequence must be a bounded non-negative integer")
        return DeckCursor(self.revision, sequence, checkpoint_id)

    def accepts(self, current: DeckCursor | None, candidate: DeckCursor) -> bool:
        """Reject a foreign revision, an unknown checkpoint, or a stale sequence."""

        if candidate.deck_revision != self.revision or candidate.checkpoint_id not in self.checkpoint_ids:
            return False
        if current is None:
            return True
        if current.deck_revision != self.revision:
            return False
        if candidate.sequence == current.sequence:
            return candidate.checkpoint_id == current.checkpoint_id
        return candidate.sequence > current.sequence
