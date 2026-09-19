"""Edges router - manage annotated relationships in logos.yaml."""

from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from doxagon.config import DOXAI_DIR, LOGOS_FILE, SCHEMA_FILE
from doxagon.graph import invalidate_cache
from doxagon.models import EdgeCreate, EdgeDetail, EdgeListItem, EdgeType, EdgeUpdate
from doxagon.storage import read_logos, write_logos
from doxagon.validation import GraphIntegrityError, normalize_edge

router = APIRouter(prefix="/edges", tags=["edges"])


def _load_logos() -> dict:
    data = read_logos(LOGOS_FILE)
    normalized = []
    for raw_edge in data.get("edges", []):
        edge = normalize_edge(raw_edge)
        if edge is None:
            raise HTTPException(status_code=500, detail="Malformed edge data")
        edge.setdefault("strength", "moderate")
        normalized.append(edge)
    return {**data, "edges": normalized}


def _save_logos(data: dict) -> None:
    try:
        write_logos(data, path=LOGOS_FILE, doxai_dir=DOXAI_DIR, schema_file=SCHEMA_FILE)
    except GraphIntegrityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _find_edge_index(edges: list[dict], source: str, target: str, edge_type: str | None = None) -> int | None:
    matches = [
        index
        for index, edge in enumerate(edges)
        if edge.get("source") == source
        and edge.get("target") == target
        and (edge_type is None or edge.get("type") == edge_type)
    ]
    if not matches:
        return None
    if len(matches) > 1:
        raise HTTPException(status_code=409, detail="Parallel edges require an explicit type query parameter")
    return matches[0]


@router.get("", response_model=list[EdgeListItem])
def list_edges(
    source: Optional[str] = Query(None, description="Filter by source node"),
    target: Optional[str] = Query(None, description="Filter by target node"),
    type: Optional[EdgeType] = Query(None, description="Filter by edge type"),
    disputed: Optional[bool] = Query(None, description="Filter by disputed status"),
):
    """List all edges, optionally filtered."""
    results = []
    for edge in _load_logos().get("edges", []):
        if source and edge.get("source") != source:
            continue
        if target and edge.get("target") != target:
            continue
        if type and edge.get("type") != type:
            continue
        if disputed is not None and edge.get("disputed", False) != disputed:
            continue
        results.append(EdgeListItem.model_validate(edge))
    return results


@router.get("/{source}/{target}", response_model=EdgeDetail)
def get_edge(
    source: str,
    target: str,
    edge_type: EdgeType | None = Query(None, alias="type"),
):
    """Get full edge details by typed identity."""
    data = _load_logos()
    idx = _find_edge_index(data.get("edges", []), source, target, edge_type)
    if idx is None:
        raise HTTPException(status_code=404, detail=f"Edge not found: {source} -> {target}")
    return EdgeDetail.model_validate(data["edges"][idx])


@router.post("", status_code=201)
def create_edge(data: EdgeCreate):
    """Create one typed edge while allowing other types on the same pair."""
    logos = _load_logos()
    edges = logos.get("edges", [])
    if _find_edge_index(edges, data.source, data.target, data.type) is not None:
        raise HTTPException(status_code=409, detail=f"Edge already exists: {data.source} -> {data.target} ({data.type})")

    edge = data.model_dump(exclude={"from_phantasia"}, exclude_none=True, mode="json")
    if data.provenance is None:
        edge["provenance"] = {
            "method": "extraction" if data.from_phantasia else "manual",
            **({"phantasia": data.from_phantasia} if data.from_phantasia else {}),
        }
    edge.setdefault("created", date.today().isoformat())
    edges.append(edge)
    _save_logos({**logos, "edges": edges})
    invalidate_cache()
    return {"source": data.source, "target": data.target, "type": data.type, "status": "created"}


@router.put("/{source}/{target}")
def update_edge(
    source: str,
    target: str,
    data: EdgeUpdate,
    edge_type: EdgeType | None = Query(None, alias="type"),
):
    """Update one edge selected by source, target, and type."""
    logos = _load_logos()
    edges = logos.get("edges", [])
    idx = _find_edge_index(edges, source, target, edge_type)
    if idx is None:
        raise HTTPException(status_code=404, detail=f"Edge not found: {source} -> {target}")

    updates = data.model_dump(exclude_unset=True, exclude_none=True, mode="json")
    edges[idx] = {**edges[idx], **updates}
    _save_logos({**logos, "edges": edges})
    invalidate_cache()
    return {
        "source": source,
        "target": target,
        "type": edges[idx]["type"],
        "status": "updated",
    }


@router.delete("/{source}/{target}")
def delete_edge(
    source: str,
    target: str,
    edge_type: EdgeType | None = Query(None, alias="type"),
):
    """Delete one edge selected by source, target, and type."""
    logos = _load_logos()
    edges = logos.get("edges", [])
    idx = _find_edge_index(edges, source, target, edge_type)
    if idx is None:
        raise HTTPException(status_code=404, detail=f"Edge not found: {source} -> {target}")
    removed = edges.pop(idx)
    _save_logos({**logos, "edges": edges})
    invalidate_cache()
    return {"source": source, "target": target, "type": removed["type"], "status": "deleted"}
