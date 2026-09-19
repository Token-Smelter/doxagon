"""Revisioned workspace operations over one presentation.

Every mutation names the exact revision it was written against, stages a
complete candidate, validates it, and promotes it atomically; a refused
candidate leaves HEAD, every source, and every blob exactly as they were.
Reads recompute nothing and write nothing. Groups are edited here as metadata
only: `checkpoint_order` is the sole navigation authority, so a group can never
carry an order, a cursor, or a default.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import shutil
from typing import Any, Callable, Mapping, Sequence

from doxagon.html_editions.contracts import sha256

from .agent import (
    AgentOutcome,
    AgentPatch,
    AgentTaskRecord,
    AgentTaskStore,
    authorize,
    build_scope,
    build_task,
    checkpoint_state,
    scope_of,
    state_digest,
)
from .authoring import MAX_INSTRUCTION_CHARS, AgentAuthor, AuthoringRequest, author_proposal
from .contracts import (
    ASSET_ROOT,
    CAPABILITIES,
    DEFAULT_VALIDATION_POLICY,
    MANIFEST_KEY,
    REGISTRATION_SCHEMA,
    AssetProvenance,
    ValidationPolicy,
)
from .errors import WorkspaceError
from .generation import (
    GeneratedOutput,
    ImageGenerator,
    Style,
    execute_plan,
    plan_generation,
    specs_from_request,
)
from .jobs import GENERATION_KIND, THUMBNAIL_KIND, JobRecord, JobStore
from .session import SessionService
from .sources import read_contained
from .store import Promotion, RevisionStore, now, read_json, write_bytes, write_json
from .thumbnails import read_thumbnail, write_thumbnail

SOURCE_ROLES = ("entry", "document", "styles", "notes")

#: A new step registers itself and nothing else: no edge, no asset, no grant.
#: Every one of those is an explicit, separately validated act, so a created
#: step never arrives already holding authority its author did not ask for.
_NEW_PROGRAM = """/* doxagon-checkpoint-registration
{registration}
*/
export function create(context) {{
  const root = context.root;
  return {{
    enter() {{ root.dataset.entered = context.checkpointId; }},
    exit() {{ delete root.dataset.entered; }},
    signature() {{
      let hash = 2166136261;
      const text = context.checkpointId + '\\u0000' + root.innerHTML;
      for (let index = 0; index < text.length; index += 1) {{
        hash ^= text.charCodeAt(index);
        hash = Math.imul(hash, 16777619) >>> 0;
      }}
      return 'fnv1a32:' + hash.toString(16).padStart(8, '0');
    }},
    inspect() {{ return {{ checkpointId: context.checkpointId }}; }},
  }};
}}
"""

_NEW_STYLES = """.checkpoint { display: flex; flex-direction: column; gap: 1rem; padding: 2rem; }
.checkpoint h1 { font: 600 2.5rem/1.2 system-ui, sans-serif; margin: 0; }
.checkpoint p { font: 1.125rem/1.6 system-ui, sans-serif; margin: 0; }
"""

_HTML_ESCAPES = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}


def _escape(value: str) -> str:
    return "".join(_HTML_ESCAPES.get(character, character) for character in value)


def canonical_registration(checkpoint_id: str) -> str:
    """The one registration block a new step's module carries.

    The validator reads this block from the same digest-pinned bytes the
    runtime loads, so it declares exactly what the manifest record declares:
    no edge endpoint, no asset, no capability.
    """

    return json.dumps(
        {
            "schema": REGISTRATION_SCHEMA,
            "id": checkpoint_id,
            "version": "1.0.0",
            "assets": [],
            "capabilities": [],
        },
        indent=2,
        sort_keys=True,
    )


def step_id_for(label: str, taken: Sequence[str]) -> str:
    """A stable, unique step id derived from the label the author typed.

    Uniqueness is resolved by suffix rather than by silently reusing an id:
    two steps that shared one id would be one step with two labels.
    """

    cleaned = "".join(character if character.isalnum() else "-" for character in label.lower())
    cleaned = "-".join(part for part in cleaned.split("-") if part)[:56] or "step"
    if cleaned not in taken:
        return cleaned
    for suffix in range(2, 1000):
        candidate = f"{cleaned}-{suffix}"
        if candidate not in taken:
            return candidate
    raise WorkspaceError("PRES_CHECKPOINT_ID_EXHAUSTED", f"no free step id for {label!r}", status=409)
IMMUTABLE_ASSET_FIELDS = ("sha256", "bytes", "media_type", "storage_key", "provenance")
GROUP_FIELDS = frozenset({"id", "kind", "label", "checkpoints", "export_boundary"})
STYLE_FIELDS = frozenset({"id", "text", "references"})
TRANSITION_FIELDS = frozenset(
    {"edge_id", "forward_to", "back_edge_id", "back_to", "linear", "forward", "reverse", "duration_ms", "export_boundary"}
)

_STRONG_ETAG = re.compile(r'"(sha256:[a-f0-9]{64})"\Z')


def etag_for(revision: str) -> str:
    return f'"{revision}"'


@dataclass(frozen=True)
class WorkspaceView:
    """One non-mutating projection of the promoted revision."""

    revision: str
    manifest: dict[str, Any]
    checkpoints: tuple[dict[str, Any], ...]
    groups: tuple[dict[str, Any], ...]
    assets: tuple[dict[str, Any], ...]
    styles: tuple[dict[str, Any], ...] = ()

    @property
    def etag(self) -> str:
        return etag_for(self.revision)

    def as_dict(self) -> dict[str, Any]:
        return {
            "revision": self.revision,
            "checkpoint_order": list(self.manifest.get("checkpoint_order", ())),
            "checkpoints": [dict(item) for item in self.checkpoints],
            "groups": [dict(item) for item in self.groups],
            "assets": [dict(item) for item in self.assets],
            "styles": [dict(item) for item in self.styles],
        }


class _Candidate:
    """A private, complete copy of one revision that is about to be validated."""

    def __init__(self, root: Path) -> None:
        self.root = root
        manifest = read_json(root / MANIFEST_KEY)
        if not isinstance(manifest, dict):
            raise WorkspaceError("PRES_MANIFEST_INVALID_JSON", "candidate manifest is unreadable", status=500)
        # `revision` is calculated at promotion; carrying the parent's value
        # into an edited candidate would declare a digest of different bytes.
        manifest.pop("revision", None)
        self.manifest = manifest

    @property
    def checkpoints(self) -> list[dict[str, Any]]:
        return self.manifest.setdefault("checkpoints", [])

    @property
    def groups(self) -> list[dict[str, Any]]:
        return self.manifest.setdefault("groups", [])

    @property
    def assets(self) -> list[dict[str, Any]]:
        return self.manifest.setdefault("assets", [])

    @property
    def styles(self) -> list[dict[str, Any]]:
        return self.manifest.setdefault("styles", [])

    def checkpoint(self, checkpoint_id: str) -> dict[str, Any]:
        for record in self.checkpoints:
            if record.get("id") == checkpoint_id:
                return record
        raise WorkspaceError("PRES_CHECKPOINT_UNKNOWN", f"no checkpoint {checkpoint_id!r}", status=404)

    def asset(self, asset_id: str) -> dict[str, Any]:
        for record in self.assets:
            if record.get("id") == asset_id:
                return record
        raise WorkspaceError("PRES_ASSET_UNKNOWN", f"no asset {asset_id!r}", status=404)

    def write_source(self, checkpoint: Mapping[str, Any], role: str, data: bytes) -> None:
        key = checkpoint.get(role)
        if not isinstance(key, str):
            raise WorkspaceError(
                "PRES_SOURCE_UNDECLARED",
                f"checkpoint {checkpoint.get('id')!r} declares no {role!r} source",
                status=409,
            )
        write_bytes(self.root / str(checkpoint["source"]) / key, data)

    def write_asset_bytes(self, data: bytes) -> str:
        digest = sha256(data)
        path = self.root / ASSET_ROOT / "sha256" / digest
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            write_bytes(path, data)
        return digest

    def remove_asset_bytes(self, storage_key: str) -> None:
        (self.root / ASSET_ROOT / storage_key).unlink(missing_ok=True)

    def flush(self) -> None:
        write_json(self.root / MANIFEST_KEY, self.manifest)


class PresentationWorkspace:
    """The revisioned service every workspace mutation and read goes through."""

    def __init__(self, store: RevisionStore) -> None:
        self.store = store
        self.jobs = JobStore(store.root)
        self.agent_tasks = AgentTaskStore(store.root)
        # Sessions are server-authoritative: a client sends actions here and
        # receives snapshots; it never mints a cursor of its own.
        self.sessions = SessionService(store)

    @classmethod
    def create(
        cls, root: Path, deck: Path, *, policy: ValidationPolicy = DEFAULT_VALIDATION_POLICY
    ) -> "PresentationWorkspace":
        """Admit a validated deck as the first revision of a new workspace."""

        store = RevisionStore.create(root, policy=policy)
        if store.head is not None:
            raise WorkspaceError("PRES_WORKSPACE_EXISTS", "this root already holds a workspace", status=409)
        with store.candidate() as candidate:
            shutil.rmtree(candidate)
            shutil.copytree(deck, candidate, symlinks=True)
            store.promote(candidate)
        return cls(store)

    @classmethod
    def open(cls, root: Path, *, policy: ValidationPolicy = DEFAULT_VALIDATION_POLICY) -> "PresentationWorkspace":
        return cls(RevisionStore.open(root, policy=policy))

    @property
    def policy(self) -> ValidationPolicy:
        """The validation policy every mutation and export of this deck uses."""

        return self.store.policy

    # --- reads (never write) ---------------------------------------------

    @property
    def revision(self) -> str:
        return self.store.revision

    @property
    def etag(self) -> str:
        return etag_for(self.revision)

    def read(self, revision: str | None = None) -> WorkspaceView:
        """Project one promoted revision from its stored manifest and receipt.

        A caller that just promoted names its own revision so the projection
        describes that promotion and not whatever HEAD has since become.
        """

        revision = revision or self.store.revision
        manifest = self.store.read_manifest(revision)
        receipt = self.store.read_receipt(revision)
        order = list(manifest.get("checkpoint_order", ()))
        registered = {str(item["id"]): item for item in receipt.get("checkpoints", ())}
        generated_by = self._generation_index(manifest)
        checkpoints = tuple(
            {
                "id": checkpoint_id,
                "index": index,
                "label": registered[checkpoint_id]["label"],
                "groups": list(registered[checkpoint_id].get("groups", ())),
                "assets": list(registered[checkpoint_id].get("assets", ())),
                "capabilities": list(registered[checkpoint_id].get("capabilities", ())),
                "sources": [dict(item) for item in registered[checkpoint_id].get("sources", ())],
                # HEAD is validated by construction: a candidate that fails
                # validation is never promoted, so a listed checkpoint is
                # registered, and no read has to re-derive that.
                "status": "registered",
            }
            for index, checkpoint_id in enumerate(order)
            if checkpoint_id in registered
        )
        references: dict[str, list[str]] = {}
        for checkpoint in checkpoints:
            for asset_id in checkpoint["assets"]:
                references.setdefault(asset_id, []).append(checkpoint["id"])
        assets = tuple(
            {
                **record,
                "referenced_by": references.get(str(record["id"]), []),
                "generation": generated_by.get(str(record["id"])),
                "thumbnail": read_thumbnail(self.store.root, str(record["sha256"])) is not None,
            }
            for record in manifest.get("assets", ())
        )
        return WorkspaceView(
            revision,
            manifest,
            checkpoints,
            tuple(manifest.get("groups", ())),
            assets,
            tuple(manifest.get("styles", ())),
        )

    def asset_bytes(self, asset_id: str, revision: str | None = None) -> bytes:
        target = revision or self.store.revision
        record = self._asset_record(self.store.read_manifest(target), asset_id)
        return read_contained(
            self.store.revision_root(target),
            f"{ASSET_ROOT}/{record['storage_key']}",
            declared_size=int(record["bytes"]),
            maximum=int(record["bytes"]),
        )

    def thumbnail(self, asset_id: str) -> bytes | None:
        """Return an already-derived thumbnail; a read never derives one."""

        record = self._asset_record(self.store.read_manifest(), asset_id)
        return read_thumbnail(self.store.root, str(record["sha256"]))

    # --- checkpoint, group, and source mutations --------------------------

    def set_checkpoint_label(self, if_match: str | None, checkpoint_id: str, label: str) -> WorkspaceView:
        def mutate(candidate: _Candidate) -> None:
            candidate.checkpoint(checkpoint_id)["label"] = label

        return self._mutate(if_match, mutate)

    def reorder_checkpoints(self, if_match: str | None, checkpoint_ids: Sequence[str]) -> WorkspaceView:
        """Rewrite `checkpoint_order` only; creative source is never touched."""

        def mutate(candidate: _Candidate) -> None:
            current = [str(record["id"]) for record in candidate.checkpoints]
            requested = list(checkpoint_ids)
            if sorted(requested) != sorted(current):
                raise WorkspaceError(
                    "PRES_CHECKPOINT_ORDER_MISMATCH",
                    "a reorder must list every existing checkpoint exactly once",
                    status=422,
                )
            candidate.manifest["checkpoint_order"] = requested

        return self._mutate(if_match, mutate)

    def add_checkpoint(self, if_match: str | None, label: str, *, after: str | None = None) -> WorkspaceView:
        """Register one new step and place it in `checkpoint_order`.

        The step is created with its own registered source and no edge, asset,
        or capability. `after` names the step it follows; omitting it appends.
        A step is only ever created by promoting a validated candidate, so a
        source the validator would refuse never lands.
        """

        def mutate(candidate: _Candidate) -> None:
            taken = [str(record["id"]) for record in candidate.checkpoints]
            checkpoint_id = step_id_for(label, taken)
            source = f"checkpoints/{checkpoint_id}"
            registration = canonical_registration(checkpoint_id)
            record = {
                "id": checkpoint_id,
                "label": label,
                "source": source,
                "entry": "program.js",
                "document": "document.html",
                "styles": "styles.css",
                "notes": "notes.md",
                "assets": [],
            }
            root = candidate.root / source
            root.mkdir(parents=True, exist_ok=True)
            write_bytes(root / "program.js", _NEW_PROGRAM.format(registration=registration).encode("utf-8"))
            write_bytes(
                root / "document.html",
                (
                    f'<section class="checkpoint" data-checkpoint="{_escape(checkpoint_id)}">\n'
                    f"  <h1>{_escape(label)}</h1>\n</section>\n"
                ).encode("utf-8"),
            )
            write_bytes(root / "styles.css", _NEW_STYLES.encode("utf-8"))
            write_bytes(root / "notes.md", f"Notes for {label}.\n".encode("utf-8"))
            candidate.checkpoints.append(record)
            order = list(candidate.manifest.get("checkpoint_order", ()))
            position = len(order) if after is None or after not in order else order.index(after) + 1
            order.insert(position, checkpoint_id)
            candidate.manifest["checkpoint_order"] = order

        return self._mutate(if_match, mutate)

    def delete_checkpoint(self, if_match: str | None, checkpoint_id: str) -> WorkspaceView:
        """Retire one step, refusing while any registered edge still names it.

        Deleting a step another step's registration points at would either
        break that registration or silently rewrite creative source. Both are
        worse than a refusal that says which step still holds the edge.
        """

        def mutate(candidate: _Candidate) -> None:
            candidate.checkpoint(checkpoint_id)
            order = [item for item in candidate.manifest.get("checkpoint_order", ()) if item != checkpoint_id]
            if not order:
                raise WorkspaceError(
                    "PRES_CHECKPOINT_LAST",
                    "a presentation keeps at least one step; delete the presentation instead",
                    status=409,
                )
            holders = [
                str(record["id"])
                for record in candidate.checkpoints
                if str(record["id"]) != checkpoint_id
                and checkpoint_id in (record.get("transition") or {}).values()
            ]
            if holders:
                raise WorkspaceError(
                    "PRES_CHECKPOINT_REFERENCED",
                    f"{', '.join(sorted(holders))} still registers a transition to {checkpoint_id!r}; "
                    "retire that transition first",
                    status=409,
                )
            candidate.manifest["checkpoint_order"] = order
            candidate.manifest["checkpoints"] = [
                record for record in candidate.checkpoints if str(record["id"]) != checkpoint_id
            ]
            for group in candidate.groups:
                group["checkpoints"] = [item for item in group.get("checkpoints", ()) if item != checkpoint_id]

        return self._mutate(if_match, mutate)

    def put_checkpoint_source(self, if_match: str | None, checkpoint_id: str, role: str, data: bytes) -> WorkspaceView:
        if role not in SOURCE_ROLES:
            raise WorkspaceError("PRES_SOURCE_ROLE_UNSUPPORTED", f"source role {role!r} is not editable", status=422)

        def mutate(candidate: _Candidate) -> None:
            candidate.write_source(candidate.checkpoint(checkpoint_id), role, data)

        return self._mutate(if_match, mutate)

    def set_checkpoint_assets(self, if_match: str | None, checkpoint_id: str, asset_ids: Sequence[str]) -> WorkspaceView:
        """Declare which assets a checkpoint may receive handles for."""

        def mutate(candidate: _Candidate) -> None:
            candidate.checkpoint(checkpoint_id)["assets"] = list(asset_ids)

        return self._mutate(if_match, mutate)

    def set_checkpoint_capabilities(
        self, if_match: str | None, checkpoint_id: str, capabilities: Sequence[str]
    ) -> WorkspaceView:
        """Rewrite one checkpoint's capability grants.

        The manifest is the grant authority and the registration is the
        request, so validation refuses a revision whose program still requests
        a capability this grant removed (`PRES_CAPABILITY_UNGRANTED`). Denial
        is therefore the default a revoke actually reaches, not a display
        state: an unknown capability is refused here by name.
        """

        unknown = sorted(set(capabilities) - CAPABILITIES)
        if unknown:
            raise WorkspaceError(
                "PRES_CAPABILITY_UNKNOWN",
                f"capability {unknown[0]!r} is not a declared capability",
                status=422,
            )

        def mutate(candidate: _Candidate) -> None:
            candidate.checkpoint(checkpoint_id)["capabilities"] = list(capabilities)

        return self._mutate(if_match, mutate)

    def set_checkpoint_transition(
        self, if_match: str | None, checkpoint_id: str, transition: Mapping[str, Any] | None
    ) -> WorkspaceView:
        """Rewrite one checkpoint's half of its registered edges.

        An edge is only ever checkpoint-to-checkpoint and must be reversible:
        `build_edges` refuses a forward half with no matching reverse half, and
        `registration_agreement` refuses an endpoint the checkpoint's program
        does not declare. Both run during promotion, so a partial or
        one-directional edit is rejected rather than landed.
        """

        record = None if transition is None else dict(transition)
        if record is not None:
            unknown = sorted(set(record) - TRANSITION_FIELDS)
            if unknown:
                raise WorkspaceError(
                    "PRES_TRANSITION_FIELD_UNKNOWN",
                    f"a transition cannot declare {unknown[0]!r}",
                    status=422,
                )

        def mutate(candidate: _Candidate) -> None:
            checkpoint = candidate.checkpoint(checkpoint_id)
            if record is None:
                checkpoint.pop("transition", None)
            else:
                checkpoint["transition"] = record

        return self._mutate(if_match, mutate)

    def put_group(self, if_match: str | None, group: Mapping[str, Any]) -> WorkspaceView:
        """Create or replace one grouping record. A group owns no navigation."""

        unknown = sorted(set(group) - GROUP_FIELDS)
        if unknown:
            raise WorkspaceError(
                "PRES_GROUP_NOT_AUTHORITY",
                f"a group cannot declare {unknown[0]!r}; checkpoint_order is the only navigation authority",
                status=422,
            )
        record = {key: group[key] for key in ("id", "kind", "label", "checkpoints") if key in group}
        if "export_boundary" in group:
            record["export_boundary"] = group["export_boundary"]

        def mutate(candidate: _Candidate) -> None:
            groups = candidate.groups
            for index, existing in enumerate(groups):
                if existing.get("id") == record.get("id"):
                    groups[index] = record
                    return
            groups.append(record)

        return self._mutate(if_match, mutate)

    def delete_group(self, if_match: str | None, group_id: str) -> WorkspaceView:
        def mutate(candidate: _Candidate) -> None:
            groups = candidate.groups
            remaining = [record for record in groups if record.get("id") != group_id]
            if len(remaining) == len(groups):
                raise WorkspaceError("PRES_GROUP_UNKNOWN", f"no group {group_id!r}", status=404)
            candidate.manifest["groups"] = remaining

        return self._mutate(if_match, mutate)

    # --- prompt style mutations -------------------------------------------

    def put_style(self, if_match: str | None, style: Mapping[str, Any]) -> WorkspaceView:
        """Create or replace one reusable prompt style, by id.

        A style is deck content, so an edit is a promotion: the generations that
        already ran keep the prompt text they were given, and the next one reads
        the revision it names.
        """

        unknown = sorted(set(style) - STYLE_FIELDS)
        if unknown:
            raise WorkspaceError("PRES_STYLE_FIELD_UNKNOWN", f"a style cannot declare {unknown[0]!r}", status=422)
        record = {"id": style.get("id"), "text": style.get("text"), "references": list(style.get("references") or ())}

        def mutate(candidate: _Candidate) -> None:
            styles = candidate.styles
            for index, existing in enumerate(styles):
                if existing.get("id") == record["id"]:
                    styles[index] = record
                    return
            styles.append(record)

        return self._mutate(if_match, mutate)

    def delete_style(self, if_match: str | None, style_id: str) -> WorkspaceView:
        def mutate(candidate: _Candidate) -> None:
            styles = candidate.styles
            remaining = [record for record in styles if record.get("id") != style_id]
            if len(remaining) == len(styles):
                raise WorkspaceError("PRES_STYLE_UNKNOWN", f"no style {style_id!r}", status=404)
            candidate.manifest["styles"] = remaining

        return self._mutate(if_match, mutate)

    # --- asset mutations ---------------------------------------------------

    def add_asset(
        self,
        if_match: str | None,
        data: bytes,
        *,
        label: str,
        alt: str | None,
        media_type: str,
        provenance: AssetProvenance,
        asset_id: str | None = None,
    ) -> WorkspaceView:
        """Admit immutable bytes as one independently labeled asset record."""

        def mutate(candidate: _Candidate) -> None:
            _admit(candidate, data, label, alt, media_type, provenance, asset_id)

        return self._mutate(if_match, mutate)

    def admit_generated(self, if_match: str | None, outputs: Sequence[GeneratedOutput]) -> WorkspaceView:
        """Admit every produced variant in one revision, selecting none of them."""

        def mutate(candidate: _Candidate) -> None:
            for output in outputs:
                _admit(
                    candidate,
                    output.image.data,
                    output.variant.label,
                    output.variant.alt,
                    output.image.media_type,
                    output.provenance(),
                    output.asset_id,
                )

        return self._mutate(if_match, mutate)

    def set_asset_label(
        self, if_match: str | None, asset_id: str, *, label: str | None = None, alt: str | None = None
    ) -> WorkspaceView:
        """Relabel an asset. Its bytes, digest, and provenance stay immutable."""

        def mutate(candidate: _Candidate) -> None:
            record = candidate.asset(asset_id)
            if label is not None:
                record["label"] = label
            if alt is not None:
                record["alt"] = alt

        return self._mutate(if_match, mutate)

    def delete_asset(self, if_match: str | None, asset_id: str) -> WorkspaceView:
        """Retire an unreferenced asset; a referenced one is refused."""

        def mutate(candidate: _Candidate) -> None:
            record = candidate.asset(asset_id)
            holders = [
                str(checkpoint["id"])
                for checkpoint in candidate.checkpoints
                if asset_id in (checkpoint.get("assets") or ())
            ]
            if holders:
                raise WorkspaceError(
                    "PRES_ASSET_IN_USE",
                    f"asset {asset_id!r} is referenced by {', '.join(holders)}",
                    status=409,
                )
            remaining = [item for item in candidate.assets if item.get("id") != asset_id]
            candidate.manifest["assets"] = remaining
            storage_key = str(record["storage_key"])
            # Content-identical variants are separate records over one blob, so
            # the bytes are retired only when the last record naming them goes.
            if all(item.get("storage_key") != storage_key for item in remaining):
                candidate.remove_asset_bytes(storage_key)

        return self._mutate(if_match, mutate)

    # --- single-checkpoint agent modification ------------------------------

    def open_agent_task(self, checkpoint_id: str, *, grants: Sequence[str] = ()) -> dict[str, Any]:
        """Issue one versioned task scoped to exactly one checkpoint."""

        revision = self.store.revision
        scope = build_scope(self.store.read_receipt(revision), checkpoint_id, tuple(grants))
        return self._agent_task(self.agent_tasks.create(revision, scope))

    def read_agent_task(self, task_id: str) -> dict[str, Any]:
        return self._agent_task(self.agent_tasks.get(task_id))

    def propose_agent_edit(
        self, task_id: str, *, role: str, instruction: str, author: AgentAuthor | None
    ) -> dict[str, Any]:
        """Have the configured author write one editable role of this task.

        The scope check happens here, against the issued task, before any
        backend is invoked: an author is never asked to write a role the task
        could not promote. Nothing is mutated — the answer is a proposal a human
        still has to approve through `apply_agent_patch`.
        """

        if author is None:
            raise WorkspaceError(
                "PRES_AGENT_AUTHOR_UNAVAILABLE", "no authoring backend is configured", status=503
            )
        if not isinstance(instruction, str) or not instruction.strip():
            raise WorkspaceError(
                "PRES_AGENT_INSTRUCTION_REQUIRED", "an AI edit needs an instruction to write against", status=422
            )
        if len(instruction) > MAX_INSTRUCTION_CHARS:
            raise WorkspaceError(
                "PRES_AGENT_INSTRUCTION_TOO_LONG",
                f"an instruction may be at most {MAX_INSTRUCTION_CHARS} characters",
                status=422,
            )
        task = self.read_agent_task(task_id)
        if task["stale"]:
            # Writing against a revision this task can no longer patch would
            # spend the backend's work on bytes the server must refuse.
            raise WorkspaceError(
                "PRES_AGENT_TASK_STALE",
                "this agent task was issued against an older revision",
                status=409,
                revision=self.store.revision,
            )
        editable = {str(item["role"]) for item in task["scope"]["editable_sources"]}
        if role not in editable:
            raise WorkspaceError(
                "PRES_AGENT_SCOPE_VIOLATION",
                f"this task cannot write the {role!r} source of {task['scope']['checkpoint_id']!r}",
                status=403,
            )
        return author_proposal(AuthoringRequest(task, role, instruction), author)

    def apply_agent_patch(self, if_match: str | None, task_id: str, patch: Mapping[str, Any]) -> AgentOutcome:
        """Stage, validate, and promote one agent patch, or change nothing.

        Scope and base revision come from the issued task; the patch supplies
        only content. Every refusal happens before the candidate is promoted, so
        a rejected patch leaves HEAD, every source, and every blob untouched.
        """

        record = self.agent_tasks.get(task_id)
        parsed = AgentPatch.parse(patch)
        receipt = self.store.read_receipt(record.base_revision)
        before = checkpoint_state(receipt, record.checkpoint_id)
        authorize(record, scope_of(record, receipt), parsed, state_digest(before))
        current = self.store.revision
        if record.base_revision != current:
            # The context this patch was written against is no longer the deck;
            # re-issuing the task is the only honest recovery.
            raise WorkspaceError(
                "PRES_AGENT_TASK_STALE",
                "this agent task was issued against an older revision",
                status=409,
                revision=current,
            )
        # The task's base revision is the state this mutation edits, so the
        # caller's If-Match must name it; `_promote` re-checks the same tag
        # under the store lock, which makes base == current atomic.
        require_match(if_match, record.base_revision)

        def mutate(candidate: _Candidate) -> None:
            checkpoint = candidate.checkpoint(record.checkpoint_id)
            for request in parsed.asset_requests:
                _admit(
                    candidate,
                    request.data,
                    request.label,
                    request.alt,
                    request.media_type,
                    request.provenance,
                    request.asset_id,
                )
            if parsed.label is not None:
                checkpoint["label"] = parsed.label
            for role, data in parsed.sources:
                candidate.write_source(checkpoint, role, data)
            if parsed.assets is not None:
                checkpoint["assets"] = list(parsed.assets)
            if parsed.capabilities is not None:
                checkpoint["capabilities"] = list(parsed.capabilities)

        # Source, closure, and capability changes land as one candidate: an
        # intermediate revision that granted a capability without the module
        # using it — or the reverse — need not validate, and must not be stored.
        #
        # The evidence below is read from the promotion this call produced,
        # never from HEAD: HEAD is mutable, so a writer that lands between the
        # unlock and this response would otherwise be reported as this patch's
        # own after-state, revision, and receipt.
        promotion = self._promote(if_match, mutate)
        return AgentOutcome(
            record.task_id,
            record.checkpoint_id,
            record.base_revision,
            promotion.revision,
            before,
            checkpoint_state(promotion.receipt, record.checkpoint_id),
            tuple(request.asset_id for request in parsed.asset_requests),
            promotion.receipt,
            parsed.summary,
        )

    def _agent_task(self, record: AgentTaskRecord) -> dict[str, Any]:
        root = self.store.revision_root(record.base_revision)
        return build_task(
            record,
            self.store.read_receipt(record.base_revision),
            lambda key: read_contained(root, key),
            current_revision=self.store.revision,
        )

    # --- generation and thumbnail jobs -------------------------------------

    def start_generation(
        self,
        *,
        idempotency_key: str,
        targets: Sequence[Mapping[str, Any]],
        defaults: Mapping[str, Any] | None = None,
        styles: Sequence[Mapping[str, Any]] = (),
    ) -> JobRecord:
        """Record one generation request. A single target is a batch of one."""

        request = {
            "targets": [dict(target) for target in targets],
            "defaults": dict(defaults or {}),
            "styles": [dict(style) for style in styles],
        }
        # Planning here fails an impossible request before it becomes a job.
        self._plan(request)
        return self.jobs.submit(GENERATION_KIND, idempotency_key, request, self.store.revision)

    def run_generation(self, job_id: str, generator: ImageGenerator) -> JobRecord:
        """Execute a planned generation and admit whatever it produced."""

        record = self.jobs.start(job_id)
        failures: tuple[dict[str, Any], ...] = ()
        try:
            plan = self._plan(record.request, record.base_revision)
            manifest = self.store.read_manifest(record.base_revision)
            known = {str(item["id"]) for item in manifest.get("checkpoints", ())}
            for variant in plan.variants:
                if variant.checkpoint_id not in known:
                    raise WorkspaceError(
                        "PRES_CHECKPOINT_UNKNOWN",
                        f"no checkpoint {variant.checkpoint_id!r} in the requested revision",
                        status=404,
                    )
            references = {
                asset_id: self.asset_bytes(asset_id, record.base_revision) for asset_id in plan.references
            }
            outputs, failures = execute_plan(
                plan, generator, references, created_at=now(), lineage=record.lineage_id
            )
            if not outputs:
                return self.jobs.fail(job_id, "PRES_GENERATION_FAILED", "no variant was produced", failures=failures)
            view = self.admit_generated(etag_for(record.base_revision), outputs)
        except WorkspaceError as error:
            return self.jobs.fail(job_id, error.code, error.message)
        return self.jobs.succeed(
            job_id,
            outputs=[
                {
                    "checkpoint_id": output.variant.checkpoint_id,
                    "variant_index": output.variant.variant_index,
                    "asset_id": output.asset_id,
                    "label": output.variant.label,
                    "sha256": output.digest,
                    "prompt_sha256": output.variant.prompt.sha256,
                    # The exact text this generator was given, not a recipe for
                    # rebuilding it. `prompt_sha256` attests to these bytes, and
                    # a later change to how prompts are assembled would make a
                    # reconstruction attest to something else entirely.
                    "prompt": output.variant.prompt.text,
                    "prompt_references": list(output.variant.prompt.references),
                    "settings": output.variant.settings.as_dict(),
                }
                for output in outputs
            ],
            failures=failures,
            revision=view.revision,
        )

    def start_thumbnails(self, *, idempotency_key: str, asset_ids: Sequence[str]) -> JobRecord:
        return self.jobs.submit(
            THUMBNAIL_KIND, idempotency_key, {"asset_ids": list(asset_ids)}, self.store.revision
        )

    def run_thumbnails(self, job_id: str) -> JobRecord:
        """Derive thumbnails outside every revision; no source byte changes."""

        record = self.jobs.start(job_id)
        outputs: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        for asset_id in record.request.get("asset_ids", ()):
            try:
                data = self.asset_bytes(str(asset_id), record.base_revision)
                outputs.append({"asset_id": asset_id, **write_thumbnail(self.store.root, sha256(data), data)})
            except WorkspaceError as error:
                failures.append({"asset_id": asset_id, "code": error.code, "message": error.message})
        if not outputs:
            return self.jobs.fail(job_id, "PRES_THUMBNAIL_FAILED", "no thumbnail was derived", failures=failures)
        return self.jobs.succeed(job_id, outputs=outputs, failures=failures, revision=record.base_revision)

    def retry_job(self, job_id: str) -> JobRecord:
        """Retry failed work against the revision that is current now."""

        return self.jobs.retry(job_id, self.store.revision)

    # --- internals ---------------------------------------------------------

    def _plan(self, request: Mapping[str, Any], base_revision: str | None = None):
        """Plan against the deck's stored styles, plus whatever this request inlined.

        The library is read from the revision the job was submitted for, not
        from HEAD, so re-planning a recorded job at run time cannot silently
        compose a different prompt than the one its digest was minted from.
        """

        stored = self.store.read_manifest(base_revision).get("styles", ())
        styles = {
            str(style["id"]): Style(str(style["id"]), str(style["text"]), tuple(style.get("references") or ()))
            for style in stored
        }
        for style in request.get("styles", ()):
            style_id = str(style["id"])
            # A request may still inline a one-off fragment, but it cannot take
            # a stored style's name: shadowing one would run the generation
            # against the client's text while the record, and every later
            # reader of it, named the style the deck approved.
            if style_id in styles:
                raise WorkspaceError(
                    "PRES_STYLE_ID_DUPLICATE",
                    f"style {style_id!r} is stored on this deck; edit it there rather than inlining it",
                    status=422,
                )
            styles[style_id] = Style(style_id, str(style["text"]), tuple(style.get("references") or ()))
        specs = specs_from_request(request.get("targets", ()), request.get("defaults"))
        return plan_generation(specs, styles)

    def _generation_index(self, manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
        """What each generated asset's job recorded, as far as the deck attests it.

        Only `prompt_sha256` is promoted into an asset's provenance; the prompt
        text itself stays in the job record, which lives outside the revision
        tree and outside the revision digest. So the attestation is what a read
        trusts: the text is shown when it still hashes to the digest the deck
        promoted, and withheld when it does not, rather than repeating whatever
        a job file happens to say now as the prompt an asset was generated from.
        """

        attested = {
            str(record["id"]): (record.get("provenance") or {}).get("prompt_sha256")
            for record in manifest.get("assets", ())
        }
        index: dict[str, dict[str, Any]] = {}
        for record in self.jobs.list(kind=GENERATION_KIND):
            for output in record.outputs:
                asset_id = str(output["asset_id"])
                digest = attested.get(asset_id)
                prompt = output.get("prompt")
                intact = isinstance(prompt, str) and digest is not None and sha256(prompt.encode("utf-8")) == digest
                index[asset_id] = {
                    "job_id": record.job_id,
                    "status": record.status,
                    "prompt_sha256": digest,
                    "prompt": prompt if intact else None,
                    "prompt_references": list(output.get("prompt_references") or ()),
                    "variant_index": output.get("variant_index"),
                    "requested_for": output.get("checkpoint_id"),
                }
        return index

    def _asset_record(self, manifest: Mapping[str, Any], asset_id: str) -> Mapping[str, Any]:
        for record in manifest.get("assets", ()):
            if record.get("id") == asset_id:
                return record
        raise WorkspaceError("PRES_ASSET_UNKNOWN", f"no asset {asset_id!r}", status=404)

    def _promote(self, if_match: str | None, mutate: Callable[[_Candidate], None]) -> Promotion:
        """Stage, validate, and land one mutation, returning the exact promotion.

        The returned revision and receipt are the ones this call landed, so a
        caller never has to reread mutable HEAD to describe its own result.
        """

        with self.store.exclusive():
            current = self.store.revision
            require_match(if_match, current)
            with self.store.candidate() as root:
                candidate = _Candidate(root)
                mutate(candidate)
                candidate.flush()
                return self.store.promote(root)

    def _mutate(self, if_match: str | None, mutate: Callable[[_Candidate], None]) -> WorkspaceView:
        return self.read(self._promote(if_match, mutate).revision)


def require_match(if_match: str | None, current: str) -> None:
    """Demand one strong quoted revision. `*` and weak tags are not identity."""

    if if_match is None or not if_match.strip():
        raise WorkspaceError(
            "PRES_IF_MATCH_REQUIRED", "this mutation requires an If-Match revision", status=428, revision=current
        )
    matched = _STRONG_ETAG.fullmatch(if_match.strip())
    if matched is None:
        # `*`, `W/"…"`, a list, or a bare digest cannot express "exactly the
        # revision I read", so none of them is accepted as a precondition.
        raise WorkspaceError(
            "PRES_IF_MATCH_INVALID",
            "If-Match must be exactly one strong quoted revision",
            status=400,
            revision=current,
        )
    if matched.group(1) != current:
        raise WorkspaceError(
            "PRES_REVISION_CONFLICT", "If-Match does not name the current revision", status=409, revision=current
        )


def _admit(
    candidate: _Candidate,
    data: bytes,
    label: str,
    alt: str | None,
    media_type: str,
    provenance: AssetProvenance,
    asset_id: str | None,
) -> None:
    """Add one immutable asset record; re-admitting an identical one is a no-op."""

    digest = candidate.write_asset_bytes(data)
    identifier = asset_id or f"asset_{digest[:16]}"
    record = {
        "id": identifier,
        "label": label,
        "alt": alt,
        "media_type": media_type,
        "bytes": len(data),
        "sha256": digest,
        "storage_key": f"sha256/{digest}",
        "provenance": provenance.as_dict(),
    }
    for existing in candidate.assets:
        if existing.get("id") != identifier:
            continue
        # Same identifier means same asset, so every immutable member must
        # already agree. Comparing only the digest would let one record keep
        # the first admission's provenance while answering success to a second
        # admission that carried different origin. `label` and `alt` are the
        # two members set_asset_label may edit, so they are not compared.
        differing = [field for field in IMMUTABLE_ASSET_FIELDS if existing.get(field) != record[field]]
        if differing:
            raise WorkspaceError(
                "PRES_ASSET_IMMUTABLE",
                f"asset {identifier!r} already holds a different {differing[0]}",
                status=409,
            )
        return
    candidate.assets.append(record)
