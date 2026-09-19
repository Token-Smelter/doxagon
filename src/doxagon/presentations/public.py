"""Explicit public projection of a deck payload; the private payload is never published as-is."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from .errors import WorkspaceError

PROJECTION_SCHEMA = "doxagon.public-projection/1"
PUBLIC_CLAIM_STATUSES = frozenset({"supported", "qualified"})
PUBLIC_ASSET_KEYS = frozenset({"id", "label", "alt", "media_type", "base64"})
EXCLUDED = (
    "notes",
    "cue_notes",
    "registration",
    "export_policy",
    "capability_grants",
    "claims:unassessed",
    "claims:contested",
)
_PRIVATE_MARKERS = ("/home/", "/Users/", "C:\\", "file:", ".doxagon-presentation-v2", "/.doxagon/")


def project_public_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return the subset of a deck payload that may be published.

    The projection is allow-by-omission: private members are removed by name,
    and the remaining text is then checked by a tripwire that refuses the whole
    projection if any private path-like text survived.
    """

    projected: dict[str, Any] = deepcopy(dict(payload))
    for checkpoint in projected.get("checkpoints", ()):
        checkpoint.pop("notes", None)
        # Per-cue speaking notes are notes: they never travel to a reader.
        checkpoint.pop("cue_notes", None)
        checkpoint.pop("registration", None)
        claims = checkpoint.get("claims")
        if isinstance(claims, list):
            checkpoint["claims"] = [
                claim
                for claim in claims
                if isinstance(claim, Mapping) and claim.get("status") in PUBLIC_CLAIM_STATUSES
            ]
        checkpoint["assets"] = [
            {key: value for key, value in asset.items() if key in PUBLIC_ASSET_KEYS}
            for asset in checkpoint.get("assets", ())
        ]
    projected.pop("export_policy", None)
    projected.pop("capability_grants", None)
    projected["projection"] = {"schema": PROJECTION_SCHEMA, "excluded": list(EXCLUDED)}
    _tripwire(projected)
    return projected


def _tripwire(projected: Mapping[str, Any]) -> None:
    # A tripwire, not a sanitizer: it never rewrites text. Private path-like
    # text in a public projection means the projection itself is wrong, and
    # the export must fail rather than ship a scrubbed guess.
    for key, value in projected.items():
        if key == "checkpoints":
            for checkpoint in value:
                checkpoint_id = str(checkpoint.get("id", "?"))
                for field, member in checkpoint.items():
                    _walk(member, checkpoint_id, field)
            continue
        _walk(value, None, str(key))


def _walk(value: Any, checkpoint_id: str | None, field: str) -> None:
    if isinstance(value, str):
        if any(marker in value for marker in _PRIVATE_MARKERS):
            location = f"checkpoint {checkpoint_id} {field}" if checkpoint_id is not None else f"top-level {field}"
            raise WorkspaceError("PRES_PUBLIC_LEAK", f"{location} carries private path-like text", status=422)
        return
    if isinstance(value, Mapping):
        for member in value.values():
            _walk(member, checkpoint_id, field)
    elif isinstance(value, (list, tuple)):
        for member in value:
            _walk(member, checkpoint_id, field)
