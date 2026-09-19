"""Proof for the revisioned presentation workspace.

The legacy image path writes a bundle-relative ``selected`` plus one
``is_primary`` flag and renders thumbnails while answering a read; the target
here has neither. Generation produces independently labeled immutable assets,
single and batch share one prompt/generator path, every mutation names the
exact revision it edits, and a refused candidate leaves the promoted tree
byte-identical.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import threading
from types import SimpleNamespace
from typing import Any

from PIL import Image
from fastapi.testclient import TestClient
import pytest

from doxagon.presentations import (
    LEGACY_FIELDS,
    MANIFEST_SCHEMA,
    REGISTRATION_SCHEMA,
    AssetProvenance,
    GeneratedImage,
    GenerationSettings,
    GenerationSpec,
    PresentationWorkspace,
    Style,
    WorkspaceError,
    plan_generation,
    verify_receipt,
)
from doxagon.presentations.api import create_presentation_workspace_app
from doxagon.presentations.generation import specs_from_request
from doxagon.presentations import jobs
from doxagon.presentations.jobs import GENERATION_KIND, JobStore
from doxagon.presentations.store import RevisionStore
from doxagon.presentations.thumbnails import thumbnail_path

_PROGRAM = """export function create(context) {
  const stage = context.root.querySelector('#stage');
  return {
    enter() {
      stage.dataset.state = 'ready';
    },
    exit() {
      delete stage.dataset.state;
    },
    signature() {
      return 'ready@1.0.0';
    },
  };
}
"""

_DOCUMENT = """<section class="stage">
  <h2>Stage</h2>
  <div id="stage"></div>
