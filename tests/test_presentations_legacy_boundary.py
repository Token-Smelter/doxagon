"""The boundary between the target system and the legacy compatibility window.

The legacy slide surfaces still exist on purpose: the design keeps a read-only
compatibility window until inventory reports zero unmigrated decks. What must
not exist is legacy authority *inside* the target — a slide cursor, a layout
mode, an image selection, a second runtime, or a relative step protocol reaching
back across the boundary.

These are source-level assertions over the real files, not over a description of
them, so a future edit that reintroduces one of those semantics fails here.
"""

from __future__ import annotations

from pathlib import Path
import re

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]

FRONTEND = ROOT / "apps" / "web" / "frontend" / "src"

# The whole product surface, not just the old workbench: `/presentations` is
# the primary editor and viewer now, so the retired vocabulary must be absent
# from it, from the presenter route, and from the audience display too.
TARGET_TREES = (
    ROOT / "src" / "doxagon" / "presentations",
    FRONTEND / "lib" / "presentation",
    FRONTEND / "lib" / "components" / "deck",
    FRONTEND / "lib" / "components" / "presentation",
    FRONTEND / "routes" / "decks",
    FRONTEND / "routes" / "presentations",
    FRONTEND / "routes" / "present",
)

TARGET_FILES = (FRONTEND / "lib" / "components" / "PresentationWorkspace.svelte",)

#: The primary editor and viewer. `/decks` is no longer one of them.
PRIMARY_EDITOR = FRONTEND / "lib" / "components" / "PresentationWorkspace.svelte"
PRIMARY_ROUTE = FRONTEND / "routes" / "presentations" / "+page.svelte"
RETIRED_ROUTE = FRONTEND / "routes" / "decks" / "+page.svelte"

#: The client every non-presentation page imports. It is the public surface the
#: rest of the app can reach, so a retired authority declared here is reachable
#: no matter what the presentation tree does.
PUBLIC_CLIENT = FRONTEND / "lib" / "api.ts"

#: Any viewport *height* unit, in every spelling. Only the app shell may own
#: one: a second declaration below it double-counts the global header, which is
#: how a stage grows taller than the screen it is drawn on.
VIEWPORT_HEIGHT = re.compile(r"\d+(?:\.\d+)?(?:d|s|l)?vh\b")

# Vocabulary that would reintroduce slide-first authority or image selection.
RETIRED = (
    "is_primary",
    "isPrimary",
    "slide_index",
    "slideIndex",
    "stepIndex",
    "Display Image",
    "has_selected_image",
)

LEGACY_MODULES = ("htmlSlideMount", "slideController", "broadcastSync", "PresentationViewer")


def target_files() -> list[Path]:
    found: list[Path] = [path for path in TARGET_FILES if path.is_file()]
    for tree in TARGET_TREES:
        found.extend(
            path
            for path in sorted(tree.rglob("*"))
            if path.is_file() and path.suffix in {".py", ".ts", ".js", ".svelte"}
        )
    return found


