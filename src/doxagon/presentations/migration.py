"""Legacy inventory, promotion, and retirement census.

Inventory is a pure read: it opens legacy sources, records exactly what the
current producers expose, and writes nothing — no thumbnail is derived, no
`.thumb_` file is created, and no `mtime` becomes an authoring decision. The
current list path derives thumbnails while reading
(``apps/web/backend/routers/theses.py`` ``ensure_thumbnails_exist``); this one
does not, because a display artifact is not authorship.

Promotion mints one asset record for every candidate — selected or not —
converts each legacy visual state into a registered checkpoint, refuses to
guess through any ambiguity, shadow-validates the whole candidate deck, and
only then promotes it atomically behind one signed, idempotent receipt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
from typing import Any, Iterable, Mapping, Sequence

import frontmatter
import yaml

from doxagon.html_editions.contracts import canonical_json, sha256

from .contracts import (
    DEFAULT_VALIDATION_POLICY,
    MANIFEST_KEY,
    MANIFEST_SCHEMA,
    MAX_SOURCE_BYTES,
    ValidationPolicy,
)
from .errors import Diagnostic, WorkspaceError
from .legacy_stock import (
    BUILDER_CHOREOGRAPHY_SCRIPT,
    MAX_LEGACY_STEPS,
    builder_motion_literal,
    render_builder_choreography,
    render_stock_choreography,
)
from .registration import scan_document, scan_styles
from .store import HEAD_KEY, fsync_directory, now, write_bytes, write_json
from .workspace import PresentationWorkspace

INVENTORY_SCHEMA = "doxagon.presentation-legacy-inventory/2"
MIGRATION_RECEIPT_SCHEMA = "doxagon.presentation-migration-receipt/2"
CENSUS_SCHEMA = "doxagon.presentation-retirement-census/2"

_INVENTORY_DOMAIN = b"doxagon-presentation-legacy-inventory/v2\0"
_CANDIDATE_DOMAIN = b"doxagon-presentation-legacy-candidate/v2\0"
_RECEIPT_DOMAIN = b"doxagon-presentation-migration-receipt/v2\0"

PRESENTATION_SUBPATH = ("outputs", "presentation")
#: The legacy producers keep one stylesheet for the whole deck
#: (``apps/web/backend/routers/theses.py`` serves it as ``global_css``).
LEGACY_STYLES_SUBPATH = ("styles", "html", "global.css")
#: The name that one stylesheet takes inside a promoted checkpoint source.
STYLES_KEY = "global.css"
IMAGE_MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".svg": "image/svg+xml"}
_RASTER_SIGNATURES = {"image/png": b"\x89PNG\r\n\x1a\n", "image/jpeg": b"\xff\xd8\xff"}
MIGRATION_MARKER = ".doxagon-presentation-v2"
MIGRATION_RECEIPT_KEY = "migration-receipt.json"
#: The store lives beside the receipt that vouches for it, under the marker
#: directory promotion publishes atomically.
STORE_SUBPATH = "store"

# The legacy list path resolves a declared slug to either a directory of that
# exact name or a numbered one (``apps/web/backend/routers/theses.py``
# ``NUMBERED_SLIDE_DIR_PATTERN`` / ``resolve_slide_dir``). The inventory has to
# resolve slugs the same way, or a slide the producer serves would read as
# missing here.
_NUMBERED_SLIDE_DIR = re.compile(r"^\d+(?:-\d+)?-(.+)$")

# The two markers are the only normalized bytes. Everything else, including
# whitespace and quote style, must equal these canonical producer bytes.
STOCK_CHOREOGRAPHY_TEMPLATE = """var MOTION = __DOXAGON_MOTION__;
var STEPS = __DOXAGON_STEPS__;
function applyStep(n) {
  document.body.dataset.step = String(n);
  document.querySelectorAll('[data-enter]').forEach(function(el) {
    var entered = n >= Number(el.dataset.enter);
    el.classList.toggle('on', entered);
    el.classList.toggle('off', !entered);
  });
  document.querySelectorAll('[data-exit]').forEach(function(el) {
    var exited = n >= Number(el.dataset.exit);
    el.classList.toggle('on', !exited);
    el.classList.toggle('off', exited);
  });
  document.querySelectorAll('.plate:not([data-enter])').forEach(function(el) {
    el.style.transform = MOTION[n] || '';
  });
}
if (window.dox && dox.slide) {
  dox.slide.steps(STEPS);
  for (var s = 0; s < STEPS; s += 1) {
    dox.slide.onStep(s, function(step) {
      return function() { applyStep(step); };
    }(s));
  }
}
applyStep(0);"""

_MOTION_PREFIX = "var MOTION = "
_STEPS_PREFIX = "var STEPS = "
#: The builder writes the same two declarations indented inside its IIFE.
_BUILDER_MOTION_PREFIX = "  var MOTION = "
_BUILDER_STEPS_PREFIX = "  var STEPS = "
#: An integer key and a quoted transform, scanned rather than split: a
#: transform contains `", "` (``translate(-1.5%, -1%)``) often enough that
#: splitting on the separator would tear one value in half.
_BUILDER_MOTION_ENTRY = re.compile(r'(0|[1-9][0-9]*): "([^"\\]*)"')
# The producer emits exact lowercase tags, so no other spelling is canonical.
_SCRIPT_ELEMENT = re.compile(r"<script>(?P<body>.*?)</script>", re.DOTALL)

#: Recognized producers, most specific first. A deck's script must be one of
#: these byte for byte; nothing here guesses at a script it cannot re-emit.
STOCK_VARIANT = "stock"
BUILDER_VARIANT = "builder"


def _unique_keyed_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject a repeated key, which `json.dumps` of the producer's dict cannot emit."""

    keys = [key for key, _ in pairs]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate object key")
    return dict(pairs)


@dataclass(frozen=True)
class StockChoreography:
    steps: int
    motion: dict[str, str]
    document: str
    #: Which legacy producer wrote this script. The two implement different
    #: choreography, so the promoted checkpoint has to replay the one it came
    #: from rather than a house style both are assumed to approximate.
    variant: str = STOCK_VARIANT


@dataclass(frozen=True)
class _ScriptSlots:
    """One recognized script with its two substituted declarations lifted out."""

    motion_literal: str
    steps: int
    normalized: str
    #: The document either side of the script element, kept apart because the
    #: producers do not agree on what follows it: one ends the file at
    #: `</script>`, the other writes a newline after it.
    prefix: str
    suffix: str


