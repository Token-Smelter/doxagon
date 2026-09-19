"""Proof for the one configurable validation limit: the aggregate asset budget.

A real vault deck declares every image candidate ever produced for it, so the
aggregate declared-asset total is the only validation limit whose right value
depends on the corpus rather than on the schema. These tests prove the budget is
explicit, bounded on both sides, refused when unreadable, and carried by the
same object through migration, later mutation, receipt verification, and export
— and that raising it relaxes nothing else.

Every fixture here is synthetic and public. The large-deck cases declare their
sizes and stub the contained byte read, so both sides of the boundary are forced
without allocating a single large file; the small-deck cases read real bytes
through the unchanged containment path.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
from typing import Any

import pytest

from doxagon.presentations import (
    DEFAULT_TOTAL_ASSET_BYTES,
    DEFAULT_VALIDATION_POLICY,
    MAX_ASSET_BYTES,
    MAX_ASSETS,
    MAX_TOTAL_ASSET_BYTES_CEILING,
    TOTAL_ASSET_BYTES_ENV,
    PresentationWorkspace,
    ValidationPolicy,
    VerifiedAsset,
    WorkspaceError,
    export_offline_html,
    resolve_validation_policy,
    validate_presentation,
    verify_receipt,
)
from doxagon.presentations.vault import open_or_migrate
from tests.synthetic_vault import write_vault

FIXTURE = Path(__file__).parent / "fixtures" / "presentations" / "synthetic-deck"

# What the sampled real presentation looks like in aggregate: many candidates,
# each far below the per-asset maximum, summing above the conservative default.
_LARGE_DECK_ASSETS = 156
_LARGE_DECK_ASSET_BYTES = 6 * 1024 * 1024


def _manifest(deck: Path) -> dict[str, Any]:
    return json.loads((deck / "presentation.json").read_text(encoding="utf-8"))


def _write_manifest(deck: Path, manifest: dict[str, Any]) -> None:
    (deck / "presentation.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def _deck(tmp_path: Path) -> Path:
    deck = tmp_path / "presentation"
    shutil.copytree(FIXTURE, deck)
    return deck


def _declare_many_assets(deck: Path, count: int, size: int) -> int:
    """Declare `count` unreferenced asset variants and return their total bytes.

    The record shape is copied from the committed fixture rather than invented,
    so the parser, the accumulator, and the pointer under test see exactly the
    shape a migrated deck writes.
    """

    manifest = _manifest(deck)
    template = dict(manifest["assets"][0])
    manifest.pop("revision", None)
    for index in range(count):
        digest = f"{index:064x}"
        manifest["assets"].append(
            {
                **template,
                "id": f"asset-variant-{index:04d}",
                "bytes": size,
                "sha256": digest,
                "storage_key": f"sha256/{digest}",
            }
        )
    _write_manifest(deck, manifest)
    return sum(int(record["bytes"]) for record in manifest["assets"])


@pytest.fixture()
def contained_reads_stubbed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Admit each declared asset's bytes without allocating them.

    Only the byte read is stood in for. The aggregate accumulator, the manifest
    parser, the diagnostic, and the pointer under test are the real ones.
    """

    monkeypatch.setattr(
        "doxagon.presentations.validator.read_asset",
        lambda _root, record: VerifiedAsset(record, record.sha256),
    )


# --- the configured budget ------------------------------------------------


def test_an_unnamed_budget_keeps_the_conservative_default() -> None:
    assert resolve_validation_policy(None) == ValidationPolicy(DEFAULT_TOTAL_ASSET_BYTES)


def test_the_default_budget_is_the_limit_this_validator_shipped_with() -> None:
    assert DEFAULT_VALIDATION_POLICY.total_asset_bytes == 512 * 1024 * 1024


def test_a_named_budget_is_read_as_whole_bytes() -> None:
    assert resolve_validation_policy("2147483648").total_asset_bytes == 2 * 1024 * 1024 * 1024


def test_the_ceiling_is_every_asset_this_schema_can_admit_at_its_maximum_size() -> None:
    assert MAX_TOTAL_ASSET_BYTES_CEILING == MAX_ASSETS * MAX_ASSET_BYTES


def test_the_ceiling_itself_is_a_configurable_budget() -> None:
    assert resolve_validation_policy(str(MAX_TOTAL_ASSET_BYTES_CEILING)).total_asset_bytes == MAX_TOTAL_ASSET_BYTES_CEILING


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        "0",
        "-1",
        "512MiB",
        "1e9",
        "1_073_741_824",
        "0x40000000",
        "1.5",
        "none",
        str(MAX_TOTAL_ASSET_BYTES_CEILING + 1),
    ],
)
def test_an_unreadable_or_out_of_range_budget_refuses_instead_of_falling_back(value: str) -> None:
    with pytest.raises(WorkspaceError) as raised:
        resolve_validation_policy(value)

    assert raised.value.code == "PRES_ASSET_POLICY_INVALID"


