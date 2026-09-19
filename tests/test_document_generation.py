import importlib.util
import json
from pathlib import Path

import pytest

from doxagon.presentations.generation import (AssembledPrompt, GeneratedImage, GenerationSettings, generator_argv)
from doxagon.presentations.errors import WorkspaceError
from doxagon.renderings.document_assets import plan_adopt_bundle, plan_create_asset
from doxagon.renderings.document_changes import apply_plan
from doxagon.renderings.document_generation import DocumentVariant, generate, generation_plan, provider_capabilities
from doxagon.renderings.document_inspection import inspect_document
from doxagon.renderings.project import DocumentWorkspaceError, resolve_document_project
from tests.authored_vault import write_authored_project
from tests.test_document_authoring import legacy, write
from tests.synthetic_vault import png

PROVIDER = {**provider_capabilities({}), 'configured': True, 'provider': 'deterministic-test', 'model': 'test'}


@pytest.fixture
def project(tmp_path):
    write_authored_project(tmp_path)
    return resolve_document_project('observatory', cwd=tmp_path, environ={})


def test_legacy_dialect_preserves_exact_prompt_and_reference_order(project, monkeypatch):
    source = legacy(project)
    write(project, 'outputs/presentation/styles/constraints/layout/definition.md', b'Layout constraints.\n')
    write(project, 'outputs/presentation/styles/constraints/layout/sources/a.png', png((3, 3, 3)))
    write(project, 'outputs/presentation/styles/ink/sources/z.png', png((4, 4, 4)))
    write(project, 'outputs/presentation/styles/ink/sources/a.png', png((5, 5, 5)))
    scripts = Path(__file__).resolve().parents[1] / 'factory/scripts'
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location('legacy_visuals_test', scripts / 'generate_visuals.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    prompt, references, _ = module.construct_prompt(project.path(source), project.path('outputs/presentation/styles'))
    apply_plan(project, plan_adopt_bundle(inspect_document(project), 'plate', source))
    plan = generation_plan(inspect_document(project), 'plate', {'variants': 1}, provider=PROVIDER)
    assert plan['prompt'].encode() == prompt.encode()
    assert [(project.vault / item['path']).read_bytes() for item in plan['references']] == [path.read_bytes() for path in references]


def test_generation_keeps_partial_results_and_retry_is_explicit_idempotent(project):
    apply_plan(project, plan_create_asset(inspect_document(project), 'new-plate', b'A new plate.\n'))
    plan = generation_plan(inspect_document(project), 'new-plate', {'variants': 3}, provider=PROVIDER)
    html = project.path('outputs/document/observatory.html').read_bytes()
    calls = []

    def provider(variant, references):
        calls.append(variant.variant_index)
        assert variant.prompt.text == plan['prompt']
        assert references == []
        if variant.variant_index == 1 and calls.count(1) == 1:
            raise RuntimeError('Simulated provider outage')
        return GeneratedImage(png((30 + variant.variant_index, 50, 80)))

    failed = generate(project, plan, 'request-1', generator=provider, provider=PROVIDER)
    assert failed['status'] == 'failed'
    assert len(failed['outputs']) == 2
    assert len(failed['failures']) == 1
    assert generate(project, plan, 'request-1', generator=provider, provider=PROVIDER) == failed
    assert calls == [0, 1, 2]
    retried = generate(project, plan, 'request-1', retry_of=failed['job_id'], generator=provider, provider=PROVIDER)
    assert retried['status'] == 'succeeded'
    assert retried['lineage'] == failed['lineage']
    assert len(retried['outputs']) == 3
    assert calls == [0, 1, 2, 1]
    assert generate(project, plan, 'request-1', retry_of=failed['job_id'], generator=provider, provider=PROVIDER) == retried
    assert calls == [0, 1, 2, 1]
    assert project.path('outputs/document/observatory.html').read_bytes() == html
    authoring = inspect_document(project).summary['authoring']
    assert len(authoring['assets'][0]['variants']) == 3
    assert all(item['current_definition'] == 'matches_receipt' for item in authoring['assets'][0]['variants'])
    project.path('assets/visuals/new-plate/definition.md').write_text('Current intent changed.')
    assert all(item['current_definition'] == 'changed' for item in inspect_document(project).summary['authoring']['assets'][0]['variants'])


def test_pending_admission_retries_without_a_second_provider_call(project, monkeypatch):
    from doxagon.renderings import document_generation as generation
    apply_plan(project, plan_create_asset(inspect_document(project), 'plate', b'A plate'))
    plan = generation_plan(inspect_document(project), 'plate', {'variants': 1}, provider=PROVIDER)
    calls = []

    def provider(variant, references):
        calls.append(variant)
        return GeneratedImage(png((1, 2, 3)))

    original = generation.apply_plan
    def interrupted(*args):
        raise DocumentWorkspaceError('DOCUMENT_SNAPSHOT_CONFLICT', 'Simulated concurrent edit')
    monkeypatch.setattr(generation, 'apply_plan', interrupted)
    failed = generate(project, plan, 'request', generator=provider, provider=PROVIDER)
    assert len(calls) == 1 and failed['status'] == 'failed'
    monkeypatch.setattr(generation, 'apply_plan', original)
    retried = generate(project, plan, 'request', retry_of=failed['job_id'], generator=provider, provider=PROVIDER)
    assert retried['status'] == 'succeeded' and len(calls) == 1


def test_generation_refuses_changed_input_and_provider_before_call(project):
    apply_plan(project, plan_create_asset(inspect_document(project), 'plate', b'A plate'))
    plan = generation_plan(inspect_document(project), 'plate', {'variants': 1}, provider=PROVIDER)
    def forbidden(*args):
        pytest.fail('Provider must not be called')
    with pytest.raises(DocumentWorkspaceError, match='provider'):
        generate(project, plan, 'one', generator=forbidden, provider={**PROVIDER, 'model': 'changed'})
    project.path('assets/visuals/plate/definition.md').write_text('Changed')
    with pytest.raises(DocumentWorkspaceError, match='changed generation input'):
        generate(project, plan, 'one', generator=forbidden, provider=PROVIDER)


@pytest.mark.parametrize('count', [0, 15])
def test_shared_argv_rejects_mismatched_or_over_budget_reference_count(count):
    variant = DocumentVariant('plate', 0, 'Plate', '', AssembledPrompt('Prompt', ('ref',)), GenerationSettings())
    with pytest.raises(WorkspaceError):
        generator_argv('generator', variant, 'prompt', 'outputs', ['ref'] * count)


def test_stored_style_uses_the_existing_prompt_dialect(project):
    from doxagon.renderings.document_changes import REGISTRY_SCHEMA
    write(project, 'assets/visuals/plate/definition.md', b'---\nstyles: [ink]\n---\nA plate.\n')
    write(project, 'assets/styles/ink/definition.md', b'Ink.\n')
    prefix = 'projects/observatory/'
    write(project, 'outputs/document/authoring.json', json.dumps({'schema': REGISTRY_SCHEMA, 'assets': {'plate': {
        'label': 'Plate', 'definition': prefix + 'assets/visuals/plate/definition.md', 'dialect': 'stored-style/1', 'references': [], 'variants': {}}},
        'styles': {'ink': {'definition': prefix + 'assets/styles/ink/definition.md', 'dialect': 'stored-style/1', 'references': []}}, 'usages': {}}).encode())
    plan = generation_plan(inspect_document(project), 'plate', {'variants': 1}, provider=PROVIDER)
    assert plan['prompt'] == '# Plate\n\n## Style: ink\nInk.\n\n## Visual description\nA plate.\n\n## Settings\n- Resolution: 2K\n- Aspect Ratio: 16:9\n'


def test_failed_subprocess_retains_candidate_and_failure_receipt(project, tmp_path):
    import base64
    from doxagon.presentation_backends import SubprocessImageGenerator
    apply_plan(project, plan_create_asset(inspect_document(project), 'plate', b'A plate'))
    plan = generation_plan(inspect_document(project), 'plate', {'variants': 1}, provider=PROVIDER)
    script = tmp_path / 'partial-generator'
    script.write_text('#!/usr/bin/env python3\nimport base64,sys\nfrom pathlib import Path\n'
                      'output=Path(sys.argv[sys.argv.index("--output")+1])\n'
                      'output.joinpath("partial.png").write_bytes(base64.b64decode(' + repr(base64.b64encode(png((9, 8, 7))).decode()) + '))\n'
                      'raise SystemExit(1)\n')
    script.chmod(0o700)
    original = project.path('outputs/document/observatory.html').read_bytes()
    job = generate(project, plan, 'partial', generator=SubprocessImageGenerator(str(script)), provider=PROVIDER)
    assert job['status'] == 'failed' and len(job['outputs']) == 1
    candidate = job['outputs'][0]
    assert candidate['provenance'] == 'partial_generation'
    assert (project.vault / candidate['path']).read_bytes() == png((9, 8, 7))
    receipt = json.loads((project.vault / candidate['receipt']).read_bytes())
    assert receipt['errors'][0]['code'] == 'PRES_GENERATION_PARTIAL'
    assert project.path('outputs/document/observatory.html').read_bytes() == original
    def forbidden(*args):
        pytest.fail('A retained candidate must not cause another paid invocation')
    retry = generate(project, plan, 'partial', retry_of=job['job_id'], generator=forbidden, provider=PROVIDER)
    assert retry['status'] == 'failed' and retry['outputs'] == job['outputs']
    assert retry['failures'][0]['retained_candidate'] == candidate['asset_id']


def test_generation_plan_uses_negotiated_reference_limit(project):
    view = inspect_document(project)
    image = next(item for item in view.items if item['kind'] == 'image')
    apply_plan(project, plan_create_asset(view, 'eleven', b'Eleven references.', references={
        f'{index}.png': image['id'] for index in range(11)
    }))
    adapter = {**PROVIDER, 'max_references': 10, 'capabilities_source': 'adapter'}
    with pytest.raises(DocumentWorkspaceError, match='10 images .*adapter') as error:
        generation_plan(inspect_document(project), 'eleven', provider=adapter)
    assert error.value.code == 'DOCUMENT_REFERENCE_LIMIT'
    assert generation_plan(inspect_document(project), 'eleven', provider=PROVIDER)['provider']['max_references'] == 14


def test_generation_refuses_missing_and_oversized_reference_closure(project):
    view = inspect_document(project)
    image = next(item for item in view.items if item['kind'] == 'image')
    apply_plan(project, plan_create_asset(view, 'ink', b'Ink', references={f'{i}.png': image['id'] for i in range(14)}, style=True))
    apply_plan(project, plan_create_asset(inspect_document(project), 'plate', b'---\nstyles: [ink]\n---\nPlate', references={'plate.png': image['id']}))
    with pytest.raises(DocumentWorkspaceError) as error:
        generation_plan(inspect_document(project), 'plate', provider=PROVIDER)
    assert error.value.code == 'DOCUMENT_REFERENCE_LIMIT'
    project.path('assets/styles/ink/sources/0.png').unlink()
    with pytest.raises(DocumentWorkspaceError) as error:
        generation_plan(inspect_document(project), 'plate', provider=PROVIDER)
    assert error.value.code == 'DOCUMENT_INPUT_MISSING'
