"""A document change lands whole as one revision through the store's only write path."""

import hashlib
import json
import os
from pathlib import Path
import threading

from click.testing import CliRunner
import pytest

from doxagon.presentations import PresentationWorkspace, WorkspaceError
from doxagon.presentations.changes import (
    AUTHORING_DIR,
    DocumentChange,
    apply_document_change,
    plan_document_change,
)
from scripts.dox import cli

FIXTURE = Path(__file__).parent / "fixtures/presentations/scene-deck"


@pytest.fixture
def workspace(tmp_path: Path) -> PresentationWorkspace:
    return PresentationWorkspace.create(tmp_path / "store", FIXTURE)


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def relabelled_manifest(workspace: PresentationWorkspace, label: str) -> dict:
    manifest = workspace.store.read_manifest()
    manifest["checkpoints"][0]["label"] = label
    return manifest


def change(workspace: PresentationWorkspace, **overrides) -> DocumentChange:
    fields = {
        "expected_revision": workspace.revision,
        "writes": {
            "scene/document.html": b"<h1>Rewritten together.</h1>\n<svg viewBox=\"0 0 460 150\"><rect width=\"35\" height=\"35\"/><image width=\"20\" height=\"20\"/><circle cx=\"430\" cy=\"20\" r=\"4\"/><circle class=\"sweep\" cx=\"30\" cy=\"130\" r=\"6\"/></svg>\n",
            "scene/shape-start.md": b"Notes rewritten in the same change.\n",
        },
        "deletes": (),
        "manifest": relabelled_manifest(workspace, "Opening, relabelled"),
        "summary": "Rewrite the opening markup, its notes, and its label together.",
    }
    fields.update(overrides)
    return DocumentChange(**fields)


def test_a_multi_file_change_lands_as_one_new_revision(workspace: PresentationWorkspace) -> None:
    before = workspace.revision
    outcome = apply_document_change(workspace.store, change(workspace))
    assert (outcome.before_revision, outcome.after_revision == workspace.store.revision, outcome.after_revision != before) == (before, True, True)


def test_the_previous_revision_is_untouched_by_a_change(workspace: PresentationWorkspace) -> None:
    previous = workspace.store.revision_root(workspace.revision)
    digest = tree_digest(previous)
    apply_document_change(workspace.store, change(workspace))
    assert tree_digest(previous) == digest


def test_a_stale_expected_revision_is_refused_and_head_stays(workspace: PresentationWorkspace) -> None:
    head = workspace.revision
    with pytest.raises(WorkspaceError) as error:
        apply_document_change(workspace.store, change(workspace, expected_revision="sha256:" + "0" * 64))
    assert (error.value.code, workspace.store.revision) == ("PRES_REVISION_CONFLICT", head)


def test_a_change_that_fails_validation_is_refused_whole(workspace: PresentationWorkspace) -> None:
    head = workspace.revision
    broken = change(workspace, writes={"scene/shape-start.js": b"/* doxagon-checkpoint-registration\n{}\n*/\neval('x');\n"})
    with pytest.raises(WorkspaceError) as error:
        apply_document_change(workspace.store, broken)
    assert (error.value.code, workspace.store.revision, (workspace.store.root / AUTHORING_DIR).exists()) == (
        "PRES_VALIDATION_FAILED", head, False,
    )


@pytest.mark.parametrize("key", ["presentation.json", "receipts/forged.validation.json"])
def test_manifest_and_receipts_cannot_be_written_as_files(workspace: PresentationWorkspace, key: str) -> None:
    with pytest.raises(WorkspaceError) as error:
        change(workspace, writes={key: b"{}"})
    assert error.value.code == "PRES_AUTHORING_KEY_RESERVED"


def test_a_traversing_key_is_refused_before_any_lock(workspace: PresentationWorkspace) -> None:
    with pytest.raises(WorkspaceError) as error:
        change(workspace, writes={"../escape.js": b""})
    assert error.value.code == "PRES_SOURCE_CONTAINMENT"