</section>
"""

_STYLES = ".stage { display: grid; }\n"


def _png(colour: tuple[int, int, int] = (12, 34, 56)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (8, 8), colour).save(buffer, format="PNG")
    return buffer.getvalue()


def _module(checkpoint_id: str, **registration: Any) -> str:
    block = json.dumps(
        {"schema": REGISTRATION_SCHEMA, "id": checkpoint_id, "version": "1.0.0", **registration},
        indent=2,
        sort_keys=True,
    )
    return f"/* doxagon-checkpoint-registration\n{block}\n*/\n{_PROGRAM}"


def _write(path: Path, data: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))


def _deck(tmp_path: Path) -> Path:
    """A two-checkpoint deck with one grouped edge and one declared asset."""

    deck = tmp_path / "deck"
    png = _png()
    digest = hashlib.sha256(png).hexdigest()
    _write(deck / "assets" / "sha256" / digest, png)
    for checkpoint_id, registration in (
        ("intro", {"assets": ["asset_map"], "forward_to": "detail"}),
        ("detail", {"assets": [], "back_to": "intro"}),
    ):
        _write(deck / "checkpoints" / checkpoint_id / "program.js", _module(checkpoint_id, **registration))
        _write(deck / "checkpoints" / checkpoint_id / "document.html", _DOCUMENT)
        _write(deck / "checkpoints" / checkpoint_id / "styles.css", _STYLES)
    _write(
        deck / "presentation.json",
        json.dumps(
            {
                "schema": MANIFEST_SCHEMA,
                "presentation_id": "pres_workspace",
                "checkpoint_order": ["intro", "detail"],
                "checkpoints": [
                    {
                        "id": "intro",
                        "label": "Intro",
                        "source": "checkpoints/intro",
                        "entry": "program.js",
                        "document": "document.html",
                        "styles": "styles.css",
                        "assets": ["asset_map"],
                        "transition": {"edge_id": "reveal", "forward_to": "detail"},
                    },
                    {
                        "id": "detail",
                        "label": "Detail",
                        "source": "checkpoints/detail",
                        "entry": "program.js",
                        "document": "document.html",
                        "styles": "styles.css",
                        "assets": [],
                        "transition": {"edge_id": "reveal", "back_to": "intro"},
                    },
                ],
                "groups": [{"id": "opening", "kind": "slide", "label": "Opening", "checkpoints": ["intro", "detail"]}],
                "assets": [
                    {
                        "id": "asset_map",
                        "label": "Map",
                        "alt": "A map",
                        "media_type": "image/png",
                        "bytes": len(png),
                        "sha256": digest,
                        "storage_key": f"sha256/{digest}",
                        "provenance": {"kind": "authored", "created_at": "2026-08-29T00:00:00Z"},
                    }
                ],
            }
        ),
    )
    return deck


@pytest.fixture
def workspace(tmp_path: Path) -> PresentationWorkspace:
    return PresentationWorkspace.create(tmp_path / "workspace", _deck(tmp_path))


def _tree_digest(root: Path) -> str:
    entries: list[tuple[str, str, str]] = []
    for path in sorted(root.rglob("*")):
        relative = str(path.relative_to(root))
        if path.is_symlink():
            entries.append((relative, "symlink", os.readlink(path)))
        elif path.is_file():
            entries.append((relative, "file", hashlib.sha256(path.read_bytes()).hexdigest()))
        else:
            entries.append((relative, "dir", ""))
    return hashlib.sha256(json.dumps(entries).encode()).hexdigest()


def _nested_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {key for item in value.values() for key in _nested_keys(item)}
    if isinstance(value, list):
        return {key for item in value for key in _nested_keys(item)}
    return set()


def _source_digests(workspace: PresentationWorkspace) -> dict[str, list[dict[str, Any]]]:
    return {record["id"]: record["sources"] for record in workspace.read().checkpoints}


def _release_asset(workspace: PresentationWorkspace) -> None:
    """Drop the reference from the registered module first, then the manifest.

    A checkpoint's asset closure cannot be narrowed below what its digest-pinned
    registration claims, so releasing an asset is a source edit and a manifest
    edit, each validated and promoted on its own revision.
    """

    workspace.put_checkpoint_source(
        workspace.etag, "intro", "entry", _module("intro", assets=[], forward_to="detail").encode("utf-8")
    )
    workspace.set_checkpoint_assets(workspace.etag, "intro", [])


def _target(checkpoint_id: str = "intro", **overrides: Any) -> dict[str, Any]:
    return {
        "checkpoint_id": checkpoint_id,
        "label": "Stage art",
        "alt": "Generated stage art",
        "description": "A wide stage lit from the left",
        "styles": ["house"],
        "references": ["asset_map"],
        **overrides,
    }


_STYLE = {"id": "house", "text": "House style: muted, high contrast", "references": []}


def _counting_generator(colours: list[tuple[int, int, int]]):
    """Return distinct bytes per call so every variant is its own asset."""

    calls: list[dict[str, Any]] = []

    def generate(variant, references):
        calls.append(
            {
                "checkpoint_id": variant.checkpoint_id,
                "variant_index": variant.variant_index,
                "prompt_sha256": variant.prompt.sha256,
                "references": list(variant.prompt.references),
                "settings": variant.settings.as_dict(),
                "reference_bytes": [hashlib.sha256(item).hexdigest() for item in references],
            }
        )
        return GeneratedImage(_png(colours[(len(calls) - 1) % len(colours)]))

    generate.calls = calls
    return generate


def _identical_generator(colour: tuple[int, int, int] = (5, 6, 7)):
    """Return byte-identical output for every variant a plan asks for."""

    def generate(variant, references):
        return GeneratedImage(_png(colour))

    return generate


def _generate_identical(workspace: PresentationWorkspace, *, variants: int = 2, key: str = "gen-same"):
    job = workspace.start_generation(idempotency_key=key, targets=[_target(variants=variants)], styles=[_STYLE])
    return workspace.run_generation(job.job_id, _identical_generator())


def _generate(workspace: PresentationWorkspace, targets: list[dict[str, Any]], *, key: str = "gen-1", **request: Any):
    job = workspace.start_generation(idempotency_key=key, targets=targets, styles=[_STYLE], **request)
    generator = _counting_generator([(10, 20, 30), (40, 50, 60), (70, 80, 90), (100, 110, 120)])
    return workspace.run_generation(job.job_id, generator), generator


# --- AC1: immutable, independently labeled generated assets ----------------


def test_each_generated_variant_is_its_own_labeled_asset(workspace: PresentationWorkspace) -> None:
    record, _ = _generate(workspace, [_target(variants=3)])

    labels = [asset["label"] for asset in workspace.read().assets if asset["id"] in record.asset_ids]
    assert sorted(labels) == ["Stage art — variant 1", "Stage art — variant 2", "Stage art — variant 3"]


def test_variants_that_render_identical_bytes_stay_separately_labeled(workspace: PresentationWorkspace) -> None:
    record = _generate_identical(workspace)

    labels = [asset["label"] for asset in workspace.read().assets if asset["id"] in record.asset_ids]
    assert sorted(labels) == ["Stage art — variant 1", "Stage art — variant 2"]


def test_variants_that_render_identical_bytes_share_one_stored_blob(workspace: PresentationWorkspace) -> None:
    record = _generate_identical(workspace)

    keys = {asset["storage_key"] for asset in workspace.read().assets if asset["id"] in record.asset_ids}
    assert (len(set(record.asset_ids)), keys) == (2, {f"sha256/{record.outputs[0]['sha256']}"})


def test_two_jobs_that_render_identical_bytes_admit_two_assets(workspace: PresentationWorkspace) -> None:
    """Independent jobs never collapse into one record just by rendering alike."""

    first = _generate_identical(workspace, variants=1, key="gen-job-a")
    second = _generate_identical(workspace, variants=1, key="gen-job-b")

    assert set(first.asset_ids).isdisjoint(second.asset_ids)


def test_each_job_keeps_its_own_lineage_on_identical_bytes(workspace: PresentationWorkspace) -> None:
    first = _generate_identical(workspace, variants=1, key="gen-lineage-a")
    second = _generate_identical(workspace, variants=1, key="gen-lineage-b")

    generated = {asset["id"]: asset["generation"] for asset in workspace.read().assets if asset["generation"]}
    assert (generated[first.asset_ids[0]]["job_id"], generated[second.asset_ids[0]]["job_id"]) == (
        first.job_id,
        second.job_id,
    )


def test_readmitting_one_asset_id_with_different_provenance_is_refused(workspace: PresentationWorkspace) -> None:
    """A shared identifier must agree on every immutable member, not just bytes."""

    png = _png((3, 4, 5))

    def admit(provenance: AssetProvenance) -> None:
        workspace.add_asset(
            workspace.etag,
            png,
            label="Plate",
            alt="A plate",
            media_type="image/png",
            provenance=provenance,
            asset_id="asset_plate",
        )

    admit(AssetProvenance("imported", "2026-08-29T00:00:00Z", None, None, None, None))

    with pytest.raises(WorkspaceError) as error:
        admit(AssetProvenance("generated", "2026-08-29T00:01:00Z", "image-generation/1", None, None, None))

    assert error.value.code == "PRES_ASSET_IMMUTABLE"


def test_deleting_one_identical_variant_keeps_the_other_readable(workspace: PresentationWorkspace) -> None:
    record = _generate_identical(workspace)
    retired, kept = record.asset_ids

    workspace.delete_asset(workspace.etag, retired)

    assert hashlib.sha256(workspace.asset_bytes(kept)).hexdigest() == record.outputs[1]["sha256"]


def test_generated_assets_carry_generator_and_prompt_provenance(workspace: PresentationWorkspace) -> None:
    record, _ = _generate(workspace, [_target(variants=1)])

    asset = next(item for item in workspace.read().assets if item["id"] == record.asset_ids[0])
    assert asset["provenance"]["kind"] == "generated"
    assert asset["provenance"]["generator"] == GenerationSettings().generator
    assert asset["provenance"]["prompt_sha256"] == record.outputs[0]["prompt_sha256"]


def test_a_generated_asset_reads_back_the_prompt_its_digest_attests_to(
    workspace: PresentationWorkspace,
) -> None:
    """A digest nothing can resolve is not provenance; the sent text is kept."""

    record, generator = _generate(workspace, [_target(variants=1)])

    asset = next(item for item in workspace.read().assets if item["id"] == record.asset_ids[0])
    prompt = asset["generation"]["prompt"]
    assert hashlib.sha256(prompt.encode("utf-8")).hexdigest() == asset["provenance"]["prompt_sha256"]
    assert _STYLE["text"] in prompt
    assert asset["generation"]["prompt_references"] == generator.calls[0]["references"]


def test_a_prompt_the_deck_no_longer_attests_to_is_withheld_rather_than_shown(
    workspace: PresentationWorkspace,
) -> None:
    """The text lives outside the revision tree; the digest inside it decides."""

    record, _ = _generate(workspace, [_target(variants=1)])
    job_path = workspace.jobs.root / f"{record.job_id}.json"
    payload = json.loads(job_path.read_text())
    payload["outputs"][0]["prompt"] = "Render something else entirely"
    job_path.write_text(json.dumps(payload))

    asset = next(item for item in workspace.read().assets if item["id"] == record.asset_ids[0])
    assert asset["generation"]["prompt"] is None
    assert asset["generation"]["prompt_sha256"] == asset["provenance"]["prompt_sha256"]


# --- the deck's own reusable prompt styles ---------------------------------


def test_a_generation_resolves_a_style_the_deck_stores(workspace: PresentationWorkspace) -> None:
    """A style library nothing persists is a library no request can name."""

    workspace.put_style(workspace.etag, {"id": "house", "text": "Muted, high contrast", "references": ["asset_map"]})

    job = workspace.start_generation(idempotency_key="gen-stored-style", targets=[_target(variants=1)])
    record = workspace.run_generation(job.job_id, _counting_generator([(1, 1, 1)]))

    asset = next(item for item in workspace.read().assets if item["id"] == record.asset_ids[0])
    assert "Muted, high contrast" in asset["generation"]["prompt"]


def test_a_request_may_not_inline_a_style_the_deck_already_stores(workspace: PresentationWorkspace) -> None:
    """A stored style's name resolves to the deck's text, never a client's."""

    workspace.put_style(workspace.etag, {"id": "house", "text": "Muted, high contrast", "references": []})

    with pytest.raises(WorkspaceError) as error:
        workspace.start_generation(
            idempotency_key="gen-shadowed-style",
            targets=[_target(variants=1)],
            styles=[{"id": "house", "text": "Saturated, low contrast", "references": []}],
        )

    assert error.value.code == "PRES_STYLE_ID_DUPLICATE"


