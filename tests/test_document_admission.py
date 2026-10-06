"""Admitting artwork that already exists, without claiming a generation.

The case these cover is a real one: a brand kit whose finished images existed
before any asset was registered. Two of them existed only as payloads embedded
in the document, so admission has to accept an inspection item as well as a
file. What must never happen is an admitted image acquiring the receipt chain
that makes a generated image auditable.
"""
import json
from pathlib import Path

from click.testing import CliRunner
import pytest

from doxagon.renderings.document_assets import plan_admit_image, plan_adopt_bundle, plan_create_asset
from doxagon.renderings.document_changes import apply_plan, registry
from doxagon.renderings.document_cli import document_group
from doxagon.renderings.document_generation import generate, generation_plan
from doxagon.renderings.document_images import ImageDocument
from doxagon.renderings.document_inspection import inspect_document, read_item, sha
from doxagon.renderings.project import DocumentWorkspaceError, resolve_document_project
from doxagon.presentations.generation import GeneratedImage
from tests.authored_vault import write_authored_project, write_image_generation_inputs
from tests.synthetic_vault import png
from tests.test_document_generation import PROVIDER

ROOT = Path(__file__).parents[1]
GENERATION_ONLY = {'receipt', 'prompt', 'prompt_sha256', 'provider', 'settings', 'lineage', 'job'}


@pytest.fixture
def project(tmp_path):
    write_authored_project(tmp_path)
    selected = resolve_document_project('observatory', cwd=tmp_path, environ={})
    apply_plan(selected, plan_create_asset(inspect_document(selected), 'plate', b'A plate.'))
    return selected


def artwork(project, raw=png((12, 34, 56)), name='incoming/finished-plate.png'):
    path = project.path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return name


def variants(project, key='plate'):
    return registry(inspect_document(project))['assets'][key]['variants']


def test_admitted_variant_is_selected_into_its_slot_through_the_cli(project, monkeypatch, tmp_path):
    """The whole documented path: a JSON request, a reviewed plan, then apply."""
    source = artwork(project)
    monkeypatch.chdir(project.root)
    monkeypatch.delenv('DOXAGON_ROOT', raising=False)
    runner = CliRunner()

    def run(*args):
        result = runner.invoke(document_group, list(args))
        assert result.exit_code == 0, result.output
        return json.loads(result.output)

    def request(value):
        name = sha(json.dumps(value).encode())[:12]
        (tmp_path / f'{name}.json').write_text(json.dumps(value))
        plan = run('asset-plan', '--snapshot', run('context', '--json')['snapshot'],
                   '--request', str(tmp_path / f'{name}.json'), '--output', str(tmp_path / f'{name}-plan.json'))
        return plan, run('apply', str(tmp_path / f'{name}-plan.json'))

    plan, applied = request({'operation': 'admit-image', 'key': 'plate', 'source': source})
    assert plan['operation'] == 'admit-image' and applied['status'] == 'applied'
    variant = plan['details']['variant']
    request({'operation': 'bind-slots', 'associations': {'slot-0': 'plate'}})
    request({'operation': 'select-image', 'key': 'plate', 'variant': variant, 'slots': ['slot-0']})

    record = registry(inspect_document(project))
    candidate = record['assets']['plate']['variants'][variant]
    assert {'path', 'sha256', 'provenance'} <= set(candidate)
    assert record['usages']['slot-0']['variant'] == variant
    assert record['assets']['plate']['selected'] == variant
    document = ImageDocument(project.path('outputs/document/observatory.html').read_bytes())
    slot = next(item for item in document.slots if item.attrs.get('id') == 'slot-0')
    encoding = record['assets']['plate']['encodings'][record['usages']['slot-0']['encoding']]
    assert encoding['original_sha256'] == candidate['sha256']
    assert document.digest(slot) == encoding['embedded_sha256']


def test_admitted_provenance_carries_no_generation_claim(project):
    plan = plan_admit_image(inspect_document(project), 'plate', artwork(project))
    apply_plan(project, plan)
    candidate = variants(project)[plan['details']['variant']]
    assert plan['details']['provenance'] == 'admitted'
    assert candidate['provenance'] == 'admitted'
    assert GENERATION_ONLY.isdisjoint(candidate)
    assert GENERATION_ONLY.isdisjoint(plan['details'])
    view = inspect_document(project)
    summary = next(item for item in view.summary['authoring']['assets'] if item['key'] == 'plate')
    assert [(item['provenance'], item['generated_with']) for item in summary['variants']] == [('admitted', None)]
    origin = read_item(view, summary['variants'][0]['image'])['generation']['origins'][0]
    assert (origin['receipt'], origin['provider'], origin['saved_prompts'], origin['saved_settings']) == (None, None, [], None)


