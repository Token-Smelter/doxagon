"""HTTP surface for the revisioned presentation workspace.

Reads answer with the revision as a strong `ETag`; every mutation demands that
exact tag back as `If-Match` and answers with the revision it produced. The
agent surface issues a task scoped to one checkpoint and applies a patch back
against that task, so no route lets an agent name its own scope. There is no
display-selection route here: a checkpoint's position comes from
`checkpoint_order`, and an asset is never marked primary or selected.
"""

from __future__ import annotations

import base64
import binascii
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Header, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .authoring import AgentAuthor
from .contracts import DEFAULT_VALIDATION_POLICY, AssetProvenance, ValidationPolicy
from .errors import PresentationError, WorkspaceError
from .exporters import (
    DEFERRED_FORMATS,
    RasterCapturer,
    export_offline_html,
    export_document_html,
    export_public_html,
    export_raster,
    export_scroll_html,
    export_source_archive,
)
from .generation import ImageGenerator
from .jobs import JOB_KINDS, THUMBNAIL_KIND
from .runtime import RUNTIME_SHA256, build_deck_payload, runtime_source
from .session import ACTIONS
from .thumbnails import THUMBNAIL_MEDIA_TYPE
from .vault import open_or_migrate
from .workspace import PresentationWorkspace, WorkspaceView, etag_for


class _ClosedRequest(BaseModel):
    """A body may not carry a member this surface does not declare.

    Accepting and dropping an undeclared member answers success to work that
    was never done, so an unknown member is a refused request, not a silent
    omission.
    """

    model_config = ConfigDict(extra="forbid")


class ReorderRequest(_ClosedRequest):
    checkpoint_order: list[str]


class LabelRequest(_ClosedRequest):
    label: str = Field(min_length=1, max_length=4096)


class CheckpointCreateRequest(_ClosedRequest):
    label: str = Field(min_length=1, max_length=4096)
    # The step this one follows. Absent means append; the server never infers
    # a position from a client-supplied index.
    after: str | None = None


class CheckpointAssetsRequest(_ClosedRequest):
    assets: list[str]


class CapabilitiesRequest(_ClosedRequest):
    capabilities: list[str]


class TransitionRequest(_ClosedRequest):
    # `None` retires this checkpoint's edge halves entirely; a body that named
    # a member this surface does not declare would be a silent partial edit.
    transition: dict[str, Any] | None = None


class GroupRequest(BaseModel):
    # Open at the model, closed at the guard: an undeclared member is forwarded
    # to put_group, which refuses it by name as PRES_GROUP_NOT_AUTHORITY, while
    # the route refuses a body-owned `id` before that. A group that carried an
    # order, cursor, or default would be a second navigation authority, and
    # exactly one guard states that there is only one.
    model_config = ConfigDict(extra="allow")

    kind: str
    label: str
    checkpoints: list[str] = Field(default_factory=list)
    export_boundary: bool = False


class AssetRequest(_ClosedRequest):
    data_base64: str
    label: str
    media_type: str
    alt: str | None = None
    asset_id: str | None = None
    provenance: dict[str, Any]


class AssetLabelRequest(_ClosedRequest):
    label: str | None = None
    alt: str | None = None


class GenerationRequest(_ClosedRequest):
    idempotency_key: str = Field(min_length=1, max_length=200)
    targets: list[dict[str, Any]]
    defaults: dict[str, Any] = Field(default_factory=dict)
    styles: list[dict[str, Any]] = Field(default_factory=list)


class ThumbnailRequest(_ClosedRequest):
    idempotency_key: str = Field(min_length=1, max_length=200)
    asset_ids: list[str]


class AgentTaskRequest(_ClosedRequest):
    grants: list[str] = Field(default_factory=list)


class AgentProposalRequest(_ClosedRequest):
    # The role is checked against the issued task's own editable sources, so a
    # body cannot widen what an author is asked to write.
    role: str = Field(min_length=1, max_length=64)
    instruction: str = Field(min_length=1, max_length=4096)


