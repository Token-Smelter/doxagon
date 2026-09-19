"""Capability-gated FastAPI surface for the fence-owned HTML Edition service."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from doxagon.workspace import WorkspaceOpenRequest

from .service import HtmlEditionCoordinator, HtmlEditionServiceError


class BuildRequest(BaseModel):
    project: str
    document: str


class RetryRequest(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=200)


class PreviewRequest(BaseModel):
    lifetime_seconds: int = Field(default=300, ge=1, le=3600)


def _error(error: HtmlEditionServiceError) -> HTTPException:
    status = 404 if error.code.endswith("NOT_FOUND") or error.code.endswith("NOT_AVAILABLE") else 403 if error.code.endswith("DENIED") else 409 if error.code.endswith(("DIVERGED", "CONFLICT")) else 400
    return HTTPException(status, {"code": error.code})


def create_html_editions_app(
    request: WorkspaceOpenRequest,
    *,
    allowed_origins: tuple[str, ...] = (),
    recovery_interval_seconds: float = 1.0,
) -> FastAPI:
    """Create an isolated same-origin-by-default application.

    Callers must provide the explicit workspace request.  This factory does not
    import legacy configuration, inspect cwd, or mount a filesystem tree.
    """

    if recovery_interval_seconds <= 0:
        raise ValueError("recovery interval must be positive")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        coordinator = HtmlEditionCoordinator.open(request)
        app.state.html_editions = coordinator
        stopped = asyncio.Event()
        recovery_task: asyncio.Task[None] | None = None

        async def recover_expired_leases() -> None:
            while True:
                try:
                    await asyncio.wait_for(stopped.wait(), timeout=recovery_interval_seconds)
                    return
                except TimeoutError:
                    try:
                        coordinator.recover()
                    except HtmlEditionServiceError:
                        # Individual jobs record deterministic errors; a timer
                        # must remain available for the next expired lease.
                        pass

        try:
            if coordinator.can_build:
                coordinator.recover()
                recovery_task = asyncio.create_task(recover_expired_leases())
            yield
        finally:
            stopped.set()
            if recovery_task is not None:
                await recovery_task
            coordinator.close()

    app = FastAPI(title="Doxagon HTML Editions", version="1", lifespan=lifespan)
    if allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(allowed_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["Content-Type", "Idempotency-Key"],
        )

    def coordinator() -> HtmlEditionCoordinator:
        return app.state.html_editions

    @app.get("/api/html-editions/documents/{project}/{document}")
    def document(project: str, document: str) -> dict[str, object]:
        try:
            return coordinator().read_document(project, document)
        except HtmlEditionServiceError as error:
            raise _error(error) from error

    @app.post("/api/html-editions/documents/{project}/{document}/validate")
    def validate(project: str, document: str) -> dict[str, object]:
        try:
            return coordinator().validate(project, document)
        except HtmlEditionServiceError as error:
            raise _error(error) from error

    @app.get("/api/html-editions/documents/{project}/{document}/resources/{resource_id}")
    def resource(project: str, document: str, resource_id: str) -> Response:
        try:
            media_type, payload = coordinator().resource(project, document, resource_id)
            return Response(payload, media_type=media_type)
        except HtmlEditionServiceError as error:
            raise _error(error) from error

    @app.post("/api/html-editions/builds")
    def build(payload: BuildRequest, idempotency_key: str = Header(alias="Idempotency-Key")) -> dict[str, object]:
        try:
            job = coordinator().enqueue(payload.project, payload.document, idempotency_key)
            coordinator().recover()
            return coordinator().status(job.job_id).public()
        except HtmlEditionServiceError as error:
            raise _error(error) from error

    @app.get("/api/html-editions/builds/{job_id}")
    def status(job_id: str) -> dict[str, object]:
        try:
            return coordinator().status(job_id).public()
        except HtmlEditionServiceError as error:
            raise _error(error) from error

    @app.post("/api/html-editions/builds/{job_id}/cancel")
    def cancel(job_id: str) -> dict[str, object]:
        try:
            return coordinator().cancel(job_id).public()
        except HtmlEditionServiceError as error:
            raise _error(error) from error

    @app.post("/api/html-editions/builds/{job_id}/retry")
    def retry(job_id: str, payload: RetryRequest) -> dict[str, object]:
        try:
            job = coordinator().retry(job_id, payload.idempotency_key)
            coordinator().recover()
            return coordinator().status(job.job_id).public()
        except HtmlEditionServiceError as error:
            raise _error(error) from error

    @app.get("/api/html-editions/builds/{job_id}/download")
    def download(job_id: str) -> Response:
        try:
            return Response(
                coordinator().download(job_id), media_type="text/html; charset=utf-8",
                headers={"Content-Disposition": 'attachment; filename="edition.html"'},
            )
        except HtmlEditionServiceError as error:
            raise _error(error) from error

    @app.post("/api/html-editions/builds/{job_id}/preview")
    def preview(job_id: str, payload: PreviewRequest) -> dict[str, str]:
        try:
            return {"token": coordinator().create_preview(job_id, lifetime_seconds=payload.lifetime_seconds)}
        except HtmlEditionServiceError as error:
            raise _error(error) from error

    @app.get("/api/html-editions/previews/{token}")
    def preview_get(token: str) -> Response:
        try:
            return Response(coordinator().preview(token), media_type="text/html; charset=utf-8")
        except HtmlEditionServiceError as error:
            raise _error(error) from error

    @app.delete("/api/html-editions/previews/{token}", status_code=204)
    def preview_revoke(token: str) -> Response:
        try:
            coordinator().revoke_preview(token)
            return Response(status_code=204)
        except HtmlEditionServiceError as error:
            raise _error(error) from error

    return app