def _script_slots(html: str, motion_prefix: str, steps_prefix: str) -> _ScriptSlots | None:
    """Lift MOTION and STEPS out of the deck's single script, or refuse it.

    Only these two declarations are normalized. Every other byte, including
    whitespace and quote style, has to survive to the producer comparison the
    caller makes next.
    """

    matches = list(_SCRIPT_ELEMENT.finditer(html))
    if len(matches) != 1:
        return None
    script = matches[0].group("body")
    lines = script.splitlines(keepends=True)
    motion_lines = [index for index, line in enumerate(lines) if line.startswith(motion_prefix)]
    steps_lines = [index for index, line in enumerate(lines) if line.startswith(steps_prefix)]
    if len(motion_lines) != 1 or len(steps_lines) != 1:
        return None

    motion_index = motion_lines[0]
    steps_index = steps_lines[0]
    motion_newline = "\n" if lines[motion_index].endswith("\n") else ""
    steps_newline = "\n" if lines[steps_index].endswith("\n") else ""
    motion_suffix = ";" + motion_newline
    steps_suffix = ";" + steps_newline
    if not lines[motion_index].endswith(motion_suffix) or not lines[steps_index].endswith(steps_suffix):
        return None
    motion_literal = lines[motion_index][len(motion_prefix) : -len(motion_suffix)]
    steps_literal = lines[steps_index][len(steps_prefix) : -len(steps_suffix)]
    if not steps_literal.isascii() or not steps_literal.isdigit() or str(int(steps_literal)) != steps_literal:
        return None
    steps = int(steps_literal)
    if not 1 <= steps <= MAX_LEGACY_STEPS:
        return None

    normalized = list(lines)
    normalized[motion_index] = motion_prefix + "__DOXAGON_MOTION__;" + motion_newline
    normalized[steps_index] = steps_prefix + "__DOXAGON_STEPS__;" + steps_newline
    return _ScriptSlots(
        motion_literal, steps, "".join(normalized), html[: matches[0].start()], html[matches[0].end() :]
    )


def _stock_choreography(html: str) -> StockChoreography | None:
    slots = _script_slots(html, _MOTION_PREFIX, _STEPS_PREFIX)
    if slots is None or slots.normalized != STOCK_CHOREOGRAPHY_TEMPLATE:
        return None
    try:
        motion = json.loads(slots.motion_literal, object_pairs_hook=_unique_keyed_object)
    except ValueError:
        return None
    if not isinstance(motion, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in motion.items()):
        return None
    # Only bytes the producer can re-emit verbatim are canonical. Parsing alone
    # accepts literals `json.dumps` never writes — an escaped `</script>` among
    # them, which would reach the export as a live element.
    document = slots.prefix + slots.suffix
    if render_stock_choreography(document, steps=slots.steps, motion=motion) != html:
        return None
    return StockChoreography(slots.steps, motion, document, STOCK_VARIANT)


def _builder_choreography(html: str) -> StockChoreography | None:
    """The same discipline for the producer real decks actually contain.

    Its motion map is not JSON — unquoted integer keys — so it is scanned for
    entries and then re-emitted. Anything the scan misread fails that
    comparison, which is the only thing that admits the script.
    """

    slots = _script_slots(html, _BUILDER_MOTION_PREFIX, _BUILDER_STEPS_PREFIX)
    if slots is None or slots.normalized != BUILDER_CHOREOGRAPHY_SCRIPT:
        return None
    literal = slots.motion_literal
    if not literal.startswith("{ ") or not literal.endswith(" }"):
        return None
    pairs = [(int(key), value) for key, value in _BUILDER_MOTION_ENTRY.findall(literal)]
    motion = dict(pairs)
    if len(motion) != len(pairs) or builder_motion_literal(motion) != literal:
        return None
    if render_builder_choreography(slots.prefix, steps=slots.steps, motion=motion) != html:
        return None
    return StockChoreography(
        slots.steps, {str(key): value for key, value in motion.items()}, slots.prefix, BUILDER_VARIANT
    )


def _choreography(html: str) -> StockChoreography | None:
    """The one recognized producer that wrote this deck, or nothing."""

    return _stock_choreography(html) or _builder_choreography(html)


@dataclass(frozen=True)
class LegacyCandidate:
    """One generated image file exactly as the legacy tree holds it."""

    bundle_id: str
    filename: str
    relative_path: str
    media_type: str
    size: int
    sha256: str
    selected: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "filename": self.filename,
            "relative_path": self.relative_path,
            "media_type": self.media_type,
            "bytes": self.size,
            "sha256": self.sha256,
            # Recorded because the legacy frontmatter says so, never because a
            # thumbnail existed or a file was the most recently written one.
            "legacy_selected": self.selected,
        }


@dataclass(frozen=True)
class LegacyBundle:
    """One legacy `images[]` entry with its observed, non-authoritative flags."""

    bundle_id: str
    selected: str | None
    is_primary: bool
    purpose: str | None
    placement: str | None
    candidates: tuple[LegacyCandidate, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "observed_selected": self.selected,
            "observed_is_primary": self.is_primary,
            "purpose": self.purpose,
            "placement": self.placement,
            "candidates": [item.as_dict() for item in self.candidates],
        }


@dataclass(frozen=True)
class LegacySlide:
    """One legacy slide directory as its producers expose it."""

    slug: str
    directory: str
    order_index: int
    title: str
    body: str
    speaker_notes: str
    layout: str
    html: str | None
    bundles: tuple[LegacyBundle, ...]
    doxai: tuple[str, ...]
    choreography: StockChoreography | None = None
    # False when the slide directory exists on disk but no declared order names
    # it. Such a slide is still inventoried in full; promotion is blocked.
    declared: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            # The directory the producer actually serves, which a numbered
            # legacy tree spells differently from the declared slug.
            "directory": self.directory,
            "order_index": self.order_index,
            "declared": self.declared,
            "title": self.title,
            "body_sha256": sha256(self.body.encode("utf-8")),
            "speaker_notes_sha256": sha256(self.speaker_notes.encode("utf-8")),
            # `layout` is migration input only; the target has no such member.
            "observed_layout": self.layout,
            "html_sha256": None if self.html is None else sha256(self.html.encode("utf-8")),
            "bundles": [item.as_dict() for item in self.bundles],
            "doxai": list(self.doxai),
        }


@dataclass
class LegacyInventory:
    """A complete, non-mutating reading of one legacy presentation."""

    presentation_id: str
    source_root: str
    order_source: str
    slides: tuple[LegacySlide, ...]
    diagnostics: tuple[Diagnostic, ...] = ()
    unreadable: tuple[dict[str, Any], ...] = ()
    #: The deck's one legacy stylesheet, or None where the producers wrote
    #: none. Promotion carries these bytes; without them every migrated HTML
    #: slide renders unstyled.
    styles: str | None = None

    @property
    def candidate_count(self) -> int:
        return sum(len(bundle.candidates) for slide in self.slides for bundle in slide.bundles)

    @property
    def blockers(self) -> tuple[Diagnostic, ...]:
        return self.diagnostics

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": INVENTORY_SCHEMA,
            "presentation_id": self.presentation_id,
            "source_root": self.source_root,
            "order_source": self.order_source,
            "slides": [slide.as_dict() for slide in self.slides],
            "candidate_count": self.candidate_count,
            "styles_sha256": None if self.styles is None else sha256(self.styles.encode("utf-8")),
            "diagnostics": [item.as_dict() for item in self.diagnostics],
            "unreadable": [dict(item) for item in self.unreadable],
        }

    @property
    def digest(self) -> str:
        """Identity of exactly what was read, so promotion can be idempotent."""

        body = self.as_dict()
        body.pop("source_root")
        return sha256(_INVENTORY_DOMAIN + canonical_json(body))