def test_a_request_may_still_inline_a_style_under_a_name_the_deck_does_not_hold(
    workspace: PresentationWorkspace,
) -> None:
    job = workspace.start_generation(
        idempotency_key="gen-inline-style",
        targets=[_target(variants=1, styles=["once"])],
        styles=[{"id": "once", "text": "Saturated, low contrast", "references": []}],
    )
    record = workspace.run_generation(job.job_id, _counting_generator([(3, 3, 3)]))

    asset = next(item for item in workspace.read().assets if item["id"] == record.asset_ids[0])
    assert "Saturated, low contrast" in asset["generation"]["prompt"]


def test_a_style_referencing_an_unknown_asset_is_refused(workspace: PresentationWorkspace) -> None:
    with pytest.raises(WorkspaceError) as error:
        workspace.put_style(workspace.etag, {"id": "house", "text": "Muted", "references": ["asset_missing"]})

    assert error.value.code == "PRES_VALIDATION_FAILED"


def test_deleting_a_style_leaves_the_generation_that_used_it_readable(
    workspace: PresentationWorkspace,
) -> None:
    """Retiring a library entry must not rewrite what an earlier prompt said."""

    workspace.put_style(workspace.etag, {"id": "house", "text": "Muted, high contrast", "references": []})
    job = workspace.start_generation(idempotency_key="gen-deleted-style", targets=[_target(variants=1)])
    record = workspace.run_generation(job.job_id, _counting_generator([(2, 2, 2)]))

    workspace.delete_style(workspace.etag, "house")

    asset = next(item for item in workspace.read().assets if item["id"] == record.asset_ids[0])
    assert "Muted, high contrast" in asset["generation"]["prompt"]
    assert workspace.read().styles == ()


