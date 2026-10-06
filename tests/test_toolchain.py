from hashlib import sha256
import json
from pathlib import Path
import re

from click.testing import CliRunner

from doxagon.renderings.document_generation import provider_capabilities
from doxagon.presentation_backends import resolve_image_generator_path
from doxagon import toolchain
from doxagon.toolchain import resource_status, skill_status
from scripts.dox import cli
from tests.authored_vault import write_authored_project

# Names the orientation must never teach: platform-side paths, a retired vault
# script, and the legacy corpus aliases the canonical names replaced.
RETIRED_NAMES = ('factory/scripts', 'publish/', 'load_context.py', 'presentation-factory', 'library/', 'theses/')


def adapter(path: Path) -> Path:
    path.write_text("""#!/usr/bin/env python3
import json, sys
from pathlib import Path
if sys.argv[1:] == ['--capabilities']:
    counter = Path(__file__ + '.count')
    counter.write_text(str(int(counter.read_text()) + 1) if counter.exists() else '1')
    print(json.dumps({'schema': 'doxagon.provider-capabilities/1', 'max_references': 10, 'resolutions': ['1K'], 'aspect_ratios': ['1:1'], 'model': 'fixture', 'text_rendering': False}))
    raise SystemExit(0)
out = Path(sys.argv[sys.argv.index('--output') + 1])
out.joinpath('fixture.png').write_bytes(b'fixture')
""")
    path.chmod(0o700)
    return path


def provisioned(tmp_path, monkeypatch) -> tuple[Path, dict[str, str]]:
    """Build a vault and environment in which every doctor check passes."""
    platform = tmp_path / 'platform'
    (platform / 'apps/web/frontend/build').mkdir(parents=True)
    monkeypatch.setattr(toolchain, 'platform_root', lambda: platform)
    monkeypatch.setattr(toolchain, 'platform_sha', lambda: 'a' * 40)
    vault = tmp_path / 'vault'
    (vault / 'knowledge').mkdir(parents=True)
    (vault / 'projects').mkdir()
    toolchain.sync_agent_resources(vault)
    binary = tmp_path / 'bin'
    binary.mkdir()
    dox = binary / 'dox'
    dox.write_text('#!/bin/sh\nexit 0\n')
    dox.chmod(0o700)
    environment = {'PATH': str(binary), 'DOXAGON_ROOT': str(vault),
                   'DOXAGON_IMAGE_GENERATOR': str(adapter(tmp_path / 'adapter'))}
    return vault, environment


def test_skills_sync_preserves_foreign_skill(tmp_path):
    vault = tmp_path / 'vault'
    vault.mkdir()
    runner = CliRunner()
    first = runner.invoke(cli, ['skills', 'sync', '--vault', str(vault), '--json'])
    assert first.exit_code == 0, first.output
    assert json.loads(first.output)['created']
    assert (vault / '.pi/skills/.platform-manifest.json').is_file()
    second = runner.invoke(cli, ['skills', 'sync', '--vault', str(vault), '--json'])
    assert second.exit_code == 0
    assert json.loads(second.output)['changed'] is False
    target = vault / '.pi/skills/presentation-context/SKILL.md'
    target.write_text('local edit')
    third = runner.invoke(cli, ['skills', 'sync', '--vault', str(vault), '--json'])
    assert 'presentation-context' in json.loads(third.output)['foreign']
    assert target.read_text() == 'local edit'
    assert skill_status(vault)['presentation-context']['status'] == 'foreign'


def test_skills_sync_refuses_unmanaged_name_collision(tmp_path):
    vault = tmp_path / 'vault'
    target = vault / '.pi/skills/presentation-context/SKILL.md'
    target.parent.mkdir(parents=True)
    target.write_text('vault-owned content')
    result = CliRunner().invoke(cli, ['skills', 'sync', '--vault', str(vault), '--json'])
    assert result.exit_code == 0
    assert 'presentation-context' in json.loads(result.output)['foreign']
    assert target.read_text() == 'vault-owned content'