def _slide_order(presentation_root: Path, diagnostics: list[Diagnostic]) -> tuple[tuple[str, ...], str]:
    """Read a configured order or preserve an unambiguous legacy numbered deck.

    The old viewer's no-config path reads directories in lexical order. Accept
    that existing sequence only when every directory has a unique, consecutive
    ordinal starting at zero or one, and lexical and numeric order agree. This
    preserves a deck already authored as 00-title, 01-intro, ... without asking
    for a duplicate manifest. Gaps, duplicate ordinals, mixed names, and nested
    numbering remain unresolved; alphabetical titles alone are not an order.
    An explicit config always wins, including its missing/unordered findings.
    """

    config_path = presentation_root / "config.yaml"
    if config_path.is_file():
        try:
            config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as error:
            diagnostics.append(Diagnostic("PRES_MIGRATION_ORDER_UNREADABLE", f"config.yaml is unreadable: {error}", "", "config.yaml"))
            config = {}
        if isinstance(config, dict):
            declared = config.get("slide_order")
            if declared is None or declared == []:
                declared = config.get("slides")
            if declared is not None:
                if isinstance(declared, list) and all(isinstance(item, str) and item for item in declared):
                    if declared:
                        return tuple(declared), "config.slide_order"
                else:
                    diagnostics.append(Diagnostic("PRES_MIGRATION_ORDER_UNREADABLE", "slide_order must be a list of nonempty slide names", "", "config.yaml"))
        else:
            diagnostics.append(Diagnostic("PRES_MIGRATION_ORDER_UNREADABLE", "config.yaml must contain a mapping", "", "config.yaml"))
    slides_dir = presentation_root / "slides"
    if not slides_dir.is_dir():
        return (), "absent"
    observed = tuple(sorted(entry.name for entry in slides_dir.iterdir() if entry.is_dir()))
    numbered = [re.fullmatch(r"([0-9]+)-(?![0-9]+-).+", name) for name in observed]
    if observed and not diagnostics and all(numbered):
        ordinals = [int(match.group(1)) for match in numbered if match is not None]
        first = ordinals[0]
        if first in (0, 1) and ordinals == list(range(first, first + len(observed))):
            return observed, "numbered-directories"
    if observed:
        diagnostics.append(
            Diagnostic(
                "PRES_MIGRATION_ORDER_UNDECLARED",
                f"no config.yaml declares slide_order for {len(observed)} slides; "
                "the folders do not form a complete numbered sequence in legacy display order; "
                "declare the order before promotion",
                "",
                "config.yaml",
            )
        )
    return observed, "unresolved"


def _selected_relative(selected: str | None, slug: str, bundle_id: str, diagnostics: list[Diagnostic]) -> PurePosixPath | None:
    """The exact bundle-relative path a legacy `selected` names, or nothing.

    The legacy producer resolves this value as ``img_dir / selected``
    (``apps/web/backend/routers/theses.py`` ``set_selected_image``), so it is a
    bundle-relative path and nothing else. Reducing it to a basename let a
    wrong or traversing value select ``outputs/<basename>`` and record that
    choice as legacy authorship. An uncontained value selects nothing and
    blocks instead.
    """

    if selected is None:
        return None
    candidate = PurePosixPath(selected.replace("\\", "/"))
    contained = (
        not candidate.is_absolute()
        and selected.strip() != ""
        and "\\" not in selected
        and all(part not in ("..", ".", "") for part in candidate.parts)
    )
    if not contained:
        diagnostics.append(
            Diagnostic(
                "PRES_MIGRATION_SELECTION_UNCONTAINED",
                f"slide {slug!r} bundle {bundle_id!r} selects {selected!r}, which is not a contained bundle-relative path",
                "",
                slug,
            )
        )
        return None
    return candidate


def _candidates(
    bundle_dir: Path,
    bundle_id: str,
    selected: PurePosixPath | None,
    diagnostics: list[Diagnostic],
) -> tuple[LegacyCandidate, ...]:
    outputs = bundle_dir / "outputs"
    if not outputs.is_dir():
        return ()
    found: list[LegacyCandidate] = []
    for entry in sorted(outputs.iterdir()):
        if not entry.is_file() or entry.name.startswith(".thumb_"):
            continue
        media_type = IMAGE_MEDIA_TYPES.get(entry.suffix.lower())
        if media_type is None:
            continue
        try:
            data = entry.read_bytes()
        except OSError as error:
            diagnostics.append(
                Diagnostic("PRES_MIGRATION_CANDIDATE_UNREADABLE", f"candidate is unreadable: {error}", "", str(entry))
            )
            continue
        # Legacy image selection kept the supplied filename, including JPEGs
        # named selected.png. The promoted blob is extensionless: declare its
        # actual raster type, without rewriting bytes or losing the source name.
        # Unknown bytes still face the normal positive media check at promotion.
        media_type = next((kind for kind, signature in _RASTER_SIGNATURES.items() if data.startswith(signature)), media_type)
        found.append(
            LegacyCandidate(
                bundle_id,
                entry.name,
                f"images/{bundle_id}/outputs/{entry.name}",
                media_type,
                len(data),
                sha256(data),
                # Exact match on the whole bundle-relative path; a near miss is
                # a blocker, never a selection.
                selected is not None and selected == PurePosixPath("outputs") / entry.name,
            )
        )
    return tuple(found)


def _slide_directories(slides_dir: Path) -> tuple[Path, ...]:
    """Every slide directory the legacy producers can see, order-independent."""

    if not slides_dir.is_dir():
        return ()
    return tuple(sorted((entry for entry in slides_dir.iterdir() if entry.is_dir() and not entry.name.startswith(".")), key=lambda item: item.name))


def _resolve_slide_dir(directories: Sequence[Path], slug: str) -> Path | None:
    """Resolve one declared slug the way the legacy list path resolves it."""

    for directory in directories:
        if directory.name == slug:
            return directory
    for directory in directories:
        match = _NUMBERED_SLIDE_DIR.match(directory.name)
        if match is not None and match.group(1) == slug:
            return directory
    return None


def inventory_presentation(thesis_dir: Path, presentation_id: str | None = None) -> LegacyInventory:
    """Read one legacy presentation without changing a single byte of it.

    The declared order is reconciled against the slide directories the legacy
    producers actually serve (``apps/web/backend/routers/theses.py``
    ``count_slides`` enumerates the same directories, not the configured
    order). A directory no declared order names is still inventoried in full —
    every slide and every candidate — and blocks promotion, because dropping it
    would delete legacy authorship without a blocker.
    """

    presentation_root = thesis_dir.joinpath(*PRESENTATION_SUBPATH)
    diagnostics: list[Diagnostic] = []
    unreadable: list[dict[str, Any]] = []
    order, order_source = _slide_order(presentation_root, diagnostics)
    slides_dir = presentation_root / "slides"
    directories = _slide_directories(slides_dir)

    slides: list[LegacySlide] = []
    seen: set[str] = set()
    claimed: set[Path] = set()
    for index, slug in enumerate(order):
        if slug in seen:
            diagnostics.append(
                Diagnostic("PRES_MIGRATION_SLIDE_DUPLICATE", f"legacy order names {slug!r} more than once", "", slug)
            )
            continue
        seen.add(slug)
        slide_dir = _resolve_slide_dir(directories, slug)
        if slide_dir is None:
            diagnostics.append(
                Diagnostic("PRES_MIGRATION_SLIDE_MISSING", f"ordered slide {slug!r} has no slide directory", "", slug)
            )
            continue
        claimed.add(slide_dir)
        slide = _read_slide(slide_dir, slug, index, True, diagnostics, unreadable)
        if slide is not None:
            slides.append(slide)

    for slide_dir in directories:
        if slide_dir in claimed:
            continue
        slug = slide_dir.name
        diagnostics.append(
            Diagnostic(
                "PRES_MIGRATION_SLIDE_UNORDERED",
                f"slide directory {slug!r} exists but no declared order names it; "
                "declare it before promotion rather than dropping it and its candidates",
                "",
                slug,
            )
        )
        slide = _read_slide(slide_dir, slug, len(slides), False, diagnostics, unreadable)
        if slide is not None:
            slides.append(slide)

    styles = _read_text(presentation_root.joinpath(*LEGACY_STYLES_SUBPATH))
    diagnostics.extend(_ambiguities(slides))
    diagnostics.extend(_unsafe_styles(styles))
    return LegacyInventory(
        presentation_id or _identifier(thesis_dir.name),
        str(thesis_dir),
        order_source,
        tuple(slides),
        tuple(sorted(diagnostics, key=lambda item: item.sort_key)),
        tuple(unreadable),
        styles=styles,
    )


