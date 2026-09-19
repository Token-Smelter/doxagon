"""Read the explicitly selected single-page rendering of a thesis."""

import hashlib
import json
from pathlib import Path
import re
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from doxagon.config import THESES_DIR
from doxagon.renderings.document_inspection import barrier
from doxagon.renderings.project import DocumentProject, DocumentWorkspaceError

router = APIRouter(prefix="/theses", tags=["authored documents"])
MAX_HTML_BYTES = 32 * 1024 * 1024
MAX_NOTES_BYTES = 2 * 1024 * 1024
DOCUMENT_CSP = (
    "sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; "
    "style-src 'unsafe-inline'; img-src data: blob:; font-src data:; "
    "media-src data: blob:; frame-src 'none'; connect-src 'none'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'self'"
)


def _rendering(slug: str) -> tuple[Path, dict]:
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", slug) is None:
        raise HTTPException(404, "Thesis not found")
    project = (THESES_DIR / slug).resolve()
    root = (project / "outputs" / "document").resolve()
    if not project.is_relative_to(THESES_DIR.resolve()) or not root.is_relative_to(project):
        raise HTTPException(422, "The authored document must belong to this thesis")
    manifest = (root / "presentation.json").resolve()
    if not manifest.is_relative_to(root):
        raise HTTPException(422, "The document selection must remain inside its rendering directory")
    try:
        with manifest.open("rb") as stream:
            raw = stream.read(65537)
    except FileNotFoundError:
        raise HTTPException(404, "This thesis has no selected authored document") from None
    except OSError:
        raise HTTPException(422, "The authored document selection could not be read") from None
    try:
        if len(raw) > 65536:
            raise ValueError("selection too large")
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get("schema") != "doxagon.authored-document/1":
            raise ValueError("unknown selection schema")
        if set(data) - {"schema", "document", "notes"}:
            raise ValueError("unknown selection fields")
    except (ValueError, UnicodeError):
        raise HTTPException(422, "Invalid authored document selection") from None
    return root, data


def _source(root: Path, selection: dict, kind: Literal["html", "notes"]) -> tuple[str, bytes]:
    key = "document" if kind == "html" else "notes"
    name = selection.get(key)
    if name is None and kind == "notes":
        raise HTTPException(404, "This authored document has no companion notes")
    suffixes = {".html", ".htm"} if kind == "html" else {".json"}
    if (
        not isinstance(name, str)
        or not name
        or "/" in name
        or "\\" in name
        or "\0" in name
        or Path(name).suffix.lower() not in suffixes
    ):
        raise HTTPException(422, f"Invalid authored document {key} filename")
    path = (root / name).resolve()
    if not path.is_relative_to(root):
        raise HTTPException(422, "Authored document files must remain inside their rendering directory")
    limit = MAX_HTML_BYTES if kind == "html" else MAX_NOTES_BYTES
    try:
        with path.open("rb") as stream:
            content = stream.read(limit + 1)
    except OSError:
        raise HTTPException(422, f"The selected {key} file could not be read") from None
    if not content or len(content) > limit:
        raise HTTPException(422, f"The selected {key} file is empty or exceeds its size limit")
    return name, content


def _coherent_source(slug: str, kind: Literal['html', 'notes'], document_sha256: str | None = None) -> tuple[str, bytes, dict]:
    if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', slug) is None:
        raise HTTPException(404, 'Thesis not found')
    vault = THESES_DIR.resolve().parent
    project = DocumentProject(vault, (THESES_DIR / slug).resolve(), slug)
    try:
        before = barrier(project)
        root, selection = _rendering(slug)
        name, content = _source(root, selection, kind)
        if document_sha256 is not None:
            _, html = _source(root, selection, 'html')
            if hashlib.sha256(html).hexdigest() != document_sha256:
                raise HTTPException(409, 'The companion belongs to a different document revision; refresh context')
        root_after, selection_after = _rendering(slug)
        if before != barrier(project) or root != root_after or selection != selection_after:
            raise HTTPException(409, 'The authored selection changed while being read; refresh context')
        return name, content, selection
    except DocumentWorkspaceError as error:
        raise HTTPException(error.status, error.as_dict()) from error


@router.get("/{slug}/authored-document")
def authored_document(slug: str, response: Response) -> dict:
    filename, content, selection = _coherent_source(slug, 'html')
    base = f"/api/theses/{slug}/authored-document"
    response.headers["Cache-Control"] = "no-store"
    digest = hashlib.sha256(content).hexdigest()
    return {
        "filename": filename,
        "url": f"{base}/html",
        "renderUrl": f"{base}/render/{digest}",
        "notesUrl": f"{base}/notes" if selection.get("notes") is not None else None,
        "sha256": digest,
    }


@router.get("/{slug}/authored-document/render/{digest}")
def render_authored_document(slug: str, digest: str) -> Response:
    if re.fullmatch(r"[a-f0-9]{64}", digest) is None:
        raise HTTPException(404, "Invalid document revision")
    _, content, _ = _coherent_source(slug, 'html')
    if hashlib.sha256(content).hexdigest() != digest:
        raise HTTPException(409, "The document changed. Reload the presentation to select its current revision.")
    # Verify and send the same bounded snapshot, not a file reopened after hashing.
    # The browser can parse this response incrementally; no client ArrayBuffer gate.
    return Response(
        content,
        media_type="text/html",
        headers={
            "Content-Security-Policy": DOCUMENT_CSP,
            "Content-Disposition": "inline",
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Cross-Origin-Resource-Policy": "same-origin",
        },
    )


@router.get("/{slug}/authored-document/{kind}")
def authored_document_source(slug: str, kind: Literal["html", "notes"], document_sha256: str | None = None) -> Response:
    _, content, _ = _coherent_source(slug, kind, document_sha256)
    # Bytes are downloaded into the existing isolated player, not executed on
    # the API's origin. Notes have their own endpoint and never enter the frame.
    return Response(
        content,
        media_type="application/octet-stream",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": "attachment",
            "X-Content-Type-Options": "nosniff",
        },
    )