class SessionRequest(_ClosedRequest):
    session_id: str | None = None
    revision: str | None = None


class ActionRequest(_ClosedRequest):
    type: str
    checkpointId: str | None = None
    cue: str | None = None
    expected_revision: str | None = None


class StyleRequest(BaseModel):
    # Open at the model, closed at the guard, exactly as GroupRequest is: an
    # undeclared member reaches put_style, which refuses it by name.
    model_config = ConfigDict(extra="allow")

    text: str
    references: list[str] = Field(default_factory=list)


class RasterRequest(_ClosedRequest):
    groups: list[str] | None = None


def _view_response(view: WorkspaceView, status: int = 200) -> JSONResponse:
    return JSONResponse(view.as_dict(), status_code=status, headers={"ETag": view.etag})


def _decode(payload: str) -> bytes:
    try:
        return base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as error:
        raise WorkspaceError("PRES_ASSET_PAYLOAD_INVALID", "asset data must be base64") from error


def _provenance(record: dict[str, Any]) -> AssetProvenance:
    try:
        return AssetProvenance.parse(record, "/provenance")
    except PresentationError as error:
        raise WorkspaceError(error.diagnostic.code, error.diagnostic.message, status=422) from error


def create_presentation_router(dependency: Any, prefix: str = "/presentation") -> APIRouter:
    """Build the workspace router over an injected workspace provider.

    `prefix` is empty for the vault-native mount, whose addressing prefix
    already names the presentation being edited.
    """

    router = APIRouter(prefix=prefix, tags=["presentation"])

    @router.get("")
    def read(workspace: PresentationWorkspace = Depends(dependency)) -> JSONResponse:
        return _view_response(workspace.read())

    @router.get("/runtime.js")
    def read_runtime() -> Response:
        # The runtime is content-addressed and immutable: one deck revision and
        # one runtime digest fully determine what a checkpoint will do.
        return Response(
            runtime_source(),
            media_type="text/javascript; charset=utf-8",
            headers={"ETag": f'"{RUNTIME_SHA256}"', "Cache-Control": "public, max-age=31536000, immutable"},
        )

    @router.get("/deck")
    def read_deck(workspace: PresentationWorkspace = Depends(dependency)) -> JSONResponse:
        payload = build_deck_payload(workspace.store)
        return JSONResponse(payload.as_dict(), headers={"ETag": etag_for(payload.revision)})

    @router.post("/sessions")
    def open_session(body: SessionRequest, workspace: PresentationWorkspace = Depends(dependency)) -> JSONResponse:
        snapshot = workspace.sessions.open(revision=body.revision, session_id=body.session_id)
        return JSONResponse(snapshot.as_dict(), status_code=201, headers={"ETag": etag_for(snapshot.deck_revision)})

    @router.get("/sessions/{session_id}")
    def read_session(session_id: str, workspace: PresentationWorkspace = Depends(dependency)) -> JSONResponse:
        snapshot = workspace.sessions.snapshot(session_id)
        return JSONResponse(snapshot.as_dict(), headers={"ETag": etag_for(snapshot.deck_revision)})

    @router.post("/sessions/{session_id}/actions")
    def apply_action(
        session_id: str, body: ActionRequest, workspace: PresentationWorkspace = Depends(dependency)
    ) -> JSONResponse:
        if body.type not in ACTIONS:
            raise WorkspaceError("PRES_ACTION_UNKNOWN", f"action {body.type!r} is not a deck action", status=422)
        action = {"type": body.type, "checkpointId": body.checkpointId, "cue": body.cue}
        snapshot = workspace.sessions.apply(session_id, action, expected_revision=body.expected_revision)
        return JSONResponse(snapshot.as_dict(), headers={"ETag": etag_for(snapshot.deck_revision)})

    @router.post("/sessions/{session_id}/repin")
    def repin_session(
        session_id: str, body: SessionRequest, workspace: PresentationWorkspace = Depends(dependency)
    ) -> JSONResponse:
        snapshot = workspace.sessions.repin(session_id, body.revision or workspace.revision)
        return JSONResponse(snapshot.as_dict(), headers={"ETag": etag_for(snapshot.deck_revision)})

    @router.get("/exports/offline-html")
    def export_offline(workspace: PresentationWorkspace = Depends(dependency)) -> Response:
        result = export_offline_html(workspace.store)
        return Response(
            result.artifact,
            media_type="text/html; charset=utf-8",
            headers={"ETag": f'"{result.digest}"', "X-Doxagon-Revision": result.revision},
        )

    @router.get("/exports/public-html")
    def export_public(workspace: PresentationWorkspace = Depends(dependency)) -> Response:
        result = export_public_html(workspace.store)
        return Response(
            result.artifact,
            media_type="text/html; charset=utf-8",
            headers={"ETag": f'"{result.digest}"', "X-Doxagon-Revision": result.revision},
        )

    @router.get("/exports/document-html")
    def export_document(workspace: PresentationWorkspace = Depends(dependency)) -> Response:
        result = export_document_html(workspace.store)
        return Response(
            result.artifact,
            media_type="text/html; charset=utf-8",
            headers={"ETag": f'"{result.digest}"', "X-Doxagon-Revision": result.revision},
        )

    @router.get("/exports/scroll-html")
    def export_scroll(workspace: PresentationWorkspace = Depends(dependency)) -> Response:
        result = export_scroll_html(workspace.store)
        return Response(
            result.artifact,
            media_type="text/html; charset=utf-8",
            headers={"ETag": f'"{result.digest}"', "X-Doxagon-Revision": result.revision},
        )

    @router.get("/exports/source-archive")
    def export_sources(workspace: PresentationWorkspace = Depends(dependency)) -> Response:
        result = export_source_archive(workspace.store)
        return Response(
            result.artifact,
            media_type="application/zip",
            headers={"ETag": f'"{result.digest}"', "X-Doxagon-Revision": result.revision},
        )

    @router.post("/exports/raster")
    def export_images(
        request: Request, body: RasterRequest, workspace: PresentationWorkspace = Depends(dependency)
    ) -> Response:
        capturer: RasterCapturer | None = getattr(request.app.state, "raster_capturer", None)
        if capturer is None:
            raise WorkspaceError(
                "PRES_EXPORT_RUNTIME_UNAVAILABLE", "no browser runtime is configured for raster export", status=503
            )
        result = export_raster(workspace.store, capturer, groups=body.groups)
        return Response(
            result.artifact,
            media_type="application/zip",
            headers={"ETag": f'"{result.digest}"', "X-Doxagon-Revision": result.revision},
        )

    @router.get("/exports/{export_format}")
    def export_unsupported(export_format: str) -> JSONResponse:
        # Video is designed-but-deferred. Saying so is the whole point: an
        # export that silently produced a still would be a false artifact.
        code = "PRES_EXPORT_FORMAT_DEFERRED" if export_format in DEFERRED_FORMATS else "PRES_EXPORT_FORMAT_UNKNOWN"
        raise WorkspaceError(code, f"the {export_format!r} export is not available", status=501)

    @router.put("/checkpoint-order")
    def reorder(
        body: ReorderRequest,
        if_match: str | None = Header(default=None, alias="If-Match"),
        workspace: PresentationWorkspace = Depends(dependency),
    ) -> JSONResponse:
        return _view_response(workspace.reorder_checkpoints(if_match, body.checkpoint_order))

    @router.post("/checkpoints")
    def add_checkpoint(
        body: CheckpointCreateRequest,
        if_match: str | None = Header(default=None, alias="If-Match"),
        workspace: PresentationWorkspace = Depends(dependency),
    ) -> JSONResponse:
        return _view_response(workspace.add_checkpoint(if_match, body.label, after=body.after), status=201)

    @router.delete("/checkpoints/{checkpoint_id}")
    def delete_checkpoint(
        checkpoint_id: str,
        if_match: str | None = Header(default=None, alias="If-Match"),
        workspace: PresentationWorkspace = Depends(dependency),
    ) -> JSONResponse:
        return _view_response(workspace.delete_checkpoint(if_match, checkpoint_id))

    @router.patch("/checkpoints/{checkpoint_id}")
    def relabel_checkpoint(
        checkpoint_id: str,
        body: LabelRequest,
        if_match: str | None = Header(default=None, alias="If-Match"),
        workspace: PresentationWorkspace = Depends(dependency),
    ) -> JSONResponse:
        return _view_response(workspace.set_checkpoint_label(if_match, checkpoint_id, body.label))

    @router.put("/checkpoints/{checkpoint_id}/sources/{role}")
    async def put_source(
        checkpoint_id: str,
        role: str,
        request: Request,
        if_match: str | None = Header(default=None, alias="If-Match"),
        workspace: PresentationWorkspace = Depends(dependency),
    ) -> JSONResponse:
        return _view_response(await _put_source(workspace, if_match, checkpoint_id, role, request))

    @router.put("/checkpoints/{checkpoint_id}/assets")
    def set_checkpoint_assets(
        checkpoint_id: str,
        body: CheckpointAssetsRequest,
        if_match: str | None = Header(default=None, alias="If-Match"),
        workspace: PresentationWorkspace = Depends(dependency),
    ) -> JSONResponse:
        return _view_response(workspace.set_checkpoint_assets(if_match, checkpoint_id, body.assets))

    @router.put("/checkpoints/{checkpoint_id}/capabilities")
    def set_capabilities(
        checkpoint_id: str,
        body: CapabilitiesRequest,
        if_match: str | None = Header(default=None, alias="If-Match"),
        workspace: PresentationWorkspace = Depends(dependency),
    ) -> JSONResponse:
        return _view_response(workspace.set_checkpoint_capabilities(if_match, checkpoint_id, body.capabilities))

    @router.put("/checkpoints/{checkpoint_id}/transition")
    def set_transition(
        checkpoint_id: str,
        body: TransitionRequest,
        if_match: str | None = Header(default=None, alias="If-Match"),
        workspace: PresentationWorkspace = Depends(dependency),
    ) -> JSONResponse:
        return _view_response(workspace.set_checkpoint_transition(if_match, checkpoint_id, body.transition))

    @router.put("/groups/{group_id}")
    def put_group(
        group_id: str,
        body: GroupRequest,
        if_match: str | None = Header(default=None, alias="If-Match"),
        workspace: PresentationWorkspace = Depends(dependency),
    ) -> JSONResponse:
        members = body.model_dump()
        if "id" in members:
            # The path names the group this request edits. A body-owned id
            # would let a request addressed to one group mutate another, so it
            # is refused rather than silently overridden by the path value.
            raise WorkspaceError(
                "PRES_GROUP_ID_NOT_OWNED",
                "a group body cannot declare 'id'; the path names the group",
                status=422,
            )
        return _view_response(workspace.put_group(if_match, {"id": group_id, **members}))

    @router.delete("/groups/{group_id}")
    def delete_group(
        group_id: str,
        if_match: str | None = Header(default=None, alias="If-Match"),
        workspace: PresentationWorkspace = Depends(dependency),
    ) -> JSONResponse:
        return _view_response(workspace.delete_group(if_match, group_id))

    @router.put("/styles/{style_id}")
    def put_style(
        style_id: str,
        body: StyleRequest,
        if_match: str | None = Header(default=None, alias="If-Match"),
        workspace: PresentationWorkspace = Depends(dependency),
    ) -> JSONResponse:
        members = body.model_dump()
        if "id" in members:
            # The path names the style this request edits, for the same reason
            # a group's does: a body-owned id would let one address edit another.
            raise WorkspaceError(
                "PRES_STYLE_ID_NOT_OWNED", "the path names the style this request edits", status=422
            )
        return _view_response(workspace.put_style(if_match, {"id": style_id, **members}))

    @router.delete("/styles/{style_id}")
    def delete_style(
        style_id: str,
        if_match: str | None = Header(default=None, alias="If-Match"),
        workspace: PresentationWorkspace = Depends(dependency),
    ) -> JSONResponse:
        return _view_response(workspace.delete_style(if_match, style_id))

    @router.post("/assets")
    def add_asset(
        body: AssetRequest,
        if_match: str | None = Header(default=None, alias="If-Match"),
        workspace: PresentationWorkspace = Depends(dependency),
    ) -> JSONResponse:
        view = workspace.add_asset(
            if_match,
            _decode(body.data_base64),
            label=body.label,
            alt=body.alt,
            media_type=body.media_type,
            provenance=_provenance(body.provenance),
            asset_id=body.asset_id,
        )
        return _view_response(view, status=201)

    @router.patch("/assets/{asset_id}")
    def relabel_asset(
        asset_id: str,
        body: AssetLabelRequest,
        if_match: str | None = Header(default=None, alias="If-Match"),
        workspace: PresentationWorkspace = Depends(dependency),
    ) -> JSONResponse:
        return _view_response(workspace.set_asset_label(if_match, asset_id, label=body.label, alt=body.alt))

    @router.delete("/assets/{asset_id}")
    def delete_asset(
        asset_id: str,
        if_match: str | None = Header(default=None, alias="If-Match"),
        workspace: PresentationWorkspace = Depends(dependency),
    ) -> JSONResponse:
        return _view_response(workspace.delete_asset(if_match, asset_id))

    @router.get("/assets/{asset_id}/content")
    def read_asset_content(
        asset_id: str,
        revision: str | None = None,
        workspace: PresentationWorkspace = Depends(dependency),
    ) -> Response:
        target = revision or workspace.revision
        manifest = workspace.store.read_manifest(target)
        record = next((item for item in manifest.get("assets", ()) if item["id"] == asset_id), None)
        if record is None:
            raise WorkspaceError("PRES_ASSET_UNKNOWN", "asset is not in this presentation", status=404)
        return Response(
            workspace.asset_bytes(asset_id, target),
            media_type=record["media_type"],
            headers={
                "ETag": etag_for(target),
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": "sandbox; default-src 'none'; style-src 'unsafe-inline'",
            },
        )

    @router.get("/assets/{asset_id}/thumbnail")
    def read_thumbnail(asset_id: str, workspace: PresentationWorkspace = Depends(dependency)) -> Response:
        thumbnail = workspace.thumbnail(asset_id)
        if thumbnail is None:
            # A read never derives: an absent thumbnail is reported, not made.
            raise WorkspaceError("PRES_THUMBNAIL_ABSENT", "no thumbnail has been derived for this asset", status=404)
        return Response(thumbnail, media_type=THUMBNAIL_MEDIA_TYPE)

    @router.post("/checkpoints/{checkpoint_id}/agent-tasks")
    def open_agent_task(
        checkpoint_id: str, body: AgentTaskRequest, workspace: PresentationWorkspace = Depends(dependency)
    ) -> JSONResponse:
        task = workspace.open_agent_task(checkpoint_id, grants=body.grants)
        return JSONResponse(task, status_code=201, headers={"ETag": etag_for(task["base_revision"])})

    @router.get("/agent-tasks/{task_id}")
    def read_agent_task(task_id: str, workspace: PresentationWorkspace = Depends(dependency)) -> JSONResponse:
        task = workspace.read_agent_task(task_id)
        return JSONResponse(task, headers={"ETag": etag_for(task["base_revision"])})

    @router.post("/agent-tasks/{task_id}/proposal")
    def propose_agent_edit(
        request: Request,
        task_id: str,
        body: AgentProposalRequest,
        workspace: PresentationWorkspace = Depends(dependency),
    ) -> JSONResponse:
        # A proposal promotes nothing, so it carries no If-Match: the revision
        # it was written against is the task's own base revision, and the patch
        # that eventually lands re-checks exactly that tag.
        author: AgentAuthor | None = getattr(request.app.state, "agent_author", None)
        proposal = workspace.propose_agent_edit(
            task_id, role=body.role, instruction=body.instruction, author=author
        )
        return JSONResponse(proposal, status_code=201, headers={"ETag": etag_for(proposal["base_revision"])})

    @router.post("/agent-tasks/{task_id}/patch")
    def apply_agent_patch(
        task_id: str,
        body: dict[str, Any],
        if_match: str | None = Header(default=None, alias="If-Match"),
        workspace: PresentationWorkspace = Depends(dependency),
    ) -> JSONResponse:
        # The patch is closed by `AgentPatch.parse`, which also owns the scope,
        # context, and grant checks; a second partial model here would be a
        # second, weaker guard over the same body.
        outcome = workspace.apply_agent_patch(if_match, task_id, body)
        return JSONResponse(outcome.as_dict(), headers={"ETag": etag_for(outcome.revision)})

    @router.post("/generations")
    def start_generation(
        body: GenerationRequest, workspace: PresentationWorkspace = Depends(dependency)
    ) -> JSONResponse:
        record = workspace.start_generation(
            idempotency_key=body.idempotency_key,
            targets=body.targets,
            defaults=body.defaults,
            styles=body.styles,
        )
        return JSONResponse(record.as_dict(), status_code=202, headers={"ETag": etag_for(record.base_revision)})

    @router.post("/thumbnails")
    def start_thumbnails(
        body: ThumbnailRequest, workspace: PresentationWorkspace = Depends(dependency)
    ) -> JSONResponse:
        record = workspace.start_thumbnails(idempotency_key=body.idempotency_key, asset_ids=body.asset_ids)
        return JSONResponse(record.as_dict(), status_code=202)

    @router.get("/jobs")
    def list_jobs(kind: str | None = None, workspace: PresentationWorkspace = Depends(dependency)) -> JSONResponse:
        # Every job is listed, whatever it produced. A surface that could only
        # reach a job through the assets it admitted would never show a failed
        # one, which is precisely the job a retry exists for.
        if kind is not None and kind not in JOB_KINDS:
            raise WorkspaceError("PRES_JOB_KIND_UNSUPPORTED", f"job kind {kind!r} is not supported", status=422)
        return JSONResponse({"jobs": [record.as_dict() for record in workspace.jobs.list(kind=kind)]})

    @router.get("/jobs/{job_id}")
    def read_job(job_id: str, workspace: PresentationWorkspace = Depends(dependency)) -> JSONResponse:
        return JSONResponse(workspace.jobs.get(job_id).as_dict())

    @router.post("/jobs/{job_id}/retry")
    def retry_job(job_id: str, workspace: PresentationWorkspace = Depends(dependency)) -> JSONResponse:
        return JSONResponse(workspace.retry_job(job_id).as_dict(), status_code=202)

    @router.post("/jobs/{job_id}/run")
    def run_job(request: Request, job_id: str, workspace: PresentationWorkspace = Depends(dependency)) -> JSONResponse:
        record = workspace.jobs.get(job_id)
        if record.kind == THUMBNAIL_KIND:
            return JSONResponse(workspace.run_thumbnails(job_id).as_dict())
        generator: ImageGenerator | None = getattr(request.app.state, "image_generator", None)
        if generator is None:
            raise WorkspaceError("PRES_GENERATOR_UNAVAILABLE", "no image generator is configured", status=503)
        return JSONResponse(workspace.run_generation(job_id, generator).as_dict())

    return router