def test_generation_changes_no_order_group_or_source_byte(workspace: PresentationWorkspace) -> None:
    before = workspace.read()
    before_sources = _source_digests(workspace)

    _generate(workspace, [_target(variants=2)])

    after = workspace.read()
    assert (after.manifest["checkpoint_order"], after.groups, _source_digests(workspace)) == (
        before.manifest["checkpoint_order"],
        before.groups,
        before_sources,
    )


def test_generated_manifest_declares_no_primary_or_layout_vocabulary(workspace: PresentationWorkspace) -> None:
    _generate(workspace, [_target(variants=2)])

    assert not _nested_keys(workspace.read().manifest) & LEGACY_FIELDS


def test_relabelling_an_asset_leaves_its_bytes_and_digest_immutable(workspace: PresentationWorkspace) -> None:
    record, _ = _generate(workspace, [_target(variants=1)])
    asset_id = record.asset_ids[0]
    before = next(item for item in workspace.read().assets if item["id"] == asset_id)

    view = workspace.set_asset_label(workspace.etag, asset_id, label="Chosen framing")

    after = next(item for item in view.assets if item["id"] == asset_id)
    assert (after["label"], after["sha256"], after["bytes"]) == ("Chosen framing", before["sha256"], before["bytes"])


def test_generation_status_and_outputs_survive_a_new_store_instance(
    workspace: PresentationWorkspace, tmp_path: Path
) -> None:
    record, _ = _generate(workspace, [_target(variants=2)])

    reloaded = JobStore(tmp_path / "workspace").get(record.job_id)

    assert (reloaded.status, reloaded.asset_ids) == ("succeeded", record.asset_ids)


# --- AC2: one prompt, reference, and generator path ------------------------


def test_single_and_batch_plan_the_same_variants_for_one_target(workspace: PresentationWorkspace) -> None:
    styles = {"house": Style("house", _STYLE["text"])}
    specs = specs_from_request([_target("intro"), _target("detail")], {"variants": 2})

    single = plan_generation(specs[:1], styles)
    batch = plan_generation(specs, styles)

    assert [variant.as_dict() for variant in batch.variants if variant.checkpoint_id == "intro"] == [
        variant.as_dict() for variant in single.variants
    ]


def test_batch_resolves_authored_defaults_exactly_as_single_does() -> None:
    defaults = {"resolution": "4k", "aspect_ratio": 969, "variants": 2}

    single = specs_from_request([_target("intro")], defaults)
    batch = specs_from_request([_target("intro"), _target("detail")], defaults)

    assert {spec.settings for spec in batch} == {single[0].settings}
    assert single[0].settings == GenerationSettings("4k", "16:9", 2)


def test_one_target_and_a_batch_invoke_the_generator_identically(
    workspace: PresentationWorkspace, tmp_path: Path
) -> None:
    _, single = _generate(workspace, [_target("intro", variants=2)], key="single")
    batched = PresentationWorkspace.create(tmp_path / "second", _deck(tmp_path / "second-deck"))
    _, batch = _generate(batched, [_target("intro", variants=2), _target("detail", variants=2)], key="batch")

    assert [call for call in batch.calls if call["checkpoint_id"] == "intro"] == single.calls


def test_a_style_reference_reaches_the_generator_as_bytes(workspace: PresentationWorkspace) -> None:
    _, generator = _generate(workspace, [_target(variants=1)])

    assert generator.calls[0]["reference_bytes"] == [hashlib.sha256(workspace.asset_bytes("asset_map")).hexdigest()]


# --- AC3: revisioned, precondition-guarded, atomic mutations ---------------


def test_a_mutation_without_if_match_is_refused(workspace: PresentationWorkspace) -> None:
    with pytest.raises(WorkspaceError) as error:
        workspace.set_checkpoint_label(None, "intro", "Opening")

    assert (error.value.code, error.value.status) == ("PRES_IF_MATCH_REQUIRED", 428)


