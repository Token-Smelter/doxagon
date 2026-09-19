"""Proof for the closed exports built on the one runtime.

A closed document is proved closed here by reading what it declares and what it
references; the live property — a network-denied load issuing zero ambient
requests — is proved against a real browser in
``apps/web/frontend/tests/presentation-runtime.spec.ts`` over this same
committed artifact.
"""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path
import re
from typing import Sequence
import zipfile

import pytest

from doxagon.presentations import (
    RUNTIME_SHA256,
    Capture,
    PresentationWorkspace,
    WorkspaceError,
    export_index,
    export_offline_html,
    export_raster,
    export_source_archive,
)
from doxagon.html_editions.contracts import sha256
from doxagon.presentations.exporters import EXPORT_SCHEMA, RASTER_MANIFEST_KEY, PlaywrightRasterCapturer
from doxagon.presentations.runtime import compose_offline_html

FIXTURE = Path(__file__).parent / "fixtures" / "presentations" / "synthetic-deck"


class RecordingCapturer:
    """A capturer that reports what it was asked for and what the deck says.

    It exists to prove the exporter's own contract — order, completeness,
    signature checking, and manifest pinning. It never stands in for the
    browser: the runtime's real behaviour is proved in the browser suite.
    """

    def __init__(self, *, signatures: dict[str, str] | None = None, drop: str | None = None) -> None:
        self.documents: list[bytes] = []
        self.requested: list[Sequence[str]] = []
        self.signatures = signatures or {}
        self.drop = drop

    def capture(self, document: bytes, checkpoint_ids: Sequence[str]) -> Sequence[Capture]:
        self.documents.append(document)
        self.requested.append(tuple(checkpoint_ids))
        return [
            Capture(checkpoint_id, self.signatures.get(checkpoint_id, f"sig:{checkpoint_id}"), "image/png", b"\x89PNG" + checkpoint_id.encode())
            for checkpoint_id in checkpoint_ids
            if checkpoint_id != self.drop
        ]


@pytest.fixture
def workspace(tmp_path: Path) -> PresentationWorkspace:
    return PresentationWorkspace.create(tmp_path / "store", FIXTURE)


def chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False
    try:
        with sync_playwright() as driver:
            driver.chromium.launch().close()
    except Exception:  # pragma: no cover - environment probe
        return False
    return True


needs_chromium = pytest.mark.skipif(not chromium_available(), reason="no chromium for the real raster capturer")


def _members(archive: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(archive)) as opened:
        return {info.filename: opened.read(info) for info in opened.infolist()}


# --- the real capturer ----------------------------------------------------


@needs_chromium
def test_the_real_capturer_rasters_every_checkpoint_from_the_closed_document(
    workspace: PresentationWorkspace,
) -> None:
    """The configured production capturer, not a double, drives a real browser.

    This is the path the hosted export route uses: the closed offline document
    is loaded with network denied, the runtime must report readiness, each
    checkpoint is reached by absolute seek, and the frame is taken only after
    the runtime returns that state's own signature.
    """

    order = workspace.store.read_receipt()["checkpoint_order"]

    result = export_raster(workspace.store, PlaywrightRasterCapturer(width=640, height=400))

    members = _members(result.artifact)
    frames = {key: data for key, data in members.items() if key != RASTER_MANIFEST_KEY}
    assert list(frames) == [f"{index:04d}-{checkpoint}.png" for index, checkpoint in enumerate(order)]
    assert all(data.startswith(b"\x89PNG") for data in frames.values()), "every member is a real PNG frame"
    assert json.loads(members[RASTER_MANIFEST_KEY]) == result.manifest
    # Signatures come from the runtime replaying each state, so they pin what
    # was actually rendered rather than what was requested. The exporter
    # refuses an empty one, which is what makes a frame provable at all.
    signatures = result.manifest["signatures"]
    assert sorted(signatures) == sorted(order)
    assert all(isinstance(value, str) and value for value in signatures.values())
    assert result.manifest["receipt_sha256"] and result.manifest["revision"] == workspace.revision


@needs_chromium
def test_the_real_capturer_honours_a_group_export_boundary(workspace: PresentationWorkspace) -> None:
    """A group selects which checkpoints are captured, never their order."""

    receipt = workspace.store.read_receipt()
    group = next(item for item in receipt["groups"] if item["checkpoints"])
    expected = [item for item in receipt["checkpoint_order"] if item in set(group["checkpoints"])]

    result = export_raster(
        workspace.store, PlaywrightRasterCapturer(width=640, height=400), groups=[group["id"]]
    )

    assert [key for key in _members(result.artifact) if key != RASTER_MANIFEST_KEY] == [
        f"{index:04d}-{checkpoint}.png" for index, checkpoint in enumerate(expected)
    ]
    assert result.manifest["groups"] == [group["id"]]


# --- offline html ---------------------------------------------------------


def test_offline_document_declares_no_network_source(workspace: PresentationWorkspace) -> None:
    result = export_offline_html(workspace.store)
    document = result.artifact.decode("utf-8")

    assert "default-src &#39;none&#39;" in document
    assert "connect-src &#39;none&#39;" in document
    # Not one absolute URL, so a load has nothing ambient to fetch.
    assert re.search(r"https?://", document) is None
    assert "<script src=" not in document
    assert '<link rel="stylesheet"' not in document


