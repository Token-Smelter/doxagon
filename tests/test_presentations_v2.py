"""Adversarial coverage for the checkpoint-first presentation v2 foundation.

The fixtures below register arbitrary HTML, CSS, and JavaScript — canvas/WebGL
drawing, SVG, video, keyframes — and prove the validator admits them without
ever executing author code, while refusing every escape from the pinned-bytes,
contained-source, brokered-capability model.
"""

from __future__ import annotations

import ast
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
from typing import Any, Callable

from PIL import Image
import pytest

from doxagon.presentations import (
    CURSOR_SCHEMA,
    LEGACY_FIELDS,
    MANIFEST_SCHEMA,
    REGISTRATION_SCHEMA,
    Checkpoint,
    CheckpointOrder,
    DeckCursor,
    DiagnosticLog,
    PresentationError,
    build_edges,
    validate_presentation,
    verify_receipt,
)
from doxagon.presentations.contracts import pointer

ROOT = Path(__file__).parents[1]
_REVISION = "sha256:" + "0" * 64

_BASE_PROGRAM = """export function create(context) {
  const canvas = context.root.querySelector('#chart');
  const gl = canvas.getContext('webgl') || canvas.getContext('2d');
  let handle = 0;
  return {
    enter() {
      handle = requestAnimationFrame(() => paint(gl, context.assets.get('asset_market_map')));
    },
    exit() {
      cancelAnimationFrame(handle);
      handle = 0;
    },
    signature() {
      return 'market-base@1.0.0';
    },
    inspect() {
      return { frames: handle };
    },
  };
}

function paint(gl, map) {
  gl.clearColor(0.02, 0.05, 0.09, 1);
}
"""

_FORECAST_PROGRAM = """export function create(context) {
  const layer = context.root.querySelector('#forecast');
  return {
    enter() {
      layer.dataset.state = 'forecast';
    },
    exit() {
      delete layer.dataset.state;
    },
    signature() {
      return 'market-forecast@1.0.0';
    },
  };
}
"""

_SUMMARY_PROGRAM = """export function create(context) {
  const list = context.root.querySelector('#summary');
  return {
    enter() {
      list.setAttribute('aria-busy', 'false');
    },
    exit() {
      list.removeAttribute('aria-busy');
    },
    signature() {
      return 'summary@1.0.0';
    },
  };
}
"""

_BASE_DOCUMENT = """<section class="market">
  <h2>Market — base view</h2>
  <canvas id="chart" width="640" height="360"></canvas>
  <svg viewBox="0 0 12 12" role="img" aria-label="trend"><circle cx="6" cy="6" r="5"></circle></svg>
</section>
"""

_FORECAST_DOCUMENT = """<section class="market">
  <h2>Market — forecast</h2>
  <div id="forecast" data-state="base"></div>
  <video muted playsinline></video>
</section>
"""

_SUMMARY_DOCUMENT = """<section class="summary">
  <h2>Summary</h2>
  <ul id="summary"><li>Base and forecast reconciled</li></ul>
</section>
"""

_STYLES = """.market { display: grid; gap: 1rem; }
@keyframes reveal { from { opacity: 0; } to { opacity: 1; } }
#chart { transform: rotate(0.25deg); animation: reveal 320ms ease-out; }
"""


def _png_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (4, 4), (12, 34, 56)).save(buffer, format="PNG")
    return buffer.getvalue()


def _registration(
    checkpoint_id: str,
    *,
    assets: tuple[str, ...] = (),
    capabilities: tuple[str, ...] = (),
    forward_to: str | None = None,
    back_to: str | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "schema": REGISTRATION_SCHEMA,
        "id": checkpoint_id,
        "version": "1.0.0",
        "assets": list(assets),
        "capabilities": list(capabilities),
    }
    if forward_to is not None:
        record["forward_to"] = forward_to
    if back_to is not None:
        record["back_to"] = back_to
    return record


def _module(registration: dict[str, Any], body: str) -> str:
    block = json.dumps(registration, indent=2, sort_keys=True)
    return f"/* doxagon-checkpoint-registration\n{block}\n*/\n{body}"


def _write(path: Path, data: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))


def read_manifest(deck: Path) -> dict[str, Any]:
    return json.loads((deck / "presentation.json").read_text(encoding="utf-8"))


def write_manifest(deck: Path, manifest: dict[str, Any]) -> None:
    _write(deck / "presentation.json", json.dumps(manifest, indent=2) + "\n")


