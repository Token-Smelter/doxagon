"""The first failure must name the real cause.

Each case below cost a debugging cycle while authoring the first asset through
this path. A typed code alone did not identify which of several conditions it
was reporting, so these tests assert on the identifying detail in the message,
not on the code.
"""
import base64
import json

from click.testing import CliRunner
import pytest

from doxagon.renderings.document_assets import plan_create_asset
from doxagon.renderings.document_changes import apply_plan, plan_text_change
from doxagon.renderings.document_cli import document_group
from doxagon.renderings.document_inspection import inspect_document
from doxagon.renderings.document_validation import notes_disagreement, validate_change
from doxagon.renderings.project import DocumentWorkspaceError, resolve_document_project
from tests.authored_vault import write_authored_project
from tests.synthetic_vault import png

PROOF = {'documentId': 'synthetic-observatory', 'edition': 'public-1',
         'cues': [{'id': f'cue-{index}'} for index in range(5)]}


@pytest.fixture
def project(tmp_path):
    write_authored_project(tmp_path)
    return resolve_document_project('observatory', cwd=tmp_path, environ={})


def notes(**overrides):
    value = {'documentId': PROOF['documentId'], 'edition': PROOF['edition'],
             'cues': [{'id': cue['id'], 'notes': 'A body.'} for cue in PROOF['cues']]}
    return json.dumps({**value, **overrides}).encode()


def test_notes_mismatch_names_the_cue_missing_from_the_notes():
    short = json.loads(notes())
    del short['cues'][3]
    message = notes_disagreement(json.dumps(short).encode(), PROOF)
    assert "missing from the notes: 'cue-3'" in message


def test_notes_mismatch_names_the_cue_the_document_never_reported():
    extra = json.loads(notes())
    extra['cues'].append({'id': 'cue-references', 'notes': 'Sources.'})
    message = notes_disagreement(json.dumps(extra).encode(), PROOF)
    assert "in the notes but not reported by the document: 'cue-references'" in message


def test_notes_mismatch_reports_both_edition_values():
    message = notes_disagreement(notes(edition='public-2'), PROOF)
    assert "'public-2'" in message and "'public-1'" in message


def test_notes_mismatch_reports_both_document_identities():
    message = notes_disagreement(notes(documentId='other-document'), PROOF)
    assert "'other-document'" in message and "'synthetic-observatory'" in message


def test_notes_mismatch_names_the_cue_whose_body_is_not_a_string():
    bodies = json.loads(notes())
    bodies['cues'][2]['notes'] = ['a', 'list']
    message = notes_disagreement(json.dumps(bodies).encode(), PROOF)
    assert "cue 'cue-2'" in message and 'not a string' in message


def test_reordered_cues_report_both_orders():
    reordered = json.loads(notes())
    reordered['cues'][0], reordered['cues'][1] = reordered['cues'][1], reordered['cues'][0]
    message = notes_disagreement(json.dumps(reordered).encode(), PROOF)
    assert "'cue-1', 'cue-0'" in message.replace('"', "'")


def test_applying_mismatched_notes_raises_the_named_disagreement(project):
    """The message reaches the operator through the real refusal path."""
    view = inspect_document(project)
    path = project.path('outputs/document/notes.json')
    edition = json.loads(path.read_bytes())['edition']
    plan = plan_text_change(view, [{'item': view.summary['notes']['id'], 'before': edition, 'after': 'public-9'}])
    with pytest.raises(DocumentWorkspaceError, match="'public-9'") as error:
        apply_plan(project, plan)
    assert error.value.code == 'DOCUMENT_NOTES_MISMATCH'
    assert json.loads(path.read_bytes())['edition'] == edition


def late_cue_project(project) -> None:
    """A scaffolded document with one cue section moved after the bridge script.

    The template is the real producer (`dox scaffold`), and its bridge builds
    the cue list with a DOM query when the script runs. A section that starts
    after that script is therefore invisible to the runtime while remaining in
    source order and matching the notes exactly — the shape that produced an
    unexplained notes mismatch.
    """
    from scripts.dox import _DOCUMENT_TEMPLATE
    body = ('<section class="chapter" id="opening">'
            '<p class="beat" data-cue="opening-beat">The first belief.</p></section>')
    late = ('<section class="chapter" id="references">'
            '<p class="beat" data-cue="references">Sources.</p></section>')
    html = _DOCUMENT_TEMPLATE.format(title='Probe', document_id='probe-doc', edition='probe-1', body=body)
    assert html.index('data-cue="opening-beat"') < html.index('<script>') < html.index('</body>')
    project.path('outputs/document/observatory.html').write_text(html.replace('</body>', late + '\n</body>'))
    project.path('outputs/document/notes.json').write_text(json.dumps({
        'documentId': 'probe-doc', 'edition': 'probe-1',
        'cues': [{'id': 'opening-beat', 'notes': 'Open.'}, {'id': 'references', 'notes': 'Sources.'}]}))


