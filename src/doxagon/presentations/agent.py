"""One-checkpoint agent modification: an issued task, a scoped patch, a result.

This replaces the legacy annotation prompt, which named a slide by slug, carried
no revision, no source digest, no edge, and no asset provenance, and whose only
contract was prose. A task here is versioned, targets exactly one checkpoint,
and carries the source, edge, before-state, asset, capability, and scope context
an agent needs to answer with a patch the server can check independently.

The scope travels with the server-issued task and is never read from the patch,
so an agent cannot widen its own grant. Arbitrary HTML, CSS, and JavaScript are
accepted inside the targeted checkpoint — there is no reveal/hide/style ceiling
here — because containment is the validator's job, not this surface's.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from uuid import uuid4

from doxagon.html_editions.contracts import canonical_json, sha256

from .contracts import (
    ASSET_MEDIA_TYPES,
    CAPABILITIES,
    MAX_SOURCE_BYTES,
    RUNTIME_VERSION,
    AssetProvenance,
    _identifier,
    _object,
    _string,
)
from .errors import PresentationError, WorkspaceError
from .store import now, read_json, write_json

AGENT_TASK_SCHEMA = "doxagon.presentation-agent-task/2"
AGENT_PATCH_SCHEMA = "doxagon.presentation-agent-patch/2"
AGENT_RESULT_SCHEMA = "doxagon.presentation-agent-result/2"

AGENT_TASKS_DIR = "agent-tasks"

PREVIEW_DOMAIN = b"doxagon-presentation-preview/v2\0"
STATE_DOMAIN = b"doxagon-presentation-agent-state/v2\0"

EDITABLE_ROLES = ("document", "entry", "notes", "styles")

# An agent may always produce arbitrary source inside the checkpoint its task
# targets, relabel it, and declare asset references and capability requests for
# it. Everything else — new asset bytes above all — needs a grant issued with
# the task, so the grantable set is deliberately the smaller one.
INHERENT_OPERATIONS = frozenset(
    {f"edit:{role}" for role in EDITABLE_ROLES} | {"relabel", "declare_assets", "request_capabilities"}
)
GRANTABLE_OPERATIONS = frozenset({"add_asset"})
OPERATIONS = INHERENT_OPERATIONS | GRANTABLE_OPERATIONS

# Validation never executes author code, so no static pass may claim a
# ``signature()`` value; only the sandbox runtime produces one, exactly as the
# receipt's replay block records. Both sides of the before/after evidence say so
# rather than presenting a fabricated digest as replay proof.
SIGNATURE_DEFERRED: dict[str, Any] = {"status": "deferred-to-runtime", "runtime": RUNTIME_VERSION, "value": None}

_PATCH_FIELDS = frozenset(
    {
        "schema",
        "task_id",
        "base_revision",
        "checkpoint_id",
        "before_digest",
        "label",
        "sources",
        "assets",
        "capabilities",
        "asset_requests",
        "summary",
    }
)
_CONTEXT_FIELDS = ("task_id", "base_revision", "checkpoint_id", "before_digest")
_ASSET_REQUEST_FIELDS = frozenset({"asset_id", "label", "alt", "media_type", "data_base64", "provenance"})
_MAX_SUMMARY_CHARS = 4096


def _invalid(message: str) -> WorkspaceError:
    return WorkspaceError("PRES_AGENT_PATCH_INVALID", message, status=422)


def _field(parser: Callable[[Any, str, str], Any], value: Any, subject: str) -> Any:
    try:
        return parser(value, "", subject)
    except PresentationError as error:
        raise _invalid(error.diagnostic.message) from error


# --- state, preview, and before/after evidence ---------------------------


def _receipt_checkpoint(receipt: Mapping[str, Any], checkpoint_id: str) -> Mapping[str, Any]:
    for record in receipt.get("checkpoints", ()):
        if record.get("id") == checkpoint_id:
            return record
    raise WorkspaceError("PRES_CHECKPOINT_UNKNOWN", f"no checkpoint {checkpoint_id!r} in this revision", status=404)


def preview_of(state: Mapping[str, Any]) -> dict[str, Any]:
    """Digest exactly the pinned payload a sandbox realm would load for a state."""

    payload = {
        "runtime": RUNTIME_VERSION,
        "checkpoint_id": state["checkpoint_id"],
        "sources": [dict(item) for item in state["sources"]],
        "registration": state["registration"],
        "assets": [{"id": item["id"], "sha256": item["sha256"]} for item in state["assets"]],
        "capabilities": list(state["capabilities"]),
    }
    return {**payload, "preview_sha256": sha256(PREVIEW_DOMAIN + canonical_json(payload))}


def checkpoint_state(receipt: Mapping[str, Any], checkpoint_id: str) -> dict[str, Any]:
    """Project one checkpoint's evidence from an already-validated receipt.

    Everything here was computed by the validator, so a before state and an
    after state of the same checkpoint are directly comparable and neither
    re-derives a digest the receipt already pinned.
    """

    record = _receipt_checkpoint(receipt, checkpoint_id)
    order = [str(item) for item in receipt.get("checkpoint_order", ())]
    declared = {str(item) for item in record.get("assets", ())}
    edges = [dict(item) for item in receipt.get("edges", ())]
    state = {
        "revision": receipt.get("revision"),
        "checkpoint_id": checkpoint_id,
        "index": order.index(checkpoint_id),
        "label": record.get("label"),
        "groups": list(record.get("groups", ())),
        "sources": [
            {key: item.get(key) for key in ("role", "path", "sha256", "bytes")} for item in record.get("sources", ())
        ],
        "registration": record.get("registration"),
        "assets": [dict(item) for item in receipt.get("assets", ()) if item.get("id") in declared],
        "capabilities": list(record.get("capabilities", ())),
        "edges": {
            "outgoing": [item for item in edges if item.get("from") == checkpoint_id],
            "incoming": [item for item in edges if item.get("to") == checkpoint_id],
        },
        "signature": dict(SIGNATURE_DEFERRED),
    }
    state["preview"] = preview_of(state)
    return state


def state_digest(state: Mapping[str, Any]) -> str:
    return sha256(STATE_DOMAIN + canonical_json(dict(state)))


def _neighbour(receipt: Mapping[str, Any], checkpoint_id: str) -> dict[str, Any]:
    state = checkpoint_state(receipt, checkpoint_id)
    return {
        "id": checkpoint_id,
        "label": state["label"],
        "index": state["index"],
        "preview_sha256": state["preview"]["preview_sha256"],
        "signature": state["signature"],
    }


def _edge_ids(state: Mapping[str, Any]) -> dict[str, list[str]]:
    return {
        direction: [str(edge["id"]) for edge in state["edges"][direction]] for direction in ("incoming", "outgoing")
    }


def diff_states(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    """The source, asset, capability, and edge difference the two states show."""

    before_sources = {str(item["path"]): item for item in before["sources"]}
    after_sources = {str(item["path"]): item for item in after["sources"]}
    sources = []
    for path in sorted(set(before_sources) | set(after_sources)):
        previous = before_sources.get(path)
        current = after_sources.get(path)
        sources.append(
            {
                "path": path,
                "role": (current or previous)["role"],
                "before_sha256": None if previous is None else previous["sha256"],
                "after_sha256": None if current is None else current["sha256"],
                "changed": (previous or {}).get("sha256") != (current or {}).get("sha256"),
            }
        )
    before_assets = [str(item["id"]) for item in before["assets"]]
    after_assets = [str(item["id"]) for item in after["assets"]]
    return {
        "sources": sources,
        "assets": {
            "before": before_assets,
            "after": after_assets,
            "added": sorted(set(after_assets) - set(before_assets)),
            "removed": sorted(set(before_assets) - set(after_assets)),
        },
        "capabilities": {
            "before": list(before["capabilities"]),
            "after": list(after["capabilities"]),
            "added": sorted(set(after["capabilities"]) - set(before["capabilities"])),
            "removed": sorted(set(before["capabilities"]) - set(after["capabilities"])),
        },
        "edges": {
            "before": _edge_ids(before),
            "after": _edge_ids(after),
            "changed": before["edges"] != after["edges"],
        },
        "label": {
            "before": before["label"],
            "after": after["label"],
            "changed": before["label"] != after["label"],
        },
        "preview": {
            "before": before["preview"]["preview_sha256"],
            "after": after["preview"]["preview_sha256"],
            "changed": before["preview"]["preview_sha256"] != after["preview"]["preview_sha256"],
        },
    }


# --- scope ----------------------------------------------------------------


@dataclass(frozen=True)
class AgentScope:
    """What exactly one issued task permits, named in server terms."""

    checkpoint_id: str
    allowed_operations: tuple[str, ...]
    editable_sources: tuple[tuple[str, str], ...]
    capability_vocabulary: tuple[str, ...]

    @property
    def editable_roles(self) -> frozenset[str]:
        return frozenset(role for role, _ in self.editable_sources)

    def as_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "allowed_operations": list(self.allowed_operations),
            "denied_operations": sorted(OPERATIONS - set(self.allowed_operations)),
            # A patch names a role, never a path, so these are the only bytes it
            # can reach; every other file in the revision is out of reach by
            # construction rather than by a path check.
            "editable_sources": [{"role": role, "path": path} for role, path in self.editable_sources],
            "capability_vocabulary": list(self.capability_vocabulary),
        }


def build_scope(receipt: Mapping[str, Any], checkpoint_id: str, grants: Sequence[str] = ()) -> AgentScope:
    """Resolve the operations and exact source paths one task may reach."""

    record = _receipt_checkpoint(receipt, checkpoint_id)
    for grant in grants:
        if grant not in GRANTABLE_OPERATIONS:
            raise WorkspaceError(
                "PRES_AGENT_GRANT_UNSUPPORTED",
                f"operation {grant!r} cannot be granted to an agent task",
                status=422,
            )
    allowed = tuple(sorted(INHERENT_OPERATIONS | set(grants)))
    declared = {str(item["role"]): str(item["path"]) for item in record.get("sources", ())}
    editable = tuple(
        (role, declared[role]) for role in EDITABLE_ROLES if role in declared and f"edit:{role}" in allowed
    )
    return AgentScope(checkpoint_id, allowed, editable, tuple(sorted(CAPABILITIES)))


# --- durable task records --------------------------------------------------


@dataclass(frozen=True)
class AgentTaskRecord:
    """The server-issued binding between one revision, one checkpoint, one scope."""

    task_id: str
    created_at: str
    base_revision: str
    checkpoint_id: str
    allowed_operations: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": AGENT_TASK_SCHEMA,
            "task_id": self.task_id,
            "created_at": self.created_at,
            "base_revision": self.base_revision,
            "checkpoint_id": self.checkpoint_id,
            "allowed_operations": list(self.allowed_operations),
        }

    @classmethod
    def parse(cls, payload: Any) -> "AgentTaskRecord":
        if not isinstance(payload, dict) or payload.get("schema") != AGENT_TASK_SCHEMA:
            raise WorkspaceError("PRES_STORE_CORRUPT", "stored task is not an agent task record", status=500)
        return cls(
            str(payload["task_id"]),
            str(payload["created_at"]),
            str(payload["base_revision"]),
            str(payload["checkpoint_id"]),
            tuple(str(item) for item in payload.get("allowed_operations", ())),
        )


class AgentTaskStore:
    """File-backed issued tasks; a scope is read from here, never from a patch."""

    def __init__(self, root: Path) -> None:
        self.root = root / AGENT_TASKS_DIR

    def _path(self, task_id: str) -> Path:
        if len(task_id) != 32 or any(character not in "0123456789abcdef" for character in task_id):
            raise WorkspaceError("PRES_AGENT_TASK_NOT_FOUND", "no such agent task", status=404)
        return self.root / f"{task_id}.json"

    def get(self, task_id: str) -> AgentTaskRecord:
        payload = read_json(self._path(task_id))
        if payload is None:
            raise WorkspaceError("PRES_AGENT_TASK_NOT_FOUND", "no such agent task", status=404)
        return AgentTaskRecord.parse(payload)

    def create(self, base_revision: str, scope: AgentScope) -> AgentTaskRecord:
        record = AgentTaskRecord(uuid4().hex, now(), base_revision, scope.checkpoint_id, scope.allowed_operations)
        self.root.mkdir(parents=True, exist_ok=True)
        write_json(self._path(record.task_id), record.as_dict())
        return record


# --- the issued task payload ----------------------------------------------


def scope_of(record: AgentTaskRecord, receipt: Mapping[str, Any]) -> AgentScope:
    """Rebuild the issued scope from the durable record, never from a patch."""

    return build_scope(receipt, record.checkpoint_id, tuple(sorted(set(record.allowed_operations) & GRANTABLE_OPERATIONS)))


def build_task(
    record: AgentTaskRecord,
    receipt: Mapping[str, Any],
    read_source: Callable[[str], bytes],
    *,
    current_revision: str,
) -> dict[str, Any]:
    """Assemble the versioned, single-checkpoint context an agent receives."""

    scope = scope_of(record, receipt)
    before = checkpoint_state(receipt, record.checkpoint_id)
    checkpoint = _receipt_checkpoint(receipt, record.checkpoint_id)
    order = [str(item) for item in receipt.get("checkpoint_order", ())]
    index = before["index"]
    return {
        "schema": AGENT_TASK_SCHEMA,
        "task_id": record.task_id,
        "created_at": record.created_at,
        "presentation_id": receipt.get("presentation_id"),
        "base_revision": record.base_revision,
        # An agent that reads a task after the deck moved on must know that its
        # patch cannot land, before it spends work producing one.
        "stale": record.base_revision != current_revision,
        "scope": scope.as_dict(),
        "checkpoint": {
            "id": record.checkpoint_id,
            "label": before["label"],
            "index": index,
            "source": checkpoint.get("source"),
            "groups": before["groups"],
            "sources": _sources_with_text(checkpoint, read_source),
            "registration": before["registration"],
            "assets": list(checkpoint.get("assets", ())),
            "capabilities": before["capabilities"],
        },
        "edges": before["edges"],
        "neighbours": {
            "predecessor": None if index == 0 else _neighbour(receipt, order[index - 1]),
            "successor": None if index + 1 >= len(order) else _neighbour(receipt, order[index + 1]),
        },
        "assets": {
            "declared": before["assets"],
            "available": [dict(item) for item in receipt.get("assets", ())],
        },
        "capabilities": {"granted": before["capabilities"], "vocabulary": list(scope.capability_vocabulary)},
        "before": before,
        "before_digest": state_digest(before),
        "validation": {
            "validator": receipt.get("validator"),
            "runtime": receipt.get("runtime"),
            "compose_hash": receipt.get("compose_hash"),
            "asset_closure_digest": receipt.get("asset_closure_digest"),
            "replay": receipt.get("replay"),
        },
    }


def _sources_with_text(checkpoint: Mapping[str, Any], read_source: Callable[[str], bytes]) -> list[dict[str, Any]]:
    """Every registered source of this checkpoint, as the raw bytes on disk."""

    items: list[dict[str, Any]] = []
    for item in checkpoint.get("sources", ()):
        raw = read_source(str(item["path"]))
        try:
            text: str | None = raw.decode("utf-8")
        except UnicodeDecodeError:
            # Notes are the one role no scanner forces through UTF-8, so a
            # non-text file is reported as such instead of being mangled.
            text = None
        items.append({"role": item["role"], "path": item["path"], "sha256": item["sha256"], "text": text})
    return items


# --- the patch an agent answers with ---------------------------------------


@dataclass(frozen=True)
class AssetAdmission:
    """One new immutable asset an explicitly granted patch may admit."""

    asset_id: str
    label: str
    alt: str | None
    media_type: str
    data: bytes
    provenance: AssetProvenance


@dataclass(frozen=True)
class AgentPatch:
    """A parsed, closed patch. It declares no scope; the task owns that."""

    task_id: str
    base_revision: str
    checkpoint_id: str
    before_digest: str
    label: str | None
    sources: tuple[tuple[str, bytes], ...]
    assets: tuple[str, ...] | None
    capabilities: tuple[str, ...] | None
    asset_requests: tuple[AssetAdmission, ...]
    summary: str | None

    @property
    def empty(self) -> bool:
        return not (self.sources or self.asset_requests or self.label or self.assets is not None or self.capabilities is not None)

    @classmethod
    def parse(cls, value: Any) -> "AgentPatch":
        record = _field(_object, value, "agent patch")
        unknown = sorted(set(record) - _PATCH_FIELDS)
        if unknown:
            raise _invalid(f"agent patch declares unknown field {unknown[0]!r}")
        if record.get("schema") != AGENT_PATCH_SCHEMA:
            raise WorkspaceError(
                "PRES_AGENT_PATCH_SCHEMA_UNSUPPORTED",
                f"agent patch schema must be {AGENT_PATCH_SCHEMA!r}",
                status=422,
            )
        for field in _CONTEXT_FIELDS:
            if record.get(field) is None:
                # A patch without the context it was written against cannot be
                # checked against anything, so it is refused before persistence
                # rather than applied against whatever is current.
                raise WorkspaceError(
                    "PRES_AGENT_CONTEXT_INCOMPLETE",
                    f"agent patch is missing required context {field!r}",
                    status=422,
                )
        summary = record.get("summary")
        if summary is not None:
            summary = _field(_string, summary, "agent patch summary")
        return cls(
            _field(_string, record.get("task_id"), "agent patch task_id"),
            _field(_string, record.get("base_revision"), "agent patch base_revision"),
            _field(_identifier, record.get("checkpoint_id"), "agent patch checkpoint_id"),
            _field(_string, record.get("before_digest"), "agent patch before_digest"),
            None if record.get("label") is None else _field(_string, record.get("label"), "agent patch label"),
            _parse_sources(record.get("sources")),
            _parse_ids(record.get("assets"), "agent patch asset reference"),
            _parse_capabilities(record.get("capabilities")),
            _parse_asset_requests(record.get("asset_requests")),
            summary,
        )


def _parse_sources(value: Any) -> tuple[tuple[str, bytes], ...]:
    if value is None:
        return ()
    record = _field(_object, value, "agent patch sources")
    sources: list[tuple[str, bytes]] = []
    for role in sorted(record):
        if role not in EDITABLE_ROLES:
            raise _invalid(f"source role {role!r} is not editable")
        text = record[role]
        if not isinstance(text, str):
            raise _invalid(f"source {role!r} must be a string")
        data = text.encode("utf-8")
        if len(data) > MAX_SOURCE_BYTES:
            raise _invalid(f"source {role!r} exceeds the source size limit")
        sources.append((role, data))
    return tuple(sources)


def _parse_ids(value: Any, subject: str) -> tuple[str, ...] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise _invalid(f"{subject} list must be an array")
    return tuple(_field(_identifier, item, subject) for item in value)


def _parse_capabilities(value: Any) -> tuple[str, ...] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise _invalid("agent patch capabilities must be an array")
    capabilities: list[str] = []
    for item in value:
        capability = _field(_string, item, "agent patch capability")
        if capability not in CAPABILITIES:
            raise WorkspaceError(
                "PRES_CAPABILITY_INVALID",
                f"capability {capability!r} is outside the brokered vocabulary",
                status=422,
            )
        capabilities.append(capability)
    return tuple(capabilities)


def _parse_asset_requests(value: Any) -> tuple[AssetAdmission, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise _invalid("agent patch asset_requests must be an array")
    requests: list[AssetAdmission] = []
    for item in value:
        record = _field(_object, item, "agent asset request")
        unknown = sorted(set(record) - _ASSET_REQUEST_FIELDS)
        if unknown:
            raise _invalid(f"agent asset request declares unknown field {unknown[0]!r}")
        media_type = _field(_string, record.get("media_type"), "agent asset request media_type")
        if media_type not in ASSET_MEDIA_TYPES:
            raise _invalid(f"asset media_type {media_type!r} is not supported")
        alt = record.get("alt")
        try:
            provenance = AssetProvenance.parse(record.get("provenance"), "")
        except PresentationError as error:
            raise _invalid(error.diagnostic.message) from error
        requests.append(
            AssetAdmission(
                # A requested asset names itself so the same patch can declare
                # the checkpoint reference that will point at it.
                _field(_identifier, record.get("asset_id"), "agent asset request asset_id"),
                _field(_string, record.get("label"), "agent asset request label"),
                None if alt is None else _field(_string, alt, "agent asset request alt"),
                media_type,
                _decode_asset(record.get("data_base64")),
                provenance,
            )
        )
    return tuple(requests)


def _decode_asset(payload: Any) -> bytes:
    if not isinstance(payload, str):
        raise _invalid("agent asset request data_base64 must be a base64 string")
    try:
        return base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as error:
        raise _invalid("agent asset request data_base64 is not valid base64") from error


# --- authorization ---------------------------------------------------------


def authorize(record: AgentTaskRecord, scope: AgentScope, patch: AgentPatch, before_digest: str) -> None:
    """Refuse a patch that is stale, out of scope, ungranted, or contextless."""

    if patch.task_id != record.task_id:
        raise WorkspaceError(
            "PRES_AGENT_SCOPE_VIOLATION",
            f"patch names task {patch.task_id!r}, which is not the task it was submitted to",
            status=403,
        )
    if patch.checkpoint_id != record.checkpoint_id:
        raise WorkspaceError(
            "PRES_AGENT_SCOPE_VIOLATION",
            f"patch targets checkpoint {patch.checkpoint_id!r}; this task is scoped to {record.checkpoint_id!r}",
            status=403,
        )
    if patch.base_revision != record.base_revision:
        raise WorkspaceError(
            "PRES_AGENT_BASE_REVISION_MISMATCH",
            "patch base_revision is not the revision this task was issued against",
            status=409,
            revision=record.base_revision,
        )
    if patch.before_digest != before_digest:
        # The digest covers the exact source, edge, asset, and capability state
        # the task published, so a patch written against a different before
        # state cannot be reviewed as a before/after pair.
        raise WorkspaceError(
            "PRES_AGENT_CONTEXT_STALE",
            "patch before_digest does not match the before state this task published",
            status=409,
            revision=record.base_revision,
        )
    if patch.empty:
        raise _invalid("agent patch changes nothing")
    allowed = set(record.allowed_operations)
    for role, _ in patch.sources:
        if role not in scope.editable_roles:
            raise WorkspaceError(
                "PRES_AGENT_SCOPE_VIOLATION",
                f"this task cannot write the {role!r} source of {record.checkpoint_id!r}",
                status=403,
            )
    for operation, requested in (
        ("relabel", patch.label is not None),
        ("declare_assets", patch.assets is not None),
        ("request_capabilities", patch.capabilities is not None),
        ("add_asset", bool(patch.asset_requests)),
    ):
        if requested and operation not in allowed:
            raise WorkspaceError(
                "PRES_AGENT_UNGRANTED",
                f"operation {operation!r} was not granted to this task",
                status=403,
            )


# --- outcome ---------------------------------------------------------------


@dataclass(frozen=True)
class AgentOutcome:
    """The staged result: before, after, diff, receipt, and resulting revision."""

    task_id: str
    checkpoint_id: str
    base_revision: str
    revision: str
    before: dict[str, Any]
    after: dict[str, Any]
    assets_admitted: tuple[str, ...]
    receipt: dict[str, Any]
    summary: str | None

    @property
    def diff(self) -> dict[str, Any]:
        return diff_states(self.before, self.after)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": AGENT_RESULT_SCHEMA,
            "task_id": self.task_id,
            "checkpoint_id": self.checkpoint_id,
            "base_revision": self.base_revision,
            "revision": self.revision,
            "summary": self.summary,
            "before": self.before,
            "after": self.after,
            "diff": self.diff,
            "assets_admitted": list(self.assets_admitted),
            "receipt": self.receipt,
        }