def _build_deck(tmp_path: Path) -> Path:
    """Write a valid three-checkpoint deck and return its presentation root."""

    deck = tmp_path / "presentation"
    png = _png_bytes()
    digest = hashlib.sha256(png).hexdigest()
    _write(deck / "assets" / "sha256" / digest, png)

    sources = {
        "market-base": (
            _module(
                _registration("market-base", assets=("asset_market_map",), capabilities=("timers",), forward_to="market-forecast"),
                _BASE_PROGRAM,
            ),
            _BASE_DOCUMENT,
        ),
        "market-forecast": (
            _module(_registration("market-forecast", assets=("asset_market_map",), back_to="market-base"), _FORECAST_PROGRAM),
            _FORECAST_DOCUMENT,
        ),
        "summary": (_module(_registration("summary"), _SUMMARY_PROGRAM), _SUMMARY_DOCUMENT),
    }
    for checkpoint_id, (program, document) in sources.items():
        _write(deck / "checkpoints" / checkpoint_id / "program.js", program)
        _write(deck / "checkpoints" / checkpoint_id / "document.html", document)
        _write(deck / "checkpoints" / checkpoint_id / "styles.css", _STYLES)
    _write(deck / "checkpoints" / "market-base" / "notes.md", "Open on the base view; do not advance early.\n")

    write_manifest(
        deck,
        {
            "schema": MANIFEST_SCHEMA,
            "presentation_id": "pres_q3_review",
            "checkpoint_order": ["market-base", "market-forecast", "summary"],
            "checkpoints": [
                {
                    "id": "market-base",
                    "label": "Market — base view",
                    "source": "checkpoints/market-base",
                    "entry": "program.js",
                    "document": "document.html",
                    "styles": "styles.css",
                    "notes": "notes.md",
                    "assets": ["asset_market_map"],
                    "capabilities": ["timers"],
                    "transition": {
                        "edge_id": "market-reveal",
                        "forward_to": "market-forecast",
                        "forward": {"kind": "reveal"},
                        "duration_ms": 400,
                        "export_boundary": True,
                    },
                },
                {
                    "id": "market-forecast",
                    "label": "Market — forecast",
                    "source": "checkpoints/market-forecast",
                    "entry": "program.js",
                    "document": "document.html",
                    "styles": "styles.css",
                    "assets": ["asset_market_map"],
                    "capabilities": [],
                    "transition": {"edge_id": "market-reveal", "back_to": "market-base", "reverse": {"kind": "conceal"}},
                },
                {
                    "id": "summary",
                    "label": "Summary",
                    "source": "checkpoints/summary",
                    "entry": "program.js",
                    "document": "document.html",
                    "styles": "styles.css",
                    "assets": [],
                    "capabilities": [],
                },
            ],
            "groups": [
                {
                    "id": "market",
                    "kind": "slide",
                    "label": "Market",
                    "checkpoints": ["market-base", "market-forecast"],
                    "export_boundary": True,
                }
            ],
            "assets": [
                {
                    "id": "asset_market_map",
                    "label": "Market map",
                    "alt": "Annotated market map",
                    "media_type": "image/png",
                    "bytes": len(png),
                    "sha256": digest,
                    "storage_key": f"sha256/{digest}",
                    "provenance": {
                        "kind": "generated",
                        "generator": "image-generation/1",
                        "prompt_sha256": hashlib.sha256(b"market map").hexdigest(),
                        "created_at": "2026-08-29T00:00:00Z",
                    },
                }
            ],
        },
    )
    return deck


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


def _append(path: Path, text: str) -> None:
    path.write_text(path.read_text(encoding="utf-8") + text, encoding="utf-8")


def _prepend(path: Path, text: str) -> None:
    path.write_text(text + path.read_text(encoding="utf-8"), encoding="utf-8")


# --- canonical acceptance -------------------------------------------------


def test_arbitrary_registered_source_validates_to_a_reproducible_revision(tmp_path: Path) -> None:
    deck = _build_deck(tmp_path)

    first = validate_presentation(deck)
    second = validate_presentation(deck)

    assert first.ok and first.receipt.canonical_bytes() == second.receipt.canonical_bytes()


def test_receipt_carries_no_slide_step_or_image_bundle_vocabulary(tmp_path: Path) -> None:
    deck = _build_deck(tmp_path)

    receipt = validate_presentation(deck).receipt.as_dict()

    assert LEGACY_FIELDS.isdisjoint(_nested_keys(receipt))


def test_ungrouped_checkpoint_is_ordered_and_group_membership_stays_optional(tmp_path: Path) -> None:
    deck = _build_deck(tmp_path)

    receipt = validate_presentation(deck).receipt

    assert receipt.checkpoint_order == ("market-base", "market-forecast", "summary") and [
        item["groups"] for item in receipt.checkpoints
    ] == [["market"], ["market"], []]


def test_registered_edge_records_both_endpoints_and_directions(tmp_path: Path) -> None:
    deck = _build_deck(tmp_path)

    edges = validate_presentation(deck).receipt.edges

    assert [(edge["id"], edge["from"], edge["to"], edge["forward"], edge["reverse"]) for edge in edges] == [
        ("market-reveal", "market-base", "market-forecast", {"kind": "reveal"}, {"kind": "conceal"})
    ]


def test_capability_grants_and_export_policy_are_pinned_in_the_receipt(tmp_path: Path) -> None:
    deck = _build_deck(tmp_path)

    receipt = validate_presentation(deck).receipt

    assert receipt.capability_grants == {"market-base": ["timers"], "market-forecast": [], "summary": []} and receipt.export_policy[
        "granted_capabilities"
    ] == ["timers"]


# --- revision identity ----------------------------------------------------


def _edit_label(deck: Path) -> None:
    manifest = read_manifest(deck)
    manifest["checkpoints"][0]["label"] = "Market — base view (revised)"
    write_manifest(deck, manifest)


def _edit_module(deck: Path) -> None:
    _append(deck / "checkpoints" / "summary" / "program.js", "\n// tuned easing\n")


def _edit_notes(deck: Path) -> None:
    _append(deck / "checkpoints" / "market-base" / "notes.md", "Mention the revision date.\n")