def test_cue_section_after_the_bridge_script_is_named_as_the_cause(project):
    late_cue_project(project)
    view = inspect_document(project)
    assert [cue['id'] for cue in view.summary['cues']] == ['opening-beat', 'references']
    document = project.path('outputs/document/observatory.html')
    with pytest.raises(DocumentWorkspaceError) as error:
        validate_change(view, {document: document.read_bytes()})
    assert error.value.code == 'DOCUMENT_NOTES_MISMATCH'
    assert "data-cue=\"references\"" in str(error.value)
    assert 'after the <script> that builds the cue list' in str(error.value)


def documented_slot_example(project) -> None:
    """The example in docs/document-authoring.md, byte for byte in its shape."""
    url = 'data:image/png;base64,' + base64.b64encode(png((36, 74, 96))).decode()
    project.path('outputs/document/observatory.html').write_text(
        '<!doctype html><html lang="en"><body>'
        f'<figure data-slot="hero"><img src="{url}" alt="A house convention, not a slot"></figure>'
        f'<figure>\n  <img id="plate-hero" alt="Hero plate" src="{url}">\n</figure>'
        '</body></html>')


def test_documented_id_is_a_stable_slot_and_figure_data_slot_is_not(project):
    documented_slot_example(project)
    usages = {usage['id']: usage['stable'] for usage in inspect_document(project).summary['usages']}
    assert usages['plate-hero'] is True
    assert not any(stable for slot, stable in usages.items() if slot != 'plate-hero')


def test_binding_a_figure_data_slot_name_is_refused(project):
    """Copying the corpus's CSS convention names a slot that does not exist."""
    from doxagon.renderings.document_assets import plan_bind_slots
    documented_slot_example(project)
    apply_plan(project, plan_create_asset(inspect_document(project), 'night-sky', b'A night sky.'))
    with pytest.raises(DocumentWorkspaceError, match='hero') as error:
        plan_bind_slots(inspect_document(project), {'hero': 'night-sky'})
    assert error.value.code == 'DOCUMENT_USAGE_INVALID'


def test_documented_stable_slot_binds_and_accepts_a_variant(project):
    from doxagon.renderings.document_assets import plan_bind_slots
    documented_slot_example(project)
    apply_plan(project, plan_create_asset(inspect_document(project), 'night-sky', b'A night sky.'))
    plan = plan_bind_slots(inspect_document(project), {'plate-hero': 'night-sky'})
    assert plan['details']['associations'] == {'plate-hero': 'night-sky'}


@pytest.mark.parametrize('frontmatter, dialect', [
    (b'---\nsources: [ink-ref.jpg]\n---\nInk.\n', None),
    (b'---\ndialect: brief/1\nsources:\n  - file: ink-ref.jpg\n    role: "line quality only"\n---\nInk.\n', 'brief/1'),
])
def test_unregistered_source_is_refused_at_create_time(project, frontmatter, dialect):
    """The bundle layout invites dropping a file into sources/; that registers nothing."""
    dropped = project.path('assets/styles/ink/sources/ink-ref.jpg')
    dropped.parent.mkdir(parents=True)
    dropped.write_bytes(png((9, 9, 9)))
    with pytest.raises(DocumentWorkspaceError, match='ink-ref.jpg') as error:
        plan_create_asset(inspect_document(project), 'ink', frontmatter, dialect, style=True)
    assert error.value.code == 'DOCUMENT_REFERENCE_UNREGISTERED'
    assert 'references' in str(error.value)


def test_registering_the_source_by_item_id_succeeds(project):
    view = inspect_document(project)
    image = next(item for item in view.items if item['kind'] == 'image')
    plan = plan_create_asset(view, 'ink', b'---\nsources: [ink-ref.jpg]\n---\nInk.\n',
                             references={'ink-ref.jpg': image['id']}, style=True)
    assert plan['details']['references'] == ['projects/observatory/assets/styles/ink/sources/ink-ref.jpg']


def test_asset_plan_help_states_the_reference_and_slot_contracts():
    # Click rewraps the docstring to the terminal width, so compare the prose
    # rather than the emitted line breaks.
    output = ' '.join(CliRunner().invoke(document_group, ['asset-plan', '--help']).output.split())
    assert 'References are bound by item id from the snapshot' in output
    assert 'becomes a referenceable item only by being embedded in the selected HTML' in output
    assert "placing a file in a bundle's sources/ directory does NOT register it" in output
    assert 'A stable slot is an image element carrying an id attribute' in output
