import json

from click.testing import CliRunner
import pytest

from doxagon.renderings.document_changes import REGISTRY_SCHEMA
from doxagon.renderings.document_generation import provider_capabilities
from doxagon.renderings.project import resolve_document_project
from doxagon.renderings.style_lint import lint_styles, with_requires
from scripts.dox import cli
from tests.authored_vault import write_authored_project
from tests.synthetic_vault import png
from tests.test_prompt_dialect_stability import write

PROVIDER = {**provider_capabilities({}), 'configured': True}
STYLES = 'outputs/presentation/styles/'


@pytest.fixture
def project(tmp_path):
    write_authored_project(tmp_path)
    return resolve_document_project('observatory', cwd=tmp_path, environ={})


def by_rule(report, rule):
    return [item for item in report['findings'] if item['rule'] == rule]


def body_tag_corpus(project):
    """The vault's legacy shape: tags as identity, body markers as the only
    dependency statement, and one concatenated reference re-declaring tags."""
    write(project, STYLES + '3d/base/definition.md', b'# 3D Base\n\n**Tag:** `[3D_BASE]`\n\nBase.\n')
    write(project, STYLES + '3d/base/sources/base.png', png((1, 1, 1)))
    write(project, STYLES + '3d/characters/rabbit/definition.md', b'# Rabbit\n\n**Tag:** `[3D_RABBIT]`\n\n**Requires:** `[3D_BASE]`\n\nA rabbit.\n')
    write(project, STYLES + 'global/layout-driver/definition.md', b'# Layout\n\n**Tag:** `[LAYOUT_DRIVER]`\n\nGrid.\n')
    write(project, STYLES + 'diagram/vignette/definition.md', b'# Vignette\n\n**Tag:** `[DIAGRAM_VIGNETTE]`\n**Requires:** `[LAYOUT_DRIVER]`\n\nVoxels.\n')
    write(project, STYLES + 'FULL_REFERENCE/definition.md', b'# Everything\n\n**Tag:** `[LAYOUT_DRIVER]`\n\nGrid.\n\n**Tag:** `[DIAGRAM_VIGNETTE]`\n**Requires:** `[LAYOUT_DRIVER]`\n\nVoxels.\n')


def test_fix_requires_mirrors_body_tags_into_frontmatter_and_preserves_bodies(project):
    body_tag_corpus(project)
    before = {name: project.path(STYLES + name + '/definition.md').read_bytes() for name in ['3d/characters/rabbit', 'diagram/vignette', 'FULL_REFERENCE', '3d/base']}
    report = lint_styles(project, provider=PROVIDER)
    assert sorted(item['bundle'] for item in by_rule(report, 'requires-body-tag')) == [STYLES + '3d/characters/rabbit', STYLES + 'FULL_REFERENCE', STYLES + 'diagram/vignette']
    assert report['counts']['error'] == 3
    fixed = lint_styles(project, fix=True, provider=PROVIDER)
    assert {item['bundle']: item['requires'] for item in fixed['fixed']} == {
        STYLES + '3d/characters/rabbit': ['3d/base'], STYLES + 'diagram/vignette': ['global/layout-driver'], STYLES + 'FULL_REFERENCE': []}
    assert by_rule(fixed, 'requires-body-tag') == [] and fixed['counts']['error'] == 0
    assert by_rule(lint_styles(project, provider=PROVIDER), 'requires-body-tag') == []
    rabbit = project.path(STYLES + '3d/characters/rabbit/definition.md').read_bytes()
    assert rabbit == b'---\nrequires:\n  - 3d/base\n---\n\n' + before['3d/characters/rabbit']
    assert project.path(STYLES + 'FULL_REFERENCE/definition.md').read_bytes() == b'---\nrequires: []\n---\n\n' + before['FULL_REFERENCE']
    assert project.path(STYLES + '3d/base/definition.md').read_bytes() == before['3d/base']
    diff = next(item['diff'] for item in fixed['fixed'] if item['bundle'].endswith('rabbit'))
    assert diff.startswith('--- a/outputs/presentation/styles/3d/characters/rabbit/definition.md\n+++ b/') and '+  - 3d/base\n' in diff
    assert all(item['rule'] == 'body-marker' and item['severity'] == 'info' for item in fixed['findings'])


def test_fix_requires_leaves_unresolvable_or_ambiguous_tags_alone(project):
    write(project, STYLES + 'stray/definition.md', b'**Requires:** `[NOWHERE]`\nStray.\n')
    write(project, STYLES + 'twin-a/definition.md', b'**Tag:** `[TWIN]`\nA.\n')
    write(project, STYLES + 'twin-b/definition.md', b'**Tag:** `[TWIN]`\nB.\n')
    write(project, STYLES + 'wants-twin/definition.md', b'**Requires:** `[TWIN]`\nWants.\n')
    write(project, STYLES + 'fixable/definition.md', b'---\nlabel: Fixable\n---\n**Requires:** `[TWIN_A]`\n')
    write(project, STYLES + 'twin-a-only/definition.md', b'**Tag:** `[TWIN_A]`\nOnly.\n')
    report = lint_styles(project, fix=True, provider=PROVIDER)
    assert {item['bundle']: item['message'] for item in by_rule(report, 'requires-unresolved')} == {
        STYLES + 'stray': 'cannot map body **Requires:** to a bundle: NOWHERE',
        STYLES + 'wants-twin': 'cannot map body **Requires:** to a bundle: TWIN'}
    assert sorted(item['bundle'] for item in by_rule(report, 'requires-body-tag')) == [STYLES + 'stray', STYLES + 'wants-twin']
    assert project.path(STYLES + 'stray/definition.md').read_bytes() == b'**Requires:** `[NOWHERE]`\nStray.\n'
    assert project.path(STYLES + 'fixable/definition.md').read_bytes() == b'---\nrequires:\n  - twin-a-only\nlabel: Fixable\n---\n**Requires:** `[TWIN_A]`\n'