def _edit_asset_provenance(deck: Path) -> None:
    manifest = read_manifest(deck)
    manifest["assets"][0]["alt"] = "Annotated market map, revised"
    write_manifest(deck, manifest)


def _reverse_group_members(deck: Path) -> None:
    manifest = read_manifest(deck)
    manifest["groups"][0]["checkpoints"].reverse()
    write_manifest(deck, manifest)


def _reorder_checkpoints(deck: Path) -> None:
    manifest = read_manifest(deck)
    manifest["checkpoint_order"] = ["market-base", "summary", "market-forecast"]
    write_manifest(deck, manifest)


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(_edit_label, id="manifest"),
        pytest.param(_edit_module, id="checkpoint-source"),
        pytest.param(_edit_notes, id="notes"),
        pytest.param(_edit_asset_provenance, id="asset-provenance"),
        pytest.param(_reverse_group_members, id="group-order"),
        pytest.param(_reorder_checkpoints, id="checkpoint-order"),
    ],
)
def test_revision_changes_when_any_revision_input_changes(tmp_path: Path, mutate: Callable[[Path], None]) -> None:
    deck = _build_deck(tmp_path)
    before = validate_presentation(deck).receipt.revision

    mutate(deck)
    after = validate_presentation(deck)

    assert after.ok and after.receipt.revision != before


# --- adversarial rejection ------------------------------------------------


def _duplicate_checkpoint_id(deck: Path) -> None:
    manifest = read_manifest(deck)
    manifest["checkpoints"][2]["id"] = "market-base"
    write_manifest(deck, manifest)


def _unknown_ordered_checkpoint(deck: Path) -> None:
    manifest = read_manifest(deck)
    manifest["checkpoint_order"].append("ghost")
    write_manifest(deck, manifest)


def _checkpoint_outside_order(deck: Path) -> None:
    manifest = read_manifest(deck)
    manifest["checkpoint_order"].remove("summary")
    write_manifest(deck, manifest)


def _unknown_group_member(deck: Path) -> None:
    manifest = read_manifest(deck)
    manifest["groups"][0]["checkpoints"].append("ghost")
    write_manifest(deck, manifest)


def _legacy_layout(deck: Path) -> None:
    manifest = read_manifest(deck)
    manifest["layout"] = "html"
    write_manifest(deck, manifest)


def _legacy_checkpoint_image(deck: Path) -> None:
    manifest = read_manifest(deck)
    manifest["checkpoints"][0]["image"] = "slide-01.png"
    write_manifest(deck, manifest)


def _unknown_manifest_field(deck: Path) -> None:
    manifest = read_manifest(deck)
    manifest["theme"] = "dark"
    write_manifest(deck, manifest)


def _duplicate_json_key(deck: Path) -> None:
    path = deck / "presentation.json"
    line = '  "presentation_id": "pres_q3_review",'
    path.write_text(path.read_text(encoding="utf-8").replace(line, f"{line}\n{line}", 1), encoding="utf-8")


def _wrong_manifest_schema(deck: Path) -> None:
    manifest = read_manifest(deck)
    manifest["schema"] = "doxagon.presentation/1"
    write_manifest(deck, manifest)


def _escaping_source_key(deck: Path) -> None:
    manifest = read_manifest(deck)
    manifest["checkpoints"][0]["source"] = "checkpoints/../checkpoints/market-base"
    write_manifest(deck, manifest)


def _symlinked_document(deck: Path) -> None:
    outside = deck.parent / "outside.html"
    outside.write_text(_SUMMARY_DOCUMENT, encoding="utf-8")
    document = deck / "checkpoints" / "summary" / "document.html"
    document.unlink()
    document.symlink_to(outside)


def _symlinked_checkpoint_directory(deck: Path) -> None:
    moved = deck.parent / "relocated-summary"
    shutil.move(str(deck / "checkpoints" / "summary"), str(moved))
    (deck / "checkpoints" / "summary").symlink_to(moved, target_is_directory=True)


def _missing_source(deck: Path) -> None:
    (deck / "checkpoints" / "summary" / "styles.css").unlink()


def _tampered_asset_bytes(deck: Path) -> None:
    manifest = read_manifest(deck)
    blob = deck / "assets" / manifest["assets"][0]["storage_key"]
    data = bytearray(blob.read_bytes())
    data[-1] ^= 0xFF
    blob.write_bytes(bytes(data))


def _asset_bytes_without_media_signature(deck: Path) -> None:
    manifest = read_manifest(deck)
    payload = b"arbitrary bytes carrying no media signature"
    digest = hashlib.sha256(payload).hexdigest()
    (deck / "assets" / manifest["assets"][0]["storage_key"]).unlink()
    _write(deck / "assets" / "sha256" / digest, payload)
    manifest["assets"][0].update({"sha256": digest, "bytes": len(payload), "storage_key": f"sha256/{digest}"})
    write_manifest(deck, manifest)


def _asset_media_type_mismatch(deck: Path) -> None:
    manifest = read_manifest(deck)
    manifest["assets"][0]["media_type"] = "image/jpeg"
    write_manifest(deck, manifest)


def _asset_storage_key_mismatch(deck: Path) -> None:
    manifest = read_manifest(deck)
    manifest["assets"][0]["storage_key"] = "sha256/" + "b" * 64
    write_manifest(deck, manifest)


def _asset_without_alt(deck: Path) -> None:
    manifest = read_manifest(deck)
    del manifest["assets"][0]["alt"]
    write_manifest(deck, manifest)


