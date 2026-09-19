import json

import pytest

from doxagon.renderings.document_assets import plan_adopt_bundle, plan_bind_slots, plan_select_image
from doxagon.renderings.document_changes import REGISTRY_PATH, REGISTRY_SCHEMA, apply_plan
from doxagon.renderings.document_generation import generate, generation_plan
from doxagon.renderings.document_inspection import inspect_document, read_item, verify_inspection
from doxagon.renderings.project import DocumentWorkspaceError, resolve_document_project
from doxagon.presentations.generation import GeneratedImage
from tests.authored_vault import write_authored_project, write_image_generation_inputs
from tests.synthetic_vault import png
from tests.test_document_inspection import tree
from tests.test_document_generation import PROVIDER


@pytest.fixture
def project(tmp_path):
    write_image_generation_inputs(write_authored_project(tmp_path))
    return resolve_document_project('observatory', cwd=tmp_path, environ={})


def details(view):
    image = next(item for item in view.items if item['kind'] == 'image')
    return read_item(view, image['id'])['generation']


def text(view, identity):
    return read_item(view, identity)['text']


def test_legacy_prompt_chain_is_read_only_and_does_not_invent_history(project):
    before = tree(project.vault)
    view = inspect_document(project)
    origin = details(view)['origins'][0]
    assert details(view)['association'] == 'verified_hash_pair'
    assert origin['saved_prompts'][0]['status'] == 'unverified'
    assert 'violet sky' in text(view, origin['saved_prompts'][0]['item'])
    assert 'astronomer at dawn' in text(view, origin['image_prompt'])
    assert 'Keep the telescope' in text(view, origin['constraints'])
    assert [(component['key'], component['role']) for component in origin['components']] == [
        ('constraints/layout', 'global'), ('paper', 'inherited'), ('ink', 'inherited'), ('characters/astronomer', 'direct')]
    assert origin['components'][-1]['tags'] == ['ASTRONOMER']
    assert len(origin['components'][-1]['references']) == 1
    assert origin['unresolved_tags'] == ['OLD_TAG']
    assembled = text(view, origin['current_assembled'])
    assert '<global_constraints>\n**Tag:** `[GLOBAL]`' in assembled
    assert assembled.index('White paper.') < assembled.index('Fine black linework.') < assembled.index('A long coat')
    assert '<visual_description>' in assembled and 'violet sky' not in assembled
    assert origin['current_definition'] == 'unknown'
    # Prompts are private drill-down contents, absent from index/context JSON.
    assert 'astronomer at dawn' not in json.dumps(view.summary)
    assert 'violet sky' not in json.dumps(view.summary)
    verify_inspection(view, view.summary['authority_generation'])
    assert tree(project.vault) == before


def test_saved_prompts_and_implicit_global_references_are_snapshot_bound(project):
    view = inspect_document(project)
    project.path('outputs/presentation/slides/dawn/images/main/outputs/assembled_prompt.md').write_text('New saved prompt')
    with pytest.raises(DocumentWorkspaceError, match='refresh'):
        verify_inspection(view, view.summary['authority_generation'])
    view = inspect_document(project)
    directory = project.path('outputs/presentation/styles/constraints/layout/sources')
    directory.mkdir()
    (directory / 'unlisted.png').write_bytes(png((1, 2, 3)))
    with pytest.raises(DocumentWorkspaceError, match='refresh'):
        verify_inspection(view, view.summary['authority_generation'])
    current = inspect_document(project)
    assert len(details(current)['origins'][0]['components'][0]['references']) == 1


