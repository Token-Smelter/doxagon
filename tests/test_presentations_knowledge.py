"""Claims resolve against the revision's pinned closure, never a live vault."""

from copy import deepcopy
import json
from pathlib import Path
import shutil
from typing import Any, Callable

import pytest

from doxagon.presentations import PresentationWorkspace, WorkspaceError
from doxagon.presentations.validator import validate_presentation

FIXTURES = Path(__file__).parent / "fixtures/presentations"
DIGEST = "b" * 64
UNBOUND = ("synthetic-deck", "scene-deck")
# A synthetic external identifier deliberately absent from the pinned closure.
VAULT_ONLY_DOXA = "d-external-example"


def closure() -> dict[str, Any]:
    return {
        "schema": "doxagon.knowledge-closure/1",
        "captured_at": "2026-09-06T00:00:00Z",
        "source": {"vault_id": None, "generation": None},
        "doxai": [{"id": "d-shapes-persist", "belief": "The shape persists.", "status": "active", "confidence": 0.8, "sha256": DIGEST}],
        "evidence": [{"id": "e-scene-proof", "title": "Scene proof", "sha256": DIGEST}],
        "diegeses": [{"id": "n-motion", "title": "Motion", "sha256": DIGEST, "walks": ["canonical"]}],
        "relations": [],
    }


def claim(**overrides: Any) -> dict[str, Any]:
    return {"text": "The shape persists across cues.", "doxai": ["d-shapes-persist"], "status": "supported", **overrides}


def bound_deck(tmp_path: Path, *, mutate: Callable[[dict[str, Any], dict[str, Any]], None] = lambda m, c: None) -> Path:
    source = tmp_path / "source"
    shutil.copytree(FIXTURES / "scene-deck", source)
    manifest = json.loads((source / "presentation.json").read_text())
    manifest["knowledge"] = {"thesis": "scene", "diegesis": "n-motion", "walk": "canonical", "closure": "knowledge/closure.json"}
    manifest["checkpoints"][0]["claims"] = [claim()]
    record = closure()
    mutate(manifest, record)
    (source / "knowledge").mkdir()
    (source / "knowledge/closure.json").write_text(json.dumps(record))
    (source / "presentation.json").write_text(json.dumps(manifest))
    return source


def codes(source: Path) -> set[str]:
    return set(validate_presentation(source).codes)


@pytest.mark.parametrize("deck", UNBOUND)
def test_a_deck_without_knowledge_carries_no_binding_in_its_identity(deck: str) -> None:
    """The revision input of an unbound deck has no knowledge member at all.

    Identity moves whenever the runtime bytes move, so a pinned hash would only
    ever test the runtime. What must hold is that bindings are absent, not
    null: a null member would silently re-key every promoted vault revision.
    """

    receipt = validate_presentation(FIXTURES / deck).receipt.as_dict()
    assert "knowledge" not in receipt and all("claims" not in item for item in receipt["checkpoints"])


def test_an_absent_binding_and_a_present_binding_are_distinct_identities(tmp_path: Path) -> None:
    unbound = validate_presentation(FIXTURES / "scene-deck").revision
    bound = validate_presentation(bound_deck(tmp_path)).revision
    assert unbound != bound


def test_resolved_claims_promote_and_the_receipt_pins_the_closure_digest(tmp_path: Path) -> None:
    workspace = PresentationWorkspace.create(tmp_path / "store", bound_deck(tmp_path))
    receipt = workspace.store.read_receipt()
    assert (receipt["knowledge"]["diegesis"], len(receipt["knowledge"]["closure_digest"]), receipt["checkpoints"][0]["claims"][0]["status"]) == (
        "n-motion", 64, "supported",
    )


@pytest.mark.parametrize(
    ("label", "mutate", "code"),
    [
        ("unknown doxa", lambda m, c: m["checkpoints"][0]["claims"][0].__setitem__("doxai", ["d-elsewhere"]), "PRES_KNOWLEDGE_UNRESOLVED"),
        ("vault doxa absent from closure", lambda m, c: m["checkpoints"][0]["claims"][0].__setitem__("doxai", [VAULT_ONLY_DOXA]), "PRES_KNOWLEDGE_UNRESOLVED"),
        ("unknown evidence", lambda m, c: m["checkpoints"][0]["claims"][0].__setitem__("evidence", ["e-missing"]), "PRES_KNOWLEDGE_UNRESOLVED"),
        ("supported with nothing behind it", lambda m, c: m["checkpoints"][0]["claims"][0].update(doxai=[], evidence=[]), "PRES_CLAIM_UNSUPPORTED"),
        ("diegesis outside the closure", lambda m, c: m["knowledge"].__setitem__("diegesis", "n-other"), "PRES_KNOWLEDGE_UNRESOLVED"),
        ("walk outside the diegesis", lambda m, c: m["knowledge"].__setitem__("walk", "executive"), "PRES_KNOWLEDGE_UNRESOLVED"),
        ("claims with no closure", lambda m, c: m["knowledge"].pop("closure"), "PRES_KNOWLEDGE_UNRESOLVED"),
        ("closure with an unknown field", lambda m, c: c.__setitem__("extra", 1), "PRES_KNOWLEDGE_CLOSURE_INVALID"),
        ("closure with a duplicate id", lambda m, c: c["doxai"].append(deepcopy(c["doxai"][0])), "PRES_KNOWLEDGE_CLOSURE_INVALID"),
    ],
)
def test_unresolved_or_unsupported_knowledge_is_refused(tmp_path: Path, label: str, mutate: Callable[..., None], code: str) -> None:
    assert code in codes(bound_deck(tmp_path, mutate=mutate)), label


def test_an_unassessed_claim_may_name_nothing_yet(tmp_path: Path) -> None:
    source = bound_deck(tmp_path, mutate=lambda m, c: m["checkpoints"][0]["claims"][0].update(doxai=[], evidence=[], status="unassessed"))
    assert validate_presentation(source).ok


def test_a_qualified_claim_may_rest_on_its_qualification(tmp_path: Path) -> None:
    source = bound_deck(tmp_path, mutate=lambda m, c: m["checkpoints"][0]["claims"][0].update(doxai=[], status="qualified", qualification="Illustrative only."))
    assert validate_presentation(source).ok


def test_claim_text_and_closure_bytes_are_both_part_of_revision_identity(tmp_path: Path) -> None:
    base = validate_presentation(bound_deck(tmp_path / "a")).revision
    reworded = validate_presentation(bound_deck(tmp_path / "b", mutate=lambda m, c: m["checkpoints"][0]["claims"][0].__setitem__("text", "Reworded."))).revision
    recaptured = validate_presentation(bound_deck(tmp_path / "c", mutate=lambda m, c: c.__setitem__("captured_at", "2026-09-07T00:00:00Z"))).revision
    assert len({base, reworded, recaptured}) == 3


def test_a_supported_claim_survives_promotion_but_is_refused_when_its_support_vanishes(tmp_path: Path) -> None:
    workspace = PresentationWorkspace.create(tmp_path / "store", bound_deck(tmp_path))
    with workspace.store.exclusive(), workspace.store.candidate() as candidate:
        (candidate / "knowledge/closure.json").write_text(json.dumps({**closure(), "doxai": []}))
        with pytest.raises(WorkspaceError) as error:
            workspace.store.promote(candidate)
    assert "PRES_KNOWLEDGE_UNRESOLVED" in {item.code for item in error.value.diagnostics}
