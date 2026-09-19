"""Contained reads and content-addressed asset verification.

Every byte admitted into a revision is read through the proven HTML Editions
descriptor traversal: each path component is opened ``O_NOFOLLOW`` from a
retained directory descriptor, the target must be a regular file of the exact
declared size, and its stat identity must be unchanged after the read. That
closes symlink escapes and swap-under-read races at the syscall level rather
than by string-comparing resolved paths.
"""

from __future__ import annotations

from dataclasses import dataclass
import errno
from pathlib import Path

from doxagon.html_editions.compiler import _read_regular, verify_media_bytes
from doxagon.html_editions.contracts import sha256
from doxagon.html_editions.errors import HtmlEditionError

from .contracts import ASSET_ROOT, MAX_ASSET_BYTES, MAX_SOURCE_BYTES, AssetRecord
from .errors import Diagnostic, fail

# The containment layer already distinguishes escape, absence, size drift, and
# swap-under-read; this preserves that distinction in v2 diagnostic codes.
_CONTAINMENT_CODES = {
    "HTML_EDITION_SOURCE_CONTAINMENT": "PRES_SOURCE_CONTAINMENT",
    "HTML_EDITION_SOURCE_NOT_FOUND": "PRES_SOURCE_NOT_FOUND",
    "HTML_EDITION_SOURCE_SIZE_MISMATCH": "PRES_SOURCE_SIZE_MISMATCH",
    "HTML_EDITION_SOURCE_RACE": "PRES_SOURCE_RACE",
    "HTML_EDITION_BODY_LIMIT": "PRES_SOURCE_LIMIT",
    "HTML_EDITION_RESOURCE_MIME_MISMATCH": "PRES_ASSET_MIME_MISMATCH",
    "HTML_EDITION_RESOURCE_UNSAFE": "PRES_ASSET_UNSAFE",
}
_CONTAINMENT_MESSAGES = {
    "PRES_SOURCE_CONTAINMENT": "source is not contained below the presentation root",
    "PRES_SOURCE_NOT_FOUND": "source is unavailable",
    "PRES_SOURCE_SIZE_MISMATCH": "source is not a regular file of the declared size",
    "PRES_SOURCE_RACE": "source changed while it was being read",
    "PRES_SOURCE_LIMIT": "source exceeds the size limit",
}


@dataclass(frozen=True)
class SourceFile:
    """One revisioned checkpoint file with its verified bytes and digest."""

    role: str
    path: str
    data: bytes
    sha256: str

    def as_dict(self) -> dict[str, object]:
        return {"role": self.role, "path": self.path, "sha256": self.sha256, "bytes": len(self.data)}


def read_contained(
    root: Path | int,
    key: str,
    *,
    at: str = "",
    declared_size: int | None = None,
    maximum: int = MAX_SOURCE_BYTES,
) -> bytes:
    """Read one contained regular file, mapping containment failures to v2 codes."""

    try:
        return _read_regular(root, key, declared_size, "source", maximum_size=maximum)
    except HtmlEditionError as error:
        code = _CONTAINMENT_CODES.get(error.code, "PRES_SOURCE_NOT_FOUND")
        # The containment layer refuses an absent path and a symlinked path the
        # same way; the chained OSError still separates "never existed" from
        # "refused to follow", and an author needs that distinction.
        cause = error.__cause__
        if code == "PRES_SOURCE_CONTAINMENT" and isinstance(cause, OSError) and cause.errno == errno.ENOENT:
            code = "PRES_SOURCE_NOT_FOUND"
        fail(code, _CONTAINMENT_MESSAGES.get(code, "source is unavailable"), at, key)


def read_source_file(root: Path | int, role: str, key: str, at: str = "") -> SourceFile:
    data = read_contained(root, key, at=at)
    return SourceFile(role, key, data, sha256(data))


@dataclass(frozen=True)
class VerifiedAsset:
    """A declared asset whose bytes matched its declared digest and media type."""

    record: AssetRecord
    verified_sha256: str

    def as_dict(self) -> dict[str, object]:
        return {**self.record.as_dict(), "verified_sha256": self.verified_sha256}


#: Positive byte signatures for media the presentation store admits beyond the
#: editions vocabulary. A declared type must match its bytes, never merely fail
#: to contradict them: `verify_media_bytes` refuses a type it does not know.
_PRESENTATION_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    # MPEG audio is an ID3 tag or a frame sync; both are the file's first bytes.
    "audio/mpeg": (b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2", b"\xff\xfa"),
    "image/webp": (b"RIFF",),
}


def _verify_presentation_media(record: AssetRecord, data: bytes, key: str) -> bool:
    """Admit the media types only this package declares; report anything else."""

    signatures = _PRESENTATION_SIGNATURES.get(record.media_type)
    if signatures is None:
        return False
    matched = any(data.startswith(signature) for signature in signatures)
    if record.media_type == "image/webp":
        matched = matched and len(data) >= 12 and data[8:12] == b"WEBP"
    if not matched:
        fail(
            "PRES_ASSET_MIME_MISMATCH",
            f"asset bytes do not match the declared media type {record.media_type!r}",
            record.at,
            key,
        )
    return True


def read_asset(root: Path | int, record: AssetRecord) -> VerifiedAsset:
    """Admit an asset only after type, size, digest, and signature all agree."""

    key = f"{ASSET_ROOT}/{record.storage_key}"
    data = read_contained(root, key, at=record.at, declared_size=record.size, maximum=MAX_ASSET_BYTES)
    digest = sha256(data)
    if digest != record.sha256:
        fail("PRES_ASSET_HASH_MISMATCH", "asset bytes do not match the declared sha256", record.at, key)
    if _verify_presentation_media(record, data, key):
        return VerifiedAsset(record, digest)
    try:
        verify_media_bytes(record.media_type, record.storage_key, data)
    except HtmlEditionError as error:
        code = _CONTAINMENT_CODES.get(error.code, "PRES_ASSET_MIME_MISMATCH")
        message = (
            "asset bytes contain executable SVG"
            if code == "PRES_ASSET_UNSAFE"
            else f"asset bytes do not match the declared media type {record.media_type!r}"
        )
        fail(code, message, record.at, key)
    return VerifiedAsset(record, digest)


def unreadable(diagnostic: Diagnostic) -> bool:
    return diagnostic.code.startswith("PRES_SOURCE_")
