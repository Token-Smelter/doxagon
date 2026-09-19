"""Deterministic validation of one presentation v2 revision.

Validation is fail-closed and read-only: it opens nothing outside the
presentation root, executes no author code, and mints a receipt only when zero
diagnostics remain. Two validations of the same tree produce byte-identical
receipts, and a failed validation writes neither a source nor a blob.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Mapping

from doxagon.html_editions.contracts import canonical_json

from .contracts import (
    DEFAULT_VALIDATION_POLICY,
    MANIFEST_KEY,
    MAX_MANIFEST_BYTES,
    RECEIPT_SCHEMA,
    AssetRecord,
    Checkpoint,
    PresentationManifest,
    ValidationPolicy,
    asset_closure_digest,
    build_edges,
    child,
    group_memberships,
    parse_manifest_bytes,
    pointer,
)
from .errors import Diagnostic, DiagnosticLog, PresentationError
from .knowledge import KnowledgeClosure, parse_closure
from .receipt import ValidationReceipt, build_revision_input, compose_hash, compute_revision, export_policy_for
from .registration import (
    CheckpointRegistration,
    parse_registration,
    registration_agreement,
    scan_capabilities,
    scan_document,
    scan_module,
    scan_styles,
)
from .sources import SourceFile, VerifiedAsset, read_asset, read_contained, read_source_file


@dataclass(frozen=True)
class ValidationResult:
    """A receipt or the complete, deterministically ordered diagnostic set."""

    receipt: ValidationReceipt | None
    diagnostics: tuple[Diagnostic, ...]

    @property
    def ok(self) -> bool:
        return self.receipt is not None and not self.diagnostics

    @property
    def revision(self) -> str | None:
        return None if self.receipt is None else self.receipt.revision

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(item.code for item in self.diagnostics)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "revision": self.revision,
            "receipt": None if self.receipt is None else self.receipt.as_dict(),
            "diagnostics": [item.as_dict() for item in self.diagnostics],
        }


def validate_presentation(
    root: Path | int, *, policy: ValidationPolicy = DEFAULT_VALIDATION_POLICY
) -> ValidationResult:
    """Validate a presentation root and mint a receipt only when it is clean.

    The policy carries the deployment's aggregate declared-asset budget and
    nothing else; every per-asset admission check is fixed by the schema. A
    caller that omits it validates against the conservative default, so a limit
    is never widened by accident.
    """

    log = DiagnosticLog()
    try:
        raw_manifest = read_contained(root, MANIFEST_KEY, maximum=MAX_MANIFEST_BYTES)
        manifest = PresentationManifest.parse(parse_manifest_bytes(raw_manifest), log)
    except PresentationError as error:
        return ValidationResult(None, (error.diagnostic,))

    checkpoints = _index_checkpoints(manifest, log)
    order = _resolve_order(manifest, checkpoints, log)
    assets = _index_assets(manifest, log)
    verified_assets = _verify_assets(root, assets, log, policy)
    _check_groups(manifest, checkpoints, log)
    _check_styles(manifest, assets, log)
    _check_scene_closures(manifest, log)
    closure = _check_knowledge(root, manifest, checkpoints, log)

    registrations: dict[str, CheckpointRegistration] = {}
    checkpoint_records: list[dict[str, Any]] = []
    memberships = group_memberships(manifest.groups)
    for checkpoint_id in order:
        checkpoint = checkpoints[checkpoint_id]
        files = _read_checkpoint_files(root, checkpoint, log)
        _scan_checkpoint_sources(checkpoint, files, log)
        _check_cues(checkpoint, files, log)
        registration = _parse_checkpoint_registration(checkpoint, files, log)
        if registration is not None:
            registrations[checkpoint_id] = registration
        _check_asset_references(checkpoint, assets, log)
        checkpoint_records.append(
            {
                "id": checkpoint_id,
                "label": checkpoint.label,
                "source": checkpoint.source,
                "sources": [item.as_dict() for item in files],
                "registration": None if registration is None else registration.as_dict(),
                "assets": list(checkpoint.assets),
                "capabilities": list(checkpoint.capabilities),
                "groups": list(memberships.get(checkpoint_id, ())),
                **({"scene": checkpoint.scene} if checkpoint.scene is not None else {}),
                **({"mode": checkpoint.mode} if checkpoint.mode != "stage" else {}),
                **({"cues": list(checkpoint.cues)} if checkpoint.cues else {}),
                **({"claims": [claim.as_dict() for claim in checkpoint.claims]} if checkpoint.claims else {}),
            }
        )

    edges = build_edges(order, checkpoints, log)
    if log:
        return ValidationResult(None, log.sorted())

    knowledge_record = _knowledge_record(manifest, closure)
    revision_input = build_revision_input(
        manifest.presentation_id,
        manifest.revision_input_source,
        order,
        checkpoint_records,
        [edge.as_dict() for edge in edges],
        [group.as_dict() for group in manifest.groups],
        [verified_assets[key].as_dict() for key in sorted(verified_assets)],
        knowledge=knowledge_record,
    )
    revision = compute_revision(revision_input)
    if manifest.declared_revision is not None and manifest.declared_revision != revision:
        log.fail(
            "PRES_REVISION_MISMATCH",
            "declared revision does not match the calculated revision",
            pointer("revision"),
            MANIFEST_KEY,
        )
        return ValidationResult(None, log.sorted())

    grants = {record["id"]: list(record["capabilities"]) for record in checkpoint_records}
    receipt = ValidationReceipt(
        manifest.presentation_id,
        revision,
        tuple(order),
        tuple(checkpoint_records),
        tuple(edge.as_dict() for edge in edges),
        tuple(group.as_dict() for group in manifest.groups),
        tuple(verified_assets[key].as_dict() for key in sorted(verified_assets)),
        asset_closure_digest(assets.values()),
        grants,
        compose_hash(checkpoint_records, [edge.as_dict() for edge in edges]),
        export_policy_for(grants, [group.group_id for group in manifest.groups if group.export_boundary]),
        (),
        knowledge_record,
    )
    return ValidationResult(receipt, ())


def verify_receipt(
    root: Path | int, receipt: Any, *, policy: ValidationPolicy = DEFAULT_VALIDATION_POLICY
) -> tuple[Diagnostic, ...]:
    """Recompute a receipt from current sources; a build accepts only zero findings.

    Verification must use the policy the revision was promoted under: a build or
    export that re-validated a promoted deck against a smaller budget would
    report a revision as stale that nothing changed.
    """

    if not isinstance(receipt, Mapping) or receipt.get("schema") != RECEIPT_SCHEMA:
        return (Diagnostic("PRES_RECEIPT_INVALID", f"receipt must be a {RECEIPT_SCHEMA!r} object"),)
    result = validate_presentation(root, policy=policy)
    if result.receipt is None:
        return result.diagnostics
    if canonical_json(dict(receipt)) != result.receipt.canonical_bytes():
        return (
            Diagnostic(
                "PRES_RECEIPT_STALE",
                "receipt does not recompute from the current sources",
                pointer("revision"),
                MANIFEST_KEY,
            ),
        )
    return ()


def _index_checkpoints(manifest: PresentationManifest, log: DiagnosticLog) -> dict[str, Checkpoint]:
    indexed: dict[str, Checkpoint] = {}
    for checkpoint in manifest.checkpoints:
        if checkpoint.checkpoint_id in indexed:
            log.fail(
                "PRES_CHECKPOINT_ID_DUPLICATE",
                f"checkpoint id {checkpoint.checkpoint_id!r} is declared more than once",
                child(checkpoint.at, "id"),
            )
            continue
        indexed[checkpoint.checkpoint_id] = checkpoint
    return indexed


def _resolve_order(
    manifest: PresentationManifest, checkpoints: Mapping[str, Checkpoint], log: DiagnosticLog
) -> tuple[str, ...]:
    order: list[str] = []
    for index, checkpoint_id in enumerate(manifest.checkpoint_order):
        if checkpoint_id not in checkpoints:
            log.fail(
                "PRES_CHECKPOINT_UNKNOWN",
                f"checkpoint_order names {checkpoint_id!r}, which is not a registered checkpoint",
                pointer("checkpoint_order", index),
            )
            continue
        order.append(checkpoint_id)
    ordered = set(order)
    for checkpoint in checkpoints.values():
        if checkpoint.checkpoint_id not in ordered:
            log.fail(
                "PRES_CHECKPOINT_ORDER_MISMATCH",
                f"checkpoint {checkpoint.checkpoint_id!r} is absent from checkpoint_order",
                child(checkpoint.at, "id"),
            )
    return tuple(order)


def _index_assets(manifest: PresentationManifest, log: DiagnosticLog) -> dict[str, AssetRecord]:
    indexed: dict[str, AssetRecord] = {}
    for asset in manifest.assets:
        if asset.asset_id in indexed:
            log.fail("PRES_ASSET_ID_DUPLICATE", f"asset id {asset.asset_id!r} is declared more than once", child(asset.at, "id"))
            continue
        indexed[asset.asset_id] = asset
    return indexed


def _verify_assets(
    root: Path | int, assets: Mapping[str, AssetRecord], log: DiagnosticLog, policy: ValidationPolicy
) -> dict[str, VerifiedAsset]:
    verified: dict[str, VerifiedAsset] = {}
    total = 0
    for asset_id in sorted(assets):
        record = assets[asset_id]
        total += record.size
        if total > policy.total_asset_bytes:
            # The budget that refused this record is named, so an operator reads
            # the number they must raise instead of guessing at a constant.
            log.fail(
                "PRES_ASSET_LIMIT",
                f"declared assets exceed the {policy.total_asset_bytes}-byte revision size limit",
                record.at,
            )
            continue
        with log.capture():
            verified[asset_id] = read_asset(root, record)
    return verified


def _check_groups(manifest: PresentationManifest, checkpoints: Mapping[str, Checkpoint], log: DiagnosticLog) -> None:
    seen: set[str] = set()
    for group in manifest.groups:
        if group.group_id in seen:
            log.fail("PRES_GROUP_ID_DUPLICATE", f"group id {group.group_id!r} is declared more than once", child(group.at, "id"))
        seen.add(group.group_id)
        for index, member in enumerate(group.checkpoints):
            if member not in checkpoints:
                log.fail(
                    "PRES_GROUP_UNKNOWN_CHECKPOINT",
                    f"group names checkpoint {member!r}, which is not in this revision",
                    child(group.at, "checkpoints", index),
                )


def _check_styles(manifest: PresentationManifest, assets: Mapping[str, AssetRecord], log: DiagnosticLog) -> None:
    """A style may only contribute reference assets this revision actually holds."""

    seen: set[str] = set()
    for style in manifest.styles:
        if style.style_id in seen:
            log.fail("PRES_STYLE_ID_DUPLICATE", f"style id {style.style_id!r} is declared more than once", child(style.at, "id"))
        seen.add(style.style_id)
        for index, asset_id in enumerate(style.references):
            if asset_id not in assets:
                log.fail(
                    "PRES_ASSET_UNKNOWN",
                    f"style references asset {asset_id!r}, which is not declared in this revision",
                    child(style.at, "references", index),
                )


_CUE_ATTRIBUTE = re.compile(rb"data-cue\s*=\s*[\"']([^\"']+)[\"']")


def _check_cues(checkpoint: Checkpoint, files: tuple[SourceFile, ...], log: DiagnosticLog) -> None:
    """Every declared cue must be a position this document actually carries.

    Read from the document's own bytes, never by executing it: a cue the
    session can seek to must exist before anything runs, or Next would resolve
    to a place the realm cannot reach.
    """

    if not checkpoint.cues:
        return
    document = next((item for item in files if item.role == "document"), None)
    if document is None:
        return
    present = {match.group(1).decode("utf-8", "replace") for match in _CUE_ATTRIBUTE.finditer(document.data)}
    for index, cue in enumerate(checkpoint.cues):
        if cue not in present:
            log.fail(
                "PRES_CUE_ABSENT",
                f"cue {cue!r} is declared but no element carries data-cue={cue!r}",
                child(checkpoint.at, "cues", index),
                document.path,
            )


def _check_scene_closures(manifest: PresentationManifest, log: DiagnosticLog) -> None:
    """Sharing a realm must never retain authority absent at its destination."""

    scenes: dict[str, Checkpoint] = {}
    for checkpoint in manifest.checkpoints:
        if checkpoint.scene is None:
            continue
        first = scenes.setdefault(checkpoint.scene, checkpoint)
        if set(checkpoint.assets) != set(first.assets) or set(checkpoint.capabilities) != set(first.capabilities):
            log.fail(
                "PRES_SCENE_CLOSURE_MISMATCH",
                f"scene {checkpoint.scene!r} must declare the same assets and capabilities at every state",
                child(checkpoint.at, "scene"),
            )


def _knowledge_record(manifest: PresentationManifest, closure: KnowledgeClosure | None) -> dict[str, Any] | None:
    if not manifest.knowledge.declared:
        return None
    return {**manifest.knowledge.as_dict(), "closure_digest": None if closure is None else closure.digest}


def _check_knowledge(
    root: Path | int, manifest: PresentationManifest, checkpoints: Mapping[str, Checkpoint], log: DiagnosticLog
) -> KnowledgeClosure | None:
    """Resolve every knowledge reference against the pinned closure alone.

    Nothing here reads a vault. A closure inside the revision tree is the only
    thing a reference may resolve against, so an unchanged revision verifies the
    same way whatever the live graph has become since.
    """

    binding = manifest.knowledge
    closure: KnowledgeClosure | None = None
    if binding.closure is not None:
        try:
            closure = parse_closure(read_contained(root, binding.closure, maximum=MAX_MANIFEST_BYTES))
        except PresentationError as error:
            found = error.diagnostic
            log.fail("PRES_KNOWLEDGE_CLOSURE_INVALID", found.message, found.pointer, binding.closure)
            return None
    if binding.diegesis is not None:
        diegesis = None if closure is None else closure.diegeses.get(binding.diegesis)
        if diegesis is None:
            log.fail("PRES_KNOWLEDGE_UNRESOLVED", f"diegesis {binding.diegesis!r} is not in the pinned closure", pointer("knowledge", "diegesis"))
        elif binding.walk is not None and binding.walk not in diegesis.walks:
            log.fail("PRES_KNOWLEDGE_UNRESOLVED", f"walk {binding.walk!r} is not a walk of {binding.diegesis!r}", pointer("knowledge", "walk"))
    for checkpoint in checkpoints.values():
        for index, claim in enumerate(checkpoint.claims):
            at = child(checkpoint.at, "claims", index)
            if closure is None:
                log.fail("PRES_KNOWLEDGE_UNRESOLVED", "a claim needs a pinned knowledge closure to resolve against", at)
                continue
            for key, table in (("doxai", closure.doxai), ("evidence", closure.evidence)):
                for position, reference in enumerate(getattr(claim, key)):
                    if reference not in table:
                        log.fail("PRES_KNOWLEDGE_UNRESOLVED", f"{reference!r} is not in the pinned closure", child(at, key, position))
            if claim.status != "unassessed" and not (claim.doxai or claim.evidence or claim.qualification):
                log.fail("PRES_CLAIM_UNSUPPORTED", f"a {claim.status!r} claim must name support or a qualification", child(at, "status"))
    return closure


def _read_checkpoint_files(root: Path | int, checkpoint: Checkpoint, log: DiagnosticLog) -> tuple[SourceFile, ...]:
    files: list[SourceFile] = []
    for role, key in checkpoint.files:
        with log.capture():
            files.append(read_source_file(root, role, key, checkpoint.at))
    return tuple(files)


def _scan_checkpoint_sources(checkpoint: Checkpoint, files: tuple[SourceFile, ...], log: DiagnosticLog) -> None:
    # Registered modules are compared in the same key namespace as the file that
    # imports them, so a nested module resolves exactly once.
    registered_modules = {f"{checkpoint.source}/{module}" for module in checkpoint.modules}
    for source in files:
        if source.role in {"entry", "module"}:
            for diagnostic in scan_module(source.data, source.path, registered_modules):
                log.add(diagnostic)
            for diagnostic in scan_capabilities(source.data, source.path, checkpoint.capabilities, checkpoint.at):
                log.add(diagnostic)
        elif source.role == "document":
            for diagnostic in scan_document(source.data, source.path):
                log.add(diagnostic)
        elif source.role == "styles":
            for diagnostic in scan_styles(source.data, source.path):
                log.add(diagnostic)


def _parse_checkpoint_registration(
    checkpoint: Checkpoint, files: tuple[SourceFile, ...], log: DiagnosticLog
) -> CheckpointRegistration | None:
    entry = next((item for item in files if item.role == "entry"), None)
    if entry is None:
        return None
    registration: CheckpointRegistration | None = None
    with log.capture():
        registration = parse_registration(entry.data, entry.path)
    if registration is None:
        return None
    for diagnostic in registration_agreement(
        registration,
        checkpoint.checkpoint_id,
        checkpoint.assets,
        checkpoint.capabilities,
        checkpoint.transition.forward_to,
        checkpoint.transition.back_to,
        checkpoint.at,
        entry.path,
    ):
        log.add(diagnostic)
    return registration


def _check_asset_references(checkpoint: Checkpoint, assets: Mapping[str, AssetRecord], log: DiagnosticLog) -> None:
    for index, asset_id in enumerate(checkpoint.assets):
        if asset_id not in assets:
            log.fail(
                "PRES_ASSET_UNKNOWN",
                f"checkpoint references asset {asset_id!r}, which is not declared in this revision",
                child(checkpoint.at, "assets", index),
            )
