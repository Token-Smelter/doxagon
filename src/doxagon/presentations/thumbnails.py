"""Derived thumbnails: written only by a job, never by a read.

The legacy list read renders a missing thumbnail while answering a GET, which
makes reading a deck a write and makes a thumbnail's existence an accident of
who looked at it. Here a thumbnail is derived output keyed by the immutable
asset digest: a read returns it or reports its absence, and only an explicit
job produces one.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from doxagon.html_editions.contracts import sha256

from .errors import WorkspaceError
from .store import DERIVED_DIR, write_bytes

THUMBNAIL_MEDIA_TYPE = "image/jpeg"
THUMBNAIL_MAX_EDGE = 480
_THUMBNAILS = "thumbnails"


def thumbnail_path(root: Path, digest: str) -> Path:
    return root / DERIVED_DIR / _THUMBNAILS / f"{digest}.jpg"


def read_thumbnail(root: Path, digest: str) -> bytes | None:
    """Return a derived thumbnail if one exists; never render one to answer."""

    try:
        return thumbnail_path(root, digest).read_bytes()
    except FileNotFoundError:
        return None


def render_thumbnail(data: bytes) -> bytes:
    """Rasterize one bounded JPEG preview of an image asset."""

    try:
        with Image.open(BytesIO(data)) as image:
            preview = image.convert("RGB")
            preview.thumbnail((THUMBNAIL_MAX_EDGE, THUMBNAIL_MAX_EDGE))
            buffer = BytesIO()
            preview.save(buffer, format="JPEG", quality=82)
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise WorkspaceError("PRES_THUMBNAIL_UNSUPPORTED", "asset bytes are not a renderable image") from error
    return buffer.getvalue()


def write_thumbnail(root: Path, digest: str, data: bytes) -> dict[str, object]:
    """Derive and store one thumbnail; the source revision is not touched."""

    thumbnail = render_thumbnail(data)
    path = thumbnail_path(root, digest)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_bytes(path, thumbnail)
    return {
        "sha256": digest,
        "thumbnail_sha256": sha256(thumbnail),
        "media_type": THUMBNAIL_MEDIA_TYPE,
        "bytes": len(thumbnail),
    }
