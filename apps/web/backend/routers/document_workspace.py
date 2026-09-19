"""Private, snapshot-bound authored-document inspection routes."""
from collections import OrderedDict
from threading import Lock

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse, Response

from doxagon.config import THESES_DIR
from doxagon.renderings.document_inspection import MAX_TOTAL, read_item, image_bytes, verify_inspection
from doxagon.renderings.document_context import inspect_project
from doxagon.renderings.document_validation import validation_identity
from doxagon.renderings.project import DocumentWorkspaceError, resolve_document_project

router = APIRouter(prefix='/theses', tags=['document workspace'])
_parsed = OrderedDict()
_parsed_lock = Lock()


def inspection(slug: str, snapshot: str | None = None):
    root = THESES_DIR.resolve().parent
    project = resolve_document_project(slug, cwd=root, environ={'DOXAGON_ROOT': str(root)})
    key = (str(project.root), snapshot)
    with _parsed_lock:
        cached = _parsed.get(key) if snapshot else None
    if cached and cached[1] == validation_identity():
        verify_inspection(cached[0], cached[0].summary['authority_generation'])
        return cached[0]
    view = inspect_project(project, snapshot)
    if view.summary['model'] == 'authored':
        size = sum(len(raw) for raw in view.contents.values())
        if size <= MAX_TOTAL:
            with _parsed_lock:
                _parsed[(str(project.root), view.summary['snapshot'])] = (view, validation_identity(), size)
                while len(_parsed) > 2 or sum(entry[2] for entry in _parsed.values()) > MAX_TOTAL:
                    _parsed.popitem(last=False)
    return view


def refuse(error: DocumentWorkspaceError):
    raise HTTPException(error.status, error.as_dict()) from error


@router.get('/{slug}/document-workspace')
def workspace(slug: str):
    try:
        return JSONResponse(inspection(slug).summary, headers={'Cache-Control': 'no-store'})
    except DocumentWorkspaceError as error:
        refuse(error)


@router.get('/{slug}/document-workspace/items/{identity}')
def item(slug: str, identity: str, snapshot: str, offset: int = Query(0, ge=0)):
    try:
        return JSONResponse(read_item(inspection(slug, snapshot), identity, offset), headers={'Cache-Control': 'no-store'})
    except DocumentWorkspaceError as error:
        refuse(error)


@router.get('/{slug}/document-workspace/items/{identity}/image')
def image(slug: str, identity: str, snapshot: str, thumbnail: bool = False):
    try:
        raw, media = image_bytes(inspection(slug, snapshot), identity, thumbnail)
        return Response(raw, media_type=media, headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})
    except DocumentWorkspaceError as error:
        refuse(error)


@router.get('/{slug}/document-workspace/items/{identity}/notes')
def notes(slug: str, identity: str, snapshot: str):
    try:
        view = inspection(slug, snapshot)
        companion = view.summary['notes']
        if not companion or companion['id'] != identity or identity not in view.contents:
            raise DocumentWorkspaceError('DOCUMENT_ITEM_UNKNOWN', 'Companion notes are unavailable', status=404)
        return Response(view.contents[identity], media_type='application/octet-stream',
                        headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})
    except DocumentWorkspaceError as error:
        refuse(error)
