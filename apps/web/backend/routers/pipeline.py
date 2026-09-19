"""Pipeline router - aggregate stats across all stages."""
from fastapi import APIRouter
import frontmatter
import yaml

from doxagon.config import (
    INBOX_DIR,
    PHANTASIAI_DIR,
    DOXAI_DIR,
    EVIDENCE_DIR,
    DIEGESES_DIR,
    LOGOS_FILE,
)
from doxagon.models import PipelineStats

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


def _count_by_status(directory, glob_pattern: str, status_field: str) -> dict[str, int]:
    """Count files by status in a directory."""
    counts: dict[str, int] = {}
    if directory.exists():
        for f in directory.glob(glob_pattern):
            try:
                doc = frontmatter.load(f)
                status = doc.get(status_field, "unknown")
                counts[status] = counts.get(status, 0) + 1
            except Exception:
                counts["unknown"] = counts.get("unknown", 0) + 1
    return counts


def _count_files(directory, glob_pattern: str) -> int:
    """Count files matching pattern in directory."""
    if not directory.exists():
        return 0
    return len(list(directory.glob(glob_pattern)))


def _count_inbox() -> int:
    """Count inbox items excluding .ingested markers."""
    if not INBOX_DIR.exists():
        return 0
    count = 0
    for f in INBOX_DIR.iterdir():
        if f.is_file() and not f.name.endswith(".ingested"):
            count += 1
    return count


def _count_edges() -> int:
    """Count edges in logos.yaml."""
    if not LOGOS_FILE.exists():
        return 0
    try:
        data = yaml.safe_load(LOGOS_FILE.read_text())
        return len(data.get("edges", []))
    except Exception:
        return 0


@router.get("/stats", response_model=PipelineStats)
def get_pipeline_stats():
    """Get counts for all pipeline stages."""
    return PipelineStats(
        inbox_count=_count_inbox(),
        phantasiai=_count_by_status(PHANTASIAI_DIR, "p-*.md", "status"),
        doxai_count=_count_files(DOXAI_DIR, "d-*.md"),
        evidence_count=_count_files(EVIDENCE_DIR, "e-*.md"),
        edges_count=_count_edges(),
        diegeses_count=_count_files(DIEGESES_DIR, "*.md"),
    )
