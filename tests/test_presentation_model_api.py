"""The thesis list distinguishes the two rendering models.

A document-model thesis keeps one authored HTML selected by
``outputs/document/presentation.json`` and has no ``outputs/presentation/``
directory at all, so reading ``has_presentation`` from that legacy path made it
report no presentation and suppressed the only link to it from the diegesis.

The fixtures here are the shapes the real producers write: the document
selection is exactly what ``dox scaffold-document`` emits
(``scripts/dox.py`` ``presentation.json``) and what
``apps/web/backend/routers/authored_documents.py`` reads, and the legacy slide
tree is exactly what ``count_slides`` walks.
"""

import json

from fastapi.testclient import TestClient

from apps.web.backend.main import app
from apps.web.backend.routers import diegeses, theses


client = TestClient(app)


def write_thesis_config(thesis_dir, slug, diegesis="n-example"):
    thesis_dir.mkdir(parents=True, exist_ok=True)
    (thesis_dir / "config.yaml").write_text(
        f"title: {slug} title\ndiegesis: {diegesis}\nwalk: canonical\n", encoding="utf-8",
    )


def write_document_thesis(theses_dir, slug="brand", diegesis="n-example"):
    """A document-model project: a selected authored HTML and no slide tree."""
    thesis_dir = theses_dir / slug
    write_thesis_config(thesis_dir, slug, diegesis)
    document = thesis_dir / "outputs" / "document"
    document.mkdir(parents=True)
    (document / f"{slug}.html").write_text("<!doctype html><h1>One document</h1>", encoding="utf-8")
    (document / "presentation.json").write_text(
        json.dumps({"schema": "doxagon.authored-document/1", "document": f"{slug}.html"}), encoding="utf-8",
    )
    return thesis_dir


def write_slides_thesis(theses_dir, slug="burrow", diegesis="n-example", slides=2, with_images=1):
    """A legacy project: per-slide sources under outputs/presentation/slides/."""
    thesis_dir = theses_dir / slug
    write_thesis_config(thesis_dir, slug, diegesis)
    for index in range(slides):
        slide_dir = thesis_dir / "outputs" / "presentation" / "slides" / f"0{index + 1}-part"
        slide_dir.mkdir(parents=True)
        images = (
            "images:\n  - id: main\n    selected: outputs/one.png\n" if index < with_images else ""
        )
        (slide_dir / "slide.md").write_text(
            f"---\ntext:\n  title: Part {index + 1}\n{images}---\n", encoding="utf-8",
        )
    return thesis_dir


def thesis_list(tmp_path, monkeypatch):
    theses_dir = tmp_path / "theses"
    theses_dir.mkdir()
    monkeypatch.setattr(theses, "THESES_DIR", theses_dir)
    monkeypatch.setattr(diegeses, "THESES_DIR", theses_dir)
    return theses_dir


def test_document_model_thesis_reports_a_presentation_without_a_slides_directory(tmp_path, monkeypatch):
    """AC-27: the flag follows the selected document, not outputs/presentation/."""
    theses_dir = thesis_list(tmp_path, monkeypatch)
    thesis_dir = write_document_thesis(theses_dir)
    assert not (thesis_dir / "outputs" / "presentation").exists()

    listed = client.get("/api/theses").json()

    assert [(item["slug"], item["has_presentation"], item["presentation_model"]) for item in listed] == [
        ("brand", True, "document"),
    ]


def test_legacy_slides_thesis_keeps_its_counts_and_is_named_a_slides_model(tmp_path, monkeypatch):
    """AC-29 and AC-30: legacy values are unchanged and the model is explicit."""
    theses_dir = thesis_list(tmp_path, monkeypatch)
    write_slides_thesis(theses_dir)

    listed = client.get("/api/theses").json()

    assert listed == [{
        "slug": "burrow", "name": "burrow title", "diegesis": "n-example", "walk": "canonical",
        "slide_count": 2, "slides_with_images": 1, "has_presentation": True,
        "presentation_model": "slides", "has_essay": False,
    }]


def test_the_list_separates_a_document_from_a_legacy_project(tmp_path, monkeypatch):
    """AC-30: one caller can tell the models apart without touching the disk."""
    theses_dir = thesis_list(tmp_path, monkeypatch)
    write_document_thesis(theses_dir)
    write_slides_thesis(theses_dir)

    listed = client.get("/api/theses").json()

    assert {item["slug"]: item["presentation_model"] for item in listed} == {
        "brand": "document", "burrow": "slides",
    }


def test_a_thesis_with_neither_rendering_reports_no_presentation(tmp_path, monkeypatch):
    theses_dir = thesis_list(tmp_path, monkeypatch)
    write_thesis_config(theses_dir / "bare", "bare")

    listed = client.get("/api/theses").json()

    assert [(item["has_presentation"], item["presentation_model"]) for item in listed] == [(False, "none")]


def test_a_selected_document_beside_legacy_slides_reports_the_model_that_plays(tmp_path, monkeypatch):
    """Playback resolves the authored selection first, so the document wins."""
    theses_dir = thesis_list(tmp_path, monkeypatch)
    thesis_dir = write_slides_thesis(theses_dir, slug="both")
    document = thesis_dir / "outputs" / "document"
    document.mkdir(parents=True)
    (document / "both.html").write_text("<!doctype html><h1>One document</h1>", encoding="utf-8")
    (document / "presentation.json").write_text(
        json.dumps({"schema": "doxagon.authored-document/1", "document": "both.html"}), encoding="utf-8",
    )

    listed = client.get("/api/theses").json()

    assert [(item["presentation_model"], item["slide_count"]) for item in listed] == [("document", 2)]


def test_diegesis_thesis_refs_name_the_model_for_both_kinds(tmp_path, monkeypatch):
    """The second producer of this flag answers identically to the first."""
    theses_dir = thesis_list(tmp_path, monkeypatch)
    write_document_thesis(theses_dir, diegesis="n-example")
    write_slides_thesis(theses_dir, diegesis="n-example")

    refs = diegeses.find_theses_for_diegesis("n-example")

    assert {ref.slug: (ref.has_presentation, ref.presentation_model) for ref in refs} == {
        "brand": (True, "document"), "burrow": (True, "slides"),
    }
