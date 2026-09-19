import hashlib
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from apps.web.backend.routers import authored_documents


@pytest.fixture
def rendering(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    directory = projects / "example" / "outputs" / "document"
    directory.mkdir(parents=True)
    (directory / "story.html").write_bytes(b"<!doctype html><h1>One document</h1>")
    (directory / "notes.json").write_text('{"private": "speaker text"}')
    (directory / "presentation.json").write_text(json.dumps({
        "schema": "doxagon.authored-document/1", "document": "story.html", "notes": "notes.json",
    }))
    monkeypatch.setattr(authored_documents, "THESES_DIR", projects)
    app = FastAPI()
    app.include_router(authored_documents.router, prefix="/api")
    return TestClient(app), directory


def test_selected_rendering_returns_pinned_urls_without_note_bodies(rendering):
    client, directory = rendering
    response = client.get("/api/theses/example/authored-document")
    digest = hashlib.sha256((directory / "story.html").read_bytes()).hexdigest()
    assert response.json() == {
        "filename": "story.html",
        "url": "/api/theses/example/authored-document/html",
        "renderUrl": f"/api/theses/example/authored-document/render/{digest}",
        "notesUrl": "/api/theses/example/authored-document/notes",
        "sha256": hashlib.sha256((directory / "story.html").read_bytes()).hexdigest(),
    }


def test_html_download_preserves_bytes_and_does_not_execute_on_api_origin(rendering):
    client, directory = rendering
    response = client.get("/api/theses/example/authored-document/html")
    assert (response.content, response.headers["content-type"], response.headers["content-disposition"], response.headers["cache-control"]) == (
        (directory / "story.html").read_bytes(), "application/octet-stream", "attachment", "no-store",
    )


def test_notes_download_is_separate_from_html(rendering):
    client, directory = rendering
    assert client.get("/api/theses/example/authored-document/notes").content == (directory / "notes.json").read_bytes()


def test_unselected_thesis_allows_legacy_fallback(rendering):
    client, directory = rendering
    (directory / "presentation.json").unlink()
    assert client.get("/api/theses/example/authored-document").status_code == 404


def test_missing_notes_do_not_prevent_opening_the_document(rendering):
    client, directory = rendering
    (directory / "notes.json").unlink()
    assert client.get("/api/theses/example/authored-document").status_code == 200


def test_broken_selection_does_not_silently_fall_back(rendering):
    client, directory = rendering
    (directory / "story.html").unlink()
    assert client.get("/api/theses/example/authored-document").status_code == 422


@pytest.mark.parametrize("document", ["../story.html", "/tmp/story.html", "..\\story.html", "notes.json", None])
def test_selection_cannot_name_unrelated_files(rendering, document):
    client, directory = rendering
    (directory / "presentation.json").write_text(json.dumps({"schema": "doxagon.authored-document/1", "document": document}))
    assert client.get("/api/theses/example/authored-document").status_code == 422


def test_symlink_cannot_escape_rendering_directory(rendering, tmp_path):
    client, directory = rendering
    target = tmp_path / "outside.html"
    target.write_text("not part of this presentation")
    (directory / "story.html").unlink()
    (directory / "story.html").symlink_to(target)
    assert client.get("/api/theses/example/authored-document/html").status_code == 422


def test_html_size_limit_is_enforced_before_returning_bytes(rendering, monkeypatch):
    client, _ = rendering
    monkeypatch.setattr(authored_documents, "MAX_HTML_BYTES", 2)
    assert client.get("/api/theses/example/authored-document/html").status_code == 422


def test_pending_multi_file_transaction_refuses_selection_html_and_notes(rendering):
    from doxagon.wal import _write_authority_generation
    client, directory = rendering
    vault = directory.parents[3]
    _write_authority_generation(vault, 1, 'a' * 32)
    for endpoint in ['', '/html', '/notes']:
        response = client.get('/api/theses/example/authored-document' + endpoint)
        assert response.status_code == 409
        assert response.json()['detail']['code'] == 'DOCUMENT_RECOVERY_PENDING'


def test_generation_change_during_response_is_a_conflict(rendering, monkeypatch):
    from doxagon.wal import _write_authority_generation
    client, directory = rendering
    vault = directory.parents[3]
    original = authored_documents._source
    def concurrent(*args):
        result = original(*args)
        _write_authority_generation(vault, 2, None)
        return result
    monkeypatch.setattr(authored_documents, '_source', concurrent)
    assert client.get('/api/theses/example/authored-document').status_code == 409


def test_notes_can_be_bound_to_the_playing_html_digest(rendering):
    client, _ = rendering
    assert client.get('/api/theses/example/authored-document/notes?document_sha256=' + '0' * 64).status_code == 409
