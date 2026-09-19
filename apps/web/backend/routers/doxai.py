"""Doxa reads and direct authorship.

`GET /api/doxai/{slug}/label` is the read-only source a claim chip resolves its
text from: the author's `short:` frontmatter field when one exists, else the
belief for the caller to shorten.
"""

from datetime import date
from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
import frontmatter

from doxagon.graph import load_graph, invalidate_cache
from doxagon.config import DOXAI_DIR
from doxagon.models import DoxaDetail, DoxaCreate, Edge
from doxagon.utils import generate_unique_slug

router = APIRouter(prefix="/doxai", tags=["doxai"])


@router.post("", status_code=201)
def create_doxa(data: DoxaCreate):
    """Create a doxa directly (bypasses intake pipeline)."""
    slug = data.slug or generate_unique_slug(data.belief, DOXAI_DIR, "d-")
    full_slug = f"d-{slug}" if not slug.startswith("d-") else slug

    path = DOXAI_DIR / f"{full_slug}.md"
    if path.exists():
        raise HTTPException(status_code=409, detail=f"Doxa already exists: {full_slug}")

    metadata = {
        "belief": data.belief,
        "status": data.status,
        "tags": data.tags,
        "evidence": [],
        "created": date.today().isoformat(),
        "updated": date.today().isoformat(),
        "provenance": {"method": "direct"},
    }

    DOXAI_DIR.mkdir(parents=True, exist_ok=True)
    doc = frontmatter.Post(data.content or "", **metadata)
    path.write_text(frontmatter.dumps(doc))

    invalidate_cache()
    return {"slug": full_slug, "status": "created"}


@router.get("/{slug}", response_model=DoxaDetail)
def get_doxa(slug: str):
    G = load_graph()
    if slug not in G:
        raise HTTPException(status_code=404, detail="Doxa not found")

    data = G.nodes[slug]

    # Collect edges
    incoming = [
        Edge(source=u, target=v, **dict(d))
        for u, v, d in G.in_edges(slug, data=True)
    ]
    outgoing = [
        Edge(source=u, target=v, **dict(d))
        for u, v, d in G.out_edges(slug, data=True)
    ]

    # Get diegesis membership from pre-computed index
    diegesis_membership = G.graph.get('diegesis_membership', {})
    diegeses = diegesis_membership.get(slug, [])

    # Ensure title comes from data or falls back to slug
    node_data = {k: v for k, v in data.items() if k in DoxaDetail.model_fields}
    node_data.setdefault('title', slug)

    return DoxaDetail(
        slug=slug,
        **node_data,
        incoming=incoming,
        outgoing=outgoing,
        diegeses=diegeses
    )

@router.get("/{slug}/label")
def get_doxa_label(slug: str) -> dict[str, str | None]:
    """Return the label sources for one doxa chip. Read-only; writes nothing.

    `short` is the author's hand-written frontmatter label, read from the doxa
    file the graph already points at, and is null until one is written. `belief`
    is the full belief, so a caller that has no short label can shorten the
    belief itself rather than ask for a second read.
    """
    G = load_graph()
    if slug not in G:
        raise HTTPException(status_code=404, detail="Doxa not found")

    data = G.nodes[slug]
    short = None
    path = data.get("path")
    if path:
        short = frontmatter.load(path).get("short")
    return {"slug": slug, "short": str(short) if short else None, "belief": data.get("belief") or None}


@router.get("/{slug}/content", response_class=PlainTextResponse)
def get_doxa_content(slug: str):
    """Return raw markdown body for a doxa."""
    G = load_graph()
    if slug not in G:
        raise HTTPException(status_code=404, detail="Doxa not found")

    content = G.nodes[slug].get("content", "")
    return PlainTextResponse(content, media_type="text/markdown")
