from fastapi.testclient import TestClient

from apps.web.backend.main import app
from apps.web.backend.routers import theses


client = TestClient(app)


def write_slide(theses_dir, thesis_slug, slide_slug, title, doxai):
    thesis_dir = theses_dir / thesis_slug
    (thesis_dir / "outputs" / "presentation" / "slides" / slide_slug).mkdir(parents=True)
    (thesis_dir / "config.yaml").write_text(
        f"title: {thesis_slug} title\ndiegesis: test\nwalk: canonical\n",
        encoding="utf-8",
    )
    (thesis_dir / "outputs" / "presentation" / "slides" / slide_slug / "slide.md").write_text(
        f"---\ntext:\n  title: {title}\ndoxai:\n" + "".join(f"  - {doxa}\n" for doxa in doxai) + "---\n",
        encoding="utf-8",
    )


def test_slide_usages_returns_sorted_metadata_only_and_skips_malformed(tmp_path, monkeypatch):
    theses_dir = tmp_path / "theses"
    theses_dir.mkdir()
    monkeypatch.setattr(theses, "THESES_DIR", theses_dir)

    write_slide(theses_dir, "zeta", "02-later", "Later", ["d-example"])
    write_slide(theses_dir, "alpha", "02-second", "Second", ["d-example"])
    write_slide(theses_dir, "alpha", "01-first", "First", ["d-example"])
    (theses_dir / "alpha" / "outputs" / "presentation" / "config.yaml").write_text(
        "slide_order:\n  - 01-first\n  - 02-second\n", encoding="utf-8"
    )
    malformed = theses_dir / "zeta" / "outputs" / "presentation" / "slides" / "03-bad"
    malformed.mkdir()
    (malformed / "slide.md").write_text("---\nnot: [valid\n", encoding="utf-8")

    response = client.get("/api/theses/slide-usages?doxa=d-example")

    assert response.status_code == 200
    assert response.json() == [
        {"thesis_slug": "alpha", "thesis_title": "alpha title", "slide_slug": "01-first", "slide_number": 1, "slide_title": "First"},
        {"thesis_slug": "alpha", "thesis_title": "alpha title", "slide_slug": "02-second", "slide_number": 2, "slide_title": "Second"},
        {"thesis_slug": "zeta", "thesis_title": "zeta title", "slide_slug": "02-later", "slide_number": 2, "slide_title": "Later"},
    ]


def test_slide_usages_emits_canonical_slug_for_semantic_order(tmp_path, monkeypatch):
    theses_dir = tmp_path / "theses"
    theses_dir.mkdir()
    monkeypatch.setattr(theses, "THESES_DIR", theses_dir)
    write_slide(theses_dir, "alpha", "01-first", "First", ["d-example"])
    (theses_dir / "alpha" / "outputs" / "presentation" / "config.yaml").write_text(
        "slide_order:\n  - first\n", encoding="utf-8"
    )

    response = client.get("/api/theses/slide-usages?doxa=d-example")

    assert response.status_code == 200
    assert response.json() == [
        {"thesis_slug": "alpha", "thesis_title": "alpha title", "slide_slug": "01-first", "slide_number": 1, "slide_title": "First"},
    ]
    assert client.get("/api/theses/alpha/slides/01-first").status_code == 200
    assert client.get("/api/theses/alpha/slides/first").status_code == 200


def test_slide_usages_rejects_invalid_slug_and_skips_out_of_root_configured_slide(tmp_path, monkeypatch):
    theses_dir = tmp_path / "theses"
    theses_dir.mkdir()
    monkeypatch.setattr(theses, "THESES_DIR", theses_dir)
    write_slide(theses_dir, "alpha", "01-first", "First", ["d-other"])
    private_slide = theses_dir / "alpha" / "outputs" / "presentation" / "private"
    private_slide.mkdir()
    (private_slide / "slide.md").write_text(
        "---\ntext:\n  title: Private\ndoxai:\n  - d-example\n---\n", encoding="utf-8"
    )
    (theses_dir / "alpha" / "outputs" / "presentation" / "config.yaml").write_text(
        "slide_order:\n  - ../private\n", encoding="utf-8"
    )

    assert client.get("/api/theses/slide-usages?doxa=../private").status_code == 400
    assert client.get("/api/theses/slide-usages?doxa=d-example").json() == []


def test_slide_usages_static_route_precedes_thesis_slug_route(tmp_path, monkeypatch):
    theses_dir = tmp_path / "theses"
    theses_dir.mkdir()
    monkeypatch.setattr(theses, "THESES_DIR", theses_dir)

    response = client.get("/api/theses/slide-usages?doxa=d-example")

    assert response.status_code == 200
    assert response.json() == []
