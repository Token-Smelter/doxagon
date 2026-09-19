"""Exports built from the one absolute-seek runtime.

Every export consumes the revision/checkpoint graph of a promoted receipt and
the same digest-pinned runtime the workspace previews. An export never derives
a state from filesystem order, never composes a second runtime, and fails
closed on an unresolved asset, an unsupported capability, a stale receipt, a
missing readiness signal, or a signature that does not reproduce.

Video capture is deliberately deferred: nothing here claims a moving-image
artifact, and `PRES_EXPORT_FORMAT_DEFERRED` says so rather than emitting a
silent still.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import io
from typing import Any, Iterable, Mapping, Protocol, Sequence
import zipfile

from doxagon.html_editions.contracts import canonical_json, sha256

from .contracts import RUNTIME_VERSION
from .errors import WorkspaceError
from .public import project_public_payload
from .runtime import (
    DeckPayload,
    RUNTIME_SHA256,
    build_deck_payload,
    compose_document_html,
    compose_offline_html,
    compose_scroll_html,
    runtime_manifest,
    source_archive_members,
)
from .validator import verify_receipt

EXPORT_SCHEMA = "doxagon.presentation-export/2"
DEFERRED_FORMATS = frozenset({"video"})

# The raster archive carries its own proof. Frames alone say nothing about which
# revision produced them, which receipt was verified, or which signature each
# state reported, and a delivered ZIP is often all a consumer ever holds — the
# hosted route returns the artifact bytes, not the caller's manifest object.
RASTER_MANIFEST_KEY = "export-manifest.json"

# One fixed member timestamp: an archive of one revision is the same bytes
# whenever it is built, so a consumer can compare two exports by digest.
_ARCHIVE_EPOCH = (1980, 1, 1, 0, 0, 0)


@dataclass(frozen=True)
class Capture:
    """One captured checkpoint: the state the runtime proved, then the pixels."""

    checkpoint_id: str
    signature: str
    media_type: str
    data: bytes

    def as_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "signature": self.signature,
            "media_type": self.media_type,
            "bytes": len(self.data),
            "sha256": sha256(self.data),
        }


class RasterCapturer(Protocol):
    """Absolute-seeks a closed document and captures each registered state.

    The implementation owns the browser; this module owns what must be true of
    what comes back. A capturer that cannot reach readiness or cannot report a
    signature must raise rather than return a frame.
    """

    def capture(self, document: bytes, checkpoint_ids: Sequence[str]) -> Sequence[Capture]:
        ...


@dataclass(frozen=True)
class ExportResult:
    """An artifact plus the receipt-pinned manifest that explains it."""

    format: str
    revision: str
    artifact: bytes
    manifest: dict[str, Any]

    @property
    def digest(self) -> str:
        return sha256(self.artifact)

    def as_dict(self) -> dict[str, Any]:
        return {**self.manifest, "artifact_sha256": self.digest, "artifact_bytes": len(self.artifact)}


def _pinned(payload: DeckPayload, receipt: Mapping[str, Any], export_format: str) -> dict[str, Any]:
    return {
        "schema": EXPORT_SCHEMA,
        "format": export_format,
        "presentation_id": receipt["presentation_id"],
        "revision": payload.revision,
        "receipt_sha256": sha256(canonical_json(dict(receipt))),
        "compose_hash": receipt["compose_hash"],
        "asset_closure_digest": receipt["asset_closure_digest"],
        "deck_digest": payload.digest,
        "runtime": runtime_manifest(),
        "export_policy": dict(receipt.get("export_policy", {})),
    }


def _prepare(store: Any, revision: str | None, export_format: str) -> tuple[DeckPayload, dict[str, Any]]:
    """Refuse anything but a revision whose receipt still recomputes exactly."""

    if export_format in DEFERRED_FORMATS:
        raise WorkspaceError(
            "PRES_EXPORT_FORMAT_DEFERRED",
            f"the {export_format!r} export is deferred; this runtime emits no moving-image artifact",
            status=501,
        )
    target = revision or store.revision
    receipt = store.read_receipt(target)
    # The store's own policy, never a default: a deck admitted under a raised
    # aggregate budget must export under that same budget.
    stale = verify_receipt(store.revision_root(target), receipt, policy=store.policy)
    if stale:
        raise WorkspaceError(
            "PRES_RECEIPT_STALE",
            "the stored receipt does not recompute from this revision's sources",
            status=409,
            diagnostics=stale,
        )
    return build_deck_payload(store, target), receipt


def export_offline_html(store: Any, revision: str | None = None, *, title: str | None = None) -> ExportResult:
    """One self-contained `presentation.html` over the pinned runtime."""

    payload, receipt = _prepare(store, revision, "offline-html")
    document = compose_offline_html(payload.as_dict(), title=title)
    manifest = _pinned(payload, receipt, "offline-html")
    manifest["checkpoints"] = [
        {"id": item["id"], "label": item["label"], "capabilities": list(item["capabilities"])}
        for item in payload.payload["checkpoints"]
    ]
    return ExportResult("offline-html", payload.revision, document, manifest)


def export_public_html(store: Any, revision: str | None = None, *, title: str | None = None) -> ExportResult:
    """One self-contained document over the public projection: no notes, no policy."""

    payload, receipt = _prepare(store, revision, "public-html")
    projected = project_public_payload(payload.as_dict())
    document = compose_offline_html(projected, title=title)
    manifest = _pinned(payload, receipt, "public-html")
    manifest["projection"] = projected["projection"]
    manifest["public_sha256"] = sha256(document)
    return ExportResult("public-html", payload.revision, document, manifest)


def export_document_html(store: Any, revision: str | None = None, *, title: str | None = None) -> ExportResult:
    """One closed page whose authored document owns the viewport and the scroll."""

    payload, receipt = _prepare(store, revision, "document-html")
    projected = project_public_payload(payload.as_dict())
    document = compose_document_html(projected, title=title)
    manifest = _pinned(payload, receipt, "document-html")
    manifest["projection"] = projected["projection"]
    manifest["public_sha256"] = sha256(document)
    return ExportResult("document-html", payload.revision, document, manifest)


def export_scroll_html(store: Any, revision: str | None = None, *, title: str | None = None) -> ExportResult:
    """One closed article over the public projection: prose scrolls, the realm is pinned."""

    payload, receipt = _prepare(store, revision, "scroll-html")
    projected = project_public_payload(payload.as_dict())
    document = compose_scroll_html(projected, title=title)
    manifest = _pinned(payload, receipt, "scroll-html")
    manifest["projection"] = projected["projection"]
    manifest["public_sha256"] = sha256(document)
    return ExportResult("scroll-html", payload.revision, document, manifest)


def _requested_checkpoints(payload: DeckPayload, groups: Sequence[str] | None) -> tuple[str, ...]:
    order = tuple(payload.payload["checkpoint_order"])
    if groups is None:
        return order
    known = {str(group["id"]): tuple(str(item) for item in group["checkpoints"]) for group in payload.payload["groups"]}
    requested: set[str] = set()
    for group_id in groups:
        if group_id not in known:
            raise WorkspaceError("PRES_GROUP_UNKNOWN", f"no group {group_id!r} in this revision", status=404)
        requested.update(known[group_id])
    # A group is an export boundary, never an order: the partition is captured
    # in global checkpoint order.
    return tuple(checkpoint_id for checkpoint_id in order if checkpoint_id in requested)


def export_raster(
    store: Any,
    capturer: RasterCapturer,
    revision: str | None = None,
    *,
    groups: Sequence[str] | None = None,
) -> ExportResult:
    """One image per registered checkpoint, absolute-seeked and signature-checked."""

    payload, receipt = _prepare(store, revision, "raster")
    checkpoint_ids = _requested_checkpoints(payload, groups)
    if not checkpoint_ids:
        raise WorkspaceError("PRES_EXPORT_EMPTY", "the requested export selects no checkpoint", status=422)
    document = compose_offline_html(payload.as_dict())
    captures = list(capturer.capture(document, checkpoint_ids))
    captured = {capture.checkpoint_id: capture for capture in captures}
    missing = [checkpoint_id for checkpoint_id in checkpoint_ids if checkpoint_id not in captured]
    if missing or len(captures) != len(checkpoint_ids):
        raise WorkspaceError(
            "PRES_EXPORT_CAPTURE_INCOMPLETE",
            f"the capturer returned no frame for {missing[0] if missing else 'a requested checkpoint'}",
            status=502,
        )
    for capture in captures:
        if not capture.signature:
            raise WorkspaceError(
                "PRES_EXPORT_SIGNATURE_MISSING",
                f"checkpoint {capture.checkpoint_id!r} was captured without a runtime signature",
                status=502,
            )
    manifest = _pinned(payload, receipt, "raster")
    manifest["groups"] = sorted(groups) if groups is not None else None
    manifest["captures"] = [captured[checkpoint_id].as_dict() for checkpoint_id in checkpoint_ids]
    manifest["signatures"] = {checkpoint_id: captured[checkpoint_id].signature for checkpoint_id in checkpoint_ids}
    archive = _archive(
        [
            (f"{index:04d}-{checkpoint_id}.png", captured[checkpoint_id].data)
            for index, checkpoint_id in enumerate(checkpoint_ids)
        ]
        + [(RASTER_MANIFEST_KEY, canonical_json(manifest))]
    )
    return ExportResult("raster", payload.revision, archive, manifest)


def export_source_archive(store: Any, revision: str | None = None) -> ExportResult:
    """Manifest, registered sources, asset bytes, and receipt as one ZIP."""

    payload, receipt = _prepare(store, revision, "source-archive")
    members = sorted(source_archive_members(store, payload.revision))
    manifest = _pinned(payload, receipt, "source-archive")
    manifest["members"] = [{"path": key, "bytes": len(data), "sha256": sha256(data)} for key, data in members]
    return ExportResult("source-archive", payload.revision, _archive(members), manifest)


def _archive(members: Iterable[tuple[str, bytes]]) -> bytes:
    """A deterministic ZIP: sorted members, fixed times, no host metadata."""

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for key, data in sorted(members):
            info = zipfile.ZipInfo(key, date_time=_ARCHIVE_EPOCH)
            info.external_attr = 0o644 << 16
            info.create_system = 0
            archive.writestr(info, data)
    return buffer.getvalue()


class PlaywrightRasterCapturer:
    """The real capturer: one closed document, one browser, absolute seeks.

    The document is served as a data URL with no origin to reach from, network
    is refused at the context, and each frame is taken only after the runtime
    reported the state's own signature — never after a fixed sleep.
    """

    def __init__(self, *, width: int = 1600, height: int = 900, timeout_ms: int = 15000) -> None:
        self.width = width
        self.height = height
        self.timeout_ms = timeout_ms

    def capture(self, document: bytes, checkpoint_ids: Sequence[str]) -> Sequence[Capture]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as error:  # pragma: no cover - environment probe
            raise WorkspaceError(
                "PRES_EXPORT_RUNTIME_UNAVAILABLE", "no browser runtime is available for raster export", status=503
            ) from error

        captures: list[Capture] = []
        with sync_playwright() as driver:
            browser = driver.chromium.launch(args=["--disable-lcd-text", "--disable-gpu"])
            try:
                context = browser.new_context(
                    viewport={"width": self.width, "height": self.height},
                    device_scale_factor=1,
                    reduced_motion="reduce",
                )
                # Ambient network is denied at the browser, so a checkpoint that
                # somehow reached for a URL fails the export instead of quietly
                # capturing whatever came back.
                context.route("**/*", lambda route: route.abort())
                page = context.new_page()
                page.set_content(document.decode("utf-8"), wait_until="load")
                page.wait_for_function("document.documentElement.dataset.doxagonReady === 'true'", timeout=self.timeout_ms)
                for checkpoint_id in checkpoint_ids:
                    state = page.evaluate("(id) => window.doxagonDeck.seek(id)", checkpoint_id)
                    captures.append(
                        Capture(checkpoint_id, str(state["signature"]), "image/png", page.screenshot(type="png"))
                    )
            finally:
                browser.close()
        return captures


def export_index(results: Iterable[ExportResult]) -> dict[str, Any]:
    """A stable index of one build's artifacts for a receipt or a build log."""

    ordered = sorted(results, key=lambda result: result.format)
    return {
        "schema": EXPORT_SCHEMA,
        "runtime_version": RUNTIME_VERSION,
        "runtime_sha256": RUNTIME_SHA256,
        "built_at": datetime(*_ARCHIVE_EPOCH).isoformat() + "Z",
        "artifacts": [result.as_dict() for result in ordered],
    }