def test_doctor_reports_provisioned_and_invalid_vault(tmp_path, monkeypatch):
    _, environment = provisioned(tmp_path, monkeypatch)
    healthy = CliRunner().invoke(cli, ['doctor'], env=environment)
    assert healthy.exit_code == 0, healthy.output
    assert 'frontend: built' in healthy.output
    for invalid in ('', str(tmp_path / 'wrong')):
        failed = CliRunner().invoke(cli, ['doctor'], env={**environment, 'DOXAGON_ROOT': invalid})
        assert failed.exit_code == 1
        assert 'vault_binding: failing' in failed.output


def test_doctor_reports_agents_md_in_the_skill_status_vocabulary(tmp_path, monkeypatch):
    vault, environment = provisioned(tmp_path, monkeypatch)
    orientation = vault / 'AGENTS.md'
    manifest = vault / toolchain.MANIFEST_PATH
    recorded = json.loads(manifest.read_text())

    current = CliRunner().invoke(cli, ['doctor'], env=environment)
    assert current.exit_code == 0, current.output
    assert 'agents_md: current' in current.output

    manifest.write_text(json.dumps({**recorded, 'platform_sha': 'b' * 40}))
    stale = CliRunner().invoke(cli, ['doctor'], env=environment)
    assert stale.exit_code == 1
    assert 'agents_md: stale' in stale.output

    manifest.write_text(json.dumps(recorded))
    orientation.write_text('local edit')
    foreign = CliRunner().invoke(cli, ['doctor'], env=environment)
    assert foreign.exit_code == 1
    assert 'agents_md: foreign' in foreign.output

    orientation.unlink()
    missing = CliRunner().invoke(cli, ['doctor'], env=environment)
    assert missing.exit_code == 1
    assert 'agents_md: missing' in missing.output


def test_skills_sync_installs_agents_md_and_refuses_to_clobber_an_edit(tmp_path):
    vault = tmp_path / 'vault'
    vault.mkdir()
    runner = CliRunner()
    sync = ['skills', 'sync', '--vault', str(vault), '--json']
    orientation = vault / 'AGENTS.md'

    installed = json.loads(runner.invoke(cli, sync).output)
    assert 'AGENTS.md' in installed['created']
    packaged = orientation.read_bytes()

    repeated = json.loads(runner.invoke(cli, sync).output)
    assert repeated['changed'] is False and 'AGENTS.md' in repeated['current']

    orientation.write_text('local edit')
    edited = json.loads(runner.invoke(cli, sync).output)
    assert 'AGENTS.md' in edited['foreign']
    assert orientation.read_text() == 'local edit'

    forced = json.loads(runner.invoke(cli, [*sync, '--force']).output)
    assert 'AGENTS.md' in forced['updated']
    assert orientation.read_bytes() == packaged


def test_legacy_skills_manifest_upgrades_without_reflagging_skills(tmp_path):
    vault = tmp_path / 'vault'
    packaged = toolchain.packaged_skills()
    for name, content in packaged.items():
        target = vault / '.pi/skills' / name / 'SKILL.md'
        target.parent.mkdir(parents=True)
        target.write_bytes(content)
    (vault / toolchain.MANIFEST_PATH).write_text(json.dumps({
        'schema': toolchain.SKILLS_MANIFEST_SCHEMA,
        'platform_sha': toolchain.platform_sha(),
        'synced_at': '2026-01-01T00:00:00+00:00',
        'skills': {name: {'sha256': sha256(content).hexdigest()} for name, content in packaged.items()},
    }, indent=2))

    before = resource_status(vault)
    assert {before[name]['status'] for name in packaged} == {'current'}
    attachments = set(toolchain.packaged_resources()) - set(packaged)
    assert {before[name]['status'] for name in attachments} == {'missing'}

    report = toolchain.sync_agent_resources(vault)
    assert set(report['created']) == attachments and report['foreign'] == []
    assert {record['status'] for record in resource_status(vault).values()} == {'current'}
    upgraded = json.loads((vault / toolchain.MANIFEST_PATH).read_text())
    assert upgraded['schema'] == toolchain.AGENT_RESOURCES_MANIFEST_SCHEMA