async def _put_source(
    workspace: PresentationWorkspace, if_match: str | None, checkpoint_id: str, role: str, request: Request
) -> WorkspaceView:
    return workspace.put_checkpoint_source(if_match, checkpoint_id, role, await request.body())


def install_error_contract(app: FastAPI, resolve: Any) -> None:
    """Answer every workspace refusal in the contract's own vocabulary.

    `resolve` maps one request to the workspace it addressed, so a revision
    conflict can carry the manifest the loser lost to. A resolver that cannot
    answer leaves the conflict without a manifest rather than substituting some
    other presentation's state, which would be worse than none.
    """

    @app.exception_handler(WorkspaceError)
    def handle(request: Request, error: WorkspaceError) -> JSONResponse:
        payload = error.as_dict()
        if error.code == "PRES_REVISION_CONFLICT" and error.revision is not None:
            # A loser needs the state it lost to, or it can only guess.
            try:
                payload["manifest"] = resolve(request).read().manifest
            except (WorkspaceError, PresentationError, OSError):
                pass
        headers = {"ETag": etag_for(error.revision)} if error.revision else {}
        return JSONResponse(payload, status_code=error.status, headers=headers)


def install_presentation_workspace(
    app: FastAPI,
    root: Path,
    *,
    generator: ImageGenerator | None = None,
    author: AgentAuthor | None = None,
    capturer: RasterCapturer | None = None,
    policy: ValidationPolicy = DEFAULT_VALIDATION_POLICY,
    prefix: str = "",
) -> FastAPI:
    """Mount the workspace router, its error contract, and its runtime state.

    This is the isolated single-workspace wiring: one root, one presentation.
    The hosted product mounts the vault-native variant below, which resolves the
    selected presentation instead of a configured global root.
    """

    app.state.workspace_root = root
    app.state.image_generator = generator
    app.state.agent_author = author
    app.state.raster_capturer = capturer
    app.state.presentation_validation_policy = policy

    def workspace() -> PresentationWorkspace:
        # `RevisionStore.open` is the one guard: an unprovisioned root answers
        # PRES_WORKSPACE_NOT_FOUND rather than being created on demand, so a
        # write can never land in a store nothing validated.
        return PresentationWorkspace.open(
            Path(app.state.workspace_root), policy=app.state.presentation_validation_policy
        )

    install_error_contract(app, lambda _request: workspace())
    app.include_router(create_presentation_router(workspace), prefix=prefix)
    return app


