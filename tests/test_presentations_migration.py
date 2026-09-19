"""Proof for the read-only legacy inventory, promotion, and retirement census.

Every legacy tree here is synthesised in the test's own temporary directory
from public bytes. Nothing in this module reads a vault, a thesis directory, or
any configured content root.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import zlib
from typing import Callable

import pytest

from doxagon.presentations import migration
from doxagon.presentations import (
    LegacyReadAdapter,
    WorkspaceError,
    inventory_presentation,
    plan_migration,
    promote,
    retirement_census,
    verify_migration_receipt,
)
from doxagon.presentations.legacy_stock import (
    LEGACY_BUILDER_CHOREOGRAPHY_VERSION,
    LEGACY_STOCK_CHOREOGRAPHY_VERSION,
    render_builder_choreography,
    render_stock_choreography,
)
from doxagon.presentations.migration import (
    MIGRATION_MARKER,
    MIGRATION_RECEIPT_KEY,
    asset_id_for,
    checkpoint_id_for,
    is_migrated,
)


STOCK_CHOREOGRAPHY_DOCUMENT = (
    '<main><div id="enter" data-enter="1" class="off">Enter</div>'
    '<div id="exit" data-exit="2" class="on">Exit</div>'
    '<div id="plate" class="plate">Plate</div></main>'
)


def png(colour: tuple[int, int, int], width: int = 8, height: int = 4) -> bytes:
    raw = b"".join(b"\x00" + bytes(colour) * width for _ in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def legacy_deck(
    root: Path,
    *,
    selected: str | None = "outputs/one.png",
    layout: str = "image",
    html: str | None = None,
    extra_candidates: int = 1,
    styles: str | None = None,
) -> Path:
    """Build one synthetic legacy presentation in the shape the API exposes."""

    thesis = root / "alpha"
    presentation = thesis / "outputs" / "presentation"
    slides = presentation / "slides"
    (presentation).mkdir(parents=True)
    presentation.joinpath("config.yaml").write_text("slide_order:\n  - 01-opening\n  - 02-market\n", encoding="utf-8")
    if styles is not None:
        stylesheet = presentation.joinpath("styles", "html", "global.css")
        stylesheet.parent.mkdir(parents=True)
        stylesheet.write_text(styles, encoding="utf-8")

    for index, (slug, title) in enumerate((("01-opening", "Opening"), ("02-market", "Market"))):
        directory = slides / slug
        outputs = directory / "images" / "main" / "outputs"
        outputs.mkdir(parents=True)
        outputs.joinpath("one.png").write_bytes(png((10 + index, 20, 30)))
        for extra in range(extra_candidates):
            outputs.joinpath(f"two-{extra}.png").write_bytes(png((90 + index, 40 + extra, 50)))
        # A derived display artifact the migrator must never treat as authorship.
        outputs.joinpath(".thumb_one.jpg").write_bytes(b"\xff\xd8\xff\xdb thumbnail")
        lines = [
            "---",
            "text:",
            f"  title: {title}",
            "  body: |",
            f"    First paragraph of {title}.",
            "",
            f"    Second paragraph of {title}.",
            f"speaker_notes: Notes for {title}.",
            f"layout: {layout}",
            "images:",
            "  - id: main",
            f"    purpose: The {title} visual",
            "    is_primary: true",
        ]
        if selected is not None:
            lines.append(f"    selected: {selected}")
        lines += ["doxai:", "  - d-example", "---", ""]
        directory.joinpath("slide.md").write_text("\n".join(lines), encoding="utf-8")
        if html is not None:
            directory.joinpath("slide.html").write_text(html, encoding="utf-8")
    return thesis


# --- inventory is a pure read --------------------------------------------


def test_inventory_writes_nothing_and_derives_no_thumbnail(tmp_path: Path) -> None:
    thesis = legacy_deck(tmp_path)
    before = {path: path.stat().st_mtime_ns for path in sorted(thesis.rglob("*")) if path.is_file()}

    inventory = inventory_presentation(thesis)

    after = {path: path.stat().st_mtime_ns for path in sorted(thesis.rglob("*")) if path.is_file()}
    assert after == before, "inventory must not write, and must not derive a thumbnail while reading"
    assert inventory.order_source == "config.slide_order"
    assert [slide.slug for slide in inventory.slides] == ["01-opening", "02-market"]


def test_inventory_records_every_candidate_and_no_thumbnail(tmp_path: Path) -> None:
    inventory = inventory_presentation(legacy_deck(tmp_path, extra_candidates=2))

    candidates = [candidate for slide in inventory.slides for bundle in slide.bundles for candidate in bundle.candidates]
    assert len(candidates) == 6
    assert inventory.candidate_count == 6
    assert not any(candidate.filename.startswith(".thumb_") for candidate in candidates)
    assert sum(1 for candidate in candidates if candidate.selected) == 2


def test_identical_candidate_bytes_keep_two_records_with_two_provenances(tmp_path: Path) -> None:
    """Byte-identical candidates are still two candidates.

    Addressing an asset by its digest silently dropped one filename, bundle,
    and source_ref. Identity is the legacy address; the bytes stay shared
    through the content-addressed storage key.
    """

    thesis = legacy_deck(tmp_path, extra_candidates=0)
    duplicate = png((10, 20, 30))
    for slug in ("01-opening", "02-market"):
        outputs = thesis / "outputs" / "presentation" / "slides" / slug / "images" / "main" / "outputs"
        outputs.joinpath("one.png").write_bytes(duplicate)
        outputs.joinpath("copy.png").write_bytes(duplicate)

    plan = plan_migration(inventory_presentation(thesis))
    records = {record["id"]: record for record in plan.manifest["assets"]}

    assert len(records) == 4, "every candidate keeps its own asset record"
    source_refs = sorted(record["provenance"]["source_ref"] for record in records.values())
    assert source_refs == [
        "01-opening/images/main/outputs/copy.png",
        "01-opening/images/main/outputs/one.png",
        "02-market/images/main/outputs/copy.png",
        "02-market/images/main/outputs/one.png",
    ]
    # One blob on disk, four provenance records pointing at it.
    assert len({record["storage_key"] for record in records.values()}) == 1
    assert len(plan.assets) == 1
    assert records[asset_id_for("01-opening", "main", "one.png")]["label"] == "01-opening · main · one.png"


def test_promotion_blocks_when_no_config_or_numbered_sequence_declares_slide_order(tmp_path: Path) -> None:
    """Absent order is ambiguity, not an invitation to sort directory names."""

    thesis = legacy_deck(tmp_path)
    (thesis / "outputs" / "presentation" / "config.yaml").unlink()
    slides = thesis / "outputs" / "presentation" / "slides"
    (slides / "01-opening").rename(slides / "opening")
    (slides / "02-market").rename(slides / "market")

    inventory = inventory_presentation(thesis)

    assert inventory.order_source == "unresolved"
    codes = [item.code for item in inventory.blockers]
    assert "PRES_MIGRATION_ORDER_UNDECLARED" in codes
    # The inventory still reports every candidate; only promotion is refused.
    assert inventory.candidate_count == 4
    with pytest.raises(WorkspaceError) as error:
        plan_migration(inventory)
    assert error.value.code == "PRES_MIGRATION_BLOCKED"


@pytest.mark.parametrize("names", [("00-opening", "01-market"), ("01-opening", "02-market")])
@pytest.mark.parametrize("config", [None, "timing:\n  total: 25\n"])
def test_promotion_preserves_complete_legacy_numbered_order(tmp_path: Path, names: tuple[str, str], config: str | None) -> None:
    thesis = legacy_deck(tmp_path)
    root = thesis / "outputs" / "presentation"
    for old, new in zip(("01-opening", "02-market"), names):
        (root / "slides" / old).rename(root / "slides" / new)
    if config is None:
        (root / "config.yaml").unlink()
    else:
        (root / "config.yaml").write_text(config, encoding="utf-8")
    before = {path: path.read_bytes() for path in thesis.rglob("*") if path.is_file()}

    inventory = inventory_presentation(thesis)
    plan = plan_migration(inventory)

    assert inventory.order_source == "numbered-directories"
    assert inventory.blockers == ()
    assert plan.manifest["checkpoint_order"] == [checkpoint_id_for(name) for name in names]
    assert len(plan.manifest["assets"]) == 4
    assert {path: path.read_bytes() for path in thesis.rglob("*") if path.is_file()} == before


@pytest.mark.parametrize("names", [
    ("01-opening", "03-market"),  # gap
    ("01-opening", "01-market"),  # duplicate ordinal
    ("02-opening", "03-market"),  # unknown start
    ("01-opening", "market"),  # mixed names
    ("01-01-opening", "02-market"),  # nested numbering
    ("1-opening", "02-market"),  # lexical and numeric order disagree
])
def test_numbered_order_does_not_guess_through_ambiguity(tmp_path: Path, names: tuple[str, str]) -> None:
    thesis = legacy_deck(tmp_path)
    root = thesis / "outputs" / "presentation"
    # Rename through temporary names so the two inputs cannot collide.
    for index, old in enumerate(("01-opening", "02-market")):
        (root / "slides" / old).rename(root / "slides" / f"temp-{index}")
    for index, name in enumerate(names):
        (root / "slides" / f"temp-{index}").rename(root / "slides" / name)
    (root / "config.yaml").unlink()

    inventory = inventory_presentation(thesis)

    assert inventory.order_source == "unresolved"
    assert inventory.candidate_count == 4
    with pytest.raises(WorkspaceError) as error:
        plan_migration(inventory)
    assert error.value.code == "PRES_MIGRATION_BLOCKED"


def test_explicit_order_still_overrides_numbered_directories(tmp_path: Path) -> None:
    thesis = legacy_deck(tmp_path)
    config = thesis / "outputs" / "presentation" / "config.yaml"
    config.write_text("slide_order:\n  - 02-market\n  - 01-opening\n", encoding="utf-8")

    inventory = inventory_presentation(thesis)

    assert inventory.order_source == "config.slide_order"
    assert plan_migration(inventory).manifest["checkpoint_order"] == ["slide-02-market", "slide-01-opening"]


@pytest.mark.parametrize("config", ["slide_order: [", "slide_order: first", "slide_order: [1, 2]", "slide_order: 0", "slide_order: false", "- timing"])
def test_numbered_order_cannot_bypass_an_unreadable_config(tmp_path: Path, config: str) -> None:
    thesis = legacy_deck(tmp_path)
    (thesis / "outputs" / "presentation" / "config.yaml").write_text(config, encoding="utf-8")

    inventory = inventory_presentation(thesis)

    assert inventory.order_source == "unresolved"
    assert "PRES_MIGRATION_ORDER_UNREADABLE" in {item.code for item in inventory.blockers}


@pytest.mark.parametrize("format,extension,media_type", [("JPEG", "png", "image/jpeg"), ("PNG", "jpg", "image/png")])
def test_legacy_raster_type_comes_from_bytes_without_rewriting_images(
    tmp_path: Path, format: str, extension: str, media_type: str
) -> None:
    from io import BytesIO
    from PIL import Image

    thesis = legacy_deck(tmp_path)
    slide = thesis / "outputs" / "presentation" / "slides" / "01-opening"
    image = BytesIO()
    Image.new("RGB", (8, 4), (10, 20, 30)).save(image, format=format)
    output = slide / "images" / "main" / "outputs" / f"selected.{extension}"
    output.write_bytes(image.getvalue())
    slide.joinpath("slide.md").write_text(
        slide.joinpath("slide.md").read_text().replace("outputs/one.png", f"outputs/selected.{extension}"),
        encoding="utf-8",
    )
    inventory = inventory_presentation(thesis)
    plan = plan_migration(inventory)
    record = next(item for item in plan.manifest["assets"] if item["id"] == asset_id_for("01-opening", "main", output.name))

    assert record["media_type"] == media_type
    assert record["provenance"]["source_ref"].endswith(f"/selected.{extension}")
    assert output.read_bytes() == image.getvalue()
    receipt = promote(inventory, tmp_path / "promoted")
    assert len(receipt.asset_ids) == 5


def test_a_tree_without_a_verifiable_receipt_is_not_migrated(tmp_path: Path) -> None:
    """A bare marker directory is not proof that authority moved."""

    thesis = legacy_deck(tmp_path)
    (thesis / MIGRATION_MARKER).mkdir(parents=True)

    assert is_migrated(thesis) is False

    promote(inventory_presentation(thesis), thesis / MIGRATION_MARKER)

    assert is_migrated(thesis) is True


def test_inventory_records_legacy_flags_as_observations(tmp_path: Path) -> None:
    inventory = inventory_presentation(legacy_deck(tmp_path))
    record = inventory.as_dict()["slides"][0]

    assert record["observed_layout"] == "image"
    assert record["bundles"][0]["observed_is_primary"] is True
    assert record["bundles"][0]["observed_selected"] == "outputs/one.png"
    # The observation is carried; it never becomes a target member.
    assert "is_primary" not in str(plan_migration(inventory).manifest)


def test_inventory_digest_is_stable_and_path_free(tmp_path: Path) -> None:
    thesis = legacy_deck(tmp_path)
    first = inventory_presentation(thesis)
    second = inventory_presentation(thesis)
    assert first.digest == second.digest
    assert str(thesis) not in str(first.as_dict()["slides"])


# --- ambiguity is blocking ------------------------------------------------


def test_a_bundle_with_candidates_and_no_selection_blocks(tmp_path: Path) -> None:
    inventory = inventory_presentation(legacy_deck(tmp_path, selected=None))
    assert "PRES_MIGRATION_SELECTION_ABSENT" in {item.code for item in inventory.blockers}
    with pytest.raises(WorkspaceError) as error:
        plan_migration(inventory)
    assert error.value.code == "PRES_MIGRATION_BLOCKED"


def test_a_selection_naming_no_candidate_blocks(tmp_path: Path) -> None:
    inventory = inventory_presentation(legacy_deck(tmp_path, selected="outputs/absent.png"))
    assert "PRES_MIGRATION_SELECTION_MISSING" in {item.code for item in inventory.blockers}


def test_an_html_slide_with_no_source_blocks(tmp_path: Path) -> None:
    inventory = inventory_presentation(legacy_deck(tmp_path, layout="html"))
    assert "PRES_MIGRATION_HTML_MISSING" in {item.code for item in inventory.blockers}


def test_legacy_script_is_blocked_rather_than_reduced(tmp_path: Path) -> None:
    inventory = inventory_presentation(
        legacy_deck(tmp_path, layout="html", html="<div onclick=\"go()\"><script>go()</script></div>")
    )
    codes = {item.code for item in inventory.blockers}
    # Reducing this to a reveal/hide state would silently lose behaviour.
    assert "PRES_MIGRATION_HTML_UNSAFE" in codes


def stock_html() -> str:
    return render_stock_choreography(
        STOCK_CHOREOGRAPHY_DOCUMENT,
        steps=3,
        motion={"0": "translateX(0px)", "2": "translateX(20px)"},
    )


def test_stock_choreography_producer_has_a_stable_legacy_contract() -> None:
    assert LEGACY_STOCK_CHOREOGRAPHY_VERSION == 1
    assert hashlib.sha256(stock_html().encode()).hexdigest() == "deaab00b4da9b273d7eede351e9a2d1168ddaa39203dbbafe0f8bb8fe54f622a"


def stock_script() -> str:
    _, marker, script = stock_html().partition("<script>")
    assert marker
    return script.removesuffix("</script>")


def test_stock_choreography_becomes_native_step_checkpoints(tmp_path: Path) -> None:
    inventory = inventory_presentation(legacy_deck(tmp_path, layout="html", html=stock_html()))

    assert {item.code for item in inventory.blockers} == set()
    plan = plan_migration(inventory)
    assert len(plan.manifest["checkpoint_order"]) == 6
    checkpoints = plan.manifest["checkpoints"]
    assert {tuple(item["modules"]) for item in checkpoints} == {("stock-choreography.js",)}
    assert sum(key.endswith("/stock-choreography.js") for key in plan.sources) == 1
    assert all(item["capabilities"] == [] for item in checkpoints)
    assert b'"steps":3' in plan.sources["checkpoints/legacy-stock/slide-01-opening-step-0.js"]
    assert b'"step":2' in plan.sources["checkpoints/legacy-stock/slide-01-opening-step-2.js"]



def test_the_decks_stylesheet_reaches_every_stock_step_as_one_shared_source(tmp_path: Path) -> None:
    """Without this the promoted deck renders unstyled: nothing else carries global.css."""

    sheet = ".plate { transform-origin: center; }\n"
    inventory = inventory_presentation(legacy_deck(tmp_path, layout="html", html=stock_html(), styles=sheet))

    plan = plan_migration(inventory)

    assert plan.sources["checkpoints/legacy-stock/global.css"] == sheet.encode("utf-8")
    assert {item["styles"] for item in plan.manifest["checkpoints"]} == {"global.css"}
    assert sum(key.endswith("/global.css") for key in plan.sources) == 1, "one stylesheet, edited once for the deck"


def test_editing_the_decks_stylesheet_changes_what_promotion_would_publish(tmp_path: Path) -> None:
    """The stylesheet is inventoried, so an unchanged-inventory promotion cannot skip it."""

    first = inventory_presentation(legacy_deck(tmp_path, layout="html", html=stock_html(), styles="a{}")).digest
    second = inventory_presentation(legacy_deck(tmp_path / "next", layout="html", html=stock_html(), styles="b{}")).digest

    assert first != second


# --- the producer real decks actually contain ----------------------------


BUILDER_MOTION = {0: "scale(1.0)", 1: "scale(1.05) translate(-1.5%, -1%)", 2: "scale(1.08)"}


def builder_html() -> str:
    return render_builder_choreography(STOCK_CHOREOGRAPHY_DOCUMENT, steps=3, motion=BUILDER_MOTION)


def test_builder_choreography_producer_has_a_stable_legacy_contract() -> None:
    assert LEGACY_BUILDER_CHOREOGRAPHY_VERSION == 1
    assert hashlib.sha256(builder_html().encode()).hexdigest() == "06ac52855568527da3006c294276e85388399ef7325f4022c4ea6e7a1e068220"


def test_the_builder_script_is_recognized_and_replayed_as_itself(tmp_path: Path) -> None:
    """Refusing this script refused every real deck: no deck contains the other one."""

    inventory = inventory_presentation(legacy_deck(tmp_path, layout="html", html=builder_html()))
    assert {item.code for item in inventory.blockers} == set()

    plan = plan_migration(inventory)

    assert len(plan.manifest["checkpoint_order"]) == 6
    program = plan.sources["checkpoints/legacy-stock/slide-01-opening-step-0.js"].decode("utf-8")
    # The two producers implement different choreography, so a promoted step
    # has to say which one it is replaying rather than assume a house style.
    assert '"variant":"builder"' in program
    assert '"motion":{"0":"scale(1.0)","1":"scale(1.05) translate(-1.5%, -1%)","2":"scale(1.08)"}' in program


def test_a_motion_value_holding_the_entry_separator_survives_the_round_trip() -> None:
    """`translate(-1.5%, -1%)` contains `", "`; splitting on it would tear the value."""

    recognized = migration._builder_choreography(builder_html())

    assert recognized is not None
    assert recognized.motion["1"] == "scale(1.05) translate(-1.5%, -1%)"


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda html: html.replace("applyStep(0);", "fetch('/probe');\napplyStep(0);"), id="added-call"),
        pytest.param(lambda html: html.replace("[data-enter]", "[data-arrive]"), id="changed-selector"),
        pytest.param(lambda html: html.replace('0: "scale(1.0)"', "0: 'scale(1.0)'"), id="requoted-motion"),
        pytest.param(lambda html: html.replace('1: "scale(1.05)', '0: "scale(1.05)'), id="duplicate-motion-key"),
    ],
)
def test_a_builder_near_miss_is_refused(tmp_path: Path, mutate: Callable[[str], str]) -> None:
    inventory = inventory_presentation(legacy_deck(tmp_path, layout="html", html=mutate(builder_html())))

    assert "PRES_MIGRATION_HTML_UNSAFE" in {item.code for item in inventory.blockers}


def test_every_step_of_a_slide_shares_one_document_and_one_notes_file(tmp_path: Path) -> None:
    """Per-step copies let an edit to one step silently leave the rest of the slide behind."""

    plan = plan_migration(inventory_presentation(legacy_deck(tmp_path, layout="html", html=stock_html())))

    steps = [item for item in plan.manifest["checkpoints"] if item["id"].startswith("slide-01-opening")]
    assert len(steps) == 3
    assert {item["document"] for item in steps} == {"slide-01-opening.html"}
    assert {item["notes"] for item in steps} == {"slide-01-opening.md"}
    assert sum(key.endswith(".md") for key in plan.sources) == 2, "one notes file per slide, not per step"


def stock_html_with_slot(slot: str) -> str:
    """The legacy shape exactly: an addressed image and no `src` to load."""

    return render_stock_choreography(
        f'{STOCK_CHOREOGRAPHY_DOCUMENT}<img class="plate" data-image-id="{slot}" alt="" />',
        steps=1,
        motion={},
    )


def test_a_stock_slide_binds_its_image_slot_to_the_selected_candidate(tmp_path: Path) -> None:
    """Legacy markup carries no src, so without this every promoted slide renders blank."""

    inventory = inventory_presentation(legacy_deck(tmp_path, layout="html", html=stock_html_with_slot("main")))
    assert {item.code for item in inventory.blockers} == set()

    plan = plan_migration(inventory)

    selected = asset_id_for("01-opening", "main", "one.png")
    program = plan.sources["checkpoints/legacy-stock/slide-01-opening.js"].decode("utf-8")
    assert f'"slots":{{"main":"{selected}"}}' in program
    assert selected in plan.manifest["checkpoints"][0]["assets"]


def test_a_slot_that_no_selection_fills_blocks_the_deck(tmp_path: Path) -> None:
    """A silently blank image looks migrated and is not, so it is refused instead."""

    inventory = inventory_presentation(legacy_deck(tmp_path, layout="html", html=stock_html_with_slot("ghost")))

    assert [item.code for item in inventory.blockers] == ["PRES_MIGRATION_SLOT_UNBOUND"] * 2


def test_a_deck_with_no_stylesheet_still_promotes(tmp_path: Path) -> None:
    plan = plan_migration(inventory_presentation(legacy_deck(tmp_path, layout="html", html=stock_html())))

    assert plan.sources["checkpoints/legacy-stock/global.css"] == b""


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda script: script + "\nconsole.log('extra');", id="added-statement"),
        pytest.param(lambda script: script.replace("[data-enter]", "[data-arrive]"), id="changed-selector"),
        pytest.param(lambda script: script.replace("applyStep(0);", "fetch('/probe');\napplyStep(0);"), id="fetch-call"),
    ],
)
def test_stock_choreography_near_miss_is_refused(tmp_path: Path, mutate: Callable[[str], str]) -> None:
    script = mutate(stock_script())
    html = f'<main><div data-enter="1"></div></main><script>{script}</script>'

    inventory = inventory_presentation(legacy_deck(tmp_path, layout="html", html=html))

    assert "PRES_MIGRATION_HTML_UNSAFE" in {item.code for item in inventory.blockers}


@pytest.mark.parametrize(
    "motion_literal",
    [
        pytest.param('{"0":"translateX(0px)","0":"translateX(20px)"}', id="conflicting-values"),
        pytest.param('{"0":"translateX(0px)","0":"translateX(0px)"}', id="identical-values"),
    ],
)
def test_stock_choreography_duplicate_motion_keys_are_refused(tmp_path: Path, motion_literal: str) -> None:
    script = stock_script().replace(
        'var MOTION = {"0":"translateX(0px)","2":"translateX(20px)"};', f"var MOTION = {motion_literal};"
    )
    html = f"{STOCK_CHOREOGRAPHY_DOCUMENT}<script>{script}</script>"
    assert motion_literal in html

    inventory = inventory_presentation(legacy_deck(tmp_path, layout="html", html=html))

    assert "PRES_MIGRATION_HTML_UNSAFE" in {item.code for item in inventory.blockers}


@pytest.mark.parametrize("tag", ["SCRIPT", "ScRiPt"])
def test_stock_choreography_noncanonical_script_tag_case_is_refused(tmp_path: Path, tag: str) -> None:
    html = stock_html().replace("<script>", f"<{tag}>").replace("</script>", f"</{tag}>")

    inventory = inventory_presentation(legacy_deck(tmp_path, layout="html", html=html))

    assert "PRES_MIGRATION_HTML_UNSAFE" in {item.code for item in inventory.blockers}


@pytest.mark.parametrize(
    "motion_literal",
    [
        # No literal `</script>` byte, so the element is not truncated: the
        # breakout only appears once the recognizer decodes the escapes.
        pytest.param('{"0":"\\u003c/script\\u003e\\u003cscript src=data:text/javascript,alert(1)\\u003e"}', id="escaped-script-breakout"),
        pytest.param('{"0": "translateX(0px)"}', id="separator-whitespace"),
        pytest.param('{"0":"caf\u00e9"}', id="raw-non-ascii"),
    ],
)
def test_stock_choreography_noncanonical_motion_literal_is_refused(tmp_path: Path, motion_literal: str) -> None:
    html = stock_html().replace('var MOTION = {"0":"translateX(0px)","2":"translateX(20px)"};', f"var MOTION = {motion_literal};")
    assert motion_literal in html
    assert "</script>" not in html.split("<script>", 1)[1].rsplit("</script>", 1)[0]

    inventory = inventory_presentation(legacy_deck(tmp_path, layout="html", html=html))

    assert "PRES_MIGRATION_HTML_UNSAFE" in {item.code for item in inventory.blockers}


def test_stock_choreography_with_remote_script_is_refused(tmp_path: Path) -> None:
    html = stock_html() + '<script src="https://example.invalid/extra.js"></script>'

    inventory = inventory_presentation(legacy_deck(tmp_path, layout="html", html=html))

    assert "PRES_MIGRATION_HTML_UNSAFE" in {item.code for item in inventory.blockers}


def test_stock_choreography_promotes_and_exports_deterministically(tmp_path: Path) -> None:
    from doxagon.presentations import PresentationWorkspace, build_deck_payload, export_offline_html

    target = tmp_path / "target"
    promote(inventory_presentation(legacy_deck(tmp_path, layout="html", html=stock_html())), target)
    workspace = PresentationWorkspace.open(target / "store")
    payload = build_deck_payload(workspace.store).as_dict()

    assert payload["checkpoints"][0]["modules"][0]["path"] == "stock-choreography.js"
    assert payload["checkpoints"][0]["modules"][0]["source"] == payload["checkpoints"][3]["modules"][0]["source"]
    assert export_offline_html(workspace.store).artifact == export_offline_html(workspace.store).artifact


def test_stock_choreography_absolute_seek_and_back_restore_dom(tmp_path: Path) -> None:
    from playwright.sync_api import sync_playwright

    from doxagon.presentations import PresentationWorkspace, export_offline_html
    from tests.synthetic_vault import write_stock_presentation

    thesis = write_stock_presentation(tmp_path)
    target = tmp_path / "target"
    promote(inventory_presentation(thesis), target)
    workspace = PresentationWorkspace.open(target / "store")
    document = export_offline_html(workspace.store).artifact.decode("utf-8")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(document, wait_until="load")
        page.wait_for_function("document.documentElement.dataset.doxagonReady === 'true'", timeout=15_000)

        def seek(checkpoint_id: str) -> dict[str, str]:
            page.evaluate("id => window.doxagonDeck.seek(id)", checkpoint_id)
            return page.frames[1].locator("#doxagon-checkpoint-root").evaluate(
                "root => ({html: root.innerHTML, step: root.dataset.step, steps: root.dataset.steps})"
            )

        direct_one = seek("slide-opening-step-1")
        direct_two = seek("slide-opening-step-2")
        seek("slide-opening-step-0")
        page.evaluate("window.doxagonDeck.dispatch({type: 'NEXT'})")
        page.evaluate("window.doxagonDeck.dispatch({type: 'NEXT'})")
        forward_two = page.frames[1].locator("#doxagon-checkpoint-root").evaluate(
            "root => ({html: root.innerHTML, step: root.dataset.step, steps: root.dataset.steps})"
        )
        page.evaluate("window.doxagonDeck.dispatch({type: 'PREVIOUS'})")
        back_one = page.frames[1].locator("#doxagon-checkpoint-root").evaluate(
            "root => ({html: root.innerHTML, step: root.dataset.step, steps: root.dataset.steps})"
        )
        browser.close()

    assert forward_two == direct_two
    assert back_one == direct_one


def test_builder_choreography_replays_the_transform_the_legacy_deck_held(tmp_path: Path) -> None:
    """The migrated module must reproduce the producer, not a reading of it.

    The builder assigns a transform only on a step its motion map names, so a
    legacy deck stepped from 0 carries the last named one forward. Every
    migrated step is its own realm with a cold DOM, so a single `applyStep`
    call cannot inherit anything: what the legacy deck held has to be folded
    back for. This drives the real producer in the same browser and compares.
    """

    from playwright.sync_api import sync_playwright

    from doxagon.presentations import PresentationWorkspace, export_offline_html
    from doxagon.presentations.legacy_stock import render_builder_choreography
    from tests.synthetic_vault import (
        BUILDER_MOTION,
        BUILDER_STEPS,
        STOCK_CHOREOGRAPHY_DOCUMENT,
        write_builder_presentation,
    )

    thesis = write_builder_presentation(tmp_path)
    target = tmp_path / "target"
    promote(inventory_presentation(thesis), target)
    workspace = PresentationWorkspace.open(target / "store")
    document = export_offline_html(workspace.store).artifact.decode("utf-8")
    legacy = render_builder_choreography(
        STOCK_CHOREOGRAPHY_DOCUMENT, steps=BUILDER_STEPS, motion=BUILDER_MOTION
    )
    # The producer registers its steps through the legacy slide API and only
    # ever calls them in order, which is the behaviour being reproduced.
    shim = "<script>window.dox={slide:{_s:[],steps(){},onStep(n,fn){this._s[n]=fn;}}};</script>"

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(shim + legacy, wait_until="load")
        expected = page.evaluate(
            """steps => {
                const out = [];
                for (let n = 0; n < steps; n += 1) {
                    dox.slide._s[n]();
                    out.push(document.querySelector('.plate').style.transform);
                }
                return out;
            }""",
            BUILDER_STEPS,
        )

        page.set_content(document, wait_until="load")
        page.wait_for_function("document.documentElement.dataset.doxagonReady === 'true'", timeout=15_000)
        replayed = []
        for step in range(BUILDER_STEPS):
            page.evaluate("id => window.doxagonDeck.seek(id)", f"slide-held-step-{step}")
            replayed.append(
                page.frames[1]
                .locator("#doxagon-checkpoint-root .plate")
                .evaluate("plate => plate.style.transform")
            )
        browser.close()

    assert expected == ["scale(1)", "scale(1)", "scale(1.2)", "scale(1.2)"]
    assert replayed == expected


def test_a_deck_inventory_reports_clean_is_a_deck_that_promotes(tmp_path: Path) -> None:
    """Zero blockers is the whole promise inventory makes to an operator.

    A long slug plus a step suffix used to compose a checkpoint id past the 64
    characters `_ID` admits, so a deck the inventory called clean failed at
    validation with a pointer into `checkpoint_order` and no mention of the
    slide directory that caused it.
    """

    slug = "a" * 56
    thesis = tmp_path / "long"
    outputs = thesis / "outputs" / "presentation"
    (outputs / "slides" / slug).mkdir(parents=True)
    thesis.joinpath("config.yaml").write_text("name: Long\ntitle: Long\n", encoding="utf-8")
    outputs.joinpath("config.yaml").write_text(f"slide_order:\n  - {slug}\n", encoding="utf-8")
    outputs.joinpath("slides", slug, "slide.md").write_text(
        "---\ntext:\n  title: Long\nlayout: html\n---\n", encoding="utf-8"
    )
    outputs.joinpath("slides", slug, "slide.html").write_text(
        render_builder_choreography(STOCK_CHOREOGRAPHY_DOCUMENT, steps=3, motion=BUILDER_MOTION),
        encoding="utf-8",
    )

    inventory = inventory_presentation(thesis)
    assert inventory.blockers == ()

    promote(inventory, tmp_path / "target")


def test_an_unsafe_deck_stylesheet_blocks_at_its_own_path(tmp_path: Path) -> None:
    """Promotion copies global.css onto every checkpoint, so judge it first."""

    thesis = legacy_deck(tmp_path)
    styles = thesis / "outputs" / "presentation" / "styles" / "html"
    styles.mkdir(parents=True, exist_ok=True)
    styles.joinpath("global.css").write_text(
        "@import url(https://evil.example/x.css);\nbody { color: red }\n", encoding="utf-8"
    )

    blockers = inventory_presentation(thesis).blockers

    assert {item.code for item in blockers} == {"PRES_STYLES_UNSAFE"}
    assert {item.path for item in blockers} == {"outputs/presentation/styles/html/global.css"}


def test_a_symlinked_deck_stylesheet_reads_as_absent(tmp_path: Path) -> None:
    """Inventory runs on a tree a vault author controls, inside a request."""

    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET-KEY\n", encoding="utf-8")
    thesis = legacy_deck(tmp_path)
    styles = thesis / "outputs" / "presentation" / "styles" / "html"
    styles.mkdir(parents=True, exist_ok=True)
    styles.joinpath("global.css").symlink_to(secret)

    assert inventory_presentation(thesis).styles is None


def test_an_unquoted_image_slot_blocks_before_it_can_black_out_a_slide(tmp_path: Path) -> None:
    """HTML permits an unquoted attribute value; the slot gate has to see one."""

    from tests.synthetic_vault import write_stock_presentation

    thesis = write_stock_presentation(tmp_path)
    slide = thesis / "outputs" / "presentation" / "slides" / "01-opening" / "slide.html"
    slide.write_text(
        slide.read_text(encoding="utf-8").replace("<main>", "<main><img data-image-id=missing>"),
        encoding="utf-8",
    )

    blockers = inventory_presentation(thesis).blockers

    assert "PRES_MIGRATION_SLOT_UNBOUND" in {item.code for item in blockers}


def test_a_missing_ordered_slide_blocks(tmp_path: Path) -> None:
    thesis = legacy_deck(tmp_path)
    (thesis / "outputs" / "presentation" / "slides" / "02-market" / "slide.md").unlink()
    inventory = inventory_presentation(thesis)
    assert "PRES_MIGRATION_SLIDE_MISSING" in {item.code for item in inventory.blockers}


def test_a_slide_directory_the_declared_order_omits_is_inventoried_and_blocks(tmp_path: Path) -> None:
    """A configured order is not the census of what the legacy tree holds.

    The legacy list path enumerates slide directories (`count_slides` in
    `apps/web/backend/routers/theses.py`), so a slide `config.yaml` never names
    is still legacy authorship a reader can see. Iterating only `slide_order`
    made that slide and every one of its candidates disappear silently.
    """

    thesis = legacy_deck(tmp_path)
    slides = thesis / "outputs" / "presentation" / "slides"
    stray = slides / "03-appendix"
    outputs = stray / "images" / "main" / "outputs"
    outputs.mkdir(parents=True)
    outputs.joinpath("only.png").write_bytes(png((7, 7, 7)))
    stray.joinpath("slide.md").write_text(
        "---\ntext:\n  title: Appendix\n  body: Body.\nimages:\n  - id: main\n    selected: outputs/only.png\n---\n",
        encoding="utf-8",
    )

    inventory = inventory_presentation(thesis)

    assert "PRES_MIGRATION_SLIDE_UNORDERED" in {item.code for item in inventory.blockers}
    # Nothing disappeared: the omitted slide and its candidate are both here.
    assert [slide.slug for slide in inventory.slides] == ["01-opening", "02-market", "03-appendix"]
    assert inventory.candidate_count == 5
    with pytest.raises(WorkspaceError) as error:
        plan_migration(inventory)
    assert error.value.code == "PRES_MIGRATION_BLOCKED"


def test_a_numbered_directory_resolves_the_declared_slug_the_producer_resolves(tmp_path: Path) -> None:
    """`resolve_slide_dir` accepts `NN-slug` for a declared `slug`; so must this."""

    thesis = legacy_deck(tmp_path)
    presentation = thesis / "outputs" / "presentation"
    presentation.joinpath("config.yaml").write_text(
        "slide_order:\n  - opening\n  - market\n", encoding="utf-8"
    )

    inventory = inventory_presentation(thesis)

    assert {item.code for item in inventory.blockers} == set()
    assert [(slide.slug, slide.directory) for slide in inventory.slides] == [
        ("opening", "01-opening"),
        ("market", "02-market"),
    ]
    # Promotion reads the directory the producer serves, not the declared slug.
    assert len(plan_migration(inventory).manifest["assets"]) == inventory.candidate_count


@pytest.mark.parametrize(
    "selected",
    [
        pytest.param("one.png", id="bare-basename"),
        pytest.param("../../elsewhere/outputs/one.png", id="traversal"),
        pytest.param("/etc/outputs/one.png", id="absolute"),
        pytest.param("other/outputs/one.png", id="foreign-bundle-relative-path"),
    ],
)
def test_a_selection_that_is_not_the_exact_contained_path_selects_nothing(tmp_path: Path, selected: str) -> None:
    """The legacy producer resolves `selected` as `img_dir / selected`.

    Reducing it to `Path(selected).name` let a wrong or traversing value match
    `outputs/<basename>` and be recorded as legacy authorship. Only the exact
    contained bundle-relative path selects; everything else blocks.
    """

    inventory = inventory_presentation(legacy_deck(tmp_path, selected=selected))

    assert not any(
        candidate.selected
        for slide in inventory.slides
        for bundle in slide.bundles
        for candidate in bundle.candidates
    )
    codes = {item.code for item in inventory.blockers}
    assert codes & {"PRES_MIGRATION_SELECTION_MISSING", "PRES_MIGRATION_SELECTION_UNCONTAINED"}
    with pytest.raises(WorkspaceError) as error:
        plan_migration(inventory)
    assert error.value.code == "PRES_MIGRATION_BLOCKED"


# --- promotion ------------------------------------------------------------


def test_promotion_preserves_every_candidate_with_provenance(tmp_path: Path) -> None:
    inventory = inventory_presentation(legacy_deck(tmp_path, extra_candidates=2))
    receipt = promote(inventory, tmp_path / "target")

    assert len(receipt.asset_ids) == inventory.candidate_count
    assert receipt.candidate_count == 6
    from doxagon.presentations import PresentationWorkspace

    workspace = PresentationWorkspace.open(tmp_path / "target" / "store")
    manifest = workspace.store.read_manifest()
    assert {str(item["provenance"]["kind"]) for item in manifest["assets"]} == {"imported"}
    assert all(item["provenance"]["source_ref"] for item in manifest["assets"])
    # Unselected candidates survive as records referenced by no checkpoint.
    referenced = {asset for item in manifest["checkpoints"] for asset in item["assets"]}
    assert len(referenced) == 2 and len(manifest["assets"]) == 6


def test_promotion_produces_checkpoints_and_non_authoritative_groups(tmp_path: Path) -> None:
    receipt = promote(inventory_presentation(legacy_deck(tmp_path)), tmp_path / "target")
    assert receipt.checkpoint_ids == (checkpoint_id_for("01-opening"), checkpoint_id_for("02-market"))

    from doxagon.presentations import PresentationWorkspace

    manifest = PresentationWorkspace.open(tmp_path / "target" / "store").store.read_manifest()
    assert manifest["checkpoint_order"] == list(receipt.checkpoint_ids)
    for group in manifest["groups"]:
        assert set(group) <= {"id", "kind", "label", "checkpoints", "export_boundary"}


def test_promotion_is_idempotent_and_signs_its_receipt(tmp_path: Path) -> None:
    thesis = legacy_deck(tmp_path)
    first = promote(inventory_presentation(thesis), tmp_path / "target")
    # A second run against an unchanged legacy tree re-reads it and lands on
    # the receipt that already exists rather than promoting twice.
    second = promote(inventory_presentation(thesis), tmp_path / "target")

    assert first.as_dict() == second.as_dict()
    assert verify_migration_receipt(first.as_dict())
    tampered = {**first.as_dict(), "candidate_count": 99}
    assert not verify_migration_receipt(tampered)


def test_a_blocked_inventory_leaves_the_target_untouched(tmp_path: Path) -> None:
    inventory = inventory_presentation(legacy_deck(tmp_path, selected=None))
    target = tmp_path / "target"
    with pytest.raises(WorkspaceError):
        promote(inventory, target)
    assert not target.exists()
    assert not list(tmp_path.glob(".shadow-*"))
    assert not list(tmp_path.glob(".pending-*"))


# --- promotion is atomic, compensated, and retryable ----------------------


def _fail_on_receipt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inject exactly the failure the audit found: the receipt write dies.

    Everything else — planning, shadow validation, the target store — is left
    alone, so the injected fault is the durable-completion step and nothing
    else.
    """

    real = migration.write_json

    def failing(path: Path, payload: object) -> None:
        if path.name == MIGRATION_RECEIPT_KEY:
            raise OSError("injected receipt-write failure")
        real(path, payload)

    monkeypatch.setattr(migration, "write_json", failing)


