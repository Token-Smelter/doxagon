"""Frozen dialects: the hashes below were computed from the assembly code path
before brief/1 existed. Any drift in legacy-bundle/1 or stored-style/1 output
fails here, by design; a new behavior lands as a new dialect, never by
changing these literals."""
from hashlib import sha256
import json

import pytest

from doxagon.renderings.document_assets import plan_adopt_bundle
from doxagon.renderings.document_changes import REGISTRY_SCHEMA, apply_plan
from doxagon.renderings.document_generation import generation_plan, provider_capabilities
from doxagon.renderings.document_inspection import inspect_document
from doxagon.renderings.project import resolve_document_project
from tests.authored_vault import write_authored_project
from tests.synthetic_vault import png

PROVIDER = {**provider_capabilities({}), 'configured': True, 'provider': 'deterministic-test', 'model': 'test'}
LEGACY_BUNDLE_SHA256 = 'd98358c2dda16be0465e9123c3ff3953dd9a8be18a8fd1a4f44698cd1ae4490b'
STORED_STYLE_SHA256 = '644c7f58793d8deae42b5df9d174ab08fe91bc310d18f24dbcc79ba2efe48a55'


@pytest.fixture
def project(tmp_path):
    write_authored_project(tmp_path)
    return resolve_document_project('observatory', cwd=tmp_path, environ={})


def write(project, path, raw):
    target = project.path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)


def legacy_bundle_fixture(project):
    """Exercises every legacy branch: implicit constraints, palette injection
    for a diagram style, custom constraints, requires post-order, body markers
    and both style- and asset-level sources."""
    source = 'outputs/presentation/slides/02/images/main'
    write(project, source + '/definition.md', b'---\nstyles: [diagram/flow, ink]\ncustom_constraints: |\n  - Keep the telescope visible.\n  - No lettering.\n---\nAn astronomer at dawn, [INK] telescope raised.\n')
    write(project, source + '/sources/ref.png', png((1, 2, 3)))
    write(project, 'outputs/presentation/styles/constraints/layout/definition.md', b'**Tag:** `[GLOBAL]`\nNo lettering; keep 10% margins.\n')
    write(project, 'outputs/presentation/styles/constraints/layout/sources/margin.png', png((3, 3, 3)))
    write(project, 'outputs/presentation/styles/global/palette-2025/definition.md', b'**Tag:** `[PALETTE_2025]`\nInk black, paper white, one accent.\n')
    write(project, 'outputs/presentation/styles/diagram/flow/definition.md', b'---\nrequires: [ink]\nsources: [arrow.png]\n---\n**Tag:** `[DIAGRAM_FLOW]`\n**Requires:** `[INK]`\nBoxes and arrows.\n')
    write(project, 'outputs/presentation/styles/diagram/flow/sources/arrow.png', png((7, 7, 7)))
    write(project, 'outputs/presentation/styles/ink/definition.md', b'---\nrequires: [paper]\n---\nInk.\n')
    write(project, 'outputs/presentation/styles/paper/definition.md', b'Paper.\n')
    apply_plan(project, plan_adopt_bundle(inspect_document(project), 'plate', source))


def stored_style_fixture(project):
    prefix = 'projects/observatory/'
    write(project, 'assets/visuals/plate/definition.md', b'---\nstyles: [ink, wash]\nsources: [plate.png]\n---\nA plate.\n')
    write(project, 'assets/visuals/plate/sources/plate.png', png((1, 1, 1)))
    write(project, 'assets/styles/ink/definition.md', b'---\nsources: [nib.png]\n---\nInk.\n')
    write(project, 'assets/styles/ink/sources/nib.png', png((2, 2, 2)))
    write(project, 'assets/styles/wash/definition.md', b'Wash.\n')
    write(project, 'outputs/document/authoring.json', json.dumps({'schema': REGISTRY_SCHEMA, 'assets': {'plate': {
        'label': 'Plate', 'definition': prefix + 'assets/visuals/plate/definition.md', 'dialect': 'stored-style/1',
        'references': [prefix + 'assets/visuals/plate/sources/plate.png'], 'variants': {}}},
        'styles': {'ink': {'definition': prefix + 'assets/styles/ink/definition.md', 'dialect': 'stored-style/1', 'references': [prefix + 'assets/styles/ink/sources/nib.png']},
                   'wash': {'definition': prefix + 'assets/styles/wash/definition.md', 'dialect': 'stored-style/1', 'references': []}},
        'usages': {}}).encode())


def test_legacy_bundle_prompt_is_byte_identical_to_the_frozen_hash(project):
    legacy_bundle_fixture(project)
    plan = generation_plan(inspect_document(project), 'plate', {'variants': 1}, provider=PROVIDER)
    digest = sha256(plan['prompt'].encode()).hexdigest()
    assert plan['prompt_sha256'] == digest
    assert digest == LEGACY_BUNDLE_SHA256, plan['prompt']
    assert [entry['path'].rsplit('/', 1)[1] for entry in plan['references']] == ['margin.png', 'arrow.png', 'ref.png']


def test_stored_style_prompt_is_byte_identical_to_the_frozen_hash(project):
    stored_style_fixture(project)
    plan = generation_plan(inspect_document(project), 'plate', {'variants': 1}, provider=PROVIDER)
    digest = sha256(plan['prompt'].encode()).hexdigest()
    assert plan['prompt_sha256'] == digest
    assert digest == STORED_STYLE_SHA256, plan['prompt']
    assert [entry['path'].rsplit('/', 1)[1] for entry in plan['references']] == ['nib.png', 'plate.png']