def test_a_refused_budget_is_reported_as_the_deployment_fault_it_is() -> None:
    with pytest.raises(WorkspaceError) as raised:
        resolve_validation_policy("0")

    assert raised.value.status == 500


def test_the_refusal_names_the_variable_an_operator_must_correct() -> None:
    with pytest.raises(WorkspaceError) as raised:
        resolve_validation_policy("512MiB")

    assert TOTAL_ASSET_BYTES_ENV in raised.value.message


@pytest.mark.parametrize("value", [0, -1, True, 1.5, "1024", MAX_TOTAL_ASSET_BYTES_CEILING + 1])
def test_a_policy_constructed_in_process_is_bounded_exactly_as_a_configured_one(value: Any) -> None:
    with pytest.raises(WorkspaceError) as raised:
        ValidationPolicy(value)

    assert raised.value.code == "PRES_ASSET_POLICY_INVALID"


# --- what the budget decides ----------------------------------------------


def test_a_deck_within_its_budget_validates(tmp_path: Path) -> None:
    deck = _deck(tmp_path)
    declared = sum(int(record["bytes"]) for record in _manifest(deck)["assets"])

    assert validate_presentation(deck, policy=ValidationPolicy(declared)).ok


def test_one_byte_below_the_declared_total_refuses_the_deck(tmp_path: Path) -> None:
    deck = _deck(tmp_path)
    declared = sum(int(record["bytes"]) for record in _manifest(deck)["assets"])

    result = validate_presentation(deck, policy=ValidationPolicy(declared - 1))

    assert result.codes == ("PRES_ASSET_LIMIT",)


def test_the_refusal_locates_the_asset_record_that_crossed_the_budget(tmp_path: Path) -> None:
    deck = _deck(tmp_path)

    result = validate_presentation(deck, policy=ValidationPolicy(1))

    assert result.diagnostics[0].pointer == "/assets/0"


def test_the_refusal_names_the_budget_that_refused_it(tmp_path: Path) -> None:
    deck = _deck(tmp_path)

    result = validate_presentation(deck, policy=ValidationPolicy(1))

    assert "1-byte" in result.diagnostics[0].message


def test_a_refused_deck_mints_no_receipt(tmp_path: Path) -> None:
    deck = _deck(tmp_path)

    assert validate_presentation(deck, policy=ValidationPolicy(1)).receipt is None


# --- the real vault shape, forced at both boundaries ----------------------


def test_the_default_budget_refuses_a_vault_sized_candidate_set(
    tmp_path: Path, contained_reads_stubbed: None
) -> None:
    """The landed failure: every candidate is admissible, the aggregate is not."""

    deck = _deck(tmp_path)
    total = _declare_many_assets(deck, _LARGE_DECK_ASSETS, _LARGE_DECK_ASSET_BYTES)
    assert total > DEFAULT_TOTAL_ASSET_BYTES, "the fixture must exceed the default to prove anything"

    result = validate_presentation(deck, policy=DEFAULT_VALIDATION_POLICY)

    assert set(result.codes) == {"PRES_ASSET_LIMIT"}


def test_a_budget_at_the_declared_total_admits_the_same_candidate_set(
    tmp_path: Path, contained_reads_stubbed: None
) -> None:
    deck = _deck(tmp_path)
    total = _declare_many_assets(deck, _LARGE_DECK_ASSETS, _LARGE_DECK_ASSET_BYTES)

    assert validate_presentation(deck, policy=ValidationPolicy(total)).ok


def test_every_declared_candidate_survives_a_budget_that_admits_them(
    tmp_path: Path, contained_reads_stubbed: None
) -> None:
    """Raising the budget admits the whole candidate set; it drops nothing."""

    deck = _deck(tmp_path)
    _declare_many_assets(deck, _LARGE_DECK_ASSETS, _LARGE_DECK_ASSET_BYTES)

    receipt = validate_presentation(deck, policy=ValidationPolicy(2 * 1024 * 1024 * 1024)).receipt

    assert len(receipt.assets) == _LARGE_DECK_ASSETS + 1


# --- what a raised budget must not relax ----------------------------------


def test_a_raised_budget_still_refuses_an_asset_above_the_per_asset_maximum(tmp_path: Path) -> None:
    deck = _deck(tmp_path)
    manifest = _manifest(deck)
    manifest["assets"][0]["bytes"] = MAX_ASSET_BYTES + 1
    _write_manifest(deck, manifest)

    result = validate_presentation(deck, policy=ValidationPolicy(MAX_TOTAL_ASSET_BYTES_CEILING))

    assert "PRES_FIELD_INVALID" in result.codes