def test_a_failed_receipt_write_leaves_no_authoritative_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A promotion that cannot record itself must not look promoted.

    The target store used to be created before the receipt, so this failure
    left a store `is_migrated` could not vouch for and `promote` could never
    re-create: the retry below failed PRES_WORKSPACE_EXISTS forever.
    """

    thesis = legacy_deck(tmp_path)
    target = thesis / MIGRATION_MARKER
    _fail_on_receipt(monkeypatch)

    with pytest.raises(OSError):
        promote(inventory_presentation(thesis), target)

    assert not target.exists(), "a failed promotion leaves no target at all"
    assert is_migrated(thesis) is False
    assert not list(thesis.glob(".shadow-*")) and not list(thesis.glob(".pending-*"))


def test_a_retry_after_a_failed_receipt_write_completes_exactly_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    thesis = legacy_deck(tmp_path)
    target = thesis / MIGRATION_MARKER
    _fail_on_receipt(monkeypatch)
    with pytest.raises(OSError):
        promote(inventory_presentation(thesis), target)

    monkeypatch.undo()
    receipt = promote(inventory_presentation(thesis), target)

    from doxagon.presentations import PresentationWorkspace

    store = PresentationWorkspace.open(target / "store").store
    promoted = sorted(path.name for path in (store.root / "revisions").iterdir())
    assert verify_migration_receipt(receipt.as_dict()) and is_migrated(thesis) is True
    assert store.revision == receipt.revision
    # Exactly once: the retry promoted one revision, not a second copy beside
    # whatever the failed attempt had already landed.
    assert promoted == [receipt.revision.split(":", 1)[1]]
    assert not list(thesis.glob(".shadow-*")) and not list(thesis.glob(".pending-*"))


def test_a_published_target_always_carries_its_receipt(tmp_path: Path) -> None:
    target = tmp_path / "target"
    receipt = promote(inventory_presentation(legacy_deck(tmp_path)), target)

    stored = json.loads((target / MIGRATION_RECEIPT_KEY).read_bytes())
    assert stored == receipt.as_dict() and (target / "store").is_dir()


def test_a_cleanup_failure_neither_masks_nor_undoes_a_durable_promotion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sweeping the staging tree is not part of the promotion contract."""

    thesis = legacy_deck(tmp_path)
    target = thesis / MIGRATION_MARKER
    calls: list[Path] = []

    class _FailingShutil:
        """Only the migration module's own cleanup fails; nothing else does."""

        @staticmethod
        def rmtree(path: Path, *args: object, **kwargs: object) -> None:
            calls.append(Path(path))
            raise OSError("injected cleanup failure")

    monkeypatch.setattr(migration, "shutil", _FailingShutil)
    receipt = promote(inventory_presentation(thesis), target)

    assert is_migrated(thesis) is True and verify_migration_receipt(receipt.as_dict())
    # The residue the failed sweep left is inert, and the next run reads the
    # receipt rather than the residue.
    assert calls and list(thesis.glob(".shadow-*"))
    monkeypatch.undo()
    assert promote(inventory_presentation(thesis), target).as_dict() == receipt.as_dict()


