import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from starlette.exceptions import HTTPException
from apps.web.backend.routers import (
    authored_documents,
    document_workspace,
    graph,
    doxai,
    diegeses,
    phantasiai,
    pipeline,
    inbox,
    evidence,
    edges,
    theses,
    streaming,
    dev_tasks,
)
from doxagon.config import LIBRARY_DIR, THESES_DIR
from doxagon.presentation_backends import resolve_agent_author, resolve_image_generator
from doxagon.presentations.api import install_vault_presentations
from doxagon.presentations.contracts import TOTAL_ASSET_BYTES_ENV, resolve_validation_policy
from doxagon.presentations.exporters import PlaywrightRasterCapturer

class SPAStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code == 404:
                return await super().get_response("index.html", scope)
            raise


app = FastAPI(title="Doxagon API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Lock down in production
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(graph.router, prefix="/api")
app.include_router(doxai.router, prefix="/api")
app.include_router(diegeses.router, prefix="/api")
app.include_router(phantasiai.router, prefix="/api")
app.include_router(pipeline.router, prefix="/api")
app.include_router(inbox.router, prefix="/api")
app.include_router(evidence.router, prefix="/api")
app.include_router(edges.router, prefix="/api")
app.include_router(theses.router, prefix="/api")
app.include_router(authored_documents.router, prefix="/api")
app.include_router(document_workspace.router, prefix="/api")
app.include_router(streaming.router, prefix="/api")
app.include_router(dev_tasks.router, prefix="/api")

# The vault-native Step workspace `/presentations` edits and presents.
#
# Every route is addressed by the presentation the user selected, so the real
# vault presentation is authoritative for that editor session; there is no
# second global workspace behind the product to diverge from it. The raster
# capturer is configured here because export is a hosted capability: without it
# the export route reports PRES_EXPORT_RUNTIME_UNAVAILABLE instead of emitting
# an artifact no browser ever produced.
#
# The image generator and the AI author are named by deployment for the same
# reason and resolved the same way: each is one executable this process runs,
# and when neither is configured the routes report PRES_GENERATOR_UNAVAILABLE
# and PRES_AGENT_AUTHOR_UNAVAILABLE rather than fabricating an artifact or a
# proposal that no producer wrote.
#
# The aggregate declared-asset budget is named here for the same reason: a real
# vault deck declares every candidate ever produced for it, so the size one host
# must admit is a property of that host's corpus. An unset variable keeps the
# conservative default; anything unreadable, zero, negative, or above the
# structural ceiling refuses here, at startup, rather than validating decks
# against a limit nobody chose.
install_vault_presentations(
    app,
    THESES_DIR,
    generator=resolve_image_generator(os.environ.get("DOXAGON_IMAGE_GENERATOR")),
    author=resolve_agent_author(os.environ.get("DOXAGON_AGENT_AUTHOR")),
    capturer=PlaywrightRasterCapturer(),
    policy=resolve_validation_policy(os.environ.get(TOTAL_ASSET_BYTES_ENV)),
    prefix="/api/presentations",
)

# Serve Library Assets (Images)
#
# Guarded like the thesis and frontend mounts below; without it, importing this
# module raises when no corpus sits beside the checkout, so the app cannot even
# start to report that it has no vault.
#
# Guarding only removes the import-time crash. Mounting a whole authoritative
# tree as static files still serves every file under it to any origin, which is
# what the AssetService boundary exists to replace. Do not read this as the
# asset problem being solved.
if LIBRARY_DIR.exists():
    app.mount("/api/assets", StaticFiles(directory=LIBRARY_DIR), name="assets")

# Serve Thesis Assets (Slide Images)
if THESES_DIR.exists():
    app.mount("/api/thesis-assets", StaticFiles(directory=THESES_DIR), name="thesis-assets")

# Serve Frontend Build (if exists)
frontend_build = Path(__file__).parent.parent / "frontend" / "build"
if frontend_build.exists():
    app.mount("/", SPAStaticFiles(directory=frontend_build, html=True), name="frontend")
else:
    @app.get("/")
    def root():
        return {"message": "Backend running. Frontend not built."}
