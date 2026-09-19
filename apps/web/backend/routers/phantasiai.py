"""Phantasia router - manage source impressions."""
from datetime import date
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse
import frontmatter

from doxagon.config import PHANTASIAI_DIR, DOXAI_DIR, EVIDENCE_DIR
from doxagon.graph import invalidate_cache
from doxagon.models import (
    PhantasiaListItem,
    PhantasiaDetail,
    PhantasiaCreate,
    PhantasiaUpdate,
    PhantasiaStatus,
    DoxaRef,
    EvidenceRefSummary,
)
from doxagon.utils import generate_unique_slug


def _load_doxa_belief(slug: str) -> str | None:
    """Load the belief text for a doxa."""
    path = DOXAI_DIR / f"{slug}.md"
    if path.exists():
        try:
            doc = frontmatter.load(path)
            return doc.get("belief")
        except Exception:
            pass
    return None


def _load_evidence_assertion(slug: str) -> str | None:
    """Load the assertion text for evidence."""
    path = EVIDENCE_DIR / f"{slug}.md"
    if path.exists():
        try:
            doc = frontmatter.load(path)
            return doc.get("assertion")
        except Exception:
            pass
    return None

router = APIRouter(prefix="/phantasiai", tags=["phantasiai"])


def _load_phantasia(slug: str) -> tuple[dict, str]:
    """Load phantasia file, return (metadata, content)."""
    # Handle both with and without prefix
    path = PHANTASIAI_DIR / f"{slug}.md"
    if not path.exists():
        path = PHANTASIAI_DIR / f"p-{slug}.md"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Phantasia not found: {slug}")
    doc = frontmatter.load(path)
    return dict(doc.metadata), doc.content


def _save_phantasia(slug: str, metadata: dict, content: str) -> None:
    """Save phantasia to file."""
    PHANTASIAI_DIR.mkdir(parents=True, exist_ok=True)
    path = PHANTASIAI_DIR / f"{slug}.md"
    doc = frontmatter.Post(content, **metadata)
    path.write_text(frontmatter.dumps(doc))


@router.get("", response_model=list[PhantasiaListItem])
def list_phantasiai(
    status: Optional[PhantasiaStatus] = Query(None, description="Filter by status")
):
    """List all phantasiai, optionally filtered by status."""
    results = []
    if PHANTASIAI_DIR.exists():
        for f in sorted(PHANTASIAI_DIR.glob("p-*.md")):
            try:
                doc = frontmatter.load(f)
                item_status = doc.get("status", "unprocessed")
                if status and item_status != status:
                    continue
                results.append(
                    PhantasiaListItem(
                        slug=f.stem,
                        title=doc.get("title", f.stem),
                        source=doc.get("source", ""),
                        status=item_status,
                        encountered=doc.get("encountered", date.today()),
                        doxai_count=len(doc.get("extracted_doxai", [])),
                        evidence_count=len(doc.get("extracted_evidence", [])),
                    )
                )
            except Exception:
                pass
    return results


@router.get("/{slug}", response_model=PhantasiaDetail)
def get_phantasia(slug: str):
    """Get full phantasia details."""
    metadata, content = _load_phantasia(slug)

    # Build rich doxa references with belief text
    extracted_doxai = []
    for doxa_slug in metadata.get("extracted_doxai", []):
        extracted_doxai.append(DoxaRef(
            slug=doxa_slug,
            belief=_load_doxa_belief(doxa_slug),
        ))

    # Build rich evidence references with assertion text
    extracted_evidence = []
    for ev_slug in metadata.get("extracted_evidence", []):
        extracted_evidence.append(EvidenceRefSummary(
            slug=ev_slug,
            assertion=_load_evidence_assertion(ev_slug),
        ))

    return PhantasiaDetail(
        slug=slug,
        title=metadata.get("title", slug),
        source=metadata.get("source", ""),
        status=metadata.get("status", "unprocessed"),
        encountered=metadata.get("encountered", date.today()),
        channel=metadata.get("channel"),
        shared_by=metadata.get("shared_by"),
        tags=metadata.get("tags", []),
        extracted_doxai=extracted_doxai,
        extracted_evidence=extracted_evidence,
        content=content,
    )


@router.get("/{slug}/content", response_class=PlainTextResponse)
def get_phantasia_content(slug: str):
    """Get raw markdown content."""
    _, content = _load_phantasia(slug)
    return PlainTextResponse(content, media_type="text/markdown")


@router.post("", status_code=201)
def create_phantasia(data: PhantasiaCreate):
    """Create a new phantasia."""
    title = data.title or data.source[:50]
    slug = generate_unique_slug(title, PHANTASIAI_DIR, "p-")
    full_slug = f"p-{slug}"

    metadata = {
        "source": data.source,
        "title": title,
        "encountered": date.today().isoformat(),
        "status": "unprocessed",
        "channel": data.channel,
        "shared_by": data.shared_by,
        "tags": data.tags,
        "extracted_doxai": [],
        "extracted_evidence": [],
    }
    # Remove None values
    metadata = {k: v for k, v in metadata.items() if v is not None}

    _save_phantasia(full_slug, metadata, data.content or "")
    invalidate_cache()

    return {"slug": full_slug, "status": "created"}


@router.put("/{slug}")
def update_phantasia(slug: str, data: PhantasiaUpdate):
    """Update a phantasia's metadata or content."""
    metadata, content = _load_phantasia(slug)

    if data.status is not None:
        metadata["status"] = data.status
    if data.tags is not None:
        metadata["tags"] = data.tags
    if data.content is not None:
        content = data.content

    _save_phantasia(slug, metadata, content)
    invalidate_cache()

    return {"slug": slug, "status": "updated"}


@router.delete("/{slug}")
def archive_phantasia(slug: str):
    """Archive a phantasia (soft delete)."""
    metadata, content = _load_phantasia(slug)
    metadata["status"] = "archived"
    _save_phantasia(slug, metadata, content)
    invalidate_cache()
    return {"slug": slug, "status": "archived"}


@router.post("/{slug}/extract")
def extract_from_phantasia_endpoint(slug: str, focus: Optional[str] = None):
    """Extract doxai and evidence from a phantasia using Gemini.

    This runs the full extraction pipeline:
    1. Loads the phantasia content (following source file references)
    2. Calls Gemini for extraction
    3. Validates and deduplicates against existing beliefs
    4. Writes new doxai, evidence, and edges
    5. Updates the phantasia status to 'processed'
    """
    from doxagon.extract import extract_from_phantasia

    # Ensure slug has p- prefix
    if not slug.startswith("p-"):
        slug = f"p-{slug}"

    try:
        result = extract_from_phantasia(slug, focus=focus)
        return {
            "slug": slug,
            "status": "extracted",
            "created_doxai": result.get("created_doxai", []),
            "created_evidence": result.get("created_evidence", []),
            "created_edges": len(result.get("created_edges", [])),
            "skipped_duplicates": len(result.get("skipped", [])),
            "suggested_links": len(result.get("suggested_links", [])),
        }
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Extraction failed: {str(e)}")
