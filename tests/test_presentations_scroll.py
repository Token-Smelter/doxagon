"""The scroll article is a public export over the same pinned runtime."""

from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from doxagon.presentations import PresentationWorkspace, WorkspaceError, build_deck_payload
from doxagon.presentations.api import create_presentation_workspace_app
from doxagon.presentations.exporters import export_offline_html, export_scroll_html
from doxagon.presentations.runtime import compose_scroll_html, runtime_manifest

FIXTURE = Path(__file__).parent / "fixtures/presentations/scene-deck"


@pytest.fixture
def workspace(tmp_path: Path) -> PresentationWorkspace:
    return PresentationWorkspace.create(tmp_path / "store", FIXTURE)


def test_scroll_browser_fixture_is_the_current_export(workspace: PresentationWorkspace) -> None:
    assert (FIXTURE.parent / "scene-deck.scroll.html").read_bytes() == export_scroll_html(workspace.store).artifact


def test_scroll_export_is_a_projected_public_artifact(workspace: PresentationWorkspace) -> None:
    result = export_scroll_html(workspace.store)
    assert (result.format, result.manifest["projection"]["schema"], "public_sha256" in result.manifest) == (
        "scroll-html", "doxagon.public-projection/1", True,
    )


def test_scroll_export_carries_no_note_text_but_the_offline_export_does(workspace: PresentationWorkspace) -> None:
    notes = [item["notes"].strip() for item in build_deck_payload(workspace.store).as_dict()["checkpoints"] if item.get("notes")]
    scroll = export_scroll_html(workspace.store).artifact.decode()
    offline = export_offline_html(workspace.store).artifact.decode()
    assert (any(note in scroll for note in notes), all(note in offline for note in notes)) == (False, True)


def test_composing_a_scroll_article_from_the_private_payload_is_refused(workspace: PresentationWorkspace) -> None:
    with pytest.raises(WorkspaceError) as error:
        compose_scroll_html(build_deck_payload(workspace.store).as_dict())
    assert error.value.code == "PRES_PUBLIC_LEAK"


def test_scroll_export_scaffolds_one_cue_section_per_checkpoint(workspace: PresentationWorkspace) -> None:
    order = build_deck_payload(workspace.store).as_dict()["checkpoint_order"]
    document = export_scroll_html(workspace.store).artifact.decode()
    assert [f'data-cue="{item}"' in document for item in order] == [True] * len(order)


def test_scroll_route_answers_with_the_revision(workspace: PresentationWorkspace) -> None:
    with TestClient(create_presentation_workspace_app(workspace.store.root)) as client:
        response = client.get("/presentation/exports/scroll-html")
    assert (response.status_code, response.headers["X-Doxagon-Revision"]) == (200, workspace.revision)


def test_runtime_manifest_pins_the_scroll_shell() -> None:
    assert len(runtime_manifest()["scroll_shell_sha256"]) == 64