def _duplicate_asset_id(deck: Path) -> None:
    manifest = read_manifest(deck)
    manifest["assets"].append(dict(manifest["assets"][0]))
    write_manifest(deck, manifest)


def _undeclared_asset_reference(deck: Path) -> None:
    manifest = read_manifest(deck)
    manifest["checkpoints"][2]["assets"] = ["asset_ghost"]
    write_manifest(deck, manifest)


def _executable_svg_asset(deck: Path) -> None:
    svg = b'<svg xmlns="urn:svg"><script>alert(1)</script></svg>'
    digest = hashlib.sha256(svg).hexdigest()
    _write(deck / "assets" / "sha256" / digest, svg)
    manifest = read_manifest(deck)
    manifest["assets"].append(
        {
            "id": "asset_diagram",
            "label": "Diagram",
            "alt": "Diagram",
            "media_type": "image/svg+xml",
            "bytes": len(svg),
            "sha256": digest,
            "storage_key": f"sha256/{digest}",
            "provenance": {"kind": "authored", "created_at": "2026-08-29T00:00:00Z"},
        }
    )
    write_manifest(deck, manifest)


def _invalid_capability(deck: Path) -> None:
    manifest = read_manifest(deck)
    manifest["checkpoints"][2]["capabilities"] = ["gpu"]
    write_manifest(deck, manifest)


def _ungranted_capability_use(deck: Path) -> None:
    _append(deck / "checkpoints" / "summary" / "program.js", "\nexport function refresh() { return fetch('/data'); }\n")


def _dynamic_code(deck: Path) -> None:
    _append(deck / "checkpoints" / "summary" / "program.js", "\nexport const boot = (source) => eval(source);\n")


def _template_substitution_dynamic_code(deck: Path) -> None:
    _append(deck / "checkpoints" / "summary" / "program.js", "\nexport const boot = (source) => `${eval(source)}`;\n")


def _nested_template_substitution_dynamic_code(deck: Path) -> None:
    _append(deck / "checkpoints" / "summary" / "program.js", "\nexport const deep = `a ${`b ${eval('owned')}`} c`;\n")


def _template_substitution_dynamic_import(deck: Path) -> None:
    _append(deck / "checkpoints" / "summary" / "program.js", "\nexport const ghost = `${import('./ghost.js')}`;\n")


def _template_substitution_ungranted_capability(deck: Path) -> None:
    _append(deck / "checkpoints" / "summary" / "program.js", "\nexport const probe = `${fetch('/data')}`;\n")


def _dynamic_code_after_a_division(deck: Path) -> None:
    _append(deck / "checkpoints" / "summary" / "program.js", "\nexport const ratio = {}.size / eval('owned');\n")


def _optional_call_dynamic_code(deck: Path) -> None:
    _append(deck / "checkpoints" / "summary" / "program.js", "\nexport const boot = (source) => eval?.(source);\n")


def _optional_member_unsafe_call(deck: Path) -> None:
    _append(deck / "checkpoints" / "summary" / "program.js", "\nexport const paint = (html) => document?.write?.(html);\n")


def _function_constructor_call(deck: Path) -> None:
    _append(deck / "checkpoints" / "summary" / "program.js", "\nexport const boot = (source) => Function('return ' + source)();\n")


def _optional_call_ungranted_capability(deck: Path) -> None:
    _append(deck / "checkpoints" / "summary" / "program.js", "\nexport const refresh = () => fetch?.('/data');\n")


def _optional_member_ungranted_capability(deck: Path) -> None:
    _append(
        deck / "checkpoints" / "summary" / "program.js",
        "\nexport const copy = (text) => navigator?.clipboard?.writeText?.(text);\n",
    )


def _remote_reference(deck: Path) -> None:
    _append(deck / "checkpoints" / "summary" / "program.js", "\nconst cdn = 'https://cdn.example.com/lib.js';\n")


def _unregistered_module_import(deck: Path) -> None:
    _write(deck / "checkpoints" / "summary" / "helper.js", "export const helper = 1;\n")
    path = deck / "checkpoints" / "summary" / "program.js"
    path.write_text("import { helper } from './helper.js';\n" + path.read_text(encoding="utf-8"), encoding="utf-8")


def _side_effect_module_import(deck: Path) -> None:
    _write(deck / "checkpoints" / "summary" / "ghost.js", "export const ghost = 1;\n")
    _prepend(deck / "checkpoints" / "summary" / "program.js", "import './ghost.js';\n")


def _bare_specifier_import(deck: Path) -> None:
    _prepend(deck / "checkpoints" / "summary" / "program.js", "import registry from 'registry';\n")


def _multiline_unregistered_import(deck: Path) -> None:
    _prepend(deck / "checkpoints" / "summary" / "program.js", "import {\n  helper,\n} from './helper.js';\n")


def _reexport_from_unregistered_module(deck: Path) -> None:
    _prepend(deck / "checkpoints" / "summary" / "program.js", "export * from './ghost.js';\n")


def _commented_reexport_from_unregistered_module(deck: Path) -> None:
    _prepend(deck / "checkpoints" / "summary" / "program.js", "export { value } from /* theme */ './ghost.js';\n")


def _template_literal_import(deck: Path) -> None:
    _prepend(deck / "checkpoints" / "summary" / "program.js", "import `./ghost.js`;\n")


