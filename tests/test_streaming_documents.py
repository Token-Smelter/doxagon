import base64
import hashlib
from io import BytesIO

from fastapi.testclient import TestClient
from fastapi import FastAPI
from PIL import Image
import pytest

from apps.web.backend.routers import authored_documents
from scripts.prepare_streaming_document import repack, RUNTIME


@pytest.fixture
def selected(tmp_path, monkeypatch):
    root = tmp_path / "example" / "outputs" / "document"
    root.mkdir(parents=True)
    (root / "presentation.json").write_text('{"schema":"doxagon.authored-document/1","document":"story.html"}')
    content = b"<!doctype html><h1>Selected revision</h1>"
    (root / "story.html").write_bytes(content)
    monkeypatch.setattr(authored_documents, "THESES_DIR", tmp_path)
    app = FastAPI()
    app.include_router(authored_documents.router, prefix="/api")
    client = TestClient(app)
    url = client.get("/api/theses/example/authored-document").json()["renderUrl"]
    return client, root, content, url


def test_render_delivers_exact_selected_bytes_under_response_isolation(selected):
    client, _, content, url = selected
    response = client.get(url)
    assert (response.status_code, response.content, response.headers["content-type"],
            response.headers["content-security-policy"], response.headers["content-disposition"],
            response.headers["referrer-policy"]) == (
        200, content, "text/html; charset=utf-8", authored_documents.DOCUMENT_CSP, "inline", "no-referrer",
    )


def test_render_rejects_changed_content_before_executing_it(selected):
    client, root, _, url = selected
    (root / "story.html").write_text("<script>window.changed=true</script>")
    response = client.get(url)
    assert (response.status_code, "window.changed" in response.text) == (409, False)


def test_render_uses_same_memory_snapshot_that_was_verified(selected, monkeypatch):
    client, root, content, url = selected
    original = authored_documents._source

    def racing_source(*args):
        result = original(*args)
        (root / "story.html").write_text("<script>window.changed=true</script>")
        return result

    monkeypatch.setattr(authored_documents, "_source", racing_source)
    assert client.get(url).content == content


def test_render_keeps_existing_path_confinement(selected, tmp_path):
    client, root, content, url = selected
    outside = tmp_path / "outside.html"
    outside.write_bytes(content)
    (root / "story.html").unlink()
    (root / "story.html").symlink_to(outside)
    assert client.get(url).status_code == 422


def test_render_keeps_existing_size_limit(selected, monkeypatch):
    client, _, _, url = selected
    monkeypatch.setattr(authored_documents, "MAX_HTML_BYTES", 1)
    assert client.get(url).status_code == 422


def test_packer_moves_exact_image_bytes_after_structure_and_navigation():
    image = BytesIO()
    Image.new("RGB", (4, 3), "white").save(image, "PNG")
    encoded = base64.b64encode(image.getvalue()).decode()
    source = f'''<!doctype html><html><head></head><body>
    <main><section class="chapter" id="opening"><img src="data:image/png;base64,{encoded}" alt="Plate">
    <p data-cue="first">Caption stays here</p></section></main>
    <script>/* doxagon:connect, doxagon:position */
    const popupHtml = '<html><head></head><body>Private popup template</body></html>';
    window.navigation = true;</script>
    </body></html>'''
    result = repack(source, RUNTIME.read_text())
    assert (
        result.index("window.navigation = true") < result.index("doxagon:available") < result.index(encoded),
        result.count(encoded),
        f'asset-{hashlib.sha256(image.getvalue()).hexdigest()}' in result,
        'width="4" height="3"' in result,
        '<p data-cue="first">Caption stays here</p>' in result,
        "<noscript>" in result,
        "const popupHtml = '<html><head></head><body>Private popup template</body></html>';" in result,
    ) == (True, 1, True, True, True, True, True)


def test_packer_refuses_an_unresolved_external_image():
    source = '<html><head></head><body><img src="missing.webp"><script>/* doxagon:connect doxagon:position */</script></body></html>'
    with pytest.raises(ValueError, match="already be embedded"):
        repack(source, RUNTIME.read_text())