def test_receipt_prompt_and_current_definition_drift_stay_distinct(project):
    source = 'outputs/presentation/slides/dawn/images/main'
    apply_plan(project, plan_adopt_bundle(inspect_document(project), 'dawn', source))
    plan = generation_plan(inspect_document(project), 'dawn', {'variants': 1}, provider=PROVIDER)
    job = generate(project, plan, 'candidate', provider=PROVIDER, generator=lambda *_: GeneratedImage(png((44, 55, 66))))
    apply_plan(project, plan_bind_slots(inspect_document(project), {'slot-0': 'dawn'}))
    apply_plan(project, plan_select_image(inspect_document(project), 'dawn', job['outputs'][0]['asset_id'], ['slot-0']))
    view = inspect_document(project)
    usage = next(usage for usage in view.summary['usages'] if usage['id'] == 'slot-0')
    origin = read_item(view, usage['image'])['generation']['origins'][0]
    assert origin['saved_prompts'][0]['status'] == 'verified'
    assert text(view, origin['saved_prompts'][0]['item']) == plan['prompt']
    assert origin['current_definition'] == 'matches_receipt'
    assert origin['provider']['model'] == 'test'
    project.path('assets/visuals/dawn/definition.md').write_text('An astronomer at midnight.')
    current = inspect_document(project)
    origin = read_item(current, usage['image'])['generation']['origins'][0]
    assert origin['current_definition'] == 'changed'
    assert 'midnight' in text(current, origin['image_prompt'])
    assert 'midnight' not in text(current, origin['saved_prompts'][0]['item'])
    prompt_path = project.vault / next(item for item in current.items if item['id'] == origin['saved_prompts'][0]['item'])['path']
    prompt_path.write_text('Tampered prompt')
    tampered = inspect_document(project)
    assert read_item(tampered, usage['image'])['generation']['origins'][0]['saved_prompts'][0]['status'] == 'changed_or_missing'
    receipt_path = project.vault / next(item for item in current.items if item['id'] == origin['receipt'])['path']
    receipt = json.loads(receipt_path.read_text())
    receipt['references'] = 'invalid'
    receipt_path.write_text(json.dumps(receipt))
    invalid = read_item(inspect_document(project), usage['image'])['generation']['origins'][0]
    assert invalid['receipt'] and invalid['issues']
    assert invalid['saved_prompts'] == []
    assert invalid['current_definition'] == 'unknown'


def test_ambiguous_missing_and_invalid_inputs_are_explicit(project):
    path = project.path('outputs/document/assets.json')
    record = json.loads(path.read_text())
    record['assets'].append(record['assets'][0])
    path.write_text(json.dumps(record))
    view = inspect_document(project)
    assert details(view)['association'] == 'ambiguous'
    assert details(view)['origins'] == []
    record['assets'].pop(); path.write_text(json.dumps(record))
    project.path('outputs/presentation/styles/characters/astronomer/definition.md').write_text('---\nrequires: [missing]\n---\nCharacter')
    view = inspect_document(project)
    origin = details(view)['origins'][0]
    assert origin['current_assembled'] is None
    assert origin['issues']
    assert origin['image_prompt']
    project.path('outputs/presentation/slides/dawn/images/main/outputs/original.png').unlink()
    assert details(inspect_document(project))['association'] == 'missing_original'


def test_saved_prompt_symlink_escape_is_refused(project):
    prompt = project.path('outputs/presentation/slides/dawn/images/main/outputs/assembled_prompt.md')
    prompt.unlink()
    secret = project.vault / 'secret.txt'
    secret.write_text('Never exposed')
    prompt.symlink_to(secret)
    with pytest.raises(DocumentWorkspaceError) as error:
        inspect_document(project)
    assert error.value.code == 'DOCUMENT_PATH_ESCAPE'


def test_shared_definition_keeps_each_assets_assembled_prompt_and_invalid_styles_are_inspectable(project):
    prefix = f'projects/{project.slug}/'
    bundle = 'outputs/presentation/slides/dawn/images/main'
    project.path(bundle + '/definition.md').write_text('A shared scene.')
    image_path = bundle + '/outputs/original.png'
    from doxagon.renderings.document_inspection import sha
    binding = {'definition': prefix + bundle + '/definition.md', 'dialect': 'stored-style/1',
               'references': [], 'variants': {'original': {'path': prefix + image_path,
                   'sha256': sha(project.path(image_path).read_bytes())}}}
    record = {'schema': REGISTRY_SCHEMA, 'assets': {label: {**binding, 'label': label} for label in ['First', 'Second']},
              'styles': {}, 'usages': {}}
    project.path(REGISTRY_PATH).write_text(json.dumps(record))
    view = inspect_document(project)
    first, second = details(view)['origins']
    assert first['current_assembled'] != second['current_assembled']
    assert text(view, first['current_assembled']).startswith('# First\n')
    assert text(view, second['current_assembled']).startswith('# Second\n')
    project.path(bundle + '/definition.md').write_text('---\nstyles: [broken]\n---\nA shared scene.')
    record['styles']['broken'] = 'invalid'
    project.path(REGISTRY_PATH).write_text(json.dumps(record))
    invalid = details(inspect_document(project))['origins'][0]
    assert invalid['image_prompt'] and invalid['issues']
    assert invalid['current_assembled'] is None
