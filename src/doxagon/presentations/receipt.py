"""Revision identity and the deterministic validation receipt.

`revision` is calculated, never chosen by an author. It covers the manifest with
its own `revision` member removed, the raw bytes and relative paths of every
checkpoint file, the parsed registrations, the resolved edge table, and every
declared asset record with its verified digest and provenance — and it preserves
declared checkpoint order, group membership order, and edge order exactly.

It also covers the runtime's own bytes, not just its version string. A revision
is a claim about observable behaviour, and the runtime is what produces that
behaviour: pinning only `doxagon-presentation-runtime/2` would let an edited
runtime change what an unchanged revision does. Because the digest is part of
the revision input, a runtime edit yields a different revision, and a stored
receipt from before the edit no longer recomputes — so `verify_receipt`, every
export, and every payload build fail closed until the deck is revalidated.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from doxagon.html_editions.contracts import canonical_json, sha256

from .contracts import (
    ASSET_MEDIA_TYPES,
    CAPABILITIES,
    GROUP_KINDS,
    LEGACY_FIELDS,
    MANIFEST_SCHEMA,
    PROVENANCE_KINDS,
    RECEIPT_SCHEMA,
    REGISTRATION_SCHEMA,
    REVISION_DOMAIN,
    REVISION_INPUT_SCHEMA,
    RUNTIME_VERSION,
    VALIDATOR_VERSION,
)
from .errors import Diagnostic
from .registration import policy_tokens
from .runtime import RUNTIME_SHA256

# What a revision, a compose hash, and a receipt all pin about the runtime: the
# version names the contract, the digest names the bytes that honour it.
RUNTIME_PIN = {"version": RUNTIME_VERSION, "sha256": RUNTIME_SHA256}

# The receipt pins the policy that produced it: a change to the closed
# vocabularies or the static containment rules changes every future receipt.
POLICY_DIGEST = sha256(
    b"doxagon-presentation-policy/v2\0"
    + canonical_json(
        {
            "manifest_schema": MANIFEST_SCHEMA,
            "registration_schema": REGISTRATION_SCHEMA,
            "capabilities": sorted(CAPABILITIES),
            "group_kinds": sorted(GROUP_KINDS),
            "asset_media_types": sorted(ASSET_MEDIA_TYPES),
            "provenance_kinds": sorted(PROVENANCE_KINDS),
            "rejected_legacy_fields": sorted(LEGACY_FIELDS),
            "static_rules": list(policy_tokens()),
        }
    )
)


def compute_revision(revision_input: Mapping[str, Any]) -> str:
    """Domain-separated digest of the canonical revision input."""

    return "sha256:" + sha256(REVISION_DOMAIN + canonical_json(dict(revision_input)))


def build_revision_input(
    presentation_id: str,
    manifest_source: Mapping[str, Any],
    checkpoint_order: Sequence[str],
    checkpoints: Sequence[Mapping[str, Any]],
    edges: Sequence[Mapping[str, Any]],
    groups: Sequence[Mapping[str, Any]],
    assets: Sequence[Mapping[str, Any]],
    *,
    knowledge: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    # A revision with no knowledge binding must keep the identity it had before
    # bindings existed, so the member is absent rather than null.
    return {
        **({"knowledge": dict(knowledge)} if knowledge is not None else {}),
        "schema": REVISION_INPUT_SCHEMA,
        "presentation_id": presentation_id,
        "manifest": dict(manifest_source),
        "checkpoint_order": list(checkpoint_order),
        "checkpoints": [dict(item) for item in checkpoints],
        "edges": [dict(item) for item in edges],
        "groups": [dict(item) for item in groups],
        "assets": [dict(item) for item in assets],
        "validator": VALIDATOR_VERSION,
        "runtime": dict(RUNTIME_PIN),
        "policy": POLICY_DIGEST,
    }


def compose_hash(checkpoints: Sequence[Mapping[str, Any]], edges: Sequence[Mapping[str, Any]]) -> str:
    """Digest of exactly what a build would compose, in composition order."""

    return sha256(
        b"doxagon-presentation-compose/v2\0"
        + canonical_json(
            {
                "runtime": dict(RUNTIME_PIN),
                "checkpoints": [
                    {
                        "id": item["id"], "sources": item["sources"], "registration": item["registration"],
                        **({"scene": item["scene"]} if "scene" in item else {}),
                        **({"mode": item["mode"]} if "mode" in item else {}),
                        **({"cues": item["cues"]} if "cues" in item else {}),
                    }
                    for item in checkpoints
                ],
                "edges": [dict(edge) for edge in edges],
            }
        )
    )


@dataclass(frozen=True)
class ValidationReceipt:
    """Deterministic, path-free record of one validated revision."""

    presentation_id: str
    revision: str
    checkpoint_order: tuple[str, ...]
    checkpoints: tuple[dict[str, Any], ...]
    edges: tuple[dict[str, Any], ...]
    groups: tuple[dict[str, Any], ...]
    assets: tuple[dict[str, Any], ...]
    asset_closure_digest: str
    capability_grants: dict[str, list[str]]
    compose_hash: str
    export_policy: dict[str, Any]
    diagnostics: tuple[Diagnostic, ...]
    knowledge: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            **({"knowledge": dict(self.knowledge)} if self.knowledge is not None else {}),
            "schema": RECEIPT_SCHEMA,
            "presentation_id": self.presentation_id,
            "revision": self.revision,
            "validator": {"version": VALIDATOR_VERSION, "policy_sha256": POLICY_DIGEST},
            "runtime": dict(RUNTIME_PIN),
            "checkpoint_order": list(self.checkpoint_order),
            "checkpoints": [dict(item) for item in self.checkpoints],
            "edges": [dict(item) for item in self.edges],
            "groups": [dict(item) for item in self.groups],
            "assets": [dict(item) for item in self.assets],
            "asset_closure_digest": self.asset_closure_digest,
            "capability_grants": {key: list(value) for key, value in sorted(self.capability_grants.items())},
            "compose_hash": self.compose_hash,
            "export_policy": dict(self.export_policy),
            # Validation never executes author code, so a replay signature is
            # not available here; the sandbox runtime is the only producer that
            # may fill this in, and a build must not treat its absence as proof.
            "replay": {"status": "deferred-to-runtime", "signatures": {}},
            "diagnostics": [item.as_dict() for item in self.diagnostics],
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json(self.as_dict())

    @property
    def digest(self) -> str:
        return sha256(self.canonical_bytes())


def export_policy_for(capability_grants: Mapping[str, Iterable[str]], group_boundaries: Iterable[str]) -> dict[str, Any]:
    granted = sorted({capability for values in capability_grants.values() for capability in values})
    return {
        "ambient_network": "denied",
        "realm": "opaque-origin-sandbox-per-checkpoint-or-explicit-scene",
        "capability_default": "denied",
        "granted_capabilities": granted,
        "group_export_boundaries": sorted(group_boundaries),
    }