@pytest.mark.parametrize("header", ["*", 'W/"sha256:' + "0" * 64 + '"', "sha256:" + "0" * 64])
def test_a_weak_or_wildcard_precondition_is_not_a_revision(workspace: PresentationWorkspace, header: str) -> None:
    with pytest.raises(WorkspaceError) as error:
        workspace.set_checkpoint_label(header, "intro", "Opening")

    assert error.value.code == "PRES_IF_MATCH_INVALID"


def test_a_stale_precondition_reports_the_revision_it_lost_to(workspace: PresentationWorkspace) -> None:
    stale = workspace.etag
    workspace.set_checkpoint_label(stale, "intro", "Opening")

    with pytest.raises(WorkspaceError) as error:
        workspace.set_checkpoint_label(stale, "intro", "Second writer")

    assert (error.value.code, error.value.revision) == ("PRES_REVISION_CONFLICT", workspace.revision)


def test_a_candidate_that_fails_validation_changes_no_promoted_byte(
    workspace: PresentationWorkspace, tmp_path: Path
) -> None:
    revisions = tmp_path / "workspace" / "revisions"
    before = (workspace.revision, _tree_digest(revisions))

    with pytest.raises(WorkspaceError) as error:
        workspace.put_checkpoint_source(workspace.etag, "intro", "entry", b"export function create() { eval('x'); }\n")

    assert error.value.code == "PRES_VALIDATION_FAILED"
    assert (workspace.revision, _tree_digest(revisions)) == before


def test_a_group_cannot_declare_navigation_authority(workspace: PresentationWorkspace) -> None:
    with pytest.raises(WorkspaceError) as error:
        workspace.put_group(
            workspace.etag,
            {"id": "opening", "kind": "slide", "label": "Opening", "checkpoint_order": ["detail", "intro"]},
        )

    assert error.value.code == "PRES_GROUP_NOT_AUTHORITY"


def test_regrouping_never_reorders_checkpoints(workspace: PresentationWorkspace) -> None:
    view = workspace.put_group(
        workspace.etag, {"id": "opening", "kind": "section", "label": "Opening", "checkpoints": ["detail"]}
    )

    assert view.manifest["checkpoint_order"] == ["intro", "detail"]


def test_reordering_rewrites_order_without_editing_source(workspace: PresentationWorkspace) -> None:
    before = _source_digests(workspace)

    view = workspace.reorder_checkpoints(workspace.etag, ["detail", "intro"])

    assert view.manifest["checkpoint_order"] == ["detail", "intro"]
    assert _source_digests(workspace) == before


def test_a_reorder_may_not_add_or_drop_a_checkpoint(workspace: PresentationWorkspace) -> None:
    with pytest.raises(WorkspaceError) as error:
        workspace.reorder_checkpoints(workspace.etag, ["intro"])

    assert error.value.code == "PRES_CHECKPOINT_ORDER_MISMATCH"


