import base64
from io import BytesIO
import json
from hashlib import sha256

from PIL import Image
import pytest
import yaml

from doxagon.presentation_backends import SubprocessImageGenerator
from doxagon.renderings.document_assets import plan_create_asset
from doxagon.renderings.document_changes import REGISTRY_SCHEMA, apply_plan, registry
from types import SimpleNamespace

from doxagon.renderings.document_generation import BRIEF_SCHEMA, brief_header, generate, generation_plan, provider_capabilities, yaml_scalar
from doxagon.renderings.document_inspection import inspect_document
from doxagon.renderings.project import DocumentWorkspaceError, resolve_document_project
from tests.authored_vault import write_authored_project
from tests.synthetic_vault import png
from tests.test_prompt_dialect_stability import write

PROVIDER = {**provider_capabilities({}), 'configured': True, 'provider': 'deterministic-test', 'model': 'test'}
PREFIX = 'projects/observatory/'
ASSET_DEFINITION = b'''---
dialect: brief/1
intent: "Substack avatar; circle-cropped at 40px; must read as a stamp"
styles: [foundations/linework, master]
sources:
  - file: mark-sketch.png
    role: "composition only; redraw, do not trace"
config: {resolution: 2k, aspect_ratio: "1:1"}
custom_constraints: |
  - No lettering.
---
A rubber-stamp mark of a telescope.
'''
EXPECTED_PROMPT = '''---
schema: doxagon.image-brief/1
intent: Substack avatar; circle-cropped at 40px; must read as a stamp
settings: {resolution: 2K, aspect_ratio: "1:1"}
references: [{index: 0, file: ink-ref-right.jpg, from: foundations/linework, role: "line quality only; do not copy composition or subject"},
{index: 1, file: mark-sketch.png, from: asset, role: "composition only; redraw, do not trace"}]
---

<rendered_text_rule>
CRITICAL: Only render text that appears inside <rendered_text> blocks.
Everything outside these blocks is instruction metadata - do NOT render it as visible text.
Do NOT add text that "seems appropriate" or render words from style descriptions.
</rendered_text_rule>

<image_constraints>
- No lettering.
</image_constraints>

<visual_description>
A rubber-stamp mark of a telescope.
</visual_description>

<style_definitions>
<style name="foundations/linework">
**Tag:** `[LINEWORK]`
Fine linework.
</style>
<style name="master">
Master style.
</style>
</style_definitions>'''


def jpeg(colour):
    buffer = BytesIO()
    Image.new('RGB', (8, 4), colour).save(buffer, format='JPEG')
    return buffer.getvalue()


@pytest.fixture
def project(tmp_path):
    write_authored_project(tmp_path)
    return resolve_document_project('observatory', cwd=tmp_path, environ={})


def brief_project(project, asset_definition=ASSET_DEFINITION):
    """Two roled references plus registered constraints and palette styles
    that must stay out of the prompt because styles: does not list them."""
    write(project, 'assets/visuals/avatar/definition.md', asset_definition)
    write(project, 'assets/visuals/avatar/sources/mark-sketch.png', png((1, 2, 3)))
    write(project, 'assets/styles/foundations/linework/definition.md', b'---\ndialect: brief/1\nsources:\n  - file: ink-ref-right.jpg\n    role: "line quality only; do not copy composition or subject"\n---\n**Tag:** `[LINEWORK]`\nFine linework.\n')
    write(project, 'assets/styles/foundations/linework/sources/ink-ref-right.jpg', jpeg((9, 9, 9)))
    write(project, 'assets/styles/master/definition.md', b'Master style.\n')
    write(project, 'assets/styles/constraints/layout/definition.md', b'Never injected under brief/1.\n')
    write(project, 'assets/styles/global/palette-2025/definition.md', b'Never injected under brief/1.\n')

    def style(name, references=()):
        return {'definition': f'{PREFIX}assets/styles/{name}/definition.md', 'dialect': 'brief/1',
                'references': [f'{PREFIX}assets/styles/{name}/sources/{file}' for file in references]}

    write(project, 'outputs/document/authoring.json', json.dumps({'schema': REGISTRY_SCHEMA, 'assets': {'avatar': {
        'label': 'Avatar', 'definition': PREFIX + 'assets/visuals/avatar/definition.md', 'dialect': 'brief/1',
        'references': [PREFIX + 'assets/visuals/avatar/sources/mark-sketch.png'], 'variants': {}}},
        'styles': {'foundations/linework': style('foundations/linework', ['ink-ref-right.jpg']), 'master': style('master'),
                   'constraints/layout': style('constraints/layout'), 'global/palette-2025': style('global/palette-2025')},
        'usages': {}}).encode())


