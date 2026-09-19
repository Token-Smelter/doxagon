"""`dox scaffold` emits a playable document, not a legacy slide tree."""

from pathlib import Path
import json
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def run(vault: Path, *arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "scripts.dox", "scaffold", *arguments],
        cwd=ROOT, capture_output=True, text=True,
        env={"DOXAGON_ROOT": str(vault), "PYTHONPATH": f"{ROOT}:{ROOT / 'src'}", "PATH": "/usr/bin:/bin"},
    )


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    """A diegesis that declares its structure the way real ones do."""
    (tmp_path / "knowledge" / "diegeses").mkdir(parents=True)
    (tmp_path / "knowledge" / "doxai").mkdir(parents=True)
    (tmp_path / "knowledge" / "diegeses" / "n-example.md").write_text(
        # Written literally: narrative order is the point of a diegesis, and
        # yaml.safe_dump would sort these keys alphabetically, which no real
        # file does.
        "---\n"
        "id: n-example\n"
        "title: An Example\n"
        "sections:\n"
        "  opening:\n    title: Opening\n    doxai:\n      - d-first\n      - d-second\n"
        "  closing:\n    title: Closing\n    doxai:\n      - d-third\n"
        "---\n\nProse with no [[d-]] links, as most diegeses have.\n"
    )
    for name, belief in [("d-first", "The first belief."), ("d-second", "The second."), ("d-third", "The third.")]:
        (tmp_path / "knowledge" / "doxai" / f"{name}.md").write_text(
            f"---\nid: {name}\nbelief: {belief}\n---\n"
        )
    # The real vault ships `library` as a symlink to `knowledge`, and the
    # CLI resolves diegeses through LIBRARY_DIR. Mirror that here rather
    # than asserting against a layout no vault has.
    (tmp_path / "library").symlink_to(tmp_path / "knowledge")
    return tmp_path


def test_scaffold_emits_a_selectable_document(vault: Path) -> None:
    """The three files the player reads, with cues in diegesis order.

    The previous implementation parsed `##` headings for `[[d-*]]` links and
    wrote a slide directory per section. Most diegeses carry no such links, so
    it failed on them; and a slide tree is not what a migrated project renders.
    """
    out = vault / "projects" / "example" / "outputs" / "document"
    assert run(vault, "example", "--output", str(out)).returncode == 0

    selection = json.loads((out / "presentation.json").read_text())
    notes = json.loads((out / "notes.json").read_text())
    html = (out / selection["document"]).read_text()

    assert selection["schema"] == "doxagon.authored-document/1"
    assert [cue["id"] for cue in notes["cues"]] == ["d-first", "d-second", "d-third"]
    assert notes["edition"] in html and notes["documentId"] in html
    assert html.count('data-cue="') == 3
    assert not (vault / "projects" / "example" / "outputs" / "presentation").exists()


def test_cue_order_follows_the_diegesis_not_the_alphabet(vault: Path) -> None:
    """Narrative order is the diegesis's contribution; sorting would destroy it.

    `closing` precedes `opening` alphabetically, so a loader that sorted keys
    would reverse the argument while still producing a plausible-looking deck.
    """
    out = vault / "out"
    assert run(vault, "example", "--output", str(out)).returncode == 0
    html = (out / "example.html").read_text()
    assert html.index('id="opening"') < html.index('id="closing"')


def test_scaffold_refuses_a_diegesis_with_no_sections(vault: Path) -> None:
    """Silence would leave an empty deck that looks authored."""
    (vault / "knowledge" / "diegeses" / "n-empty.md").write_text("---\nid: n-empty\n---\n\nNothing.\n")
    result = run(vault, "empty", "--output", str(vault / "out"))
    assert result.returncode == 1 and "sections" in result.stderr


def test_scaffold_will_not_silently_replace_an_authored_document(vault: Path) -> None:
    out = vault / "projects" / "example" / "outputs" / "document"
    assert run(vault, "example", "--output", str(out)).returncode == 0
    (out / "example.html").write_text("<!-- hand-authored -->")
    assert run(vault, "example", "--output", str(out)).returncode == 1
    assert (out / "example.html").read_text() == "<!-- hand-authored -->"
    assert run(vault, "example", "--output", str(out), "--force").returncode == 0
    assert (out / "example.html").read_text() != "<!-- hand-authored -->"
