"""Inbox router - manage raw input files."""
from datetime import datetime
from urllib.parse import unquote
from fastapi import APIRouter, HTTPException, UploadFile, File
from pathlib import Path

from doxagon.config import INBOX_DIR
from doxagon.models import InboxItem

router = APIRouter(prefix="/inbox", tags=["inbox"])


def _get_unique_filename(filename: str) -> str:
    """Get a unique filename, adding counter suffix if needed."""
    path = INBOX_DIR / filename
    if not path.exists():
        return filename

    stem = path.stem
    suffix = path.suffix
    counter = 2
    while (INBOX_DIR / f"{stem}-{counter}{suffix}").exists():
        counter += 1
    return f"{stem}-{counter}{suffix}"


@router.get("", response_model=list[InboxItem])
def list_inbox():
    """List all items in the inbox."""
    results = []
    if INBOX_DIR.exists():
        for f in sorted(INBOX_DIR.iterdir()):
            if f.is_file() and not f.name.endswith(".ingested"):
                stat = f.stat()
                ingested_marker = INBOX_DIR / f"{f.name}.ingested"
                results.append(
                    InboxItem(
                        filename=f.name,
                        size_bytes=stat.st_size,
                        modified=datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        ingested=ingested_marker.exists(),
                    )
                )
    return results


@router.post("", status_code=201)
async def upload_to_inbox(file: UploadFile = File(...)):
    """Upload a file to the inbox."""
    INBOX_DIR.mkdir(parents=True, exist_ok=True)

    filename = _get_unique_filename(file.filename or "untitled")
    path = INBOX_DIR / filename

    content = await file.read()
    path.write_bytes(content)

    return {"filename": filename, "size_bytes": len(content), "status": "uploaded"}


@router.delete("/{filename}")
def delete_from_inbox(filename: str):
    """Delete a file from the inbox."""
    decoded = unquote(filename)
    path = INBOX_DIR / decoded

    if not path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {decoded}")

    path.unlink()

    ingested_marker = INBOX_DIR / f"{decoded}.ingested"
    if ingested_marker.exists():
        ingested_marker.unlink()

    return {"filename": decoded, "status": "deleted"}
