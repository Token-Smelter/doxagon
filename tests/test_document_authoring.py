import base64
import json

import pytest

from doxagon.renderings.document_assets import plan_adopt_bundle, plan_bind_slots, plan_select_image
from doxagon.renderings.document_changes import apply_plan, plan_text_change
from doxagon.renderings.document_images import ImageDocument, encode_variant, replace_slots
from doxagon.renderings.document_inspection import inspect_document, sha
from doxagon.renderings.project import DocumentWorkspaceError, resolve_document_project
from tests.authored_vault import write_authored_project
from tests.synthetic_vault import png


@pytest.fixture
def project(tmp_path):
    write_authored_project(tmp_path)
    return resolve_document_project('observatory', cwd=tmp_path, environ={})


def write(project, path, raw):
    target = project.path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)


def legacy(project):
    source = 'outputs/presentation/slides/01/images/main'
    write(project, source + '/definition.md', b'---\nstyles: [ink]\n---\nA scene.\n')
    write(project, source + '/sources/ref.png', png((1, 2, 3)))
    write(project, source + '/outputs/original.png', png((4, 5, 6)))
    write(project, source + '/outputs/.thumb_original.png', png((4, 5, 6)))
    write(project, source + '/outputs/original.prompt.md', b'An exact historical prompt.\n')
    write(project, source + '/outputs/original.provenance.json', b'{"model":"unknown"}\n')
    write(project, 'outputs/presentation/styles/ink/definition.md', b'---\nrequires: [paper]\n---\nInk.\n')
    write(project, 'outputs/presentation/styles/paper/definition.md', b'Paper.\n')
    return source


def test_caption_apply_checks_browser_and_rejects_stale_plan(project):
    view = inspect_document(project)
    plan = plan_text_change(view, [{'item': view.summary['document']['id'], 'before': 'Plate 1', 'after': 'New caption'}])
    result = apply_plan(project, plan)
    assert result['validation']['navigation'] == 'first-and-last'
    assert 'New caption' in project.path('outputs/document/observatory.html').read_text()
    with pytest.raises(DocumentWorkspaceError, match='Reread'):
        apply_plan(project, plan)


def test_mismatched_notes_refuse_before_writing(project):
    view = inspect_document(project)
    notes = project.path('outputs/document/notes.json')
    old = notes.read_bytes()
    edition = json.loads(old)['edition']
    plan = plan_text_change(view, [{'item': view.summary['notes']['id'], 'before': edition, 'after': 'different-edition'}])
    with pytest.raises(DocumentWorkspaceError) as error:
        apply_plan(project, plan)
    assert error.value.code == 'DOCUMENT_NOTES_MISMATCH'
    assert notes.read_bytes() == old
    assert not project.vault.joinpath('.doxagon').exists()


def test_adoption_preserves_complete_bundle_public_artifact_and_is_idempotent(project):
    source = legacy(project)
    html = project.path('outputs/document/observatory.html').read_bytes()
    notes = project.path('outputs/document/notes.json').read_bytes()
    plan = plan_adopt_bundle(inspect_document(project), 'plate', source)
    assert plan['details']['public_html_unchanged']
    apply_plan(project, plan)
    for original, mapped in plan['details']['files'].items():
        assert (project.vault / original).read_bytes() == (project.vault / mapped['path']).read_bytes()
    assert project.path('outputs/document/observatory.html').read_bytes() == html
    assert project.path('outputs/document/notes.json').read_bytes() == notes
    assert project.path(source + '/outputs/original.png').exists()
    assert project.path('assets/visuals/plate/derived/.thumb_original.png').exists()
    repeated = plan_adopt_bundle(inspect_document(project), 'plate', source)
    assert repeated['changes'] == []
    view = inspect_document(project)
    assert view.summary['authoring']['assets'][0]['variants'][0]['provenance'] == 'historical_unknown'
    assert len(view.summary['authoring']['assets'][0]['variants']) == 1


def test_image_selection_updates_only_named_usage_and_records_encoding(project):
    source = legacy(project)
    apply_plan(project, plan_adopt_bundle(inspect_document(project), 'plate', source))
    apply_plan(project, plan_bind_slots(inspect_document(project), {'slot-0': 'plate', 'slot-reused': 'plate'}))
    before = ImageDocument(project.path('outputs/document/observatory.html').read_bytes())
    view = inspect_document(project)
    variant = view.summary['authoring']['assets'][0]['variants'][0]['id']
    plan = plan_select_image(view, 'plate', variant, ['slot-0'])
    apply_plan(project, plan)
    after = ImageDocument(project.path('outputs/document/observatory.html').read_bytes())
    assert after.digest(after.slots[0]) != before.digest(before.slots[0])
    assert all(before.digest(a) == after.digest(b) for a, b in zip(before.slots[1:], after.slots[1:]))
    registry = json.loads(project.path('outputs/document/authoring.json').read_bytes())
    assert registry['assets']['plate']['selected'] is None
    assert registry['usages']['slot-0']['variant'] == variant
    assert 'variant' not in registry['usages']['slot-reused']
    assert any(item.get('provenance') == 'encoded_variant' for item in inspect_document(project).items)


def streaming():
    urls = ['data:image/png;base64,' + base64.b64encode(png(color)).decode() for color in [(1, 2, 3), (4, 5, 6)]]
    source = '<html><body><img id="a" data-dox-asset="first" width="80" height="40" alt="A"><img id="b" data-dox-asset="second"><img id="c" data-dox-asset="first">'
    source += '<div id="dox-asset-payloads" hidden>'
    for key, url in zip(['first', 'second'], urls):
        source += f'<figure data-dox-source="{key}"><img src="{url}"></figure><script>window.doxagonAssets.receive(document.currentScript.previousElementSibling);</script>'
    return (source + '</div><script>window.doxagonAssets.complete();</script></body></html>').encode()


def test_split_streaming_payload_reorders_by_first_usage_and_retains_sentinel():
    raw = streaming()
    before = ImageDocument(raw)
    encoded, _ = encode_variant(png((7, 8, 9)))
    changed = replace_slots(raw, {'a': before.digest(before.slots[0])}, encoded)
    after = ImageDocument(changed)
    assert list(after.payloads) == ['asset-' + sha(encoded), 'second', 'first']
    assert after.slots[0].attrs['width'] == '80'
    assert after.slots[0].attrs['alt'] == 'A'
    changed = replace_slots(raw, {name: before.digest(before.slots[index]) for name, index in [('a', 0), ('c', 2)]}, encoded)
    assert list(ImageDocument(changed).payloads) == ['asset-' + sha(encoded), 'second']


def test_adoption_refuses_cycle_and_changed_source_between_plan_apply(project):
    source = legacy(project)
    plan = plan_adopt_bundle(inspect_document(project), 'plate', source)
    write(project, source + '/outputs/original.prompt.md', b'Changed prompt')
    with pytest.raises(DocumentWorkspaceError) as error:
        apply_plan(project, plan)
    assert error.value.code == 'DOCUMENT_SNAPSHOT_CONFLICT'
    write(project, 'outputs/presentation/styles/paper/definition.md', b'---\nrequires: [ink]\n---\nPaper')
    with pytest.raises(DocumentWorkspaceError) as error:
        plan_adopt_bundle(inspect_document(project), 'plate', source)
    assert error.value.code == 'DOCUMENT_STYLE_CYCLE'