def _import_after_a_regex_literal(deck: Path) -> None:
    _prepend(deck / "checkpoints" / "summary" / "program.js", "const pattern = /['\"]/g;\nimport './ghost.js';\n")


def _parent_directory_import(deck: Path) -> None:
    _prepend(deck / "checkpoints" / "summary" / "program.js", "import '../market-base/program.js';\n")


def _registration_omits_the_manifest_forward_edge(deck: Path) -> None:
    path = deck / "checkpoints" / "market-base" / "program.js"
    path.write_text(
        path.read_text(encoding="utf-8").replace('  "forward_to": "market-forecast",\n', "", 1),
        encoding="utf-8",
    )


def _registration_omits_the_manifest_back_edge(deck: Path) -> None:
    path = deck / "checkpoints" / "market-forecast" / "program.js"
    path.write_text(path.read_text(encoding="utf-8").replace('  "back_to": "market-base",\n', "", 1), encoding="utf-8")


def _css_asset(deck: Path, payload: bytes) -> None:
    """Declare one `text/css` asset whose extensionless storage key proves nothing."""

    digest = hashlib.sha256(payload).hexdigest()
    _write(deck / "assets" / "sha256" / digest, payload)
    manifest = read_manifest(deck)
    manifest["assets"].append(
        {
            "id": "asset_theme",
            "label": "Theme",
            "media_type": "text/css",
            "bytes": len(payload),
            "sha256": digest,
            "storage_key": f"sha256/{digest}",
            "provenance": {"kind": "authored", "created_at": "2026-08-29T00:00:00Z"},
        }
    )
    write_manifest(deck, manifest)


def _css_asset_without_stylesheet_syntax(deck: Path) -> None:
    _css_asset(deck, b"arbitrary bytes carrying no CSS syntax")


def _css_asset_carrying_json(deck: Path) -> None:
    _css_asset(deck, b'{"theme": "dark"}')


def _invalid_registration_id(deck: Path) -> None:
    path = deck / "checkpoints" / "summary" / "program.js"
    path.write_text(path.read_text(encoding="utf-8").replace('"id": "summary"', '"id": "Summary!"', 1), encoding="utf-8")


def _registration_id_mismatch(deck: Path) -> None:
    path = deck / "checkpoints" / "summary" / "program.js"
    path.write_text(path.read_text(encoding="utf-8").replace('"id": "summary"', '"id": "market-base"', 1), encoding="utf-8")


def _registration_schema_mismatch(deck: Path) -> None:
    path = deck / "checkpoints" / "summary" / "program.js"
    path.write_text(
        path.read_text(encoding="utf-8").replace(REGISTRATION_SCHEMA, "doxagon.presentation-checkpoint/0", 1),
        encoding="utf-8",
    )


def _registration_removed(deck: Path) -> None:
    _write(deck / "checkpoints" / "summary" / "program.js", _SUMMARY_PROGRAM)


def _registration_asset_outside_closure(deck: Path) -> None:
    path = deck / "checkpoints" / "summary" / "program.js"
    path.write_text(path.read_text(encoding="utf-8").replace('"assets": []', '"assets": ["asset_market_map"]', 1), encoding="utf-8")


def _inline_script_document(deck: Path) -> None:
    _append(deck / "checkpoints" / "summary" / "document.html", "<script>window.boot()</script>\n")


def _imported_stylesheet(deck: Path) -> None:
    path = deck / "checkpoints" / "summary" / "styles.css"
    path.write_text('@import "theme.css";\n' + path.read_text(encoding="utf-8"), encoding="utf-8")


def _forward_edge_without_reverse(deck: Path) -> None:
    manifest = read_manifest(deck)
    del manifest["checkpoints"][1]["transition"]
    write_manifest(deck, manifest)


