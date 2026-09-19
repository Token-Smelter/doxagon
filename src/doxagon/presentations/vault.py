"""Resolve one vault presentation's revisioned checkpoint workspace.

The product editor is vault-native: selecting a real presentation in
`/presentations` opens *that* presentation's revisioned Step workspace. There
is no separate global workspace root behind the product any more, so nothing
the editor mutates can land in a store the selected presentation does not own.

A presentation that has not been promoted yet is migrated here, deterministically
and idempotently, by exactly the migrator `migration.promote` already implements:
the legacy tree is inventoried without mutation, shadow-validated, and published
in one rename behind a verifiable receipt. A tree with blocking mapping
ambiguities is refused with those diagnostics rather than guessed through.
"""

from __future__ import annotations

from pathlib import Path
import threading

from .contracts import DEFAULT_VALIDATION_POLICY, ValidationPolicy
from .errors import WorkspaceError
from .migration import (
    MIGRATION_MARKER,
    STORE_SUBPATH,
    inventory_presentation,
    is_migrated,
    promote,
    unmigrate,
)
from .workspace import PresentationWorkspace

#: Re-exported: promotion owns the store layout, and callers that resolve a
#: workspace here should not have to know which module decided it.
__all__ = [
    "STORE_SUBPATH",
    "discard_migration",
    "open_or_migrate",
    "resolve_presentation_dir",
    "workspace_root",
]

# Migration publishes with one rename and refuses an occupied target, so two
# concurrent first opens of the same presentation would make one of them fail
# PRES_MIGRATION_TARGET_OCCUPIED. Serialising per presentation makes the second
# caller wait for the first receipt instead of racing it.
#
# These locks are process-local, so they order the callers inside one server
# and nothing beyond it. What makes a second process safe is the publication
# itself: promotion lands in one rename onto a target it refuses to occupy.
_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(key: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.Lock())


def resolve_presentation_dir(vault_root: Path, slug: str) -> Path:
    """Resolve one vault presentation directory, refusing to escape the vault.

    A slug is a single directory name. Anything that traverses, absolutises, or
    resolves outside the vault root is refused by name rather than normalised,
    because a normalised traversal is still a request for someone else's tree.
    """

    if slug == "" or slug in {".", ".."} or "/" in slug or "\\" in slug or slug.startswith("."):
        raise WorkspaceError("PRES_PRESENTATION_SLUG_INVALID", f"{slug!r} is not a presentation slug", status=422)
    root = Path(vault_root)
    candidate = root / slug
    try:
        resolved = candidate.resolve()
        inside = resolved.is_relative_to(root.resolve())
    except OSError as error:
        raise WorkspaceError("PRES_PRESENTATION_UNKNOWN", f"no presentation {slug!r}", status=404) from error
    if not inside:
        raise WorkspaceError("PRES_PRESENTATION_SLUG_INVALID", f"{slug!r} is not a presentation slug", status=422)
    if not candidate.is_dir():
        raise WorkspaceError("PRES_PRESENTATION_UNKNOWN", f"no presentation {slug!r}", status=404)
    return candidate


def workspace_root(presentation_dir: Path) -> Path:
    """Where one promoted presentation keeps its revisioned store."""

    return presentation_dir / MIGRATION_MARKER / STORE_SUBPATH


def open_or_migrate(
    vault_root: Path, slug: str, *, policy: ValidationPolicy = DEFAULT_VALIDATION_POLICY
) -> PresentationWorkspace:
    """Open the selected presentation's Step workspace, migrating it once.

    The receipt is the authority: `is_migrated` verifies it before any store is
    opened, so a half-written marker is re-promoted rather than read as a
    workspace nothing validated. That check and the open it guards are held
    under one lock, because a rollback landing between them would hand back a
    workspace over a store that is already being retired.

    One policy governs the whole lifecycle of the selected deck: the migration
    that first admits it and every later open of the promoted store carry the
    same aggregate budget, so a deck that migrated cannot fail its next edit.
    """

    presentation = resolve_presentation_dir(vault_root, slug)
    with _lock_for(str(presentation.resolve())):
        if not is_migrated(presentation):
            promote(inventory_presentation(presentation), presentation / MIGRATION_MARKER, policy=policy)
        return PresentationWorkspace.open(workspace_root(presentation), policy=policy)


def discard_migration(vault_root: Path, slug: str, *, discard_edits: bool = False) -> bool:
    """Roll one presentation back to legacy authority, reporting whether it moved.

    Held under the same per-presentation lock as `open_or_migrate`, so a
    rollback cannot land between another caller's `is_migrated` check and the
    open it guards: that caller would otherwise open a store this one is in the
    middle of retiring.
    """

    presentation = resolve_presentation_dir(vault_root, slug)
    with _lock_for(str(presentation.resolve())):
        return unmigrate(presentation, discard_edits=discard_edits)