def test_forced_sync_leaves_the_vault_owned_conventions_file_untouched(tmp_path):
    vault = tmp_path / 'vault'
    vault.mkdir()
    local = vault / 'AGENTS.local.md'
    local.write_bytes(b'# Local conventions\n\nVault-owned, never platform-written.\n')

    forced = CliRunner().invoke(cli, ['skills', 'sync', '--vault', str(vault), '--force', '--json'])

    assert forced.exit_code == 0, forced.output
    assert local.read_bytes() == b'# Local conventions\n\nVault-owned, never platform-written.\n'


def test_init_writes_packaged_orientation_leading_with_doctor(tmp_path):
    vault = tmp_path / 'created'

    created = CliRunner().invoke(cli, ['init', str(vault)])

    assert created.exit_code == 0, created.output
    orientation = (vault / 'AGENTS.md').read_bytes()
    assert orientation == toolchain.packaged_agents_md()
    text = orientation.decode('utf-8')
    assert re.search(r'`dox [a-z]+', text).group(0) == '`dox doctor'
    assert 'AGENTS.local.md' in text


def test_packaged_orientation_names_only_canonical_directories():
    text = toolchain.packaged_agents_md().decode('utf-8')

    assert [name for name in RETIRED_NAMES if name in text] == []
    assert 'knowledge/' in text and 'projects/' in text


def test_provider_check_and_capability_narrowing(tmp_path):
    executable = adapter(tmp_path / 'adapter')
    result = CliRunner().invoke(cli, ['provider', 'check', '--executable', str(executable), '--live', '--yes'])
    assert result.exit_code == 0, result.output
    capabilities = provider_capabilities({'DOXAGON_IMAGE_GENERATOR': str(executable)})
    assert capabilities['max_references'] == 10
    assert capabilities['capabilities_source'] == 'adapter'
    assert provider_capabilities({'DOXAGON_IMAGE_GENERATOR': str(executable)}) == capabilities
    assert executable.with_name(executable.name + '.count').read_text() == '2'


def test_provider_name_prefers_user_adapter_directory(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    preferred = home / '.doxagon/providers/fixture'
    preferred.parent.mkdir(parents=True)
    adapter(preferred)
    path_bin = tmp_path / 'bin'
    path_bin.mkdir()
    adapter(path_bin / 'fixture')
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('PATH', str(path_bin))
    assert resolve_image_generator_path('fixture') == preferred.resolve()


def test_context_orients_document_and_legacy_projects(tmp_path, monkeypatch):
    project = write_authored_project(tmp_path / 'vault')
    monkeypatch.setenv('DOXAGON_ROOT', str(project.parents[1]))
    runner = CliRunner()
    document = runner.invoke(cli, ['context', project.name, '--json'])
    assert document.exit_code == 0, document.output
    document_report = json.loads(document.output)
    assert document_report['model']['name'] == 'document-model'
    assert document_report['argument_sources']['diegesis'] == 'knowledge/diegeses/synthetic.md'
    (project / 'outputs/document/presentation.json').unlink()
    slide = project / 'outputs/presentation/slides/one/slide.md'
    slide.parent.mkdir(parents=True)
    slide.write_text('Legacy source')
    legacy = runner.invoke(cli, ['context', project.name, '--json'])
    assert legacy.exit_code == 0, legacy.output
    legacy_report = json.loads(legacy.output)
    assert legacy_report['model']['name'] == 'legacy-slides'
    assert legacy_report['argument_sources']['diegesis'] == 'knowledge/diegeses/synthetic.md'
    assert legacy_report['inspection']['slides'][0]['path'].endswith('/slides/one/slide.md')
