import base64
from hashlib import sha256
from io import BytesIO
import json

from click.testing import CliRunner
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
import pytest

from apps.web.backend.routers import document_workspace
from doxagon.renderings import document_inspection as inspection
from doxagon.renderings.document_cli import document_group
from doxagon.renderings.project import DocumentWorkspaceError, resolve_document_project
from tests.authored_vault import write_authored_project
from tests.synthetic_vault import png


@pytest.fixture
def project(tmp_path):
    write_authored_project(tmp_path)
    return resolve_document_project('observatory', cwd=tmp_path, environ={})


def tree(root):
    return {str(p.relative_to(root)): sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}


def test_used_payloads_notes_privacy_source_paging_and_no_writes(project):
    before = tree(project.vault)
    view = inspection.inspect_document(project)
    images = [x for x in view.items if x['kind'] == 'image']
    assert len(view.summary['usages']) == 11
    assert len(images) == 10
    assert len(images[0]['usages']) == 2
    assert all(x['provenance'] == 'unknown' for x in images)
    assert 'Introduce the synthetic' not in json.dumps(view.summary)
    assert 'data:image' not in json.dumps(view.summary)
    source = inspection.read_item(view, view.summary['document']['id'])
    assert 'data:image' not in source['text']
    assert '[embedded image payload]' in source['text']
    notes = inspection.read_item(view, view.summary['notes']['id'])
    assert 'Introduce the synthetic' in notes['text']
    raw, media = inspection.image_bytes(view, images[0]['id'], True)
    assert media == 'image/jpeg'
    assert Image.open(BytesIO(raw)).size == (8, 4)
    assert tree(project.vault) == before


def test_streaming_payloads_are_not_counted_as_extra_usages(project):
    data = base64.b64encode(png((10, 20, 30))).decode()
    project.path('outputs/document/observatory.html').write_text(
        '<img id="one" data-dox-asset="shared"><img id="two" data-dox-asset="shared">'
        f'<figure data-dox-source="shared"><img src="data:image/png;base64,{data}"></figure>'
    )
    view = inspection.inspect_document(project)
    assert len(view.summary['usages']) == 2
    assert len([x for x in view.items if x['kind'] == 'image']) == 1
    assert all(x['image'] for x in view.summary['usages'])


@pytest.mark.parametrize('change', ['document', 'config', 'notes', 'metadata', 'new_style'])
def test_any_included_input_change_conflicts(project, change):
    before = inspection.inspect_document(project)
    names = {'document': 'outputs/document/observatory.html', 'config': 'config.yaml',
             'notes': 'outputs/document/notes.json', 'metadata': 'outputs/document/authoring.json',
             'new_style': 'assets/styles/new/definition.md'}
    path = project.path(names[change])
    path.parent.mkdir(parents=True, exist_ok=True)
    if change in {'document', 'config', 'notes'}:
        path.write_bytes(path.read_bytes() + b'\n')
    else:
        path.write_text('{}' if change == 'metadata' else 'A new style')
    with pytest.raises(DocumentWorkspaceError) as error:
        inspection.inspect_document(project, before.summary['snapshot'])
    assert error.value.code == 'DOCUMENT_SNAPSHOT_CONFLICT'


@pytest.mark.parametrize('change', ['file', 'directory', 'pending'])
def test_cached_image_reads_rehash_inputs_without_reparsing(project, monkeypatch, change):
    monkeypatch.setattr(document_workspace, 'THESES_DIR', project.vault / 'projects')
    view = document_workspace.inspection(project.slug)
    def forbidden(*args):
        pytest.fail('A cached item should verify hashes without repeating the HTML parse')
    monkeypatch.setattr(document_workspace, 'inspect_project', forbidden)
    assert document_workspace.inspection(project.slug, view.summary['snapshot']) is view
    if change == 'file':
        path = project.path('config.yaml')
        path.write_bytes(path.read_bytes() + b'\n')
    elif change == 'directory':
        path = project.path('assets/styles/new/definition.md')
        path.parent.mkdir(parents=True)
        path.write_text('New input')
    else:
        from doxagon.wal import _write_authority_generation
        _write_authority_generation(project.vault, 1, 'a' * 32)
    with pytest.raises(DocumentWorkspaceError) as error:
        document_workspace.inspection(project.slug, view.summary['snapshot'])
    assert error.value.code in {'DOCUMENT_SNAPSHOT_CONFLICT', 'DOCUMENT_RECOVERY_PENDING'}


def provenance(project, entries):
    project.path('outputs/document/assets.json').write_text(json.dumps({'assets': entries}))


def test_missing_and_ambiguous_originals_do_not_invent_links(project):
    view = inspection.inspect_document(project)
    image = next(x for x in view.items if x['kind'] == 'image')
    hint = {'source': 'projects/observatory/assets/missing.png', 'embedded_sha256': image['sha256'], 'source_sha256': 'a'*64}
    provenance(project, [hint])
    current = inspection.inspect_document(project)
    assert next(x for x in current.items if x['id'] == image['id'])['provenance'] == 'missing_original'
    provenance(project, [hint, {**hint, 'source': 'projects/observatory/assets/another.png'}])
    current = inspection.inspect_document(project)
    observed = next(x for x in current.items if x['id'] == image['id'])
    assert observed['provenance'] == 'ambiguous'
    assert 'original' not in observed