def test_brief_emits_documented_header_and_source_argv_follows_reference_index(project, tmp_path):
    brief_project(project)
    plan = generation_plan(inspect_document(project), 'avatar', {'variants': 1}, provider=PROVIDER)
    assert plan['prompt'] == EXPECTED_PROMPT
    assert plan['prompt_sha256'] == sha256(EXPECTED_PROMPT.encode()).hexdigest()
    assert plan['warnings'] == []
    header = yaml.safe_load(plan['prompt'].split('\n---\n', 1)[0].removeprefix('---\n'))
    assert header['schema'] == BRIEF_SCHEMA
    assert header['settings'] == {'resolution': '2K', 'aspect_ratio': '1:1'}
    assert [entry['index'] for entry in header['references']] == [0, 1]
    assert [entry['file'] for entry in header['references']] == [entry['path'].rsplit('/', 1)[1] for entry in plan['references']]
    record = tmp_path / 'sources.json'
    script = tmp_path / 'recording-generator'
    script.write_text('#!/usr/bin/env python3\nimport base64, hashlib, json, sys\nfrom pathlib import Path\nargv = sys.argv[1:]\n'
                      'sources = [argv[i + 1] for i, a in enumerate(argv) if a == "--source"]\n'
                      f'Path({str(record)!r}).write_text(json.dumps([hashlib.sha256(Path(s).read_bytes()).hexdigest() for s in sources]))\n'
                      f'Path(argv[argv.index("--output") + 1], "out.png").write_bytes(base64.b64decode({base64.b64encode(png((4, 4, 4))).decode()!r}))\n')
    script.chmod(0o700)
    job = generate(project, plan, 'avatar-1', generator=SubprocessImageGenerator(str(script)), provider=PROVIDER)
    assert job['status'] == 'succeeded', job
    argv_order = json.loads(record.read_text())
    assert argv_order == [entry['sha256'] for entry in plan['references']]
    for entry in header['references']:
        assert argv_order[entry['index']] == sha256(project.vault.joinpath(plan['references'][entry['index']]['path']).read_bytes()).hexdigest()


def test_brief_refuses_missing_asset_intent(project):
    brief_project(project, ASSET_DEFINITION.replace(b'intent: "Substack avatar; circle-cropped at 40px; must read as a stamp"\n', b''))
    with pytest.raises(DocumentWorkspaceError, match='intent') as error:
        generation_plan(inspect_document(project), 'avatar', provider=PROVIDER)
    assert error.value.code == 'DOCUMENT_DEFINITION_INVALID'


def test_brief_refuses_role_naming_unregistered_file(project):
    brief_project(project, ASSET_DEFINITION.replace(b'file: mark-sketch.png', b'file: ghost.png'))
    with pytest.raises(DocumentWorkspaceError, match='ghost.png') as error:
        generation_plan(inspect_document(project), 'avatar', provider=PROVIDER)
    assert error.value.code == 'DOCUMENT_INPUT_MISSING'


