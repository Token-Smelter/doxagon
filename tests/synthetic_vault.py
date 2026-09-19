"""Build a synthetic legacy vault from public bytes.

Every byte here is generated in the caller's temporary directory. Nothing reads
a real vault, a thesis directory, or any configured content root, so a proof
built on this helper never inspects private content.

The shape is exactly what the legacy producers expose — `config.yaml` slide
order, `slides/<slug>/slide.md` frontmatter with `images[]`, `is_primary`, and
`selected`, and candidate files under `images/<bundle>/outputs/` — because the
migrator reads that shape and a fixture that drifted from it would prove
nothing about the real system.
"""

from __future__ import annotations

from pathlib import Path
import struct
import zlib

from doxagon.presentations.legacy_stock import render_builder_choreography, render_stock_choreography


def png(colour: tuple[int, int, int], width: int = 8, height: int = 4) -> bytes:
    """A minimal valid PNG; the asset reader matches bytes against media type."""

    raw = b"".join(b"\x00" + bytes(colour) * width for _ in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


SLIDES = (("01-opening", "Opening"), ("02-market", "Market"))
STOCK_CHOREOGRAPHY_DOCUMENT = (
    '<main><div id="enter" data-enter="1" class="off">Enter</div>'
    '<div id="exit" data-exit="2" class="on">Exit</div>'
    '<div id="plate" class="plate">Plate</div></main>'
)


def _thesis_config(presentation_dir: Path, title: str) -> None:
    """The project record `list_theses` reads to put a thesis in the rail."""

    presentation_dir.mkdir(parents=True, exist_ok=True)
    presentation_dir.joinpath("config.yaml").write_text(
        "\n".join([f"name: {title}", f"title: {title}", "diegesis: synthetic", "walk: canonical", ""]),
        encoding="utf-8",
    )


def write_legacy_presentation(vault_root: Path, slug: str = "alpha") -> Path:
    """One legacy presentation with two slides and two candidates per slide."""

    presentation_dir = vault_root / slug
    outputs_root = presentation_dir / "outputs" / "presentation"
    outputs_root.mkdir(parents=True, exist_ok=True)
    presentation_dir.joinpath("config.yaml").write_text(
        "\n".join(
            [
                f"name: {slug.title()}",
                f"title: {slug.title()} presentation",
                "diegesis: synthetic",
                "walk: canonical",
                "",
            ]
        ),
        encoding="utf-8",
    )
    outputs_root.joinpath("config.yaml").write_text(
        "slide_order:\n" + "".join(f"  - {slide}\n" for slide, _ in SLIDES),
        encoding="utf-8",
    )

    for index, (slide_slug, title) in enumerate(SLIDES):
        directory = outputs_root / "slides" / slide_slug
        candidates = directory / "images" / "main" / "outputs"
        candidates.mkdir(parents=True, exist_ok=True)
        candidates.joinpath("one.png").write_bytes(png((10 + index, 20, 30)))
        candidates.joinpath("two.png").write_bytes(png((90 + index, 40, 50)))
        # A derived display artifact; the migrator must never read it as authorship.
        candidates.joinpath(".thumb_one.jpg").write_bytes(b"\xff\xd8\xff\xdb thumbnail")
        directory.joinpath("slide.md").write_text(
            "\n".join(
                [
                    "---",
                    "text:",
                    f"  title: {title}",
                    "  body: |",
                    f"    First paragraph of {title}.",
                    "",
                    f"    Second paragraph of {title}.",
                    f"speaker_notes: Notes for {title}.",
                    "layout: image",
                    "images:",
                    "  - id: main",
                    f"    purpose: The {title} visual",
                    "    is_primary: true",
                    "    selected: outputs/one.png",
                    "doxai:",
                    "  - d-example",
                    "---",
                    "",
                ]
            ),
            encoding="utf-8",
        )
    return presentation_dir


def write_stock_presentation(vault_root: Path, slug: str = "stock") -> Path:
    """A public legacy HTML deck from the tracked stock choreography producer."""

    presentation_dir = vault_root / slug
    _thesis_config(presentation_dir, f"{slug.title()} presentation")
    outputs_root = presentation_dir / "outputs" / "presentation"
    outputs_root.mkdir(parents=True, exist_ok=True)
    outputs_root.joinpath("config.yaml").write_text(
        "slide_order:\n  - opening\n  - motion\n", encoding="utf-8"
    )
    for directory_name, title, steps, motion in (
        ("01-opening", "Opening choreography", 3, {"0": "translateX(0px)", "2": "translateX(20px)"}),
        ("02-motion", "Motion choreography", 2, {"0": "scale(1)", "1": "scale(1.2)"}),
    ):
        directory = outputs_root / "slides" / directory_name
        directory.mkdir(parents=True, exist_ok=True)
        directory.joinpath("slide.md").write_text(
            f"---\ntext:\n  title: {title}\nlayout: html\n---\n", encoding="utf-8"
        )
        directory.joinpath("slide.html").write_text(
            render_stock_choreography(STOCK_CHOREOGRAPHY_DOCUMENT, steps=steps, motion=motion), encoding="utf-8"
        )
    return presentation_dir


def write_numbered_presentation(vault_root: Path, slug: str = "numbered") -> Path:
    """A legacy deck whose complete folder sequence is its only slide order."""

    presentation = write_stock_presentation(vault_root, slug)
    root = presentation / "outputs" / "presentation"
    (root / "config.yaml").write_text("timing:\n  total: 25\n", encoding="utf-8")
    (root / "slides" / "01-opening").rename(root / "slides" / "00-opening")
    (root / "slides" / "02-motion").rename(root / "slides" / "01-motion")
    return presentation


#: The builder's motion map is deliberately non-total: step 1 names no motion,
#: so the legacy deck holds step 0's transform through it. That hold is the
#: whole difference between the two producers' motion handling.
BUILDER_MOTION = {0: "scale(1)", 2: "scale(1.2)"}
BUILDER_STEPS = 4


def write_builder_presentation(vault_root: Path, slug: str = "builder") -> Path:
    """A legacy HTML deck from the producer real vault decks actually contain."""

    presentation_dir = vault_root / slug
    _thesis_config(presentation_dir, f"{slug.title()} presentation")
    outputs_root = presentation_dir / "outputs" / "presentation"
    outputs_root.mkdir(parents=True, exist_ok=True)
    outputs_root.joinpath("config.yaml").write_text("slide_order:\n  - held\n", encoding="utf-8")
    directory = outputs_root / "slides" / "01-held"
    directory.mkdir(parents=True, exist_ok=True)
    directory.joinpath("slide.md").write_text(
        "---\ntext:\n  title: Held motion\nlayout: html\n---\n", encoding="utf-8"
    )
    directory.joinpath("slide.html").write_text(
        render_builder_choreography(
            STOCK_CHOREOGRAPHY_DOCUMENT, steps=BUILDER_STEPS, motion=BUILDER_MOTION
        ),
        encoding="utf-8",
    )
    return presentation_dir


def write_blocked_presentation(vault_root: Path, slug: str = "blocked") -> Path:
    """A legacy presentation the migrator must refuse, and say why.

    Every ambiguity here is one the real migrator raises by design, synthesised
    the same way `tests/test_presentations_migration.py` synthesises them:

    * ``01-intro`` offers two images and records no choice between them.
    * ``02-stray`` exists on disk but the declared order never names it, and it
      names a chosen image that is not one of the files it holds.
    * ``03-ghost`` is named in the declared order but has no directory.
    * ``04-html`` is unordered too, and its hand-written HTML runs script.

    The result is several diagnostics spread over several slides, which is what
    a field tree actually looks like and what a workspace has to render.
    """

    presentation_dir = vault_root / slug
    _thesis_config(presentation_dir, f"{slug.title()} presentation")
    outputs_root = presentation_dir / "outputs" / "presentation"
    outputs_root.mkdir(parents=True, exist_ok=True)
    # `03-ghost` has no directory: the order names a slide that is not there.
    outputs_root.joinpath("config.yaml").write_text(
        "slide_order:\n  - 01-intro\n  - 03-ghost\n", encoding="utf-8"
    )

    intro = outputs_root / "slides" / "01-intro"
    intro_candidates = intro / "images" / "main" / "outputs"
    intro_candidates.mkdir(parents=True, exist_ok=True)
    intro_candidates.joinpath("one.png").write_bytes(png((12, 24, 36)))
    intro_candidates.joinpath("two.png").write_bytes(png((48, 60, 72)))
    intro.joinpath("slide.md").write_text(
        "\n".join(
            [
                "---",
                "text:",
                "  title: Intro",
                "  body: The intro.",
                "layout: image",
                "images:",
                "  - id: main",
                "    purpose: The intro visual",
                "---",
                "",
            ]
        ),
        encoding="utf-8",
    )

    stray = outputs_root / "slides" / "02-stray"
    stray_candidates = stray / "images" / "main" / "outputs"
    stray_candidates.mkdir(parents=True, exist_ok=True)
    stray_candidates.joinpath("held.png").write_bytes(png((80, 90, 100)))
    stray.joinpath("slide.md").write_text(
        "\n".join(
            [
                "---",
                "text:",
                "  title: Stray",
                "  body: The stray.",
                "layout: image",
                "images:",
                "  - id: main",
                "    selected: outputs/absent.png",
                "---",
                "",
            ]
        ),
        encoding="utf-8",
    )

    hand_written = outputs_root / "slides" / "04-html"
    hand_written.mkdir(parents=True, exist_ok=True)
    hand_written.joinpath("slide.md").write_text(
        "\n".join(
            [
                "---",
                "text:",
                "  title: Hand written",
                "  body: The hand-written one.",
                "layout: html",
                "---",
                "",
            ]
        ),
        encoding="utf-8",
    )
    hand_written.joinpath("slide.html").write_text(
        "<section>\n  <p>Hand written.</p>\n  <script>window.advance();</script>\n</section>\n",
        encoding="utf-8",
    )
    return presentation_dir


def write_empty_presentation(vault_root: Path, slug: str = "unwritten") -> Path:
    """A project that has a presentation directory and no slide in it.

    This is the ordinary state of a project nobody has authored a presentation
    for yet, so the migrator refuses with PRES_MIGRATION_EMPTY and nothing else.
    """

    presentation_dir = vault_root / slug
    _thesis_config(presentation_dir, f"{slug.title()} presentation")
    (presentation_dir / "outputs" / "presentation").mkdir(parents=True, exist_ok=True)
    return presentation_dir


def write_vault(root: Path, slug: str = "alpha") -> Path:
    """A vault root holding one legacy presentation; returns the vault root."""

    vault = root / "theses"
    vault.mkdir(parents=True, exist_ok=True)
    write_legacy_presentation(vault, slug)
    return vault