def test_a_raised_budget_still_refuses_bytes_that_do_not_match_their_digest(tmp_path: Path) -> None:
    deck = _deck(tmp_path)
    record = _manifest(deck)["assets"][0]
    stored = deck / "assets" / record["storage_key"]
    stored.write_bytes(b"\x89PNG" + b"\x00" * (int(record["bytes"]) - 4))

    result = validate_presentation(deck, policy=ValidationPolicy(MAX_TOTAL_ASSET_BYTES_CEILING))

    assert "PRES_ASSET_HASH_MISMATCH" in result.codes


def test_a_raised_budget_still_refuses_an_asset_that_is_a_symlink(tmp_path: Path) -> None:
    deck = _deck(tmp_path)
    record = _manifest(deck)["assets"][0]
    stored = deck / "assets" / record["storage_key"]
    target = tmp_path / "outside.png"
    target.write_bytes(stored.read_bytes())
    stored.unlink()
    stored.symlink_to(target)

    result = validate_presentation(deck, policy=ValidationPolicy(MAX_TOTAL_ASSET_BYTES_CEILING))

    assert "PRES_SOURCE_CONTAINMENT" in result.codes


# --- one budget for the whole lifecycle of one deck -----------------------


def test_a_migration_under_a_starved_budget_refuses_rather_than_publishing(tmp_path: Path) -> None:
    vault = write_vault(tmp_path)

    with pytest.raises(WorkspaceError) as raised:
        open_or_migrate(vault, "alpha", policy=ValidationPolicy(1))

    assert {item.code for item in raised.value.diagnostics} == {"PRES_ASSET_LIMIT"}


def test_a_refused_migration_publishes_no_store(tmp_path: Path) -> None:
    vault = write_vault(tmp_path)

    with pytest.raises(WorkspaceError):
        open_or_migrate(vault, "alpha", policy=ValidationPolicy(1))

    assert not (vault / "alpha" / ".doxagon-presentation-v2" / "store").exists()


def test_the_budget_a_deck_migrated_under_is_the_budget_its_next_edit_uses(tmp_path: Path) -> None:
    """A deck that migrates must not fail on the edit immediately after it."""

    vault = write_vault(tmp_path)
    policy = ValidationPolicy(DEFAULT_TOTAL_ASSET_BYTES)
    migrated = open_or_migrate(vault, "alpha", policy=policy).revision

    reopened = open_or_migrate(vault, "alpha", policy=policy)
    view = reopened.set_checkpoint_label(reopened.etag, reopened.read().checkpoints[0]["id"], "Renamed")

    assert view.revision != migrated


def test_a_later_open_under_a_starved_budget_refuses_the_edit_it_cannot_validate(tmp_path: Path) -> None:
    """The budget is consulted on every mutation, not only at migration."""

    vault = write_vault(tmp_path)
    checkpoint_id = open_or_migrate(vault, "alpha").read().checkpoints[0]["id"]
    starved = open_or_migrate(vault, "alpha", policy=ValidationPolicy(1))

    with pytest.raises(WorkspaceError) as raised:
        starved.set_checkpoint_label(starved.etag, checkpoint_id, "Renamed")

    assert {item.code for item in raised.value.diagnostics} == {"PRES_ASSET_LIMIT"}


def test_an_opened_workspace_reports_the_budget_it_will_validate_with(tmp_path: Path) -> None:
    vault = write_vault(tmp_path)
    policy = ValidationPolicy(DEFAULT_TOTAL_ASSET_BYTES)

    assert open_or_migrate(vault, "alpha", policy=policy).policy == policy


def test_receipt_verification_uses_the_budget_the_revision_was_promoted_under(tmp_path: Path) -> None:
    workspace = PresentationWorkspace.create(tmp_path / "store", FIXTURE, policy=ValidationPolicy(1024))

    assert verify_receipt(workspace.store.head_root, workspace.store.read_receipt(), policy=workspace.policy) == ()


def test_an_export_verifies_its_receipt_under_the_store_budget(tmp_path: Path) -> None:
    workspace = PresentationWorkspace.create(tmp_path / "store", FIXTURE, policy=ValidationPolicy(1024))

    assert export_offline_html(workspace.store).revision == workspace.revision


def test_an_export_under_a_starved_budget_refuses_with_the_limit_that_refused_it(tmp_path: Path) -> None:
    PresentationWorkspace.create(tmp_path / "store", FIXTURE, policy=ValidationPolicy(1024))
    starved = PresentationWorkspace.open(tmp_path / "store", policy=ValidationPolicy(1))

    with pytest.raises(WorkspaceError) as raised:
        export_offline_html(starved.store)

    assert {item.code for item in raised.value.diagnostics} == {"PRES_ASSET_LIMIT"}
