"""Proof for the one runtime, its deck payload, and the session cursor.

The browser-side behaviour of these exact bytes — opaque realms, denied host
APIs, absolute-seek determinism, reverse edges, and closure — is proved against
a real Chromium in ``apps/web/frontend/tests/presentation-runtime.spec.ts``.
What is proved here is everything a browser cannot answer: that the payload
carries only registered bytes, that the runtime is a single pinned artifact,
and that a cursor is issued by the server and never by a client.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil

import pytest

from doxagon.presentations import (
    RUNTIME_SHA256,
    RUNTIME_VERSION,
    PresentationWorkspace,
    SessionService,
    Snapshot,
    WorkspaceError,
    build_deck_payload,
    reduce_action,
    runtime_manifest,
    runtime_source,
)
from doxagon.presentations.contracts import CAPABILITIES
from doxagon.presentations.runtime import DECK_SCHEMA, OFFLINE_CAPABILITIES, unsupported_capabilities

FIXTURE = Path(__file__).parent / "fixtures" / "presentations" / "synthetic-deck"


@pytest.fixture
def workspace(tmp_path: Path) -> PresentationWorkspace:
    return PresentationWorkspace.create(tmp_path / "store", FIXTURE)


def test_one_runtime_is_a_single_pinned_artifact() -> None:
    manifest = runtime_manifest()
    assert manifest["version"] == RUNTIME_VERSION
    assert manifest["runtime_sha256"] == RUNTIME_SHA256
    # A second runtime is the failure this asserts against: exactly one file in
    # the tree may declare the runtime version constant.
    root = Path(__file__).resolve().parents[1]
    declaring = [
        path
        for path in (root / "src").rglob("*.js")
        if RUNTIME_VERSION in path.read_text(encoding="utf-8")
    ]
    assert [path.name for path in declaring] == ["runtime.js"]


def test_deck_payload_carries_registered_bytes_and_no_paths(workspace: PresentationWorkspace) -> None:
    payload = build_deck_payload(workspace.store).as_dict()

    assert payload["schema"] == DECK_SCHEMA
    assert payload["runtime_version"] == RUNTIME_VERSION
    assert payload["checkpoint_order"] == ["market-base", "market-forecast", "probe-denied", "leaky-timer"]
    base = next(item for item in payload["checkpoints"] if item["id"] == "market-base")
    assert "export function create" in base["entry"]
    assert base["assets"][0]["base64"]
    # An asset handle carries approved bytes; a storage key or workspace path
    # would let author code address the filesystem instead of the closure.
    assert "storage_key" not in base["assets"][0]
    assert str(workspace.store.root) not in json.dumps(payload)


def test_payload_is_stable_across_two_reads(workspace: PresentationWorkspace) -> None:
    assert build_deck_payload(workspace.store).digest == build_deck_payload(workspace.store).digest


def test_runtime_bytes_are_part_of_revision_identity(
    workspace: PresentationWorkspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A revision pins the runtime's bytes, not just its version string.

    Pinning only ``doxagon-presentation-runtime/2`` would let an edited runtime
    change what an unchanged revision does while the revision identity, and
    therefore every receipt and export that names it, stayed the same.
    """

    from doxagon.presentations import receipt as receipt_module
    from doxagon.presentations.validator import validate_presentation

    before = validate_presentation(FIXTURE).receipt
    assert before is not None
    assert before.as_dict()["runtime"] == {"version": RUNTIME_VERSION, "sha256": RUNTIME_SHA256}

    # Exactly one thing changes: the digest of the runtime's bytes.
    monkeypatch.setattr(receipt_module, "RUNTIME_PIN", {"version": RUNTIME_VERSION, "sha256": "0" * 64})
    after = validate_presentation(FIXTURE).receipt
    assert after is not None

    assert after.revision != before.revision
    assert after.compose_hash != before.compose_hash

    # And the revision already promoted under the real bytes stops recomputing,
    # so an edited runtime cannot quietly keep serving it.
    stale = validate_presentation(workspace.store.revision_root(workspace.revision))
    assert stale.receipt is None
    assert [item.code for item in stale.diagnostics] == ["PRES_REVISION_MISMATCH"]


def test_a_revision_pinned_to_other_runtime_bytes_cannot_be_presented(workspace: PresentationWorkspace) -> None:
    """Fail closed rather than run an old revision under today's runtime."""

    revision = workspace.revision
    receipt_path = next((workspace.store.revision_root(revision) / "receipts").iterdir())
    record = json.loads(receipt_path.read_bytes())
    record["runtime"] = {"version": RUNTIME_VERSION, "sha256": "0" * 64}
    receipt_path.write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(WorkspaceError) as error:
        build_deck_payload(workspace.store, revision)
    assert error.value.code == "PRES_RUNTIME_BYTES_MISMATCH"
    assert error.value.status == 409


