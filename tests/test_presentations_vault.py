"""Proof for vault-native workspace resolution and the Step lifecycle.

Every vault here is synthesised in the test's own temporary directory from
public bytes (`tests/synthetic_vault.py`). Nothing reads a real vault, a thesis
directory, or any configured content root.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from doxagon.presentations.errors import WorkspaceError
from doxagon.presentations.migration import MIGRATION_MARKER, is_migrated
from doxagon.presentations.vault import (
    discard_migration,
    open_or_migrate,
    resolve_presentation_dir,
    workspace_root,
)
from doxagon.presentations.workspace import PresentationWorkspace, step_id_for
from tests.synthetic_vault import write_vault

FIXTURE = Path(__file__).parent / "fixtures" / "presentations" / "synthetic-deck"


@pytest.fixture()
def vault(tmp_path: Path) -> Path:
    return write_vault(tmp_path)


# --- resolution refuses rather than normalises ----------------------------


@pytest.mark.parametrize("slug", ["", ".", "..", "../escape", "a/b", "a\\b", ".hidden"])
def test_a_slug_that_is_not_one_plain_directory_name_is_refused(vault: Path, slug: str) -> None:
    with pytest.raises(WorkspaceError) as error:
        resolve_presentation_dir(vault, slug)

    assert error.value.code == "PRES_PRESENTATION_SLUG_INVALID"


def test_a_symlink_out_of_the_vault_is_refused_after_resolution(vault: Path, tmp_path: Path) -> None:
    """Containment is checked on the resolved path, not on the spelling."""

    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (vault / "escape").symlink_to(outside, target_is_directory=True)

    with pytest.raises(WorkspaceError) as error:
        resolve_presentation_dir(vault, "escape")

    assert error.value.code == "PRES_PRESENTATION_SLUG_INVALID"


def test_an_absent_presentation_is_reported_not_created(vault: Path) -> None:
    with pytest.raises(WorkspaceError) as error:
        resolve_presentation_dir(vault, "missing")

    assert error.value.code == "PRES_PRESENTATION_UNKNOWN"
    assert not (vault / "missing").exists()


# --- opening migrates once, deterministically -----------------------------


def test_opening_migrates_the_legacy_tree_once(vault: Path) -> None:
    assert is_migrated(vault / "alpha") is False

    first = open_or_migrate(vault, "alpha")

    assert is_migrated(vault / "alpha") is True
    assert workspace_root(vault / "alpha") == vault / "alpha" / MIGRATION_MARKER / "store"
    second = open_or_migrate(vault, "alpha")
    assert second.revision == first.revision, "a second open reads the promoted store, it does not re-promote"


def test_the_migrated_workspace_holds_every_candidate_and_no_display_choice(vault: Path) -> None:
    view = open_or_migrate(vault, "alpha").read().as_dict()

    assert view["checkpoint_order"] == ["slide-01-opening", "slide-02-market"]
    assert len(view["assets"]) == 4, "selected and unselected candidates are equal assets"
    for asset in view["assets"]:
        assert "is_primary" not in asset and "selected" not in asset
    assert "layout" not in view


def test_a_blocked_legacy_tree_refuses_promotion_rather_than_guessing(vault: Path) -> None:
    presentation = vault / "alpha" / "outputs" / "presentation"
    (presentation / "config.yaml").unlink()
    # With neither a manifest nor a complete numbered sequence, the vault
    # opener must still refuse to invent the order.
    (presentation / "slides" / "01-opening").rename(presentation / "slides" / "opening")

    with pytest.raises(WorkspaceError) as error:
        open_or_migrate(vault, "alpha")

    assert error.value.code == "PRES_MIGRATION_BLOCKED"
    assert is_migrated(vault / "alpha") is False



# --- rollback returns authority to the legacy tree -------------------------


def test_rolling_back_restores_the_legacy_tree_and_lets_it_migrate_again(vault: Path) -> None:
    """The whole of what promotion added is the marker, so removing it is the rollback."""

    before = open_or_migrate(vault, "alpha")
    composed = before.store.read_receipt()["compose_hash"]
    imported = [(item["id"], item["sha256"]) for item in before.read().assets]

    assert discard_migration(vault, "alpha") is True
    assert is_migrated(vault / "alpha") is False
    assert not (vault / "alpha" / MIGRATION_MARKER).exists()
    assert (vault / "alpha" / "outputs" / "presentation" / "config.yaml").is_file()

    again = open_or_migrate(vault, "alpha")
    # Not the revision digest: provenance records when an import happened, so
    # re-importing the same bytes an hour later is a different manifest by
    # exactly that much and no more. What the legacy bytes decide -- the deck
    # they compose to and the assets it closes over -- is unchanged.
    assert again.store.read_receipt()["compose_hash"] == composed
    assert [(item["id"], item["sha256"]) for item in again.read().assets] == imported


def test_rolling_back_a_deck_that_was_never_promoted_reports_no_change(vault: Path) -> None:
    assert discard_migration(vault, "alpha") is False


def test_rolling_back_refuses_to_discard_authorship_promotion_never_saw(vault: Path) -> None:
    workspace = open_or_migrate(vault, "alpha")
    workspace.add_checkpoint(workspace.etag, "Interlude")

    with pytest.raises(WorkspaceError) as error:
        discard_migration(vault, "alpha")

    assert error.value.code == "PRES_MIGRATION_ROLLBACK_DIRTY"
    assert is_migrated(vault / "alpha") is True


def test_rolling_back_a_marker_that_cannot_say_where_it_stands_is_refused(vault: Path) -> None:
    """A missing receipt is not proof that the store below it holds nothing."""

    open_or_migrate(vault, "alpha")
    (vault / "alpha" / MIGRATION_MARKER / "migration-receipt.json").unlink()

    with pytest.raises(WorkspaceError) as error:
        discard_migration(vault, "alpha")

    assert error.value.code == "PRES_MIGRATION_ROLLBACK_DIRTY"
    assert (vault / "alpha" / MIGRATION_MARKER).is_dir()


def test_rolling_back_discards_later_authorship_when_the_caller_says_so(vault: Path) -> None:
    workspace = open_or_migrate(vault, "alpha")
    workspace.add_checkpoint(workspace.etag, "Interlude")

    assert discard_migration(vault, "alpha", discard_edits=True) is True
    assert "interlude" not in open_or_migrate(vault, "alpha").read().as_dict()["checkpoint_order"]


# --- the Step lifecycle ----------------------------------------------------


def test_step_ids_are_unique_without_reusing_one(tmp_path: Path) -> None:
    assert step_id_for("Interlude", []) == "interlude"
    assert step_id_for("Interlude", ["interlude"]) == "interlude-2"


def test_adding_a_step_registers_it_and_places_it_after_the_named_one(vault: Path) -> None:
    workspace = open_or_migrate(vault, "alpha")

    view = workspace.add_checkpoint(workspace.etag, "Interlude", after="slide-01-opening")

    assert view.as_dict()["checkpoint_order"] == ["slide-01-opening", "interlude", "slide-02-market"]
    added = next(item for item in view.checkpoints if item["id"] == "interlude")
    assert added["label"] == "Interlude"
    # A new step arrives holding no authority it was not asked for.
    assert added["assets"] == [] and added["capabilities"] == []


def test_adding_a_step_without_a_position_appends_it(vault: Path) -> None:
    workspace = open_or_migrate(vault, "alpha")

    view = workspace.add_checkpoint(workspace.etag, "Closing")

    assert view.as_dict()["checkpoint_order"][-1] == "closing"


def test_deleting_a_step_removes_it_from_order_and_every_section(vault: Path) -> None:
    workspace = open_or_migrate(vault, "alpha")
    view = workspace.add_checkpoint(workspace.etag, "Interlude")
    view = workspace.put_group(
        view.etag,
        {"id": "act-one", "kind": "section", "label": "Act one", "checkpoints": ["interlude"]},
    )

    view = workspace.delete_checkpoint(view.etag, "interlude")

    body = view.as_dict()
    assert "interlude" not in body["checkpoint_order"]
    section = next(group for group in body["groups"] if group["id"] == "act-one")
    assert section["checkpoints"] == []
    assert not any("interlude" in group["checkpoints"] for group in body["groups"])


def test_deleting_a_step_a_transition_still_names_is_refused(tmp_path: Path) -> None:
    """A refusal beats either a broken registration or a silent source rewrite.

    The committed synthetic deck registers a real reversible edge between two
    of its checkpoints, so this exercises the guard against a transition a
    producer actually wrote rather than one invented here.
    """

    workspace = PresentationWorkspace.create(tmp_path / "store", FIXTURE)
    manifest = workspace.store.read_manifest(workspace.revision)
    target = next(
        str(record["transition"]["forward_to"])
        for record in manifest["checkpoints"]
        if "forward_to" in (record.get("transition") or {})
    )
    before = workspace.revision

    with pytest.raises(WorkspaceError) as error:
        workspace.delete_checkpoint(workspace.etag, target)

    assert error.value.code == "PRES_CHECKPOINT_REFERENCED"
    assert workspace.revision == before, "a refused deletion promotes nothing"


def test_the_last_step_cannot_be_deleted(vault: Path) -> None:
    workspace = open_or_migrate(vault, "alpha")
    view = workspace.delete_checkpoint(workspace.etag, "slide-02-market")

    with pytest.raises(WorkspaceError) as error:
        workspace.delete_checkpoint(view.etag, "slide-01-opening")

    assert error.value.code == "PRES_CHECKPOINT_LAST"


def test_a_stale_tag_refuses_a_step_mutation_and_changes_nothing(vault: Path) -> None:
    workspace = open_or_migrate(vault, "alpha")
    before = workspace.revision

    with pytest.raises(WorkspaceError) as error:
        workspace.add_checkpoint(f'"sha256:{"0" * 64}"', "Interlude")

    assert error.value.code == "PRES_REVISION_CONFLICT"
    assert workspace.revision == before