def test_with_requires_only_ever_prepends(project):
    assert with_requires('# Title\n', ['a']) == '---\nrequires:\n  - a\n---\n\n# Title\n'
    assert with_requires('\n---\nx: 1\n---\nBody\n', []) == '\n---\nrequires: []\nx: 1\n---\nBody\n'
    assert with_requires('---\nunterminated\n', ['a']) == '---\nrequires:\n  - a\n---\n\n---\nunterminated\n'


def test_dependency_source_and_closure_rules_use_the_negotiated_limit(project):
    write(project, STYLES + 'orphan/definition.md', b'---\nrequires: [ghost]\nsources: [missing.png, present.png]\n---\nOrphan.\n')
    write(project, STYLES + 'orphan/sources/present.png', png((1, 1, 1)))
    write(project, STYLES + 'loop-a/definition.md', b'---\nrequires: [loop-b]\n---\nA.\n')
    write(project, STYLES + 'loop-b/definition.md', b'---\nrequires: [loop-a]\n---\nB.\n')
    write(project, STYLES + 'heavy/definition.md', b'---\nrequires: [orphan]\n---\nHeavy.\n')
    for index in range(2):
        write(project, STYLES + f'heavy/sources/{index}.png', png((index, 0, 0)))
    write(project, STYLES + 'broken/definition.md', b'---\nrequires: not-a-list\n---\nBroken.\n')
    write(project, STYLES + 'unparsable/definition.md', b'---\n: [\n---\nBroken.\n')
    adapter = {**PROVIDER, 'max_references': 2, 'capabilities_source': 'adapter'}
    report = lint_styles(project, provider=adapter)
    assert [item['message'] for item in by_rule(report, 'requires-unknown')] == ['requires: names a bundle that does not exist: ghost']
    assert [item['message'] for item in by_rule(report, 'sources-missing')] == ['sources: names a file absent from sources/: missing.png']
    assert sorted(item['bundle'] for item in by_rule(report, 'dependency-cycle')) == [STYLES + 'loop-a', STYLES + 'loop-b']
    assert by_rule(report, 'dependency-cycle')[0]['message'] == 'requires cycle: loop-a -> loop-b -> loop-a'
    assert [(item['bundle'], item['message']) for item in by_rule(report, 'closure-too-large')] == [
        (STYLES + 'heavy', 'reference closure carries 3 images; the negotiated maximum is 2 (source: adapter)')]
    assert sorted(item['bundle'] for item in by_rule(report, 'definition-invalid')) == [STYLES + 'broken', STYLES + 'unparsable']
    assert by_rule(lint_styles(project, provider=PROVIDER), 'closure-too-large') == []
    assert report['max_references'] == 2 and report['capabilities_source'] == 'adapter'


def test_v2_projects_get_registry_and_dialect_rules(project):
    prefix = 'projects/observatory/'
    write(project, 'assets/styles/ink/definition.md', b'---\ndialect: stored-style/1\nsources: [nib.png, loose.png]\n---\nInk.\n')
    write(project, 'assets/styles/ink/sources/nib.png', png((2, 2, 2)))
    write(project, 'assets/styles/ink/sources/loose.png', png((3, 3, 3)))
    write(project, 'assets/styles/wash/definition.md', b'Wash.\n')
    write(project, STYLES + 'legacy/definition.md', b'**Tag:** `[LEGACY]`\nLegacy.\n')
    write(project, 'outputs/document/authoring.json', json.dumps({'schema': REGISTRY_SCHEMA, 'assets': {}, 'usages': {}, 'styles': {
        'ink': {'definition': prefix + 'assets/styles/ink/definition.md', 'dialect': 'stored-style/1', 'references': [prefix + 'assets/styles/ink/sources/nib.png']}}}).encode())
    report = lint_styles(project, provider=PROVIDER)
    assert [item['message'] for item in by_rule(report, 'sources-unregistered')] == ['sources: file is on disk but not registered in outputs/document/authoring.json: loose.png']
    assert sorted(item['bundle'] for item in by_rule(report, 'dialect-missing')) == ['assets/styles/wash', STYLES + 'legacy']
    assert all(item['severity'] == 'warning' for item in by_rule(report, 'dialect-missing'))
    assert by_rule(report, 'body-marker') == [{'bundle': STYLES + 'legacy', 'severity': 'info', 'rule': 'body-marker', 'message': 'stale **Tag:** marker [LEGACY]; brief/1 ignores it'}]


def test_cli_reports_fixes_and_exits_nonzero_only_on_errors(project, tmp_path, monkeypatch):
    body_tag_corpus(project)
    monkeypatch.setenv('DOXAGON_ROOT', str(project.vault))
    monkeypatch.delenv('DOXAGON_IMAGE_GENERATOR', raising=False)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    before = runner.invoke(cli, ['styles', 'lint', 'observatory'])
    assert before.exit_code == 1, before.output
    assert 'error requires-body-tag' in before.output and '3 errors' in before.output
    fixing = runner.invoke(cli, ['styles', 'lint', 'observatory', '--fix-requires'])
    assert fixing.exit_code == 0, fixing.output
    assert '+requires:\n+  - 3d/base\n' in fixing.output and '3 fixed; 0 errors' in fixing.output
    after = runner.invoke(cli, ['styles', 'lint', 'observatory', '--json'])
    assert after.exit_code == 0, after.output
    assert json.loads(after.output)['counts'] == {'error': 0, 'warning': 0, 'info': 9}