def test_brief_source_without_role_warns_instead_of_refusing(project):
    brief_project(project, ASSET_DEFINITION.replace(b'  - file: mark-sketch.png\n    role: "composition only; redraw, do not trace"\n', b'  - mark-sketch.png\n'))
    plan = generation_plan(inspect_document(project), 'avatar', provider=PROVIDER)
    assert plan['warnings'] == ['Reference mark-sketch.png from asset has no role; unlabeled references tend to be copied as composition']
    assert '{index: 1, file: mark-sketch.png, from: asset, role: "unspecified"}]' in plan['prompt']


def test_brief_warns_above_the_word_cap_and_hashes_the_whole_text(project):
    brief_project(project, ASSET_DEFINITION.replace(b'A rubber-stamp mark of a telescope.', b'word ' * 601))
    plan = generation_plan(inspect_document(project), 'avatar', provider=PROVIDER)
    assert any('600 words' in warning for warning in plan['warnings'])
    assert plan['prompt'].startswith('---\nschema: doxagon.image-brief/1\n')
    assert plan['prompt_sha256'] == sha256(plan['prompt'].encode()).hexdigest()


def test_brief_refuses_style_registered_under_another_dialect(project):
    brief_project(project)
    record = json.loads(project.path('outputs/document/authoring.json').read_bytes())
    record['styles']['master']['dialect'] = 'stored-style/1'
    project.path('outputs/document/authoring.json').write_text(json.dumps(record))
    with pytest.raises(DocumentWorkspaceError) as error:
        generation_plan(inspect_document(project), 'avatar', provider=PROVIDER)
    assert error.value.code == 'DOCUMENT_STYLE_UNKNOWN'


def test_create_asset_takes_dialect_from_frontmatter_and_refuses_disagreement(project):
    view = inspect_document(project)
    apply_plan(project, plan_create_asset(view, 'stamp', b'---\ndialect: brief/1\nintent: A stamp\n---\nA stamp.\n'))
    assert registry(inspect_document(project))['assets']['stamp']['dialect'] == 'brief/1'
    with pytest.raises(DocumentWorkspaceError) as error:
        plan_create_asset(inspect_document(project), 'other', b'---\ndialect: brief/1\n---\nA plate.\n', 'stored-style/1')
    assert error.value.code == 'DOCUMENT_DEFINITION_INVALID'


@pytest.mark.parametrize('value, expected', [
    ('Substack avatar; circle-cropped at 40px', 'Substack avatar; circle-cropped at 40px'),
    ('1:1', '"1:1"'), ('yes', '"yes"'), ('key: value', '"key: value"'), ('[bracketed]', '"[bracketed]"'),
    ('multi\nline', '"multi\\nline"'), ('', '""'),
])
def test_header_scalars_read_back_as_the_same_text(value, expected):
    assert yaml_scalar(value) == expected
    assert yaml.safe_load(f'key: {yaml_scalar(value)}') == {'key': value}


def test_brief_header_never_starts_a_line_with_a_space(project, tmp_path):
    """A composer that rewrites leading spaces must not be able to alter the prompt.

    Some providers accept prompt text through a composer that turns a
    line-leading space into U+00A0. The prompt is hashed and sent verbatim, so
    an adapter cannot repair the rewrite and correctly refuses to send. An
    emitted brief therefore starts no line with whitespace, while still
    parsing as the documented mapping.
    """
    settings = SimpleNamespace(api_resolution='2K', aspect_ratio='1:1')
    references = [{'index': 0, 'file': 'a.jpg', 'from': 'foundations/linework', 'role': 'line quality only'},
                  {'index': 1, 'file': 'b.png', 'from': 'asset', 'role': 'composition only; redraw'}]
    header = brief_header('An intent that mentions spacing', settings, references)

    assert [line for line in header.split('\n') if line.startswith((' ', '\t'))] == []
    parsed = yaml.safe_load(header.strip().strip('-'))
    assert parsed['references'] == references
    assert parsed['settings'] == {'resolution': '2K', 'aspect_ratio': '1:1'}
    assert yaml.safe_load(brief_header('x', settings, []).strip().strip('-'))['references'] == []