def _read_text(path: Path) -> str | None:
    """One legacy text file, or None where the producers wrote none.

    Inventory runs inside a request against a tree a vault author controls, so
    it reads that tree under the same discipline the store reads its own: the
    open refuses to follow a symlink, and the read is bounded. A `global.css`
    symlinked at anything the server can read would otherwise be promoted into
    the deck and served in every payload and export.
    """

    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return None
    try:
        if os.fstat(descriptor).st_size > MAX_SOURCE_BYTES:
            return None
        return os.read(descriptor, MAX_SOURCE_BYTES).decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    finally:
        os.close(descriptor)


def _read_slide(
    slide_dir: Path,
    slug: str,
    index: int,
    declared: bool,
    diagnostics: list[Diagnostic],
    unreadable: list[dict[str, Any]],
) -> LegacySlide | None:
    """Read exactly what one slide directory holds, writing nothing."""

    document = slide_dir / "slide.md"
    if not document.is_file():
        diagnostics.append(
            Diagnostic("PRES_MIGRATION_SLIDE_MISSING", f"slide {slug!r} has no slide.md", "", slug)
        )
        return None
    try:
        parsed = frontmatter.load(document)
    except Exception as error:  # frontmatter raises library-specific errors
        unreadable.append({"slug": slug, "error": str(error)})
        diagnostics.append(
            Diagnostic("PRES_MIGRATION_SLIDE_UNREADABLE", f"slide {slug!r} frontmatter is unreadable", "", slug)
        )
        return None

    text = parsed.get("text") or {}
    text = text if isinstance(text, dict) else {}
    layout = str(parsed.get("layout", "image"))
    html: str | None = None
    html_path = slide_dir / "slide.html"
    if html_path.is_file():
        try:
            html = html_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            unreadable.append({"slug": slug, "error": str(error)})
            diagnostics.append(
                Diagnostic("PRES_MIGRATION_HTML_UNREADABLE", f"slide {slug!r} slide.html is unreadable", "", slug)
            )

    bundles: list[LegacyBundle] = []
    raw_bundles = parsed.get("images") or []
    for position, raw in enumerate(raw_bundles if isinstance(raw_bundles, list) else []):
        if not isinstance(raw, dict):
            diagnostics.append(
                Diagnostic("PRES_MIGRATION_BUNDLE_INVALID", f"slide {slug!r} image entry {position} is not a mapping", "", slug)
            )
            continue
        bundle_id = str(raw.get("id", "main"))
        selected = raw.get("selected")
        selected = None if selected is None else str(selected)
        bundles.append(
            LegacyBundle(
                bundle_id,
                selected,
                bool(raw.get("is_primary", False)),
                None if raw.get("purpose") is None else str(raw["purpose"]),
                None if raw.get("placement") is None else str(raw["placement"]),
                _candidates(
                    slide_dir / "images" / bundle_id,
                    bundle_id,
                    _selected_relative(selected, slug, bundle_id, diagnostics),
                    diagnostics,
                ),
            )
        )
    doxai = parsed.get("doxai") or []
    return LegacySlide(
        slug,
        slide_dir.name,
        index,
        str(text.get("title", slug)),
        str(text.get("body", "")),
        str(parsed.get("speaker_notes", "")),
        layout,
        html,
        tuple(bundles),
        tuple(str(item) for item in doxai if isinstance(item, str)),
        None if html is None else _choreography(html),
        declared,
    )


def _unsafe_styles(styles: str | None) -> list[Diagnostic]:
    """The deck's own stylesheet, judged before promotion instead of during it.

    Promotion copies `global.css` onto every checkpoint, so a stylesheet the
    validator refuses fails the whole deck once per checkpoint, naming a
    checkpoint source key for a file the operator would have to guess at.
    Reported here, the finding names the legacy path that actually holds it.
    """

    if styles is None:
        return []
    legacy_path = "/".join(("outputs", "presentation", *LEGACY_STYLES_SUBPATH))
    return [
        Diagnostic(diagnostic.code, diagnostic.message, "", legacy_path, diagnostic.line)
        for diagnostic in scan_styles(styles.encode("utf-8"), legacy_path)
    ]


def _ambiguities(slides: Sequence[LegacySlide]) -> list[Diagnostic]:
    """Every mapping a migrator must not resolve by guessing."""

    found: list[Diagnostic] = []
    identifiers: dict[str, str] = {}
    for slide in slides:
        checkpoint_id = checkpoint_id_for(slide.slug)
        if checkpoint_id in identifiers:
            found.append(
                Diagnostic(
                    "PRES_MIGRATION_ID_COLLISION",
                    f"legacy slides {identifiers[checkpoint_id]!r} and {slide.slug!r} both map to {checkpoint_id!r}",
                    "",
                    slide.slug,
                )
            )
        identifiers[checkpoint_id] = slide.slug
        if slide.layout == "html":
            if slide.html is None:
                found.append(
                    Diagnostic("PRES_MIGRATION_HTML_MISSING", f"slide {slide.slug!r} declares layout 'html' with no slide.html", "", slide.slug)
                )
            else:
                document = slide.html if slide.choreography is None else slide.choreography.document
                if slide.choreography is not None:
                    # Only a stock slide renders the legacy document as written.
                    # The synthetic fallback replaces it, so its slots never run.
                    bound = slots_for(slide)
                    for slot in sorted(slots_in(document)):
                        if slot not in bound:
                            found.append(
                                Diagnostic(
                                    "PRES_MIGRATION_SLOT_UNBOUND",
                                    f"slide {slide.slug!r} renders image slot {slot!r}, which no selected candidate fills",
                                    "",
                                    slide.slug,
                                )
                            )
                for diagnostic in scan_document(document.encode("utf-8"), f"{slide.slug}/slide.html"):
                    # Only the exact stock script is removed. Any other unsafe
                    # document byte, including a second script or remote URL,
                    # continues through the unchanged refusal path.
                    found.append(
                        Diagnostic("PRES_MIGRATION_HTML_UNSAFE", diagnostic.message, "", diagnostic.path, diagnostic.line)
                    )
        for bundle in slide.bundles:
            if bundle.selected is None and bundle.candidates:
                found.append(
                    Diagnostic(
                        "PRES_MIGRATION_SELECTION_ABSENT",
                        f"slide {slide.slug!r} bundle {bundle.bundle_id!r} has {len(bundle.candidates)} candidates and no selection",
                        "",
                        slide.slug,
                    )
                )
            if bundle.selected is not None and not any(item.selected for item in bundle.candidates):
                found.append(
                    Diagnostic(
                        "PRES_MIGRATION_SELECTION_MISSING",
                        f"slide {slide.slug!r} bundle {bundle.bundle_id!r} selects {bundle.selected!r}, which is not a candidate",
                        "",
                        slide.slug,
                    )
                )
    return found