def test_offline_document_pins_the_runtime_by_hash(workspace: PresentationWorkspace) -> None:
    document = export_offline_html(workspace.store).artifact.decode("utf-8")
    declared = re.search(r"script-src &#39;sha256-([A-Za-z0-9+/=]+)&#39;", document)
    body = document.split('<script type="module">', 1)[1].rsplit("</script>", 1)[0]

    import hashlib

    assert declared is not None
    assert base64.b64decode(declared.group(1)) == hashlib.sha256(body.encode("utf-8")).digest()
    assert f'content="{RUNTIME_SHA256}"' in document


def test_offline_document_inlines_every_declared_asset(workspace: PresentationWorkspace) -> None:
    document = export_offline_html(workspace.store).artifact.decode("utf-8")
    asset = workspace.store.read_manifest()["assets"][0]
    data = workspace.asset_bytes(str(asset["id"]))
    assert base64.b64encode(data).decode("ascii") in document


def test_two_exports_of_one_revision_are_byte_identical(workspace: PresentationWorkspace) -> None:
    first = export_offline_html(workspace.store)
    second = export_offline_html(workspace.store)
    assert first.artifact == second.artifact
    assert first.manifest == second.manifest


def test_export_fails_closed_on_a_capability_no_closed_document_can_honour(workspace: PresentationWorkspace) -> None:
    payload = _payload(workspace)
    payload["checkpoints"][0]["capabilities"] = ["network"]

    with pytest.raises(WorkspaceError) as error:
        compose_offline_html(payload)
    assert error.value.code == "PRES_EXPORT_CAPABILITY_UNSUPPORTED"


def test_offline_export_carries_registered_module_bytes(workspace: PresentationWorkspace) -> None:
    payload = _payload(workspace)
    payload["checkpoints"][0]["modules"] = [{"path": "helper.js", "source": "window.helper = true;"}]

    document = compose_offline_html(payload).decode("utf-8")

    assert '"path":"helper.js"' in document
    assert '"source":"window.helper = true;"' in document


def test_no_author_byte_can_close_the_exported_payload_block(workspace: PresentationWorkspace) -> None:
    """Speaker notes are author text the document scanner never sees."""

    payload = _payload(workspace)
    breakout = "</script><script src=data:text/javascript,window.pwned=1></script>"
    payload["checkpoints"][0]["notes"] = breakout

    document = compose_offline_html(payload).decode("utf-8")

    head, _, tail = document.partition('<script type="application/json" id="doxagon-deck-payload">')
    block, closer, rest = tail.partition("</script>")
    assert closer == "</script>"
    # The note survives intact inside the block, and nothing it contains reached
    # the parser as markup: the element that follows is the shell's own, and the
    # injected program appears nowhere the browser would run it.
    assert json.loads(block)["checkpoints"][0]["notes"] == breakout
    assert "<script" not in block
    assert rest.lstrip().startswith('<script type="module">')
    assert "window.pwned" not in rest
    assert "window.pwned" not in head


def test_offline_export_refuses_an_unresolved_module_import(workspace: PresentationWorkspace) -> None:
    payload = _payload(workspace)
    payload["checkpoints"][0]["modules"] = [{"path": "helper.js", "source": "import './nested.js';"}]

    with pytest.raises(WorkspaceError) as error:
        compose_offline_html(payload)

    assert error.value.code == "PRES_RUNTIME_MODULE_GRAPH_UNSUPPORTED"


def test_export_refuses_a_stale_receipt(workspace: PresentationWorkspace) -> None:
    document = workspace.store.revision_root(workspace.revision) / "checkpoints" / "market-base" / "document.html"
    document.write_text(document.read_text(encoding="utf-8") + "<p>edited under the receipt</p>", encoding="utf-8")

    with pytest.raises(WorkspaceError) as error:
        export_offline_html(workspace.store)
    assert error.value.code == "PRES_RECEIPT_STALE"


def test_video_export_is_deferred_rather_than_faked(workspace: PresentationWorkspace) -> None:
    from doxagon.presentations.exporters import _prepare

    with pytest.raises(WorkspaceError) as error:
        _prepare(workspace.store, None, "video")
    assert error.value.code == "PRES_EXPORT_FORMAT_DEFERRED"
    assert error.value.status == 501


# --- raster ---------------------------------------------------------------


def test_raster_captures_every_checkpoint_in_order(workspace: PresentationWorkspace) -> None:
    capturer = RecordingCapturer()
    result = export_raster(workspace.store, capturer)

    assert capturer.requested == [("market-base", "market-forecast", "probe-denied", "leaky-timer")]
    assert list(_members(result.artifact)) == [
        "0000-market-base.png",
        "0001-market-forecast.png",
        "0002-probe-denied.png",
        "0003-leaky-timer.png",
        RASTER_MANIFEST_KEY,
    ]
    assert result.manifest["signatures"]["market-base"] == "sig:market-base"
    assert result.manifest["receipt_sha256"]
    assert result.manifest["runtime"]["runtime_sha256"] == RUNTIME_SHA256