def install_vault_presentations(
    app: FastAPI,
    vault_root: Path,
    *,
    generator: ImageGenerator | None = None,
    author: AgentAuthor | None = None,
    capturer: RasterCapturer | None = None,
    policy: ValidationPolicy = DEFAULT_VALIDATION_POLICY,
    prefix: str = "",
) -> FastAPI:
    """Mount the product's vault-native Step workspace.

    Every route is addressed by the presentation the user selected, so the real
    vault presentation — not a configured global root — is authoritative for
    that editor session. Opening one migrates it once, deterministically, and
    every later open reads the promoted store behind its receipt.

    The validation policy is deployment state like the vault root, so migration,
    every later mutation, receipt verification, and export of a selected deck all
    run under the one aggregate budget this host was configured with.
    """

    app.state.presentation_vault_root = vault_root
    app.state.image_generator = generator
    app.state.agent_author = author
    app.state.raster_capturer = capturer
    app.state.presentation_validation_policy = policy

    def workspace(presentation_slug: str) -> PresentationWorkspace:
        return open_or_migrate(
            Path(app.state.presentation_vault_root),
            presentation_slug,
            policy=app.state.presentation_validation_policy,
        )

    def from_request(request: Request) -> PresentationWorkspace:
        return workspace(str(request.path_params["presentation_slug"]))

    install_error_contract(app, from_request)
    app.include_router(create_presentation_router(workspace, prefix=""), prefix=f"{prefix}/{{presentation_slug}}")
    return app


def create_presentation_workspace_app(
    root: Path,
    *,
    generator: ImageGenerator | None = None,
    author: AgentAuthor | None = None,
    capturer: RasterCapturer | None = None,
    policy: ValidationPolicy = DEFAULT_VALIDATION_POLICY,
) -> FastAPI:
    """An isolated application over exactly one presentation workspace root."""

    app = FastAPI(title="Doxagon Presentation Workspace", version="2.0.0")
    return install_presentation_workspace(
        app, root, generator=generator, author=author, capturer=capturer, policy=policy
    )