def _declared_revision_mismatch(deck: Path) -> None:
    manifest = read_manifest(deck)
    manifest["revision"] = _REVISION
    write_manifest(deck, manifest)


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        pytest.param(_duplicate_checkpoint_id, "PRES_CHECKPOINT_ID_DUPLICATE", id="duplicate-checkpoint-id"),
        pytest.param(_unknown_ordered_checkpoint, "PRES_CHECKPOINT_UNKNOWN", id="unknown-ordered-checkpoint"),
        pytest.param(_checkpoint_outside_order, "PRES_CHECKPOINT_ORDER_MISMATCH", id="checkpoint-outside-order"),
        pytest.param(_unknown_group_member, "PRES_GROUP_UNKNOWN_CHECKPOINT", id="unknown-group-member"),
        pytest.param(_legacy_layout, "PRES_LEGACY_FIELD", id="legacy-layout"),
        pytest.param(_legacy_checkpoint_image, "PRES_LEGACY_FIELD", id="legacy-checkpoint-image"),
        pytest.param(_unknown_manifest_field, "PRES_UNKNOWN_FIELD", id="unknown-manifest-field"),
        pytest.param(_duplicate_json_key, "PRES_DUPLICATE_KEY", id="duplicate-json-key"),
        pytest.param(_wrong_manifest_schema, "PRES_SCHEMA_UNSUPPORTED", id="manifest-schema-version"),
        pytest.param(_escaping_source_key, "PRES_SOURCE_CONTAINMENT", id="escaping-source-key"),
        pytest.param(_symlinked_document, "PRES_SOURCE_CONTAINMENT", id="symlinked-document"),
        pytest.param(_symlinked_checkpoint_directory, "PRES_SOURCE_CONTAINMENT", id="symlinked-directory"),
        pytest.param(_missing_source, "PRES_SOURCE_NOT_FOUND", id="missing-source"),
        pytest.param(_tampered_asset_bytes, "PRES_ASSET_HASH_MISMATCH", id="tampered-asset-bytes"),
        pytest.param(_asset_media_type_mismatch, "PRES_ASSET_MIME_MISMATCH", id="asset-media-type"),
        pytest.param(_asset_bytes_without_media_signature, "PRES_ASSET_MIME_MISMATCH", id="asset-without-media-signature"),
        pytest.param(_asset_storage_key_mismatch, "PRES_ASSET_STORAGE_KEY_MISMATCH", id="asset-storage-key"),
        pytest.param(_asset_without_alt, "PRES_ASSET_ALT_MISSING", id="asset-without-alt"),
        pytest.param(_duplicate_asset_id, "PRES_ASSET_ID_DUPLICATE", id="duplicate-asset-id"),
        pytest.param(_undeclared_asset_reference, "PRES_ASSET_UNKNOWN", id="undeclared-asset-reference"),
        pytest.param(_executable_svg_asset, "PRES_ASSET_UNSAFE", id="executable-svg-asset"),
        pytest.param(_invalid_capability, "PRES_CAPABILITY_INVALID", id="invalid-capability"),
        pytest.param(_ungranted_capability_use, "PRES_CAPABILITY_UNGRANTED", id="ungranted-capability-use"),
        pytest.param(_dynamic_code, "PRES_REGISTRATION_UNSAFE_CODE", id="dynamic-code"),
        pytest.param(_template_substitution_dynamic_code, "PRES_REGISTRATION_UNSAFE_CODE", id="template-substitution-eval"),
        pytest.param(
            _nested_template_substitution_dynamic_code,
            "PRES_REGISTRATION_UNSAFE_CODE",
            id="nested-template-substitution-eval",
        ),
        pytest.param(
            _template_substitution_dynamic_import,
            "PRES_REGISTRATION_UNSAFE_CODE",
            id="template-substitution-dynamic-import",
        ),
        pytest.param(
            _template_substitution_ungranted_capability,
            "PRES_CAPABILITY_UNGRANTED",
            id="template-substitution-ungranted-capability",
        ),
        pytest.param(_dynamic_code_after_a_division, "PRES_REGISTRATION_UNSAFE_CODE", id="dynamic-code-after-division"),
        pytest.param(_optional_call_dynamic_code, "PRES_REGISTRATION_UNSAFE_CODE", id="optional-call-eval"),
        pytest.param(_optional_member_unsafe_call, "PRES_REGISTRATION_UNSAFE_CODE", id="optional-member-document-write"),
        pytest.param(_function_constructor_call, "PRES_REGISTRATION_UNSAFE_CODE", id="function-constructor-call"),
        pytest.param(_optional_call_ungranted_capability, "PRES_CAPABILITY_UNGRANTED", id="optional-call-fetch"),
        pytest.param(
            _optional_member_ungranted_capability,
            "PRES_CAPABILITY_UNGRANTED",
            id="optional-member-clipboard",
        ),
        pytest.param(_remote_reference, "PRES_REGISTRATION_REMOTE_REFERENCE", id="remote-reference"),
        pytest.param(_unregistered_module_import, "PRES_REGISTRATION_UNREGISTERED_MODULE", id="unregistered-module"),
        pytest.param(_side_effect_module_import, "PRES_REGISTRATION_UNREGISTERED_MODULE", id="side-effect-import"),
        pytest.param(_bare_specifier_import, "PRES_REGISTRATION_UNREGISTERED_MODULE", id="bare-specifier-import"),
        pytest.param(_multiline_unregistered_import, "PRES_REGISTRATION_UNREGISTERED_MODULE", id="multiline-import"),
        pytest.param(_reexport_from_unregistered_module, "PRES_REGISTRATION_UNREGISTERED_MODULE", id="reexport-import"),
        pytest.param(
            _commented_reexport_from_unregistered_module,
            "PRES_REGISTRATION_UNREGISTERED_MODULE",
            id="commented-reexport-import",
        ),
        pytest.param(_template_literal_import, "PRES_REGISTRATION_UNREGISTERED_MODULE", id="template-literal-import"),
        pytest.param(_import_after_a_regex_literal, "PRES_REGISTRATION_UNREGISTERED_MODULE", id="import-after-regex-literal"),
        pytest.param(_parent_directory_import, "PRES_REGISTRATION_UNREGISTERED_MODULE", id="parent-directory-import"),
        pytest.param(_registration_omits_the_manifest_forward_edge, "PRES_REGISTRATION_EDGE_MISMATCH", id="registration-omits-forward"),
        pytest.param(_registration_omits_the_manifest_back_edge, "PRES_REGISTRATION_EDGE_MISMATCH", id="registration-omits-back"),
        pytest.param(_css_asset_without_stylesheet_syntax, "PRES_ASSET_MIME_MISMATCH", id="css-asset-without-syntax"),
        pytest.param(_css_asset_carrying_json, "PRES_ASSET_MIME_MISMATCH", id="css-asset-carrying-json"),
        pytest.param(_invalid_registration_id, "PRES_FIELD_INVALID", id="invalid-registration-id"),
        pytest.param(_registration_id_mismatch, "PRES_REGISTRATION_ID_MISMATCH", id="registration-id-mismatch"),
        pytest.param(_registration_schema_mismatch, "PRES_REGISTRATION_SCHEMA_UNSUPPORTED", id="registration-schema-version"),
        pytest.param(_registration_removed, "PRES_REGISTRATION_MISSING", id="registration-missing"),
        pytest.param(_registration_asset_outside_closure, "PRES_REGISTRATION_ASSET_UNDECLARED", id="registration-asset-closure"),
        pytest.param(_inline_script_document, "PRES_DOCUMENT_UNSAFE", id="inline-script-document"),
        pytest.param(_imported_stylesheet, "PRES_STYLES_UNSAFE", id="imported-stylesheet"),
        pytest.param(_forward_edge_without_reverse, "PRES_EDGE_INCOMPLETE", id="forward-edge-without-reverse"),
        pytest.param(_declared_revision_mismatch, "PRES_REVISION_MISMATCH", id="declared-revision-mismatch"),
    ],
)
def test_adversarial_candidate_is_rejected_with_a_located_diagnostic(
    tmp_path: Path, mutate: Callable[[Path], None], code: str
) -> None:
    deck = _build_deck(tmp_path)
    mutate(deck)

    result = validate_presentation(deck)

    assert code in result.codes and all(item.pointer or item.path for item in result.diagnostics)