#: What a composed checkpoint id may spend on the slug: `_ID` admits 64
#: characters, `slide-` takes six, and a multi-step slide appends `-step-` and
#: up to three digits. Truncating here rather than at the composition keeps one
#: id per slug however many steps it turns out to hold, and a truncation that
#: collides with another slug's is still refused by name.
_IDENTIFIER_BUDGET = 64 - len("slide-") - len("-step-999")


def _identifier(value: str) -> str:
    cleaned = "".join(character if character.isalnum() else "-" for character in value.lower()).strip("-")
    cleaned = "-".join(part for part in cleaned.split("-") if part)
    return (cleaned or "deck")[:_IDENTIFIER_BUDGET]


def checkpoint_id_for(slug: str) -> str:
    """A stable v2 checkpoint id for one legacy slide slug."""

    return f"slide-{_identifier(slug)}"


def asset_id_for(slide_slug: str, bundle_id: str, filename: str) -> str:
    """A stable asset identity for one legacy candidate's *address*.

    Identity is the place a candidate was authored, never its bytes. Two
    candidates with byte-identical content are still two candidates with two
    filenames, two bundles, and two source refs; addressing them by digest
    would silently discard one record's provenance. Bytes stay shared through
    the content-addressed `storage_key`, so preserving both records costs
    nothing on disk.
    """

    address = canonical_json({"slide": slide_slug, "bundle": bundle_id, "filename": filename})
    return f"asset-{sha256(_CANDIDATE_DOMAIN + address)[:32]}"


#: Legacy documents address their images by slot, not by asset: the producers
#: wrote `<img data-image-id="main">` with no `src` and left the renderer to
#: fill it from the frontmatter's `images[]` entry of the same id.
#: HTML permits an unquoted attribute value, and the slot gate has to see one:
#: a slot it misses is not a blocker before migration but a black slide during
#: a presentation. Matched on `img` alone, because only `img` is ever filled.
_SLOT_PATTERN = re.compile(
    r"""<img\b[^>]*?\bdata-image-id\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+))""",
    re.IGNORECASE | re.DOTALL,
)


def slots_in(document: str) -> set[str]:
    """Every image slot one legacy document renders, however it quoted it."""

    return {next(value for value in match.groups() if value is not None) for match in _SLOT_PATTERN.finditer(document)}


def slots_for(slide: LegacySlide) -> dict[str, str]:
    """Each legacy image slot with the asset its selected candidate becomes.

    Only a selected candidate binds. A bundle's unselected candidates are still
    promoted as assets with their own provenance, but nothing renders them,
    exactly as the legacy renderer showed only the selection.
    """

    return {
        bundle.bundle_id: asset_id_for(slide.slug, bundle.bundle_id, candidate.filename)
        for bundle in slide.bundles
        for candidate in bundle.candidates
        if candidate.selected
    }


_HTML_ESCAPES = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}


def _escape(value: str) -> str:
    return "".join(_HTML_ESCAPES.get(character, character) for character in value)


_PROGRAM = """/* doxagon-checkpoint-registration
{registration}
*/
export function create(context) {{
  const root = context.root;
  return {{
    enter() {{
      for (const image of root.querySelectorAll('img[data-asset]')) {{
        const asset = context.assets.get(image.dataset.asset);
        if (asset === undefined) throw new Error('PRES_ASSET_UNKNOWN: ' + image.dataset.asset);
        image.src = asset.url();
        image.alt = asset.alt || asset.label;
      }}
      root.dataset.entered = context.checkpointId;
    }},
    exit() {{
      delete root.dataset.entered;
    }},
    signature() {{
      /* A digest of the managed DOM, so replaying this checkpoint from fresh
         source has to produce the same state or the runtime refuses it. */
      let hash = 2166136261;
      const text = context.checkpointId + '\\u0000' + root.innerHTML;
      for (let index = 0; index < text.length; index += 1) {{
        hash ^= text.charCodeAt(index);
        hash = Math.imul(hash, 16777619) >>> 0;
      }}
      return 'fnv1a32:' + hash.toString(16).padStart(8, '0');
    }},
    inspect() {{
      return {{ checkpointId: context.checkpointId, assets: Array.from(context.assets.keys()) }};
    }},
  }};
}}
"""

_STOCK_MODULE_KEY = "stock-choreography.js"
_STOCK_MODULE = """const api = Object.freeze({
  create(context, parameters) {
    const root = context.root;
    const step = parameters.step;
    const motion = parameters.motion;
    const slots = parameters.slots;
    const variant = parameters.variant;
    return {
      enter() {
        for (const image of root.querySelectorAll('img[data-image-id]')) {
          const assetId = slots[image.dataset.imageId];
          if (assetId === undefined) throw new Error('PRES_SLOT_UNBOUND: ' + image.dataset.imageId);
          const asset = context.assets.get(assetId);
          if (asset === undefined) throw new Error('PRES_ASSET_UNKNOWN: ' + assetId);
          image.src = asset.url();
          image.alt = asset.alt || asset.label;
        }
        root.dataset.step = String(step);
        /* Both producers wrote the step onto the body, and the deck's own
           stylesheet travels with it, so a rule keyed on body[data-step]
           still matches what it was written against. */
        root.ownerDocument.body.dataset.step = String(step);
        /* Each producer's own choreography, replayed as it was written. The
           two differ in what an element before its enter step is given, in
           whether data-exit is read in the same pass, and in whether a step
           the motion map omits clears the transform. */
        if (variant === 'builder') {
          for (const element of root.querySelectorAll('[data-enter]')) {
            const enter = Number(element.dataset.enter);
            const exit = element.dataset.exit ? Number(element.dataset.exit) : Infinity;
            element.classList.toggle('on', step >= enter && step < exit);
            element.classList.toggle('off', step >= exit);
          }
          for (const plate of root.querySelectorAll('.plate')) {
            if (plate.dataset.enter) continue;
            /* The builder assigns a transform only on a step its motion map
               names, so a legacy deck stepped from 0 still shows the last one
               that did. Every step here is its own realm with a cold DOM, so
               the transform it inherited has to be found by folding back. */
            for (let index = step; index >= 0; index -= 1) {
              if (motion[index]) { plate.style.transform = motion[index]; break; }
            }
          }
        } else {
          for (const element of root.querySelectorAll('[data-enter]')) {
            const entered = step >= Number(element.dataset.enter);
            element.classList.toggle('on', entered);
            element.classList.toggle('off', !entered);
          }
          for (const element of root.querySelectorAll('[data-exit]')) {
            const exited = step >= Number(element.dataset.exit);
            element.classList.toggle('on', !exited);
            element.classList.toggle('off', exited);
          }
          for (const plate of root.querySelectorAll('.plate:not([data-enter])')) {
            plate.style.transform = motion[step] || '';
          }
        }
        root.dataset.steps = String(parameters.steps);
      },
      exit() {},
      signature() {
        let hash = 2166136261;
        const text = root.innerHTML + '\\u0000' + root.dataset.step + '\\u0000' + root.dataset.steps;
        for (let index = 0; index < text.length; index += 1) {
          hash ^= text.charCodeAt(index);
          hash = Math.imul(hash, 16777619) >>> 0;
        }
        return 'stock-choreography:' + hash.toString(16).padStart(8, '0');
      },
      inspect() { return { step, steps: parameters.steps, motion, slots, variant }; },
    };
  },
});
window.__doxagonStockChoreography = api;
"""