@pytest.mark.parametrize("path", target_files(), ids=lambda path: str(path.relative_to(ROOT)))
def test_a_target_file_carries_no_retired_vocabulary(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    # `contracts.LEGACY_FIELDS` names the retired members in order to reject
    # them, so the rejection list itself is the one legitimate mention.
    if path.name in {"contracts.py", "cursor.py", "migration.py"}:
        pytest.skip("this file names the legacy vocabulary in order to refuse or record it")
    found = [token for token in RETIRED if token in text]
    assert found == [], f"{path.relative_to(ROOT)} reintroduces {found}"


@pytest.mark.parametrize("path", target_files(), ids=lambda path: str(path.relative_to(ROOT)))
def test_no_target_surface_imports_a_legacy_slide_module(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    imported = [module for module in LEGACY_MODULES if f"{module}'" in text or f'{module}"' in text or f"/{module}" in text]
    assert imported == [], f"{path.relative_to(ROOT)} reaches into the legacy runtime: {imported}"


def test_the_legacy_mount_is_not_reachable_from_the_step_workspace() -> None:
    """The legacy same-origin iframe mount stays outside the target surface.

    ``htmlSlideMount`` created a script-enabled *same-origin* frame; the target
    realm is opaque-origin by construction. The primary editor talks to the
    revisioned workspace client and to nothing legacy.
    """

    editor = PRIMARY_EDITOR.read_text(encoding="utf-8")
    assert "htmlSlideMount" not in editor
    assert "$lib/presentation/deck" in editor


def test_the_primary_route_opens_the_selected_vault_presentation() -> None:
    """Both formats retain the workspace after resolving the selected source.

    Selection must happen before mounting the workspace, otherwise its old
    audience renderer can diverge from the document shown by the presenter.
    """

    route = PRIMARY_ROUTE.read_text(encoding="utf-8")
    view = (FRONTEND / "lib" / "components" / "presentation" / "PresentationView.svelte").read_text(encoding="utf-8")
    assert "PresentationView" in route
    assert "findAuthoredDocument(presentationSlug)" in view
    assert "documentSource={source}" in view
    assert "<DocumentPlayer" not in view
    assert "<PresentationWorkspace {presentationSlug}" in view
    assert "PresentationViewer" not in route + view
    assert "presentationSlug" in route


def test_the_retired_decks_route_holds_no_state_or_runtime() -> None:
    """One authoritative workspace means `/decks` cannot be a second one."""

    retired = RETIRED_ROUTE.read_text(encoding="utf-8")
    assert "/presentations" in retired
    assert "presentationClient" not in retired
    assert "CheckpointPreview" not in retired


def test_no_presentation_surface_declares_a_viewport_height() -> None:
    """The shell owns the viewport; nothing mounted inside it re-declares one.

    This covers `dvh`, `svh`, and `lvh` as well as `vh`, because every one of
    them resolves against the viewport rather than against the box the shell
    actually gave the component. A component that needs its container's height
    measures the container (container query units), which is what the audience
    overlay does.
    """

    offenders = sorted(
        f"{path.relative_to(ROOT)}:{index + 1}"
        for path in target_files()
        if path.suffix == ".svelte"
        for index, line in enumerate(path.read_text(encoding="utf-8").splitlines())
        if VIEWPORT_HEIGHT.search(line)
    )
    assert offenders == []


def test_the_public_client_declares_no_selection_or_layout_authority() -> None:
    """The compatibility window is read-only, including in its type surface.

    A declared member is a member some call site will reach for. `layout`,
    `has_selected_image`, and `updateSlideLayout` were the reachable ways the
    public client carried a slide's display mode and image selection, so their
    absence — not a comment saying they are gone — is what makes the window
    read-only.
    """

    code = "\n".join(
        line
        for line in PUBLIC_CLIENT.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith(("//", "*", "/*"))
    )
    retired = (
        "has_selected_image",
        "updateSlideLayout",
        "updateSlideHtml",
        "updateSlideText",
        "createImageBundle",
        "updateImageDefinition",
        "layout",
        "is_primary",
        "selected",
    )
    assert [token for token in retired if token in code] == []


def test_no_client_source_resolves_a_display_image() -> None:
    """The `images[0]` fallback and the primary flag are gone from the client.

    These were the only reachable ways the product chose one bundle to show, so
    their absence is what makes every media item equal rather than a claim that
    they are.
    """

    def code_of(path: Path) -> str:
        # A comment naming a retired member in order to record that it is gone
        # is documentation, not a reachable decision; only real statements can
        # resolve a display image.
        return "\n".join(
            line
            for line in path.read_text(encoding="utf-8").splitlines()
            if not line.lstrip().startswith(("//", "*", "/*", "<!--"))
        )

    offenders = sorted(
        str(path.relative_to(ROOT))
        for path in FRONTEND.rglob("*")
        if path.is_file()
        and path.suffix in {".ts", ".svelte"}
        and any(
            token in code_of(path)
            for token in ("findDisplayImage", "setPrimaryImage", "is_primary", "images[0]")
        )
    )
    assert offenders == []


# --- the compatibility window is read-only once authority has moved ---------


def migrated_legacy_thesis(root: Path) -> str:
    """Synthesise one legacy deck and promote it, returning its slug."""

    from doxagon.presentations import inventory_presentation, promote
    from doxagon.presentations.migration import MIGRATION_MARKER
    from tests.test_presentations_migration import legacy_deck

    thesis = legacy_deck(root)
    promote(inventory_presentation(thesis), thesis / MIGRATION_MARKER)
    return thesis.name


@pytest.fixture()
def legacy_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The production app with its thesis root pointed at synthetic content."""

    from apps.web.backend import main
    from apps.web.backend.routers import theses

    monkeypatch.setattr(theses, "THESES_DIR", tmp_path)
    with TestClient(main.app) as client:
        yield client


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", "/api/theses/{slug}/slides", {"title": "New"}),
        ("put", "/api/theses/{slug}/slides/order", {"order": ["01-opening"]}),
        ("put", "/api/theses/{slug}/slides/01-opening/images/main/selected", {"selected": "outputs/one.png"}),
        ("put", "/api/theses/{slug}/slides/01-opening/images/main/primary", {}),
        ("put", "/api/theses/{slug}/slides/01-opening/html", {"html": "<p>x</p>"}),
        ("put", "/api/theses/{slug}/slides/01-opening/layout", {"layout": "image"}),
        ("put", "/api/theses/{slug}/slides/01-opening/text", {"title": "x", "body": "y"}),
    ],
)
def test_a_migrated_legacy_deck_refuses_every_legacy_write(
    legacy_client: TestClient, tmp_path: Path, method: str, path: str, body: dict
) -> None:
    """Authority moved, so legacy authorship is refused rather than forked.

    These are the exact mutation routes the reviewer found still mounted:
    slide creation, order, image selection, primary image, HTML, layout, and
    text. After promotion each answers through the `LegacyReadAdapter` refusal.
    """

    slug = migrated_legacy_thesis(tmp_path)

    response = getattr(legacy_client, method)(path.format(slug=slug), json=body)

    assert response.status_code == 405
    assert response.json()["code"] == "PRES_LEGACY_READ_ONLY"


def test_an_unmigrated_legacy_deck_still_answers_writes(legacy_client: TestClient, tmp_path: Path) -> None:
    """The window stays open until a deck is actually promoted.

    Without this, the gate could be closing on every deck and the refusal test
    above would prove nothing about migration state.
    """

    from tests.test_presentations_migration import legacy_deck

    slug = legacy_deck(tmp_path).name

    response = legacy_client.put(
        f"/api/theses/{slug}/slides/01-opening/layout",
        json={"layout": "image"},
    )

    assert response.status_code != 405


def test_a_migrated_legacy_deck_still_answers_reads(legacy_client: TestClient, tmp_path: Path) -> None:
    """Read-only means read, not gone: the compatibility window still serves."""

    slug = migrated_legacy_thesis(tmp_path)

    response = legacy_client.get(f"/api/theses/{slug}/slides")

    assert response.status_code == 200


def test_exactly_one_source_file_declares_the_runtime_version() -> None:
    """One runtime means one authored copy of it.

    Derived trees are excluded because a build artifact is a copy of the
    canonical file, not a second runtime: `apps/web/frontend/build` is written
    by `vite build`, and the served `static/presentation-runtime.js` is a
    symlink to the same bytes.
    """

    from doxagon.presentations import RUNTIME_VERSION

    derived = {"node_modules", ".svelte-kit", "build", "dist", "test-results"}
    declaring = sorted(
        str(path.relative_to(ROOT))
        for path in ROOT.rglob("*.js")
        if derived.isdisjoint(path.parts)
        and not path.is_symlink()
        and RUNTIME_VERSION in path.read_text(encoding="utf-8", errors="ignore")
    )
    assert declaring == ["src/doxagon/presentations/resources/runtime.js"]