def test_a_neighbouring_bundle_prompt_is_not_read_as_this_image_s_history(tmp_path):
    """An adopted bundle keeps a legacy assembled_prompt.md beside its variants.

    That prompt describes the generation that produced the legacy image. An
    admitted image was never produced there, so treating the neighbour as its
    saved prompt would be precisely the false generation claim to avoid.
    """
    write_image_generation_inputs(write_authored_project(tmp_path))
    selected = resolve_document_project('observatory', cwd=tmp_path, environ={})
    apply_plan(selected, plan_adopt_bundle(inspect_document(selected), 'dawn', 'outputs/presentation/slides/dawn/images/main'))
    assert selected.path('assets/visuals/dawn/variants/assembled_prompt.md').is_file()
    plan = plan_admit_image(inspect_document(selected), 'dawn', artwork(selected))
    apply_plan(selected, plan)
    view = inspect_document(selected)
    asset = next(item for item in view.summary['authoring']['assets'] if item['key'] == 'dawn')
    row = next(item for item in asset['variants'] if item['id'] == plan['details']['variant'])
    origin = read_item(view, row['image'])['generation']['origins'][0]
    assert (row['provenance'], origin['saved_prompts'], origin['receipt']) == ('admitted', [], None)


def test_generated_provenance_and_receipt_are_unchanged(project):
    plan = generation_plan(inspect_document(project), 'plate', {'variants': 1}, provider=PROVIDER)
    job = generate(project, plan, 'one', provider=PROVIDER, generator=lambda *_: GeneratedImage(png((7, 7, 7))))
    candidate = variants(project)[job['outputs'][0]['asset_id']]
    assert candidate['provenance'] == 'generated'
    receipt = json.loads((project.vault / candidate['receipt']).read_bytes())
    assert receipt['prompt']['sha256'] == plan['prompt_sha256'] and receipt['provider'] == PROVIDER


def test_admission_records_the_source_and_the_hash_of_the_admitted_bytes(project):
    source = artwork(project)
    plan = plan_admit_image(inspect_document(project), 'plate', source)
    apply_plan(project, plan)
    candidate = variants(project)[plan['details']['variant']]
    assert candidate['admitted_from'] == {'path': f'projects/observatory/{source}'}
    assert candidate['sha256'] == sha(project.path(source).read_bytes())
    assert candidate['sha256'] == sha((project.vault / candidate['path']).read_bytes())


def test_an_embedded_payload_is_admitted_by_item_id(project):
    """The real case: the finished image exists only inside the document."""
    view = inspect_document(project)
    image = next(item for item in view.items if item['kind'] == 'image')
    plan = plan_admit_image(view, 'plate', item=image['id'])
    apply_plan(project, plan)
    candidate = variants(project)[plan['details']['variant']]
    assert candidate['admitted_from'] == {'item': image['id']}
    assert candidate['sha256'] == image['sha256'] == sha((project.vault / candidate['path']).read_bytes())


def test_admission_refuses_bytes_that_are_not_a_supported_raster(project):
    source = artwork(project, b'GIF89a not really an image', 'incoming/not-a-raster.png')
    with pytest.raises(DocumentWorkspaceError, match='not-a-raster.png') as error:
        plan_admit_image(inspect_document(project), 'plate', source)
    assert error.value.code == 'DOCUMENT_ADMISSION_IMAGE_INVALID'
    assert 'single-frame PNG, JPEG or WebP' in str(error.value)


def test_admission_refuses_an_unregistered_asset(project):
    with pytest.raises(DocumentWorkspaceError, match='night-sky') as error:
        plan_admit_image(inspect_document(project), 'night-sky', artwork(project))
    assert error.value.code == 'DOCUMENT_ASSET_UNKNOWN'
    assert 'register the asset before admitting' in str(error.value)


def test_admission_refuses_a_variant_that_already_exists(project):
    source = artwork(project)
    plan = plan_admit_image(inspect_document(project), 'plate', source)
    apply_plan(project, plan)
    with pytest.raises(DocumentWorkspaceError, match=plan['details']['variant']) as error:
        plan_admit_image(inspect_document(project), 'plate', source)
    assert error.value.code == 'DOCUMENT_VARIANT_EXISTS'
    assert 'these exact bytes' in str(error.value)


def test_admission_is_documented_in_the_operations_guide_and_help_text():
    guide = (ROOT / 'docs/document-authoring.md').read_text()
    assert '### Admitting artwork you already have' in guide
    assert 'Use `generation-run` when the provider is to make the image; use `admit-image` when the bytes already exist.' in guide
    assert '{"operation":"admit-image","key":"night-sky","item":"IMAGE_ITEM"}' in guide
    # Click rewraps the docstring to the terminal width, so compare the prose.
    output = ' '.join(CliRunner().invoke(document_group, ['asset-plan', '--help']).output.split())
    assert 'Use generation-run when the provider is to make the image; use admit-image when the bytes already exist' in output
    assert 'An admitted variant records provenance "admitted", the source path or item id it came from and the sha256 of the admitted bytes' in output
    assert 'carries no prompt, provider identity or receipt, because no provider call happened' in output