def test_verified_and_drifted_original(project):
    view = inspection.inspect_document(project)
    image = next(x for x in view.items if x['kind'] == 'image')
    path = project.path('original.png')
    path.write_bytes(view.contents[image['id']])
    provenance(project, [{'source': 'projects/observatory/original.png', 'embedded_sha256': image['sha256'], 'source_sha256': image['sha256']}])
    assert next(x for x in inspection.inspect_document(project).items if x['id'] == image['id'])['provenance'] == 'verified_hash_pair'
    path.write_bytes(png((99, 99, 99)))
    assert next(x for x in inspection.inspect_document(project).items if x['id'] == image['id'])['provenance'] == 'stale_original'


def test_unknown_dynamic_duplicate_slots_and_invalid_images_are_explicit(project):
    path = project.path('outputs/document/observatory.html')
    path.write_text(path.read_text() + '<canvas></canvas><img id="slot-0" src="https://example.com/private.png"><img src="data:image/svg+xml;base64,PHN2Zy8+">')
    codes = {x['code'] for x in inspection.inspect_document(project).checks}
    assert {'duplicate_slot', 'unresolved_image', 'unresolved_dynamic', 'unsupported_image'} <= codes


def test_oversized_html_returns_a_typed_limit(project, monkeypatch):
    monkeypatch.setattr(inspection, 'MAX_HTML', 32)
    with pytest.raises(DocumentWorkspaceError) as error:
        inspection.inspect_document(project)
    assert error.value.code == 'DOCUMENT_LIMIT'


def test_edit_during_snapshot_assembly_is_a_conflict(project, monkeypatch):
    original = inspection.Inventory.finish
    def edit(inventory):
        original(inventory)
        project.path('config.yaml').write_text('name: observatory\ntitle: Changed during read\n')
    monkeypatch.setattr(inspection.Inventory, 'finish', edit)
    with pytest.raises(DocumentWorkspaceError) as error:
        inspection.inspect_document(project)
    assert error.value.code == 'DOCUMENT_SNAPSHOT_CONFLICT'


def test_css_images_and_svg_markup_are_inspected_without_execution(project):
    data = base64.b64encode(png((30, 60, 90))).decode()
    project.path('outputs/document/observatory.html').write_text(
        f'<div style="background-image:url(data:image/png;base64,{data})"></div>'
        '<svg viewBox="0 0 10 10"><circle cx="5" cy="5" r="4"/></svg>'
    )
    view = inspection.inspect_document(project)
    assert len(view.summary['usages']) == 1
    svg = next(x for x in view.items if x['kind'] == 'svg')
    assert inspection.read_item(view, svg['id'])['text'] == '<svg viewBox="0 0 10 10"><circle cx="5" cy="5" r="4"/></svg>'


def test_source_and_project_symlink_escapes_are_refused(project):
    outside = project.vault / 'secret.json'
    outside.write_text('{}')
    project.path('outputs/document/authoring.json').symlink_to(outside)
    with pytest.raises(DocumentWorkspaceError) as error:
        inspection.inspect_document(project)
    assert error.value.code == 'DOCUMENT_PATH_ESCAPE'


def test_pending_wal_is_not_presented_as_current(project):
    directory = project.vault / '.doxagon'
    directory.mkdir()
    (directory / 'authority-generation.json').write_text(json.dumps({'generation': 1, 'active_txid': 'pending'}))
    with pytest.raises(DocumentWorkspaceError) as error:
        inspection.inspect_document(project)
    assert error.value.code == 'DOCUMENT_RECOVERY_PENDING'


def test_cli_api_and_alias_context_share_snapshot_and_stale_routes_conflict(project, monkeypatch):
    monkeypatch.setattr(document_workspace, 'THESES_DIR', project.vault / 'theses')
    app = FastAPI()
    app.include_router(document_workspace.router, prefix='/api')
    client = TestClient(app)
    base = '/api/theses/observatory/document-workspace'
    api = client.get(base).json()
    monkeypatch.chdir(project.vault / 'theses' / 'observatory')
    monkeypatch.delenv('DOXAGON_ROOT', raising=False)
    result = CliRunner().invoke(document_group, ['context', '--json'])
    assert result.exit_code == 0, result.output
    cli = json.loads(result.output)
    assert {key: cli[key] for key in api} == api
    assert cli['environment']['project_root'] == str(project.root)
    image = next(x for x in api['items'] if x['kind'] == 'image')
    path = f"{base}/items/{image['id']}/image?snapshot={api['snapshot']}"
    assert client.get(path).status_code == 200
    assert client.get(f"{base}/items/not-an-id?snapshot={api['snapshot']}").status_code == 404
    project.path('config.yaml').write_text('name: observatory\ntitle: New title\n')
    response = client.get(path)
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'DOCUMENT_SNAPSHOT_CONFLICT'


def test_registered_unused_styles_and_reference_changes_are_included(project):
    style = project.path('assets/styles/unused/definition.md')
    style.parent.mkdir(parents=True)
    style.write_text('---\nsources: [reference.png]\n---\nSaved style constraints')
    source = style.parent / 'sources/reference.png'
    source.parent.mkdir()
    source.write_bytes(png((10, 20, 30)))
    view = inspection.inspect_document(project)
    assert any(x['kind'] == 'generation_style' for x in view.items)
    assert any(x['kind'] == 'reference' for x in view.items)
    source.write_bytes(png((20, 30, 40)))
    with pytest.raises(DocumentWorkspaceError, match='new revision'):
        inspection.inspect_document(project, view.summary['snapshot'])