def test_deleting_a_missing_key_is_refused(workspace: PresentationWorkspace) -> None:
    with pytest.raises(WorkspaceError) as error:
        apply_document_change(workspace.store, change(workspace, deletes=("scene/absent.md",)))
    assert error.value.code == "PRES_AUTHORING_KEY_ABSENT"


def test_plan_names_the_revision_apply_then_produces(workspace: PresentationWorkspace) -> None:
    planned = plan_document_change(workspace.store, change(workspace))
    applied = apply_document_change(workspace.store, change(workspace))
    assert (planned["ok"], planned["revision_if_promoted"]) == (True, applied.after_revision)


def test_plan_leaves_head_and_staging_alone(workspace: PresentationWorkspace) -> None:
    head = workspace.revision
    plan_document_change(workspace.store, change(workspace))
    assert (workspace.store.revision, list((workspace.store.root / "staging").iterdir())) == (head, [])


def test_the_authoring_record_describes_the_change(workspace: PresentationWorkspace) -> None:
    outcome = apply_document_change(workspace.store, change(workspace))
    record = json.loads((workspace.store.root / AUTHORING_DIR / f"{outcome.after_revision.split(':')[1]}.json").read_text())
    assert (record["before_revision"], record["after_revision"], sorted(record["written"]), record["summary"]) == (
        outcome.before_revision, outcome.after_revision, ["scene/document.html", "scene/shape-start.md"], outcome.summary,
    )


def test_concurrent_changes_against_one_revision_land_exactly_once(workspace: PresentationWorkspace) -> None:
    barrier = threading.Barrier(2)
    results: list[str] = []

    def attempt(label: str) -> None:
        request = change(workspace, manifest=relabelled_manifest(workspace, label))
        barrier.wait()
        try:
            apply_document_change(workspace.store, request)
            results.append("landed")
        except WorkspaceError as error:
            results.append(error.code)

    threads = [threading.Thread(target=attempt, args=(label,)) for label in ("First", "Second")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(results) == ["PRES_REVISION_CONFLICT", "landed"]


def test_cli_refuses_to_guess_a_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DOXAGON_ROOT", raising=False)
    change_file = tmp_path / "change.json"
    change_file.write_text(json.dumps({"expected_revision": "sha256:" + "0" * 64, "writes": {}, "summary": ""}))
    result = CliRunner().invoke(cli, ["rendering", "plan", "--presentation", "scene", "--change", str(change_file)])
    assert (result.exit_code, "DOXAGON_ROOT_UNSET" in result.output) == (2, True)


def test_cli_plans_and_applies_against_a_real_vault_presentation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.synthetic_vault import write_legacy_presentation

    vault = tmp_path / "vault"
    (vault / "library").mkdir(parents=True)
    write_legacy_presentation(vault, "alpha")
    monkeypatch.setenv("DOXAGON_ROOT", str(vault))
    from doxagon.presentations.vault import open_or_migrate

    store = open_or_migrate(vault, "alpha").store
    manifest = store.read_manifest()
    manifest["checkpoints"][0]["label"] = "Opening via CLI"
    change_file = tmp_path / "change.json"
    change_file.write_text(json.dumps({"expected_revision": store.revision, "manifest": manifest, "summary": "CLI relabel"}))
    runner = CliRunner()
    planned = runner.invoke(cli, ["rendering", "plan", "--presentation", "alpha", "--change", str(change_file)])
    applied = runner.invoke(cli, ["rendering", "apply", "--presentation", "alpha", "--change", str(change_file)])
    assert (planned.exit_code, applied.exit_code, json.loads(planned.output)["revision_if_promoted"]) == (
        0, 0, json.loads(applied.output)["after_revision"],
    )
    assert os.environ["DOXAGON_ROOT"] == str(vault)