def test_an_idempotent_replay_re_promotes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    thesis = legacy_deck(tmp_path)
    target = thesis / MIGRATION_MARKER
    first = promote(inventory_presentation(thesis), target)

    def refuse(_: object) -> None:
        raise AssertionError("a replay must not re-plan or re-promote")

    monkeypatch.setattr(migration, "plan_migration", refuse)
    replayed = promote(inventory_presentation(thesis), target)

    assert replayed.as_dict() == first.as_dict()


def test_a_target_holding_foreign_content_is_refused_rather_than_replaced(tmp_path: Path) -> None:
    thesis = legacy_deck(tmp_path)
    target = thesis / MIGRATION_MARKER
    target.mkdir(parents=True)
    target.joinpath("someone-elses.json").write_text("{}", encoding="utf-8")

    with pytest.raises(WorkspaceError) as refused:
        promote(inventory_presentation(thesis), target)

    assert refused.value.code == "PRES_MIGRATION_TARGET_OCCUPIED"
    assert target.joinpath("someone-elses.json").is_file()
    assert is_migrated(thesis) is False
    assert not list(thesis.glob(".pending-*"))


def test_the_promoted_deck_carries_no_legacy_vocabulary(tmp_path: Path) -> None:
    promote(inventory_presentation(legacy_deck(tmp_path)), tmp_path / "target")

    from doxagon.presentations import PresentationWorkspace

    manifest = str(PresentationWorkspace.open(tmp_path / "target" / "store").store.read_manifest())
    for retired in ("is_primary", "selected", "layout", "slide_index", "thumbnail"):
        assert retired not in manifest


# --- compatibility window and census -------------------------------------


def test_the_compatibility_adapter_reads_and_refuses_every_write(tmp_path: Path) -> None:
    adapter = LegacyReadAdapter(legacy_deck(tmp_path))
    assert adapter.read()["slides"]
    with pytest.raises(WorkspaceError) as error:
        adapter.write({"layout": "html"})
    assert error.value.code == "PRES_LEGACY_READ_ONLY"


def test_census_counts_migrated_and_blocked_decks(tmp_path: Path) -> None:
    theses = tmp_path / "theses"
    theses.mkdir()
    legacy_deck(theses)
    census = retirement_census(theses)

    assert census["deck_count"] == 1
    assert census["unmigrated_count"] == 1
    assert census["decks"][0]["observed_layouts"] == ["image"]

    promote(inventory_presentation(theses / "alpha"), theses / "alpha" / MIGRATION_MARKER)
    after = retirement_census(theses)
    assert after["migrated_count"] == 1 and after["unmigrated_count"] == 0


def test_census_is_reproducible(tmp_path: Path) -> None:
    theses = tmp_path / "theses"
    theses.mkdir()
    legacy_deck(theses)
    assert retirement_census(theses) == retirement_census(theses)
