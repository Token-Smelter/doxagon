"""Evidence router - manage evidence artifacts."""
from datetime import date
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse
import frontmatter

from doxagon.config import EVIDENCE_DIR, PHANTASIAI_DIR
from doxagon.graph import invalidate_cache
from doxagon.models import (
    EvidenceListItem,
    EvidenceDetail,
    EvidenceCreate,
    EvidenceUpdate,
    EvidenceProvenance,
    EvidenceType,
    EvidenceStrength,
    EvidenceStatus,
)
from doxagon.utils import generate_unique_slug

router = APIRouter(prefix="/evidence", tags=["evidence"])


def _load_evidence(slug: str) -> tuple[dict, str]:
    """Load evidence file, return (metadata, content)."""
    path = EVIDENCE_DIR / f"{slug}.md"
    if not path.exists():
        path = EVIDENCE_DIR / f"e-{slug}.md"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Evidence not found: {slug}")
    doc = frontmatter.load(path)
    return dict(doc.metadata), doc.content


def _save_evidence(slug: str, metadata: dict, content: str) -> None:
    """Save evidence to file."""
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    path = EVIDENCE_DIR / f"{slug}.md"
    doc = frontmatter.Post(content, **metadata)
    path.write_text(frontmatter.dumps(doc))


@router.get("", response_model=list[EvidenceListItem])
def list_evidence(
    type: Optional[EvidenceType] = Query(None, description="Filter by type"),
    strength: Optional[EvidenceStrength] = Query(None, description="Filter by strength"),
    status: Optional[EvidenceStatus] = Query(None, description="Filter by status"),
):
    """List all evidence, optionally filtered."""
    results = []
    if EVIDENCE_DIR.exists():
        for f in sorted(EVIDENCE_DIR.glob("e-*.md")):
            try:
                doc = frontmatter.load(f)
                item_type = doc.get("type", "empirical")
                item_strength = doc.get("strength", "moderate")
                item_status = doc.get("status", "provisional")

                if type and item_type != type:
                    continue
                if strength and item_strength != strength:
                    continue
                if status and item_status != status:
                    continue

                results.append(
                    EvidenceListItem(
                        slug=f.stem,
                        assertion=doc.get("assertion", ""),
                        source=doc.get("source", ""),
                        type=item_type,
                        strength=item_strength,
                        status=item_status,
                    )
                )
            except Exception:
                pass
    return results


@router.get("/{slug}", response_model=EvidenceDetail)
def get_evidence(slug: str):
    """Get full evidence details."""
    metadata, content = _load_evidence(slug)

    provenance = None
    if "provenance" in metadata:
        p = metadata["provenance"]
        provenance = EvidenceProvenance(
            phantasia=p.get("phantasia"),
            extracted=p.get("extracted"),
        )

    return EvidenceDetail(
        slug=slug,
        assertion=metadata.get("assertion", ""),
        source=metadata.get("source", ""),
        source_url=metadata.get("source_url"),
        type=metadata.get("type", "empirical"),
        strength=metadata.get("strength", "moderate"),
        status=metadata.get("status", "provisional"),
        provenance=provenance,
        annotations=metadata.get("annotations", []),
        gaps=metadata.get("gaps", []),
        content=content,
    )


@router.get("/{slug}/content", response_class=PlainTextResponse)
def get_evidence_content(slug: str):
    """Get raw markdown content."""
    _, content = _load_evidence(slug)
    return PlainTextResponse(content, media_type="text/markdown")


@router.post("", status_code=201)
def create_evidence(data: EvidenceCreate):
    """Create a new evidence artifact."""
    slug = generate_unique_slug(data.assertion, EVIDENCE_DIR, "e-")
    full_slug = f"e-{slug}"

    metadata = {
        "assertion": data.assertion,
        "source": data.source,
        "source_url": data.source_url,
        "type": data.type,
        "strength": data.strength,
        "status": data.status,
        "annotations": data.annotations,
        "gaps": data.gaps,
        "provenance": {
            "phantasia": data.from_phantasia,
            "extracted": date.today().isoformat(),
        },
    }
    # Clean None values
    metadata = {k: v for k, v in metadata.items() if v is not None}
    if "provenance" in metadata:
        metadata["provenance"] = {
            k: v for k, v in metadata["provenance"].items() if v is not None
        }

    _save_evidence(full_slug, metadata, data.content or "")

    # If from_phantasia specified, update that phantasia's extracted_evidence list
    if data.from_phantasia:
        p_path = PHANTASIAI_DIR / f"{data.from_phantasia}.md"
        if p_path.exists():
            try:
                p_doc = frontmatter.load(p_path)
                evidence_list = p_doc.get("extracted_evidence", [])
                if full_slug not in evidence_list:
                    evidence_list.append(full_slug)
                    p_doc["extracted_evidence"] = evidence_list
                    p_path.write_text(frontmatter.dumps(p_doc))
            except Exception:
                pass

    invalidate_cache()
    return {"slug": full_slug, "status": "created"}


@router.put("/{slug}")
def update_evidence(slug: str, data: EvidenceUpdate):
    """Update an evidence artifact."""
    metadata, content = _load_evidence(slug)

    if data.assertion is not None:
        metadata["assertion"] = data.assertion
    if data.source is not None:
        metadata["source"] = data.source
    if data.source_url is not None:
        metadata["source_url"] = data.source_url
    if data.type is not None:
        metadata["type"] = data.type
    if data.strength is not None:
        metadata["strength"] = data.strength
    if data.status is not None:
        metadata["status"] = data.status
    if data.annotations is not None:
        metadata["annotations"] = data.annotations
    if data.gaps is not None:
        metadata["gaps"] = data.gaps
    if data.content is not None:
        content = data.content

    _save_evidence(slug, metadata, content)
    invalidate_cache()
    return {"slug": slug, "status": "updated"}


@router.delete("/{slug}")
def delete_evidence(slug: str):
    """Delete an evidence artifact."""
    path = EVIDENCE_DIR / f"{slug}.md"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Evidence not found: {slug}")

    path.unlink()
    invalidate_cache()
    return {"slug": slug, "status": "deleted"}