def test_reading_the_workspace_writes_nothing(workspace: PresentationWorkspace, tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    before = _tree_digest(root)

    workspace.read()
    workspace.asset_bytes("asset_map")
    workspace.thumbnail("asset_map")

    assert _tree_digest(root) == before


def test_each_promoted_revision_carries_a_receipt_that_recomputes(
    workspace: PresentationWorkspace, tmp_path: Path
) -> None:
    workspace.set_checkpoint_label(workspace.etag, "intro", "Opening")
    store = RevisionStore.open(tmp_path / "workspace")

    assert verify_receipt(store.head_root, store.read_receipt()) == ()


def test_promotion_keeps_the_previous_revision_readable(workspace: PresentationWorkspace, tmp_path: Path) -> None:
    previous = workspace.revision
    workspace.set_checkpoint_label(workspace.etag, "intro", "Opening")

    assert workspace.asset_bytes("asset_map", previous) == workspace.asset_bytes("asset_map")


# --- AC4: reference safety, conflicts, retry, and thumbnail jobs -----------


def test_a_referenced_asset_cannot_be_deleted(workspace: PresentationWorkspace) -> None:
    with pytest.raises(WorkspaceError) as error:
        workspace.delete_asset(workspace.etag, "asset_map")

    assert (error.value.code, error.value.status) == ("PRES_ASSET_IN_USE", 409)


def test_detaching_an_asset_the_module_still_claims_is_refused(workspace: PresentationWorkspace) -> None:
    before = workspace.revision

    with pytest.raises(WorkspaceError) as error:
        workspace.set_checkpoint_assets(workspace.etag, "intro", [])

    assert "PRES_REGISTRATION_ASSET_UNDECLARED" in [item.code for item in error.value.diagnostics]
    assert workspace.revision == before


def test_detaching_a_reference_then_deleting_retires_the_asset(workspace: PresentationWorkspace) -> None:
    _release_asset(workspace)

    view = workspace.delete_asset(workspace.etag, "asset_map")

    assert [asset["id"] for asset in view.assets] == []


def test_deleting_an_asset_leaves_earlier_revisions_intact(workspace: PresentationWorkspace) -> None:
    original = workspace.revision
    _release_asset(workspace)
    workspace.delete_asset(workspace.etag, "asset_map")

    assert len(workspace.asset_bytes("asset_map", original)) > 0


def test_attaching_an_unknown_asset_is_refused_and_rolled_back(workspace: PresentationWorkspace) -> None:
    before = workspace.revision

    with pytest.raises(WorkspaceError) as error:
        workspace.set_checkpoint_assets(workspace.etag, "intro", ["asset_missing"])

    assert error.value.code == "PRES_VALIDATION_FAILED"
    assert workspace.revision == before


def test_a_generation_against_a_superseded_revision_fails_without_admitting_assets(
    workspace: PresentationWorkspace,
) -> None:
    job = workspace.start_generation(idempotency_key="gen-stale", targets=[_target(variants=1)], styles=[_STYLE])
    workspace.set_checkpoint_label(workspace.etag, "intro", "Opening")

    record = workspace.run_generation(job.job_id, _counting_generator([(1, 2, 3)]))

    assert (record.status, record.error["code"]) == ("failed", "PRES_REVISION_CONFLICT")
    assert [asset["id"] for asset in workspace.read().assets] == ["asset_map"]


def test_retrying_a_failed_generation_admits_its_variants(workspace: PresentationWorkspace) -> None:
    job = workspace.start_generation(idempotency_key="gen-retry", targets=[_target(variants=1)], styles=[_STYLE])

    def broken(variant, references):
        raise RuntimeError("backend unavailable")

    failed = workspace.run_generation(job.job_id, broken)
    retried = workspace.run_generation(workspace.retry_job(failed.job_id).job_id, _counting_generator([(9, 9, 9)]))

    assert (failed.status, retried.status) == ("failed", "succeeded")
    assert retried.asset_ids[0] in [asset["id"] for asset in workspace.read().assets]


def test_a_retry_keeps_the_generation_lineage_it_replaces(workspace: PresentationWorkspace) -> None:
    """Asset identity descends from the lineage, so a retry must inherit it."""

    job = workspace.start_generation(idempotency_key="gen-lineage", targets=[_target(variants=1)], styles=[_STYLE])

    def broken(variant, references):
        raise RuntimeError("backend unavailable")

    failed = workspace.run_generation(job.job_id, broken)
    retried = workspace.retry_job(failed.job_id)

    assert (retried.lineage_id, retried.job_id == failed.job_id) == (failed.lineage_id, False)


def test_a_succeeded_job_is_not_retryable(workspace: PresentationWorkspace) -> None:
    record, _ = _generate(workspace, [_target(variants=1)])

    with pytest.raises(WorkspaceError) as error:
        workspace.retry_job(record.job_id)

    assert error.value.code == "PRES_JOB_NOT_RETRYABLE"


def test_replaying_one_idempotency_key_replays_one_job(workspace: PresentationWorkspace) -> None:
    first = workspace.start_generation(idempotency_key="gen-once", targets=[_target(variants=1)], styles=[_STYLE])
    second = workspace.start_generation(idempotency_key="gen-once", targets=[_target(variants=1)], styles=[_STYLE])

    assert first.job_id == second.job_id


def test_concurrent_submissions_under_one_key_create_one_durable_job(
    workspace: PresentationWorkspace, tmp_path: Path
) -> None:
    """Two submissions that interleave the key lookup must not both persist."""

    barrier = threading.Barrier(8)

    def submit() -> str:
        barrier.wait()
        return workspace.start_generation(
            idempotency_key="gen-race", targets=[_target(variants=1)], styles=[_STYLE]
        ).job_id

    with ThreadPoolExecutor(max_workers=8) as pool:
        job_ids = {future.result() for future in [pool.submit(submit) for _ in range(8)]}

    persisted = list((tmp_path / "workspace" / "jobs").glob("*.json"))
    assert (len(job_ids), len(persisted)) == (1, 1)


def test_retrying_one_failed_attempt_twice_replays_one_retry(workspace: PresentationWorkspace) -> None:
    job = workspace.start_generation(idempotency_key="gen-twice", targets=[_target(variants=1)], styles=[_STYLE])

    def broken(variant, references):
        raise RuntimeError("backend unavailable")

    failed = workspace.run_generation(job.job_id, broken)

    assert workspace.retry_job(failed.job_id).job_id == workspace.retry_job(failed.job_id).job_id


def test_an_immediate_retry_lists_after_the_attempt_it_replaces(tmp_path: Path, monkeypatch) -> None:
    """A colliding timestamp must not decide the order of two attempts.

    ``now()`` is second-resolution, so a retry clicked right after a failure
    shares its ``created_at``; the ids are forced here so a job-id tiebreak
    would list attempt 2 first. No sleep and no timestamp precision is relied
    on: the collision is produced, not waited for.
    """

    monkeypatch.setattr(jobs, "now", lambda: "2026-01-01T00:00:00Z")
    minted = iter(["f" * 32, "0" * 32, "5" * 32])
    monkeypatch.setattr(jobs, "uuid4", lambda: SimpleNamespace(hex=next(minted)))
    store = JobStore(tmp_path)

    first = store.submit(GENERATION_KIND, "gen", {"targets": []}, "sha256:base")
    store.start(first.job_id)
    failed = store.fail(first.job_id, "PRES_GENERATION_FAILED", "the backend refused")
    retry = store.retry(failed.job_id, "sha256:base")
    independent = store.submit(GENERATION_KIND, "other", {"targets": [1]}, "sha256:base")

    assert retry.created_at == failed.created_at, "the collision this regression is about"
    assert [record.job_id for record in store.list()] == [independent.job_id, first.job_id, retry.job_id]
    assert [record.attempt for record in store.list()][-2:] == [1, 2]
    # An independent job is ordered by durable identity, so every reader of the
    # same directory sees the same list.
    assert store.list() == JobStore(tmp_path).list()


def test_reusing_a_key_for_different_work_is_refused(workspace: PresentationWorkspace) -> None:
    workspace.start_generation(idempotency_key="gen-key", targets=[_target(variants=1)], styles=[_STYLE])

    with pytest.raises(WorkspaceError) as error:
        workspace.start_generation(idempotency_key="gen-key", targets=[_target(variants=3)], styles=[_STYLE])

    assert error.value.code == "PRES_JOB_KEY_CONFLICT"


def test_a_thumbnail_job_derives_outside_every_revision(workspace: PresentationWorkspace) -> None:
    revision = workspace.revision
    job = workspace.start_thumbnails(idempotency_key="thumb-1", asset_ids=["asset_map"])

    record = workspace.run_thumbnails(job.job_id)

    assert (record.status, workspace.revision) == ("succeeded", revision)
    assert workspace.thumbnail("asset_map") is not None


def test_a_thumbnail_job_reports_an_asset_it_cannot_read(workspace: PresentationWorkspace) -> None:
    job = workspace.start_thumbnails(idempotency_key="thumb-missing", asset_ids=["asset_absent"])

    record = workspace.run_thumbnails(job.job_id)

    assert (record.status, record.failures[0]["code"]) == ("failed", "PRES_ASSET_UNKNOWN")


def test_reading_an_asset_never_derives_its_thumbnail(workspace: PresentationWorkspace, tmp_path: Path) -> None:
    digest = next(asset["sha256"] for asset in workspace.read().assets if asset["id"] == "asset_map")

    workspace.read()
    workspace.thumbnail("asset_map")

    assert not thumbnail_path(tmp_path / "workspace", digest).exists()


# --- HTTP surface ----------------------------------------------------------


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    root = tmp_path / "workspace"
    PresentationWorkspace.create(root, _deck(tmp_path))
    return TestClient(create_presentation_workspace_app(root), raise_server_exceptions=False)


def test_a_read_returns_the_revision_as_a_strong_etag(client: TestClient) -> None:
    response = client.get("/presentation")

    assert response.headers["etag"] == f'"{response.json()["revision"]}"'


def test_a_mutation_replies_with_the_revision_it_produced(client: TestClient) -> None:
    etag = client.get("/presentation").headers["etag"]

    response = client.put(
        "/presentation/checkpoint-order", json={"checkpoint_order": ["detail", "intro"]}, headers={"If-Match": etag}
    )

    assert response.json()["checkpoint_order"] == ["detail", "intro"]
    assert response.headers["etag"] != etag


def test_a_conflicting_write_answers_with_the_current_manifest(client: TestClient) -> None:
    stale = client.get("/presentation").headers["etag"]
    client.patch("/presentation/checkpoints/intro", json={"label": "Opening"}, headers={"If-Match": stale})

    response = client.patch("/presentation/checkpoints/intro", json={"label": "Later"}, headers={"If-Match": stale})

    assert response.status_code == 409
    assert response.json()["manifest"]["checkpoints"][0]["label"] == "Opening"


def test_a_mutation_without_a_precondition_is_refused_over_http(client: TestClient) -> None:
    response = client.patch("/presentation/checkpoints/intro", json={"label": "Opening"})

    assert (response.status_code, response.json()["code"]) == (428, "PRES_IF_MATCH_REQUIRED")


@pytest.mark.parametrize("member", ["checkpoint_order", "order", "cursor", "default"])
def test_a_group_request_carrying_navigation_authority_is_refused_over_http(
    client: TestClient, member: str
) -> None:
    etag = client.get("/presentation").headers["etag"]

    response = client.put(
        "/presentation/groups/opening",
        json={"kind": "slide", "label": "Opening", "checkpoints": ["intro"], member: ["detail", "intro"]},
        headers={"If-Match": etag},
    )

    assert (response.status_code, response.json()["code"]) == (422, "PRES_GROUP_NOT_AUTHORITY")


def test_a_group_body_may_not_redirect_the_group_the_path_names(client: TestClient) -> None:
    etag = client.get("/presentation").headers["etag"]

    response = client.put(
        "/presentation/groups/finale",
        json={"id": "opening", "kind": "slide", "label": "Finale", "checkpoints": ["detail"]},
        headers={"If-Match": etag},
    )

    assert (response.status_code, response.json()["code"]) == (422, "PRES_GROUP_ID_NOT_OWNED")
    assert [group["label"] for group in client.get("/presentation").json()["groups"]] == ["Opening"]


def test_a_style_round_trips_over_http_and_a_body_may_not_rename_it(client: TestClient) -> None:
    etag = client.get("/presentation").headers["etag"]

    stored = client.put(
        "/presentation/styles/house",
        json={"text": "Muted, high contrast", "references": ["asset_map"]},
        headers={"If-Match": etag},
    )
    redirected = client.put(
        "/presentation/styles/other",
        json={"id": "house", "text": "Saturated"},
        headers={"If-Match": stored.headers["etag"]},
    )

    assert stored.json()["styles"] == [{"id": "house", "text": "Muted, high contrast", "references": ["asset_map"]}]
    assert (redirected.status_code, redirected.json()["code"]) == (422, "PRES_STYLE_ID_NOT_OWNED")


def test_an_undeclared_request_member_is_refused_rather_than_dropped(client: TestClient) -> None:
    etag = client.get("/presentation").headers["etag"]

    response = client.put(
        "/presentation/checkpoint-order",
        json={"checkpoint_order": ["detail", "intro"], "cursor": "detail"},
        headers={"If-Match": etag},
    )

    assert (response.status_code, client.get("/presentation").json()["checkpoint_order"]) == (422, ["intro", "detail"])


def test_an_undelivered_thumbnail_is_reported_not_rendered(client: TestClient) -> None:
    response = client.get("/presentation/assets/asset_map/thumbnail")

    assert (response.status_code, response.json()["code"]) == (404, "PRES_THUMBNAIL_ABSENT")


def test_a_generation_request_is_accepted_as_a_durable_job(client: TestClient) -> None:
    response = client.post(
        "/presentation/generations",
        json={"idempotency_key": "http-1", "targets": [_target(variants=1)], "styles": [_STYLE]},
    )

    assert response.status_code == 202
    assert client.get(f"/presentation/jobs/{response.json()['job_id']}").json()["status"] == "pending"


def test_running_a_generation_without_a_configured_backend_is_reported(client: TestClient) -> None:
    job = client.post(
        "/presentation/generations",
        json={"idempotency_key": "http-2", "targets": [_target(variants=1)], "styles": [_STYLE]},
    ).json()

    response = client.post(f"/presentation/jobs/{job['job_id']}/run")

    assert (response.status_code, response.json()["code"]) == (503, "PRES_GENERATOR_UNAVAILABLE")


def test_an_uploaded_asset_is_admitted_with_its_declared_provenance(client: TestClient) -> None:
    import base64

    etag = client.get("/presentation").headers["etag"]

    response = client.post(
        "/presentation/assets",
        json={
            "data_base64": base64.b64encode(_png((1, 2, 3))).decode(),
            "label": "Reference plate",
            "alt": "A reference plate",
            "media_type": "image/png",
            "provenance": {"kind": "imported", "created_at": "2026-08-29T00:00:00Z"},
        },
        headers={"If-Match": etag},
    )

    assert response.status_code == 201
    assert [asset["label"] for asset in response.json()["assets"]] == ["Map", "Reference plate"]


def test_settings_reject_an_unsupported_resolution() -> None:
    with pytest.raises(WorkspaceError):
        replace(GenerationSettings(), resolution="8k")


def test_a_spec_without_alt_text_is_refused(workspace: PresentationWorkspace) -> None:
    spec = GenerationSpec("intro", "Stage art", "", "A wide stage")

    with pytest.raises(WorkspaceError) as error:
        plan_generation([spec], {})

    assert error.value.code == "PRES_GENERATION_INVALID"


def test_asset_reads_use_the_asset_size_limit(workspace: PresentationWorkspace) -> None:
    # Real presentation images routinely exceed the 4 MiB source-text limit.
    data = _png() + b"\0" * (5 * 1024 * 1024)
    workspace.add_asset(
        workspace.etag, data, label="Large image", alt="Large image",
        media_type="image/png",
        provenance=AssetProvenance("imported", "2026-08-29T00:00:00Z", None, None, None, None),
        asset_id="large_image",
    )
    assert workspace.asset_bytes("large_image") == data


def test_asset_content_is_revision_pinned_and_missing_assets_are_refused(client: TestClient) -> None:
    view = client.get("/presentation").json()
    revision = view["revision"]
    response = client.get("/presentation/assets/asset_map/content", params={"revision": revision})
    assert response.status_code == 200
    assert response.content == _png()
    assert response.headers["content-type"] == "image/png"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in response.headers["content-security-policy"]
    assert client.get("/presentation/assets/foreign/content").status_code == 404
