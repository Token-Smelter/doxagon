"""A cue is part of the server-issued position, so every surface agrees on it."""

import json
from pathlib import Path
import shutil

import pytest

from doxagon.presentations import PresentationWorkspace, SessionService, Snapshot, WorkspaceError
from doxagon.presentations.session import reduce_action
from doxagon.presentations.validator import validate_presentation

FIXTURE = Path(__file__).parent / "fixtures/presentations/document-deck"
DECK = Path(__file__).parent / "fixtures/presentations/scene-deck"


@pytest.fixture
def workspace(tmp_path: Path) -> PresentationWorkspace:
    return PresentationWorkspace.create(tmp_path / "store", FIXTURE)


def walk(service: SessionService, snapshot: Snapshot, *actions: dict) -> list[tuple[str, str | None]]:
    seen = [(snapshot.checkpoint_id, snapshot.cue)]
    for action in actions:
        snapshot = service.apply(snapshot.session_id, action)
        seen.append((snapshot.checkpoint_id, snapshot.cue))
    return seen


def test_next_walks_a_document_interior_then_crosses_its_edge(workspace: PresentationWorkspace) -> None:
    service = SessionService(workspace.store)
    assert walk(service, service.open(), *[{"type": "NEXT"}] * 3) == [
        ("field-document", "field"),
        ("field-document", "clusters"),
        ("field-document", "closing"),
        ("afterword-document", "afterword"),
    ]


def test_back_re_enters_the_previous_document_where_the_reader_left(workspace: PresentationWorkspace) -> None:
    service = SessionService(workspace.store)
    opened = service.open()
    for _ in range(3):
        opened = service.apply(opened.session_id, {"type": "NEXT"})
    returned = service.apply(opened.session_id, {"type": "PREVIOUS"})
    assert (returned.checkpoint_id, returned.cue) == ("field-document", "closing")


def test_seek_names_a_cue_and_refuses_one_the_document_does_not_declare(workspace: PresentationWorkspace) -> None:
    service = SessionService(workspace.store)
    opened = service.open()
    landed = service.apply(opened.session_id, {"type": "SEEK", "checkpointId": "field-document", "cue": "closing"})
    with pytest.raises(WorkspaceError) as error:
        service.apply(opened.session_id, {"type": "SEEK", "checkpointId": "field-document", "cue": "absent"})
    assert (landed.cue, error.value.code) == ("closing", "PRES_CUE_UNKNOWN")


def test_end_enters_the_last_document_at_its_final_cue(workspace: PresentationWorkspace) -> None:
    service = SessionService(workspace.store)
    ended = service.apply(service.open().session_id, {"type": "END"})
    assert (ended.checkpoint_id, ended.cue) == ("afterword-document", "afterword")


def test_a_stage_deck_keeps_a_cue_free_cursor() -> None:
    receipt = json.loads((DECK / "presentation.json").read_text())
    order = [item["id"] for item in receipt["checkpoints"]]
    # No cues declared anywhere: the reducer answers exactly as it always did.
    assert reduce_action(order, [{"from": order[0], "to": order[1]}], order[0], {"type": "NEXT"}) == (order[1], None)


def test_a_snapshot_naming_another_cue_is_a_fork_not_a_repeat(workspace: PresentationWorkspace) -> None:
    service = SessionService(workspace.store)
    held = service.open()
    forked = Snapshot(held.session_id, held.deck_revision, held.epoch, held.sequence, held.checkpoint_id, held.issued_at, None, "clusters")
    assert not held.accepts(forked)


def test_the_cursor_publishes_the_cue_it_rests_on(workspace: PresentationWorkspace) -> None:
    service = SessionService(workspace.store)
    advanced = service.apply(service.open().session_id, {"type": "NEXT"})
    assert advanced.cursor["cue"] == "clusters"


def test_repinning_keeps_a_cue_the_new_revision_still_declares(workspace: PresentationWorkspace) -> None:
    service = SessionService(workspace.store)
    advanced = service.apply(service.open().session_id, {"type": "NEXT"})
    repinned = service.repin(advanced.session_id, workspace.revision)
    assert (repinned.cue, repinned.epoch) == ("clusters", advanced.epoch + 1)


def test_a_declared_cue_must_exist_in_the_document(tmp_path: Path) -> None:
    source = tmp_path / "source"
    shutil.copytree(FIXTURE, source)
    manifest = json.loads((source / "presentation.json").read_text())
    manifest["checkpoints"][0]["cues"].append("imaginary")
    (source / "presentation.json").write_text(json.dumps(manifest))
    assert "PRES_CUE_ABSENT" in validate_presentation(source).codes


def test_only_a_document_checkpoint_declares_cues(tmp_path: Path) -> None:
    source = tmp_path / "source"
    shutil.copytree(DECK, source)
    manifest = json.loads((source / "presentation.json").read_text())
    manifest["checkpoints"][0]["cues"] = ["somewhere"]
    (source / "presentation.json").write_text(json.dumps(manifest))
    assert "PRES_FIELD_INVALID" in validate_presentation(source).codes