def test_a_revision_pinned_to_other_runtime_bytes_cannot_be_exported(workspace: PresentationWorkspace) -> None:
    """The same refusal reaches the export path through receipt verification."""

    from doxagon.presentations.exporters import export_offline_html

    receipt_path = next((workspace.store.revision_root(workspace.revision) / "receipts").iterdir())
    record = json.loads(receipt_path.read_bytes())
    record["runtime"] = {"version": RUNTIME_VERSION, "sha256": "0" * 64}
    receipt_path.write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(WorkspaceError) as error:
        export_offline_html(workspace.store)
    assert error.value.code == "PRES_RECEIPT_STALE"


def test_payload_refuses_a_receipt_that_does_not_describe_the_revision(workspace: PresentationWorkspace) -> None:
    revision = workspace.revision
    receipt_path = next((workspace.store.revision_root(revision) / "receipts").iterdir())
    record = json.loads(receipt_path.read_bytes())
    record["revision"] = "sha256:" + "0" * 64
    receipt_path.write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(WorkspaceError) as error:
        build_deck_payload(workspace.store, revision)
    assert error.value.code == "PRES_RECEIPT_STALE"


def test_a_checkpoint_only_receives_handles_for_its_declared_assets(workspace: PresentationWorkspace) -> None:
    payload = build_deck_payload(workspace.store).as_dict()
    forecast = next(item for item in payload["checkpoints"] if item["id"] == "market-forecast")
    assert forecast["assets"] == []


def test_ungranted_capability_is_absent_from_the_payload(workspace: PresentationWorkspace) -> None:
    payload = build_deck_payload(workspace.store).as_dict()
    grants = {item["id"]: item["capabilities"] for item in payload["checkpoints"]}
    assert grants == {
        "market-base": [],
        "market-forecast": [],
        "probe-denied": ["timers"],
        "leaky-timer": ["timers"],
    }
    assert unsupported_capabilities(payload) == ()
    assert "network" not in OFFLINE_CAPABILITIES


def test_the_grant_vocabulary_is_exactly_what_the_realm_brokers() -> None:
    """No capability may be offered that the realm cannot actually honour.

    A grant outside the broker's set reads as "granted" in the workspace, in
    the payload, and in the agent vocabulary while doing nothing at all, which
    is the hollow grant this pins shut. The realm's own list is the authority;
    the Python vocabulary mirrors it.
    """

    source = runtime_source().decode("utf-8")
    declared = re.search(r"BROKERED_CAPABILITIES = Object\.freeze\(\[(.*?)\]\)", source, re.DOTALL)
    assert declared is not None, "the runtime must declare the capabilities it brokers"
    brokered = {item.strip().strip("'\"") for item in declared.group(1).split(",") if item.strip()}

    assert brokered == set(CAPABILITIES)
    # Offline is a narrower policy over the same set, never a wider one.
    assert OFFLINE_CAPABILITIES <= CAPABILITIES
    for retired in ("network", "storage", "clipboard", "export"):
        assert retired not in CAPABILITIES