def test_registered_side_effect_import_is_admitted(tmp_path: Path) -> None:
    deck = _build_deck(tmp_path)
    _write(deck / "checkpoints" / "summary" / "helper.js", "export const helper = 1;\n")
    _append(deck / "checkpoints" / "summary" / "program.js", "\nimport './helper.js';\n")
    manifest = read_manifest(deck)
    manifest["checkpoints"][2]["modules"] = ["helper.js"]
    write_manifest(deck, manifest)

    assert validate_presentation(deck).ok


def test_registered_nested_module_import_resolves_from_the_importing_directory(tmp_path: Path) -> None:
    deck = _build_deck(tmp_path)
    _write(deck / "checkpoints" / "summary" / "lib" / "util.js", "export const util = 1;\n")
    _write(deck / "checkpoints" / "summary" / "lib" / "main.js", "import './util.js';\nexport const main = 1;\n")
    _append(deck / "checkpoints" / "summary" / "program.js", "\nimport './lib/main.js';\n")
    manifest = read_manifest(deck)
    manifest["checkpoints"][2]["modules"] = ["lib/main.js", "lib/util.js"]
    write_manifest(deck, manifest)

    assert validate_presentation(deck).ok


def test_containment_keywords_inside_strings_and_comments_are_not_code(tmp_path: Path) -> None:
    deck = _build_deck(tmp_path)
    _append(
        deck / "checkpoints" / "summary" / "program.js",
        "\nexport const notes = ['import \"./ghost.js\"', `eval(`, \"fetch(\"];\n"
        "const pattern = /[\"'`{]/g;\n"
        "const label = `${notes.length} import \"./ghost.js\"`;\n"
        "// import './ghost.js'; localStorage\n",
    )

    assert validate_presentation(deck).ok


def test_optional_chaining_on_ordinary_members_is_admitted(tmp_path: Path) -> None:
    deck = _build_deck(tmp_path)
    _append(
        deck / "checkpoints" / "summary" / "program.js",
        "\nexport const count = (state) => state?.items?.length ?? 0;\n"
        "export const first = (state) => state?.items?.[0];\n"
        "export const weight = (flag) => flag ? .5 : 1;\n",
    )

    assert validate_presentation(deck).ok


def test_asset_bytes_that_parse_as_a_stylesheet_are_admitted(tmp_path: Path) -> None:
    deck = _build_deck(tmp_path)
    _css_asset(deck, _STYLES.encode("utf-8"))

    assert validate_presentation(deck).ok


def test_invalid_registration_field_is_located_in_the_module_source(tmp_path: Path) -> None:
    deck = _build_deck(tmp_path)
    _invalid_registration_id(deck)

    found = next(item for item in validate_presentation(deck).diagnostics if item.code == "PRES_FIELD_INVALID")

    assert (found.pointer, found.path, found.line) == (pointer("id"), "checkpoints/summary/program.js", 2)


def test_failed_validation_changes_no_source_or_blob(tmp_path: Path) -> None:
    deck = _build_deck(tmp_path)
    _tampered_asset_bytes(deck)
    before = _tree_digest(deck)

    result = validate_presentation(deck)

    assert not result.ok and _tree_digest(deck) == before


# --- receipts -------------------------------------------------------------


def test_receipt_is_stale_after_a_registered_source_changes(tmp_path: Path) -> None:
    deck = _build_deck(tmp_path)
    receipt = validate_presentation(deck).receipt.as_dict()
    assert verify_receipt(deck, receipt) == ()

    _edit_module(deck)

    assert [item.code for item in verify_receipt(deck, receipt)] == ["PRES_RECEIPT_STALE"]


def test_receipt_of_a_foreign_shape_is_refused(tmp_path: Path) -> None:
    deck = _build_deck(tmp_path)

    findings = verify_receipt(deck, {"schema": "doxagon.html-edition-receipt/1"})

    assert [item.code for item in findings] == ["PRES_RECEIPT_INVALID"]


