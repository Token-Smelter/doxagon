"""Proof that the hosted application serves the vault-native Step workspace.

The product editor is `/presentations`: selecting a real presentation opens
*that* presentation's revisioned Step workspace, migrating it once on first
open. These tests exercise the *production* app object — the same
`apps.web.backend.main.app` uvicorn serves — with no request interception, so a
regression that unmounts the router, drops the error contract, or reintroduces
a separate global workspace fails here.

The vault is synthesised in the test's own temporary directory from public
bytes (`tests/synthetic_vault.py`). Nothing here reads a real vault.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import importlib

from doxagon.presentations import TOTAL_ASSET_BYTES_ENV, ValidationPolicy
from doxagon.presentations.migration import MIGRATION_MARKER, is_migrated
from tests.synthetic_vault import write_blocked_presentation, write_empty_presentation, write_vault

BASE = "/api/presentations/alpha"

# Exactly what `inventory_presentation` finds in the blocked synthetic tree, in
# the order `Diagnostic.sort_key` puts it. The workspace renders one row per
# entry here, so pinning the list is what makes "nothing was dropped" checkable.
BLOCKED_DIAGNOSTICS = [
    ("PRES_MIGRATION_SELECTION_ABSENT", "01-intro", None),
    ("PRES_MIGRATION_SELECTION_MISSING", "02-stray", None),
    ("PRES_MIGRATION_SLIDE_UNORDERED", "02-stray", None),
    ("PRES_MIGRATION_SLIDE_MISSING", "03-ghost", None),
    ("PRES_MIGRATION_SLIDE_UNORDERED", "04-html", None),
    ("PRES_MIGRATION_HTML_UNSAFE", "04-html/slide.html", 3),
]


@pytest.fixture()
def hosted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The production app, pointed at a synthetic legacy vault."""

    from apps.web.backend import main

    vault = write_vault(tmp_path)
    # The other two shapes a real vault holds: a tree the migrator refuses by
    # design, and a project nobody has authored a presentation for yet.
    write_blocked_presentation(vault)
    write_empty_presentation(vault)
    monkeypatch.setattr(main.app.state, "presentation_vault_root", vault, raising=False)
    with TestClient(main.app) as client:
        client.vault = vault
        yield client


def test_selecting_a_vault_presentation_migrates_and_opens_its_step_workspace(hosted: TestClient) -> None:
    """The real presentation — not a global workspace root — is authoritative."""

    presentation = hosted.vault / "alpha"
    assert is_migrated(presentation) is False, "the synthetic vault starts unmigrated"

    response = hosted.get(BASE)

    assert response.status_code == 200
    body = response.json()
    assert body["checkpoint_order"] == ["slide-01-opening", "slide-02-market"]
    # The revision is the concurrency token every mutation must send back.
    assert response.headers["ETag"] == f'"{body["revision"]}"'
    assert is_migrated(presentation) is True
    assert (presentation / MIGRATION_MARKER / "store").is_dir()


def test_opening_the_same_presentation_twice_is_one_deterministic_migration(hosted: TestClient) -> None:
    first = hosted.get(BASE).json()
    second = hosted.get(BASE).json()

    assert first["revision"] == second["revision"]


def test_every_legacy_candidate_survives_as_an_equal_first_class_asset(hosted: TestClient) -> None:
    """Unselected candidates are assets too; nothing is primary or selected."""

    body = hosted.get(BASE).json()

    assert len(body["assets"]) == 4, "two slides × two candidates, selected or not"
    for asset in body["assets"]:
        assert "is_primary" not in asset and "selected" not in asset
        assert asset["provenance"]["source_ref"]
    assert "layout" not in body


