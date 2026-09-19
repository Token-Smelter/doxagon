"""Proof that the public export is an explicit projection, never the private payload.

The offline export embeds the whole deck payload, speaker notes included, and
is meant for the presenter. The public export embeds only the projection, and
the projection refuses to ship if any private path-like text survives it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from doxagon.presentations import RUNTIME_SHA256, PresentationWorkspace, WorkspaceError, build_deck_payload
from doxagon.presentations.api import create_presentation_workspace_app
from doxagon.presentations.exporters import export_offline_html, export_public_html
from doxagon.presentations.public import project_public_payload

FIXTURE = Path(__file__).parent / "fixtures" / "presentations" / "scene-deck"

EXCLUDED = [
    "notes",
    "cue_notes",
    "registration",
    "export_policy",
    "capability_grants",
    "claims:unassessed",
    "claims:contested",
]


@pytest.fixture
def workspace(tmp_path: Path) -> PresentationWorkspace:
    return PresentationWorkspace.create(tmp_path / "store", FIXTURE)


def _notes(workspace: PresentationWorkspace) -> list[str]:
    payload = build_deck_payload(workspace.store).as_dict()
    notes = [(checkpoint.get("notes") or "").strip() for checkpoint in payload["checkpoints"]]
    notes = [note for note in notes if note]
    if not notes:
        raise AssertionError("the fixture must carry speaker notes for this proof to mean anything")
    return notes


def test_public_export_contains_no_note_text(workspace: PresentationWorkspace) -> None:
    notes = _notes(workspace)

    document = export_public_html(workspace.store).artifact.decode("utf-8")

    assert not any(note in document for note in notes)


def test_private_offline_export_still_contains_note_text(workspace: PresentationWorkspace) -> None:
    notes = _notes(workspace)

    document = export_offline_html(workspace.store).artifact.decode("utf-8")

    assert all(note in document for note in notes)


def test_public_artifact_embeds_the_pinned_runtime(workspace: PresentationWorkspace) -> None:
    document = export_public_html(workspace.store).artifact.decode("utf-8")

    assert RUNTIME_SHA256 in document


def test_public_manifest_names_every_excluded_member(workspace: PresentationWorkspace) -> None:
    manifest = export_public_html(workspace.store).manifest

    assert manifest["projection"]["excluded"] == EXCLUDED


def test_projection_refuses_private_path_text(workspace: PresentationWorkspace) -> None:
    payload = build_deck_payload(workspace.store).as_dict()
    payload["checkpoints"][0]["document"] += "<!-- /home/someone/secret -->"

    with pytest.raises(WorkspaceError) as caught:
        project_public_payload(payload)

    assert caught.value.code == "PRES_PUBLIC_LEAK"


def test_projected_asset_carries_only_public_keys(workspace: PresentationWorkspace) -> None:
    payload = build_deck_payload(workspace.store).as_dict()
    projected = project_public_payload(payload)
    first = next(asset for checkpoint in projected["checkpoints"] for asset in checkpoint["assets"])

    assert set(first) == {"id", "label", "alt", "media_type", "base64"}


def test_public_and_offline_exports_report_the_same_revision(workspace: PresentationWorkspace) -> None:
    public = export_public_html(workspace.store)
    offline = export_offline_html(workspace.store)

    assert public.revision == offline.revision


def test_public_html_route_answers_with_the_revision(workspace: PresentationWorkspace) -> None:
    app = create_presentation_workspace_app(workspace.store.root)
    with TestClient(app) as client:
        response = client.get("/presentation/exports/public-html")

    assert (response.status_code, response.headers["X-Doxagon-Revision"]) == (200, workspace.revision)