# --- edges ----------------------------------------------------------------


def _checkpoint(checkpoint_id: str, transition: dict[str, Any] | None, index: int) -> Checkpoint:
    return Checkpoint.parse(
        {
            "id": checkpoint_id,
            "label": checkpoint_id,
            "source": f"checkpoints/{checkpoint_id}",
            "entry": "program.js",
            "document": "document.html",
            "transition": transition,
        },
        pointer("checkpoints", index),
    )


def _edges(*specs: tuple[str, dict[str, Any] | None]) -> tuple[list[str], DiagnosticLog]:
    checkpoints = {spec[0]: _checkpoint(spec[0], spec[1], index) for index, spec in enumerate(specs)}
    log = DiagnosticLog()
    edges = build_edges(tuple(checkpoints), checkpoints, log)
    return [edge.edge_id for edge in edges], log


def test_linear_edge_is_generated_only_when_both_neighbours_opt_in() -> None:
    edge_ids, log = _edges(("a", {"linear": True}), ("b", {"linear": True}), ("c", None))

    assert edge_ids == ["linear:a->b"] and not log


def test_chained_checkpoint_registers_a_distinct_edge_in_each_direction() -> None:
    edge_ids, log = _edges(
        ("a", {"edge_id": "one", "forward_to": "b"}),
        ("b", {"edge_id": "two", "forward_to": "c", "back_edge_id": "one", "back_to": "a"}),
        ("c", {"edge_id": "two", "back_to": "b"}),
    )

    assert edge_ids == ["one", "two"] and not log


def test_reverse_half_returning_to_the_wrong_checkpoint_is_rejected() -> None:
    _, log = _edges(
        ("a", {"edge_id": "one", "forward_to": "b"}),
        ("b", {"edge_id": "one", "back_to": "c"}),
        ("c", None),
    )

    assert log.codes == ("PRES_EDGE_ENDPOINT_MISMATCH",)


def test_transition_cannot_mix_a_linear_opt_in_with_an_explicit_endpoint() -> None:
    with pytest.raises(PresentationError) as error:
        _checkpoint("a", {"linear": True, "edge_id": "one", "forward_to": "b"}, 0)

    assert error.value.diagnostic.code == "PRES_EDGE_AMBIGUOUS"


# --- cursor and order -----------------------------------------------------


@pytest.mark.parametrize("field", ["slideId", "slide_index", "step", "steps"])
def test_cursor_rejects_a_legacy_position_field(field: str) -> None:
    with pytest.raises(PresentationError) as error:
        DeckCursor.parse(
            {"schema": CURSOR_SCHEMA, "deckRevision": _REVISION, "sequence": 3, "checkpointId": "intro", field: 1}
        )

    assert error.value.diagnostic.code == "PRES_LEGACY_FIELD"


def test_order_refuses_a_stale_sequence_from_the_same_revision() -> None:
    order = CheckpointOrder.build(_REVISION, ("intro", "market-base"))

    assert not order.accepts(order.seek("market-base", 5), DeckCursor(_REVISION, 4, "intro"))


def test_order_refuses_an_equal_sequence_naming_a_different_checkpoint() -> None:
    order = CheckpointOrder.build(_REVISION, ("intro", "market-base"))

    assert not order.accepts(order.seek("intro", 5), DeckCursor(_REVISION, 5, "market-base"))


def test_seek_refuses_a_checkpoint_outside_the_revision() -> None:
    order = CheckpointOrder.build(_REVISION, ("intro",))

    with pytest.raises(PresentationError) as error:
        order.seek("ghost", 1)

    assert error.value.diagnostic.code == "PRES_CHECKPOINT_UNKNOWN"


# --- no author code executes ----------------------------------------------


def test_validation_admits_a_module_whose_evaluation_would_throw(tmp_path: Path) -> None:
    deck = _build_deck(tmp_path)
    _append(
        deck / "checkpoints" / "summary" / "program.js",
        "\nthrow new Error('checkpoint code must never run during validation');\n",
    )

    assert validate_presentation(deck).ok


# `exporters` owns the raster capturer, which is the one component whose job is
# to drive a browser over an already-validated revision. Every other module in
# the package — and the whole validation path in particular — must be unable to
# start a process, a socket, or a browser at all.
BROWSER_DRIVING_MODULE = "exporters.py"


def test_validator_package_imports_no_execution_facility() -> None:
    forbidden_modules = {"subprocess", "runpy", "ctypes", "importlib", "asyncio", "socket", "playwright"}
    forbidden_calls = {"eval", "exec", "compile", "__import__"}

    for path in sorted((ROOT / "src" / "doxagon" / "presentations").glob("*.py")):
        allowed = {"playwright"} if path.name == BROWSER_DRIVING_MODULE else set()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        imported |= {(node.module or "").split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        called = {
            node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert not (imported & forbidden_modules) - allowed, path.name
        assert not called & forbidden_calls, path.name


def test_the_validation_path_cannot_reach_the_browser_driver() -> None:
    """No module the validator depends on may import the exporter."""

    validation_path = ("validator.py", "contracts.py", "registration.py", "receipt.py", "sources.py", "javascript.py")
    for name in validation_path:
        text = (ROOT / "src" / "doxagon" / "presentations" / name).read_text(encoding="utf-8")
        assert "exporters" not in text, name