def test_a_capability_the_realm_cannot_broker_is_refused_by_the_contract(tmp_path: Path) -> None:
    manifest = json.loads((FIXTURE / "presentation.json").read_text(encoding="utf-8"))
    manifest["checkpoints"][0]["capabilities"] = ["network"]
    deck = tmp_path / "deck"
    shutil.copytree(FIXTURE, deck)
    (deck / "presentation.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(WorkspaceError) as error:
        PresentationWorkspace.create(tmp_path / "store", deck)
    assert "PRES_CAPABILITY_INVALID" in {item.code for item in error.value.diagnostics}


# --- the session cursor is server-issued ---------------------------------


def test_next_and_previous_traverse_registered_edges(workspace: PresentationWorkspace) -> None:
    receipt = workspace.store.read_receipt()
    order = receipt["checkpoint_order"]
    edges = receipt["edges"]

    # A stage deck has no interior, so every position resolves with a null cue.
    assert reduce_action(order, edges, "market-base", {"type": "NEXT"}) == ("market-forecast", None)
    assert reduce_action(order, edges, "market-forecast", {"type": "PREVIOUS"}) == ("market-base", None)
    assert reduce_action(order, edges, "market-base", {"type": "END"}) == ("leaky-timer", None)
    assert reduce_action(order, edges, "leaky-timer", {"type": "HOME"}) == ("market-base", None)


def test_a_checkpoint_without_a_forward_edge_has_no_next(workspace: PresentationWorkspace) -> None:
    receipt = workspace.store.read_receipt()
    with pytest.raises(WorkspaceError) as error:
        reduce_action(receipt["checkpoint_order"], receipt["edges"], "leaky-timer", {"type": "NEXT"})
    # No fallback to an index, a slide, or a counter: an absent edge is absent.
    assert error.value.code == "PRES_EDGE_ABSENT"


def test_seek_names_its_target_and_refuses_an_unregistered_one(workspace: PresentationWorkspace) -> None:
    receipt = workspace.store.read_receipt()
    order, edges = receipt["checkpoint_order"], receipt["edges"]
    assert reduce_action(order, edges, "market-base", {"type": "SEEK", "checkpointId": "leaky-timer"}) == ("leaky-timer", None)
    with pytest.raises(WorkspaceError) as error:
        reduce_action(order, edges, "market-base", {"type": "SEEK", "checkpointId": "not-registered"})
    assert error.value.code == "PRES_CHECKPOINT_UNKNOWN"


def test_session_issues_every_snapshot_itself(workspace: PresentationWorkspace) -> None:
    sessions = SessionService(workspace.store)
    opened = sessions.open()

    assert opened.checkpoint_id == "market-base"
    assert opened.sequence == 0
    assert opened.deck_revision == workspace.revision

    advanced = sessions.apply(opened.session_id, {"type": "NEXT"})
    assert (advanced.checkpoint_id, advanced.sequence, advanced.epoch) == ("market-forecast", 1, 0)
    assert sessions.snapshot(opened.session_id).as_dict() == advanced.as_dict()
    assert advanced.cursor["checkpointId"] == "market-forecast"


def test_a_client_rejects_a_stale_forked_or_foreign_snapshot(workspace: PresentationWorkspace) -> None:
    sessions = SessionService(workspace.store)
    held = sessions.apply(sessions.open().session_id, {"type": "NEXT"})

    assert held.accepts(Snapshot(held.session_id, held.deck_revision, 0, 2, "probe-denied", held.issued_at))
    assert not held.accepts(Snapshot(held.session_id, held.deck_revision, 0, 0, "market-base", held.issued_at))
    # Equal (epoch, sequence) with a different checkpoint is a fork, not an update.
    assert not held.accepts(Snapshot(held.session_id, held.deck_revision, 0, 1, "market-base", held.issued_at))
    assert not held.accepts(Snapshot("other", held.deck_revision, 0, 2, "probe-denied", held.issued_at))
    assert not held.accepts(Snapshot(held.session_id, "sha256:" + "0" * 64, 0, 2, "probe-denied", held.issued_at))


def test_repinning_a_revision_ends_the_previous_epoch(workspace: PresentationWorkspace) -> None:
    sessions = SessionService(workspace.store)
    held = sessions.apply(sessions.open().session_id, {"type": "NEXT"})
    repinned = sessions.repin(held.session_id, workspace.revision)

    assert repinned.epoch == held.epoch + 1
    assert repinned.sequence == 0
    # A holder of the old line adopts the new epoch; a holder of the new line
    # never falls back to the old one.
    assert held.accepts(repinned)
    assert not repinned.accepts(held)


def test_a_session_action_against_another_revision_is_refused(workspace: PresentationWorkspace) -> None:
    sessions = SessionService(workspace.store)
    opened = sessions.open()
    with pytest.raises(WorkspaceError) as error:
        sessions.apply(opened.session_id, {"type": "NEXT"}, expected_revision="sha256:" + "0" * 64)
    assert error.value.code == "PRES_SESSION_REVISION_MISMATCH"


def test_an_unknown_session_and_an_unknown_action_are_refused(workspace: PresentationWorkspace) -> None:
    sessions = SessionService(workspace.store)
    with pytest.raises(WorkspaceError) as missing:
        sessions.snapshot("session_absent")
    assert missing.value.code == "PRES_SESSION_UNKNOWN"

    opened = sessions.open()
    with pytest.raises(WorkspaceError) as unknown:
        sessions.apply(opened.session_id, {"type": "ADVANCE"})
    assert unknown.value.code == "PRES_ACTION_UNKNOWN"


def test_a_traversal_path_cannot_address_a_session_file(workspace: PresentationWorkspace, tmp_path: Path) -> None:
    sessions = SessionService(workspace.store)
    for identifier in ("../escape", "nested/id", ".hidden", ""):
        with pytest.raises(WorkspaceError) as error:
            sessions.snapshot(identifier)
        assert error.value.code == "PRES_SESSION_UNKNOWN"
    assert not list(tmp_path.glob("**/escape*"))


def test_runtime_bytes_are_shared_with_the_browser_surface() -> None:
    """The frontend serves the canonical file, not a copy of it."""

    root = Path(__file__).resolve().parents[1]
    served = root / "apps" / "web" / "frontend" / "static" / "presentation-runtime.js"
    assert served.is_symlink(), "the frontend must serve the canonical runtime, not a second copy"
    assert served.resolve() == (root / "src" / "doxagon" / "presentations" / "resources" / "runtime.js").resolve()
    assert served.read_bytes() == runtime_source()


def test_offline_fixture_is_regenerated_from_the_current_runtime(tmp_path: Path) -> None:
    """The committed browser fixture cannot drift from the runtime it proves."""

    from doxagon.presentations.exporters import export_offline_html

    committed = FIXTURE.parent / "synthetic-deck.offline.html"
    store = PresentationWorkspace.create(tmp_path / "regen", FIXTURE).store
    rebuilt = export_offline_html(store).artifact
    if committed.read_bytes() != rebuilt:
        shutil.copyfile(committed, tmp_path / "committed.html")
        pytest.fail(
            "tests/fixtures/presentations/synthetic-deck.offline.html no longer matches the runtime; "
            "regenerate it so the browser suite proves the current bytes"
        )