_STOCK_PROGRAM = """/* doxagon-checkpoint-registration
{registration}
*/
const parameters = {parameters};
export function create(context) {{
  return window.__doxagonStockChoreography.create(context, parameters);
}}
"""


def _document(slide: LegacySlide, references: Sequence[tuple[str, str]]) -> str:
    paragraphs = "\n".join(
        f"  <p>{_escape(block.strip())}</p>" for block in slide.body.split("\n\n") if block.strip()
    )
    figures = "\n".join(
        f'  <figure><img data-asset="{_escape(asset_id)}" alt="{_escape(label)}"></figure>'
        for asset_id, label in references
    )
    return (
        f'<section class="checkpoint" data-checkpoint="{_escape(checkpoint_id_for(slide.slug))}">\n'
        f"  <h1>{_escape(slide.title)}</h1>\n"
        f"{paragraphs}\n{figures}\n</section>\n"
    )


_STYLES = """.checkpoint { display: flex; flex-direction: column; gap: 1rem; padding: 2rem; }
.checkpoint h1 { font: 600 2.5rem/1.2 system-ui, sans-serif; margin: 0; }
.checkpoint p { font: 1.125rem/1.6 system-ui, sans-serif; margin: 0; }
.checkpoint figure { margin: 0; }
.checkpoint img { max-width: 100%; height: auto; display: block; }
"""


@dataclass(frozen=True)
class MigrationReceipt:
    """A signed, verifiable record of exactly one promotion."""

    presentation_id: str
    inventory_digest: str
    revision: str
    checkpoint_ids: tuple[str, ...]
    asset_ids: tuple[str, ...]
    candidate_count: int
    shadow: dict[str, Any]
    created_at: str

    def body(self) -> dict[str, Any]:
        return {
            "schema": MIGRATION_RECEIPT_SCHEMA,
            "presentation_id": self.presentation_id,
            "inventory_digest": self.inventory_digest,
            "revision": self.revision,
            "checkpoint_ids": list(self.checkpoint_ids),
            "asset_ids": list(self.asset_ids),
            "candidate_count": self.candidate_count,
            "shadow": dict(self.shadow),
            "created_at": self.created_at,
        }

    @property
    def signature(self) -> str:
        """A content signature over the receipt body.

        There is no key custodian in this system, so the signature is a
        domain-separated digest: it proves the receipt describes these exact
        inputs and this exact revision, and any edit to either invalidates it.
        """

        return sha256(_RECEIPT_DOMAIN + canonical_json(self.body()))

    def as_dict(self) -> dict[str, Any]:
        return {**self.body(), "signature": self.signature}


def verify_migration_receipt(record: Mapping[str, Any]) -> bool:
    if record.get("schema") != MIGRATION_RECEIPT_SCHEMA:
        return False
    body = {key: value for key, value in record.items() if key != "signature"}
    return record.get("signature") == sha256(_RECEIPT_DOMAIN + canonical_json(body))


@dataclass
class MigrationPlan:
    """The complete v2 deck a clean inventory would become."""

    manifest: dict[str, Any]
    sources: dict[str, bytes] = field(default_factory=dict)
    assets: dict[str, bytes] = field(default_factory=dict)


def plan_migration(inventory: LegacyInventory) -> MigrationPlan:
    """Build the whole candidate deck; every candidate becomes an asset record."""

    if inventory.blockers:
        raise WorkspaceError(
            "PRES_MIGRATION_BLOCKED",
            f"{len(inventory.blockers)} mapping ambiguity must be resolved before promotion",
            status=409,
            diagnostics=inventory.blockers,
        )
    if not inventory.slides:
        raise WorkspaceError("PRES_MIGRATION_EMPTY", "this legacy presentation registers no slide", status=422)

    root = Path(inventory.source_root).joinpath(*PRESENTATION_SUBPATH, "slides")
    plan = MigrationPlan({})
    checkpoints: list[dict[str, Any]] = []
    groups: list[dict[str, Any]] = []
    assets: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    # One import, one import time. Read per candidate, a deck large enough to
    # take a second to plan would stamp its assets with several, so provenance
    # would say the same import happened at two different moments.
    imported_at = now()

    for slide in inventory.slides:
        checkpoint_id = checkpoint_id_for(slide.slug)
        order.append(checkpoint_id)
        referenced: list[tuple[str, str]] = []
        for bundle in slide.bundles:
            for candidate in bundle.candidates:
                asset_id = asset_id_for(slide.slug, bundle.bundle_id, candidate.filename)
                # The directory the producer serves, which a numbered legacy
                # tree spells differently from the declared slug.
                data = (root / slide.directory / candidate.relative_path).read_bytes()
                if sha256(data) != candidate.sha256:
                    raise WorkspaceError(
                        "PRES_MIGRATION_CANDIDATE_CHANGED",
                        f"{candidate.relative_path} changed between inventory and promotion",
                        status=409,
                    )
                plan.assets[candidate.sha256] = data
                if asset_id in assets:
                    raise WorkspaceError(
                        "PRES_MIGRATION_CANDIDATE_AMBIGUOUS",
                        f"two legacy candidates share the address {slide.slug}/{bundle.bundle_id}/{candidate.filename}",
                        status=409,
                    )
                assets[asset_id] = {
                    "id": asset_id,
                    "label": f"{slide.slug} · {bundle.bundle_id} · {candidate.filename}",
                    "alt": bundle.purpose or f"Legacy candidate {candidate.filename}",
                    "media_type": candidate.media_type,
                    "bytes": candidate.size,
                    "sha256": candidate.sha256,
                    # Content-addressed storage, address-addressed identity:
                    # duplicate bytes are stored once and still carry two
                    # independent provenance records.
                    "storage_key": f"sha256/{candidate.sha256}",
                    "provenance": {
                        "kind": "imported",
                        "created_at": imported_at,
                        "generator": None,
                        "prompt_sha256": None,
                        # Provenance keeps the legacy address so a reviewer
                        # can trace any asset back to the bytes it came from.
                        "source_ref": f"{slide.slug}/{candidate.relative_path}",
                        "license": None,
                    },
                }
                if candidate.selected:
                    referenced.append((asset_id, assets[asset_id]["label"]))

        step_count = slide.choreography.steps if slide.choreography is not None else 1
        if step_count > 1:
            order[-1:] = [f"{checkpoint_id}-step-{index}" for index in range(step_count)]
        slide_checkpoints: list[str] = []
        for step in range(step_count):
            state_id = checkpoint_id if step_count == 1 else f"{checkpoint_id}-step-{step}"
            slide_checkpoints.append(state_id)
            stock = slide.choreography is not None
            source_key = "checkpoints/legacy-stock" if stock else f"checkpoints/{state_id}"
            entry = f"{state_id}.js" if stock else "program.js"
            # A slide's steps differ only in which step the program renders, so
            # the document they render and the notes they are spoken from
            # belong to the slide. Giving each step a private copy would let an
            # edit to one step's HTML or notes leave the other steps behind.
            document = f"{checkpoint_id}.html" if stock else "document.html"
            styles = STYLES_KEY if stock else "styles.css"
            notes = f"{checkpoint_id}.md" if stock else "notes.md"
            registration = canonical_json(
                {
                    "schema": "doxagon.presentation-checkpoint/1",
                    "id": state_id,
                    "version": "1.0.0",
                    "assets": [asset_id for asset_id, _ in referenced],
                    "capabilities": [],
                    "description": f"Migrated from legacy slide {slide.slug}",
                }
            ).decode("utf-8").strip()
            if stock:
                parameters = canonical_json(
                    {
                        "steps": step_count,
                        "motion": slide.choreography.motion,
                        "step": step,
                        "slots": slots_for(slide),
                        "variant": slide.choreography.variant,
                    }
                ).decode("utf-8").strip()
                plan.sources[f"{source_key}/{entry}"] = _STOCK_PROGRAM.format(
                    registration=registration, parameters=parameters
                ).encode("utf-8")
                plan.sources[f"{source_key}/{document}"] = slide.choreography.document.encode("utf-8")
                # One stylesheet for the whole deck, shared by every stock
                # checkpoint, because that is what the legacy producers wrote:
                # a global look is then edited once and not once per step.
                plan.sources.setdefault(
                    f"{source_key}/{styles}",
                    b"" if inventory.styles is None else inventory.styles.encode("utf-8"),
                )
                plan.sources.setdefault(f"{source_key}/{_STOCK_MODULE_KEY}", _STOCK_MODULE.encode("utf-8"))
            else:
                plan.sources[f"{source_key}/{entry}"] = _PROGRAM.format(registration=registration).encode("utf-8")
                plan.sources[f"{source_key}/{document}"] = _document(slide, referenced).encode("utf-8")
                plan.sources[f"{source_key}/{styles}"] = _STYLES.encode("utf-8")
            plan.sources[f"{source_key}/{notes}"] = slide.speaker_notes.encode("utf-8")
            checkpoints.append(
                {
                    "id": state_id,
                    "label": slide.title if step_count == 1 else f"{slide.title} — step {step + 1} of {step_count}",
                    "source": source_key,
                    "entry": entry,
                    "document": document,
                    "styles": styles,
                    "notes": notes,
                    "modules": [_STOCK_MODULE_KEY] if stock else [],
                    "assets": [asset_id for asset_id, _ in referenced],
                    "capabilities": [],
                    "transition": {"linear": len(inventory.slides) > 1 or step_count > 1},
                }
            )
        groups.append(
            {
                "id": f"group-{_identifier(slide.slug)}",
                "kind": "slide",
                "label": slide.title,
                "checkpoints": slide_checkpoints,
                "export_boundary": True,
            }
        )

    plan.manifest = {
        "schema": MANIFEST_SCHEMA,
        "presentation_id": inventory.presentation_id,
        "checkpoint_order": order,
        "checkpoints": checkpoints,
        "groups": groups,
        "assets": [assets[key] for key in sorted(assets)],
    }
    return plan