def test_the_documented_variable_names_the_budget_the_production_app_installs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The variable the docs name is the one this deployment actually reads."""

    from apps.web.backend import main

    monkeypatch.setenv(TOTAL_ASSET_BYTES_ENV, "2147483648")
    try:
        reloaded = importlib.reload(main)

        assert reloaded.app.state.presentation_validation_policy == ValidationPolicy(2 * 1024 * 1024 * 1024)
    finally:
        monkeypatch.undo()
        importlib.reload(main)


def test_the_hosted_app_admits_a_deck_under_the_aggregate_budget_it_is_deployed_with(
    hosted: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The aggregate budget is deployment state, exactly like the vault root.

    A real vault presentation declares every candidate ever produced for it, so
    the hosted app must be able to name a budget large enough for that corpus
    without weakening any per-asset check.
    """

    from apps.web.backend import main

    monkeypatch.setattr(
        main.app.state, "presentation_validation_policy", ValidationPolicy(2 * 1024 * 1024 * 1024), raising=False
    )

    response = hosted.get(BASE)

    assert response.status_code == 200
    assert len(response.json()["assets"]) == 4


def test_the_hosted_app_refuses_a_deck_over_its_aggregate_budget(
    hosted: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The refusal an operator sees names the limit, and publishes no store."""

    from apps.web.backend import main

    monkeypatch.setattr(main.app.state, "presentation_validation_policy", ValidationPolicy(1), raising=False)

    response = hosted.get(BASE)

    assert response.status_code == 422
    assert response.json()["code"] == "PRES_VALIDATION_FAILED"
    assert {item["code"] for item in response.json()["diagnostics"]} == {"PRES_ASSET_LIMIT"}
    assert is_migrated(hosted.vault / "alpha") is False


def test_a_refused_migration_publishes_every_located_diagnostic(hosted: TestClient) -> None:
    """The refusal carries the whole list, located, not a count of it.

    This is the payload the `/presentations` workspace renders row by row, so a
    producer change that collapsed, reordered, or unlocated these findings would
    silently change what an operator is told to fix.
    """

    response = hosted.get("/api/presentations/blocked")

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "PRES_MIGRATION_BLOCKED"
    assert [(item["code"], item["path"], item["line"]) for item in body["diagnostics"]] == BLOCKED_DIAGNOSTICS
    assert is_migrated(hosted.vault / "blocked") is False, "a refused tree publishes no store"


def test_a_project_with_no_authored_presentation_is_empty_rather_than_ambiguous(hosted: TestClient) -> None:
    """Nothing is wrong with this tree; there is simply no presentation in it."""

    response = hosted.get("/api/presentations/unwritten")

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "PRES_MIGRATION_EMPTY"
    assert body["diagnostics"] == []


def test_an_unknown_presentation_is_refused_rather_than_created(hosted: TestClient) -> None:
    response = hosted.get("/api/presentations/nonexistent")

    assert response.status_code == 404
    assert response.json()["code"] == "PRES_PRESENTATION_UNKNOWN"


def test_a_dotted_slug_is_refused_rather_than_normalised(hosted: TestClient) -> None:
    """A slug is one plain directory name; anything else is refused by name."""

    response = hosted.get("/api/presentations/.doxagon-presentation-v2")

    assert response.status_code == 422
    assert response.json()["code"] == "PRES_PRESENTATION_SLUG_INVALID"


def test_a_symlinked_slug_cannot_reach_a_tree_outside_the_vault(
    hosted: TestClient, tmp_path: Path
) -> None:
    """Containment is checked after resolution, not by spelling alone."""

    outside = tmp_path / "outside"
    outside.mkdir()
    (hosted.vault / "escape").symlink_to(outside, target_is_directory=True)

    response = hosted.get("/api/presentations/escape")

    assert response.status_code == 422
    assert response.json()["code"] == "PRES_PRESENTATION_SLUG_INVALID"


def test_the_production_app_serves_the_pinned_runtime(hosted: TestClient) -> None:
    response = hosted.get(f"{BASE}/runtime.js")

    assert response.status_code == 200
    assert "immutable" in response.headers["Cache-Control"]
    assert "createDeckRuntime" in response.text


def test_the_production_app_issues_and_advances_a_session(hosted: TestClient) -> None:
    """The server owns the cursor end to end on the hosted app."""

    first_checkpoint = hosted.get(BASE).json()["checkpoint_order"][0]
    opened = hosted.post(f"{BASE}/sessions", json={})
    assert opened.status_code == 201
    snapshot = opened.json()
    assert snapshot["checkpoint_id"] == first_checkpoint
    assert snapshot["sequence"] == 0

    seek = hosted.post(
        f"{BASE}/sessions/{snapshot['session_id']}/actions",
        json={"type": "SEEK", "checkpointId": first_checkpoint},
    )

    assert seek.status_code == 200
    assert seek.json()["sequence"] == 1


def test_a_second_client_reads_the_same_server_issued_cursor(hosted: TestClient) -> None:
    """Presenter and audience share one session; neither mints a position."""

    order = hosted.get(BASE).json()["checkpoint_order"]
    session = hosted.post(f"{BASE}/sessions", json={}).json()["session_id"]
    hosted.post(f"{BASE}/sessions/{session}/actions", json={"type": "SEEK", "checkpointId": order[1]})

    joined = hosted.get(f"{BASE}/sessions/{session}")

    assert joined.status_code == 200
    assert joined.json()["checkpoint_id"] == order[1]


def test_a_stale_revision_is_refused_by_the_production_error_contract(hosted: TestClient) -> None:
    """The WorkspaceError handler is mounted, so a conflict is typed, not a 500."""

    first_checkpoint = hosted.get(BASE).json()["checkpoint_order"][0]
    response = hosted.patch(
        f"{BASE}/checkpoints/{first_checkpoint}",
        headers={"If-Match": '"sha256:' + "0" * 64 + '"'},
        json={"label": "Renamed"},
    )

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "PRES_REVISION_CONFLICT"
    # The loser is handed the state it lost to, resolved for this presentation.
    assert body["manifest"]["checkpoint_order"] == ["slide-01-opening", "slide-02-market"]


def test_the_deferred_video_export_says_so_on_the_production_app(hosted: TestClient) -> None:
    response = hosted.get(f"{BASE}/exports/video")

    assert response.status_code == 501
    assert response.json()["code"] == "PRES_EXPORT_FORMAT_DEFERRED"


def test_the_hosted_offline_export_is_built_from_the_selected_presentation(hosted: TestClient) -> None:
    revision = hosted.get(BASE).json()["revision"]

    response = hosted.get(f"{BASE}/exports/offline-html")

    assert response.status_code == 200
    assert response.headers["X-Doxagon-Revision"] == revision


def test_the_hosted_raster_export_delivers_its_proof_with_the_frames(
    hosted: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The response body is the whole artifact a consumer gets.

    The route answers with `ExportResult.artifact`, so anything held only in the
    caller's `ExportResult.manifest` never reaches whoever holds the ZIP. The
    archive therefore carries the receipt, revision, runtime, and per-capture
    signature pins itself.
    """

    import io
    import json
    import zipfile

    from apps.web.backend import main
    from doxagon.presentations import Capture
    from doxagon.presentations.exporters import RASTER_MANIFEST_KEY

    class StubCapturer:
        def capture(self, document: bytes, checkpoint_ids):
            return [
                Capture(checkpoint_id, f"sig:{checkpoint_id}", "image/png", b"\x89PNG" + checkpoint_id.encode())
                for checkpoint_id in checkpoint_ids
            ]

    monkeypatch.setattr(main.app.state, "raster_capturer", StubCapturer(), raising=False)
    first_checkpoint = hosted.get(BASE).json()["checkpoint_order"][0]

    response = hosted.post(f"{BASE}/exports/raster", json={})

    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = archive.namelist()
        manifest = json.loads(archive.read(RASTER_MANIFEST_KEY))

    assert RASTER_MANIFEST_KEY in names
    assert manifest["revision"] == response.headers["X-Doxagon-Revision"]
    assert manifest["receipt_sha256"] and manifest["compose_hash"] and manifest["deck_digest"]
    assert manifest["runtime"]["runtime_sha256"]
    assert manifest["signatures"][first_checkpoint] == f"sig:{first_checkpoint}"