def test_the_raster_archive_carries_its_own_proof(workspace: PresentationWorkspace) -> None:
    """The delivered ZIP, not just the caller's ExportResult, pins the capture.

    The hosted route answers with `result.artifact`, so a consumer holding the
    archive would otherwise have PNGs and no way to say which revision, which
    verified receipt, or which reported signature produced them.
    """

    result = export_raster(workspace.store, RecordingCapturer())
    members = _members(result.artifact)

    assert RASTER_MANIFEST_KEY in members
    embedded = json.loads(members[RASTER_MANIFEST_KEY])
    assert embedded == result.manifest
    assert embedded["revision"] == workspace.revision
    assert embedded["receipt_sha256"] and embedded["compose_hash"] and embedded["deck_digest"]
    assert embedded["runtime"]["runtime_sha256"] == RUNTIME_SHA256
    assert embedded["signatures"]["market-base"] == "sig:market-base"
    # Each frame is named beside the digest of the exact bytes in the archive.
    for capture in embedded["captures"]:
        member = next(key for key in members if key.endswith(f"-{capture['checkpoint_id']}.png"))
        assert sha256(members[member]) == capture["sha256"]


def test_the_raster_archive_is_byte_identical_across_two_builds(workspace: PresentationWorkspace) -> None:
    """The embedded manifest must not make a deterministic archive vary."""

    first = export_raster(workspace.store, RecordingCapturer())
    second = export_raster(workspace.store, RecordingCapturer())

    assert first.artifact == second.artifact


def test_a_group_partitions_the_export_without_owning_the_order(workspace: PresentationWorkspace) -> None:
    capturer = RecordingCapturer()
    result = export_raster(workspace.store, capturer, groups=["market"])

    # The partition is a subset of global checkpoint order, not its own order.
    assert capturer.requested == [("market-base", "market-forecast")]
    assert result.manifest["groups"] == ["market"]
    assert sorted(_members(result.artifact)) == [
        "0000-market-base.png",
        "0001-market-forecast.png",
        RASTER_MANIFEST_KEY,
    ]


def test_an_unknown_group_is_refused(workspace: PresentationWorkspace) -> None:
    with pytest.raises(WorkspaceError) as error:
        export_raster(workspace.store, RecordingCapturer(), groups=["absent"])
    assert error.value.code == "PRES_GROUP_UNKNOWN"


def test_a_missing_frame_fails_the_export(workspace: PresentationWorkspace) -> None:
    with pytest.raises(WorkspaceError) as error:
        export_raster(workspace.store, RecordingCapturer(drop="probe-denied"))
    assert error.value.code == "PRES_EXPORT_CAPTURE_INCOMPLETE"


def test_a_frame_without_a_signature_fails_the_export(workspace: PresentationWorkspace) -> None:
    with pytest.raises(WorkspaceError) as error:
        export_raster(workspace.store, RecordingCapturer(signatures={"leaky-timer": ""}))
    assert error.value.code == "PRES_EXPORT_SIGNATURE_MISSING"


def test_raster_and_offline_compose_the_same_document(workspace: PresentationWorkspace) -> None:
    capturer = RecordingCapturer()
    export_raster(workspace.store, capturer)
    assert capturer.documents == [export_offline_html(workspace.store).artifact]


# --- source archive -------------------------------------------------------


def test_source_archive_carries_sources_assets_and_receipt(workspace: PresentationWorkspace) -> None:
    result = export_source_archive(workspace.store)
    members = _members(result.artifact)

    assert "presentation.json" in members
    assert "checkpoints/market-base/program.js" in members
    assert "checkpoints/market-base/notes.md" in members
    asset = workspace.store.read_manifest()["assets"][0]
    assert f"assets/{asset['storage_key']}" in members
    assert any(name.startswith("receipts/") for name in members)


def test_source_archive_excludes_workspace_state(workspace: PresentationWorkspace) -> None:
    workspace.sessions.open()
    workspace.start_thumbnails(idempotency_key="thumbs", asset_ids=[])
    members = _members(export_source_archive(workspace.store).artifact)

    for leaked in ("HEAD", "lock", "jobs", "sessions", "staging", "derived"):
        assert not any(name.startswith(leaked) for name in members), leaked


def test_source_archive_is_deterministic(workspace: PresentationWorkspace) -> None:
    assert export_source_archive(workspace.store).artifact == export_source_archive(workspace.store).artifact


def test_export_index_pins_every_artifact(workspace: PresentationWorkspace) -> None:
    index = export_index([export_offline_html(workspace.store), export_source_archive(workspace.store)])
    assert index["schema"] == EXPORT_SCHEMA
    assert [item["format"] for item in index["artifacts"]] == ["offline-html", "source-archive"]
    assert all(item["artifact_sha256"] for item in index["artifacts"])


def _payload(workspace: PresentationWorkspace) -> dict:
    from doxagon.presentations import build_deck_payload

    return build_deck_payload(workspace.store).as_dict()
