"""Pinned scene contracts and server-owned navigation intent."""

import json
from pathlib import Path
import shutil

import pytest

from doxagon.presentations import PresentationWorkspace, SessionService, WorkspaceError, build_deck_payload
from doxagon.presentations.exporters import export_offline_html

FIXTURE = Path(__file__).parent / "fixtures/presentations/scene-deck"


@pytest.fixture
def workspace(tmp_path: Path) -> PresentationWorkspace:
    return PresentationWorkspace.create(tmp_path / "store", FIXTURE)


def test_scene_payload_preserves_membership_and_authored_timeout(workspace: PresentationWorkspace) -> None:
    payload = build_deck_payload(workspace.store).as_dict()
    assert (payload["checkpoints"][0]["scene"], payload["edges"][0]["timeout_ms"]) == ("motion", 1200)


@pytest.mark.parametrize("field", ["assets", "capabilities"])
def test_shared_scene_cannot_retain_authority_missing_at_a_destination(tmp_path: Path, field: str) -> None:
    source = tmp_path / "source"
    shutil.copytree(FIXTURE, source)
    manifest = json.loads((source / "presentation.json").read_text())
    manifest["checkpoints"][1][field] = []
    (source / "presentation.json").write_text(json.dumps(manifest))
    with pytest.raises(WorkspaceError) as error:
        PresentationWorkspace.create(tmp_path / "store", source)
    assert "PRES_SCENE_CLOSURE_MISMATCH" in {item.code for item in error.value.diagnostics}


@pytest.mark.parametrize("timeout", [0, -1, True, 86400001, "1000"])
def test_transition_deadline_must_be_a_positive_bounded_integer(tmp_path: Path, timeout: object) -> None:
    source = tmp_path / "source"
    shutil.copytree(FIXTURE, source)
    manifest = json.loads((source / "presentation.json").read_text())
    manifest["checkpoints"][0]["transition"]["timeout_ms"] = timeout
    (source / "presentation.json").write_text(json.dumps(manifest))
    with pytest.raises(WorkspaceError) as error:
        PresentationWorkspace.create(tmp_path / "store", source)
    assert "PRES_FIELD_INVALID" in {item.code for item in error.value.diagnostics}


def test_session_persists_server_derived_intent_and_repin_retires_it(workspace: PresentationWorkspace) -> None:
    service = SessionService(workspace.store)
    initial = service.open()
    service.apply(initial.session_id, {"type": "NEXT", "from": "forged", "navigation": {"type": "SEEK"}})
    forward = service.snapshot(initial.session_id)
    service.apply(initial.session_id, {"type": "PREVIOUS"})
    reverse = service.snapshot(initial.session_id)
    jumped = service.apply(initial.session_id, {"type": "SEEK", "checkpointId": "shape-morphed"})
    repinned = service.repin(initial.session_id, workspace.revision)
    assert [item.navigation for item in [initial, forward, reverse, jumped, repinned]] == [
        None,
        {"type": "NEXT", "from": "shape-start"},
        {"type": "PREVIOUS", "from": "shape-moved"},
        {"type": "SEEK", "from": "shape-start"},
        None,
    ]


def test_scene_browser_fixture_is_the_current_closed_export(workspace: PresentationWorkspace) -> None:
    assert FIXTURE.with_suffix(".offline.html").read_bytes() == export_offline_html(workspace.store).artifact