def _materialize(plan: MigrationPlan, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for key, data in plan.sources.items():
        path = destination / key
        path.parent.mkdir(parents=True, exist_ok=True)
        write_bytes(path, data)
    for digest, data in plan.assets.items():
        path = destination / "assets" / "sha256" / digest
        path.parent.mkdir(parents=True, exist_ok=True)
        write_bytes(path, data)
    write_json(destination / MANIFEST_KEY, plan.manifest)


def promote(
    inventory: LegacyInventory,
    target_root: Path,
    *,
    staging: Path | None = None,
    policy: ValidationPolicy = DEFAULT_VALIDATION_POLICY,
) -> MigrationReceipt:
    """Shadow-validate the whole candidate deck, then land it in one rename.

    The shadow store and the published store validate under the same policy the
    caller will later open the deck with, so a migration cannot succeed against a
    budget the deck's next edit, receipt verification, or export would fail.

    Authority moves at exactly one instant. The target store and the receipt
    that vouches for it are assembled together in a private directory beside
    the target and published by a single ``os.replace``, so every failure
    before that instant — the receipt write above all — leaves no target at
    all. The previous order created the target store first and wrote the
    receipt after, which left a promoted store that ``is_migrated`` could not
    vouch for and that a retry could not re-promote: the second attempt found
    the orphaned store and failed ``PRES_WORKSPACE_EXISTS`` forever.

    Re-running against an unchanged legacy tree returns the receipt of the
    promotion that already happened; nothing is written twice.
    """

    receipt_path = target_root / MIGRATION_RECEIPT_KEY
    existing = _read_receipt(receipt_path)
    if existing is not None and existing.get("inventory_digest") == inventory.digest:
        return _receipt_from(existing)

    plan = plan_migration(inventory)
    shadow_root = (staging or target_root.parent) / f".shadow-{inventory.digest[:16]}"
    # The pending target is always a sibling of the target so publication is a
    # rename inside one filesystem; a cross-device copy could not be atomic,
    # and `staging` may name any directory the caller likes.
    pending_root = target_root.parent / f".pending-{inventory.digest[:16]}"
    _discard(shadow_root)
    _discard(pending_root)
    try:
        deck = shadow_root / "deck"
        _materialize(plan, deck)
        # Shadow first: the candidate deck is validated and promoted into a
        # throwaway store, so a deck that cannot validate never touches the
        # target root at all.
        shadow_workspace = PresentationWorkspace.create(shadow_root / STORE_SUBPATH, deck, policy=policy)
        shadow_revision = shadow_workspace.revision
        shadow_receipt = shadow_workspace.store.read_receipt(shadow_revision)

        pending_root.mkdir(parents=True)
        workspace = PresentationWorkspace.create(pending_root / STORE_SUBPATH, deck, policy=policy)
        if workspace.revision != shadow_revision:
            raise WorkspaceError(
                "PRES_MIGRATION_UNSTABLE",
                "the promoted revision did not reproduce the shadow revision",
                status=500,
            )

        receipt = MigrationReceipt(
            inventory.presentation_id,
            inventory.digest,
            shadow_revision,
            tuple(shadow_receipt["checkpoint_order"]),
            tuple(str(item["id"]) for item in shadow_receipt["assets"]),
            inventory.candidate_count,
            {
                "compose_hash": shadow_receipt["compose_hash"],
                "asset_closure_digest": shadow_receipt["asset_closure_digest"],
                "checkpoint_count": len(shadow_receipt["checkpoint_order"]),
                "asset_count": len(shadow_receipt["assets"]),
            },
            now(),
        )
        # Durable inside the pending target, where nothing reads it yet: the
        # published target therefore can never be a store without its receipt.
        write_json(pending_root / MIGRATION_RECEIPT_KEY, receipt.as_dict())
        _publish(pending_root, target_root)
    except BaseException:
        # Compensation: nothing was published, so the whole attempt goes. A
        # cleanup that itself fails leaves inert residue and must not replace
        # the failure that caused it.
        _discard(pending_root)
        _discard(shadow_root)
        raise
    # Cleanup is not authority. The migration is already durable, so a staging
    # tree that refuses to be removed is residue to sweep, never a reason to
    # report a promotion that happened as a promotion that did not.
    _discard(shadow_root)
    return receipt


def _discard(path: Path) -> None:
    """Remove one private staging tree, whatever else is happening.

    This never raises: before publication the original failure is the one worth
    reporting, and after publication the target is already durable, so residue
    that resists removal is residue and nothing more.
    """

    try:
        shutil.rmtree(path, ignore_errors=True)
    except OSError:
        pass


def _publish(pending_root: Path, target_root: Path) -> None:
    """Move the fully assembled target into place with one rename."""

    target_root.parent.mkdir(parents=True, exist_ok=True)
    if target_root.exists():
        try:
            # A caller may create the marker directory ahead of the promotion;
            # an empty one is a placeholder, and anything else is content this
            # promotion did not write and must not silently replace.
            target_root.rmdir()
        except OSError as error:
            raise WorkspaceError(
                "PRES_MIGRATION_TARGET_OCCUPIED",
                f"{target_root} already holds content that no migration receipt vouches for",
                status=409,
            ) from error
    try:
        os.replace(pending_root, target_root)
    except OSError as error:
        raise WorkspaceError(
            "PRES_MIGRATION_PUBLISH_FAILED",
            "the migrated target could not be published in one rename",
            status=500,
        ) from error
    fsync_directory(target_root.parent)


def _read_receipt(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    from .store import read_json

    record = read_json(path)
    if not isinstance(record, dict) or not verify_migration_receipt(record):
        raise WorkspaceError("PRES_MIGRATION_RECEIPT_INVALID", "the stored migration receipt is not verifiable", status=409)
    return record


def _receipt_from(record: Mapping[str, Any]) -> MigrationReceipt:
    return MigrationReceipt(
        str(record["presentation_id"]),
        str(record["inventory_digest"]),
        str(record["revision"]),
        tuple(str(item) for item in record["checkpoint_ids"]),
        tuple(str(item) for item in record["asset_ids"]),
        int(record["candidate_count"]),
        dict(record["shadow"]),
        str(record["created_at"]),
    )


def migration_receipt_path(thesis_dir: Path) -> Path:
    """Where one legacy tree records the promotion that already happened."""

    return thesis_dir / MIGRATION_MARKER / MIGRATION_RECEIPT_KEY


def is_migrated(thesis_dir: Path) -> bool:
    """Whether this legacy tree has a verifiable promotion receipt.

    Migration is proved by a receipt that still verifies, not by the presence
    of a directory: a half-written marker must not be read as authority having
    moved, because that would close legacy writes for a deck that was never
    actually promoted.
    """

    from .store import read_json

    record = read_json(migration_receipt_path(thesis_dir))
    return isinstance(record, dict) and verify_migration_receipt(record)


def unmigrate(thesis_dir: Path, *, discard_edits: bool = False) -> bool:
    """Return one promoted deck to legacy authority, reporting whether it moved.

    Promotion never mutates the legacy tree — inventory is a pure read — so the
    whole of what a promotion added is the marker directory it published. The
    legacy sources are still exactly the bytes they were, and removing the
    receipt is what makes them authoritative again.

    A store whose HEAD has moved past the revision the receipt names holds
    authorship that exists nowhere else; discarding it silently would destroy
    work no legacy source records. That case is refused by name unless the
    caller asks for it, because rolling a migration back is routine and losing
    an edit is not. So is a marker that cannot say where it stands: proving a
    store holds nothing new is the precondition, not merely failing to prove
    that it does.

    The marker leaves the deck's view in one rename, so a rollback interrupted
    midway can never leave a partially deleted store that still answers to
    `is_migrated`.
    """

    from .store import read_json

    marker = Path(thesis_dir) / MIGRATION_MARKER
    if not marker.exists():
        return False

    if not discard_edits:
        receipt = read_json(marker / MIGRATION_RECEIPT_KEY)
        promoted = receipt.get("revision") if isinstance(receipt, dict) else None
        head = read_json(marker / STORE_SUBPATH / HEAD_KEY)
        current = head.get("revision") if isinstance(head, dict) else None
        # Fail closed. A receipt or a HEAD that cannot be read is not evidence
        # that nothing was authored here, and what follows this check is a
        # deletion, so an unreadable pair is refused exactly like a moved one.
        if promoted is None or current is None:
            raise WorkspaceError(
                "PRES_MIGRATION_ROLLBACK_DIRTY",
                "this marker does not state what it promoted or where its store now stands, "
                "so what a rollback would discard cannot be established",
                status=409,
            )
        if current != promoted:
            raise WorkspaceError(
                "PRES_MIGRATION_ROLLBACK_DIRTY",
                f"revision {current} was authored after promotion and is not recorded in any legacy source",
                status=409,
            )

    retired = marker.parent / f".retired-{os.urandom(8).hex()}"
    try:
        os.replace(marker, retired)
    except OSError as error:
        raise WorkspaceError(
            "PRES_MIGRATION_ROLLBACK_FAILED",
            "the promoted marker could not be retired in one rename",
            status=500,
        ) from error
    fsync_directory(marker.parent)
    _discard(retired)
    return True


class LegacyReadAdapter:
    """The read-only compatibility window over a legacy tree.

    It answers legacy-shaped reads for a deck that has not been retired yet and
    refuses every write, so no new legacy authorship can appear during the
    window and a target mutation never round-trips into legacy sources.
    """

    def __init__(self, thesis_dir: Path) -> None:
        self.thesis_dir = thesis_dir

    def read(self) -> dict[str, Any]:
        return inventory_presentation(self.thesis_dir).as_dict()

    def write(self, *_: Any, **__: Any) -> None:
        raise WorkspaceError(
            "PRES_LEGACY_READ_ONLY",
            "the legacy compatibility window accepts no write; author in the target workspace",
            status=405,
        )


def retirement_census(theses_dir: Path) -> dict[str, Any]:
    """Count what is migrated and what still holds legacy authority.

    The census reads only public presentation trees under the directory it is
    given; it never opens private-vault content, and it reports the exact
    blockers standing between a deck and retirement.
    """

    decks: list[dict[str, Any]] = []
    for entry in sorted(_directories(theses_dir)):
        presentation_root = entry.joinpath(*PRESENTATION_SUBPATH)
        if not presentation_root.is_dir():
            continue
        inventory = inventory_presentation(entry)
        migrated = is_migrated(entry)
        decks.append(
            {
                "thesis": entry.name,
                "presentation_id": inventory.presentation_id,
                "slide_count": len(inventory.slides),
                "candidate_count": inventory.candidate_count,
                "order_source": inventory.order_source,
                "observed_layouts": sorted({slide.layout for slide in inventory.slides}),
                "migrated": migrated,
                "blockers": [item.as_dict() for item in inventory.blockers],
            }
        )
    return {
        "schema": CENSUS_SCHEMA,
        "root": str(theses_dir),
        "deck_count": len(decks),
        "migrated_count": sum(1 for deck in decks if deck["migrated"]),
        "unmigrated_count": sum(1 for deck in decks if not deck["migrated"]),
        "blocked_count": sum(1 for deck in decks if deck["blockers"]),
        "decks": decks,
    }


def _directories(root: Path) -> Iterable[Path]:
    if not root.is_dir():
        return ()
    return (entry for entry in root.iterdir() if entry.is_dir() and not entry.name.startswith("."))
