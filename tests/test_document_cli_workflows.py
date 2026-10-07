import base64
import json

from click.testing import CliRunner

from doxagon.renderings.document_cli import document_group
from doxagon.renderings.document_images import ImageDocument
from tests.authored_vault import write_authored_project
from tests.synthetic_vault import png


def test_documented_cli_image_style_and_cue_workflows(tmp_path, monkeypatch):
    project = write_authored_project(tmp_path / 'vault')
    monkeypatch.chdir(project / 'outputs/document')
    monkeypatch.delenv('DOXAGON_ROOT', raising=False)
    script = tmp_path / 'generator'
    script.write_text('#!/usr/bin/env python3\nimport argparse,base64\nfrom pathlib import Path\np=argparse.ArgumentParser()\np.add_argument("--prompt-file");p.add_argument("--output");p.add_argument("--image-size");p.add_argument("--aspect-ratio");p.add_argument("--source",action="append")\na=p.parse_args()\nassert a.source and len(a.source)==1\nassert all(Path(x).read_bytes() for x in a.source)\nPath(a.output,"result.png").write_bytes(base64.b64decode(' + repr(base64.b64encode(png((200, 30, 60))).decode()) + '))\n')
    script.chmod(0o700)
    monkeypatch.setenv('DOXAGON_IMAGE_GENERATOR', str(script))
    monkeypatch.setenv('DOXAGON_IMAGE_MODEL', 'deterministic-fixture')
    runner = CliRunner()
    sequence = 0

    def run(*args):
        result = runner.invoke(document_group, list(args))
        assert result.exit_code == 0, result.output
        return json.loads(result.output)

    def context():
        return run('context', '--json')

    def apply_request(value, *, text=False):
        nonlocal sequence
        sequence += 1
        request = tmp_path / f'request-{sequence}.json'
        output = tmp_path / f'plan-{sequence}.json'
        request.write_text(json.dumps(value))
        run('plan' if text else 'asset-plan', '--snapshot', context()['snapshot'], '--change' if text else '--request', str(request), '--output', str(output))
        return run('apply', str(output))

    current = context()
    assert current['environment']['cwd'] == str(project / 'outputs/document')
    assert current['generation']['configured']
    image = next(item for item in current['items'] if item['kind'] == 'image')
    apply_request({'operation': 'create-style', 'key': 'ink', 'definition': 'Fine ink drawing.', 'references': {'plate.png': image['id']}})
    apply_request({'operation': 'create', 'key': 'telescope', 'definition': '---\nstyles: [ink]\n---\nA telescope under the stars.'})
    html = project / 'outputs/document/observatory.html'
    original = html.read_bytes()
    output = tmp_path / 'generation.json'
    run('generation-plan', '--snapshot', context()['snapshot'], '--asset', 'telescope', '--variants', '1', '--output', str(output))
    job = run('generation-run', '--key', 'one-telescope', str(output))
    assert job['status'] == 'succeeded', job
    assert html.read_bytes() == original
    assert run('generation-run', '--key', 'one-telescope', str(output)) == job
    apply_request({'operation': 'bind-slots', 'associations': {'slot-0': 'telescope', 'slot-reused': 'telescope'}})
    apply_request({'operation': 'select-image', 'key': 'telescope', 'variant': job['outputs'][0]['asset_id'], 'slots': ['slot-0']})
    before, after = ImageDocument(original), ImageDocument(html.read_bytes())
    assert before.digest(before.slots[0]) != after.digest(after.slots[0])
    assert before.digest(before.slots[-1]) == after.digest(after.slots[-1])
    apply_request({'patches': [{'item': context()['document']['id'], 'before': '</body>', 'after': '<div id="textures" hidden></div></body>'}]}, text=True)
    apply_request({'operation': 'add-slots', 'container': 'textures', 'slots': [{'id': 'tex-paper', 'alt': '', 'key': 'telescope', 'variant': job['outputs'][0]['asset_id']}]})
    assert sum(1 for slot in ImageDocument(html.read_bytes()).slots if slot.attrs.get('id') == 'tex-paper') == 1
    run('validate', '--record')
    assert context()['authoring']['validation'] == 'current'
    from doxagon.renderings import document_validation
    with monkeypatch.context() as changed_build:
        changed_build.setattr(document_validation, 'validation_identity', lambda: {'source_sha256': 'changed'})
        assert context()['authoring']['validation'] == 'stale'
    style = next(item for item in context()['items'] if item.get('path', '').endswith('/ink/definition.md'))
    selected = html.read_bytes()
    apply_request({'patches': [{'item': style['id'], 'before': 'Fine ink drawing.', 'after': 'Detailed ink drawing.'}]}, text=True)
    assert html.read_bytes() == selected
    assert context()['authoring']['assets'][0]['variants'][0]['current_definition'] == 'changed'
    assert context()['authoring']['validation'] == 'stale'

    # Add one real runtime cue, including the layout/travel limits that make
    # it reachable. HTML/edition/notes land as one checked transaction.
    current = context()
    item = current['document']['id']
    pairs = [("'Night']", "'Night', 'Stars']"), ("const edition = 'public-1'", "const edition = 'public-2'"),
             ('Math.min(4, scrollY / innerHeight)', 'Math.min(5, scrollY / innerHeight)'),
             ('Math.min(4, Math.floor(position + .0001))', 'Math.min(5, Math.floor(position + .0001))'),
             ('Math.min(4, (travel?.index ?? state().index) + direction)', 'Math.min(5, (travel?.index ?? state().index) + direction)'),
             ('index === 4 ? 1', 'index === 5 ? 1'), ('height:500vh', 'height:600vh'), ('top:420vh', 'top:520vh')]
    patches = [{'item': item, 'before': a, 'after': b} for a, b in pairs]
    notes_path = project / 'outputs/document/notes.json'
    old = notes_path.read_text()
    notes = json.loads(old)
    notes['edition'] = 'public-2'
    notes['cues'].append({'id': 'cue-5', 'notes': 'Show the stars.'})
    patches.append({'item': current['notes']['id'], 'before': old, 'after': json.dumps(notes)})
    result = apply_request({'patches': patches}, text=True)
    assert result['validation']['edition'] == 'public-2'
    assert len(result['validation']['cues']) == 6
    assert 'Show the stars.' not in html.read_text()


def test_root_lists_projects_and_invalid_selection_never_revives_legacy(tmp_path, monkeypatch):
    project = write_authored_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv('DOXAGON_ROOT', raising=False)
    runner = CliRunner()
    result = runner.invoke(document_group, ['context', '--json'])
    assert result.exit_code == 0
    assert json.loads(result.output)['projects'] == ['observatory']
    selected = project / 'outputs/document/presentation.json'
    selected.write_text('broken')
    result = runner.invoke(document_group, ['context', '--project', 'observatory', '--json'])
    assert result.exit_code != 0 and 'DOCUMENT_SELECTION_INVALID' in result.output
    selected.unlink()
    legacy = project / 'outputs/presentation/slides/one/slide.md'
    legacy.parent.mkdir(parents=True)
    legacy.write_text('Legacy slide')
    result = runner.invoke(document_group, ['context', '--project', 'observatory', '--json'])
    assert result.exit_code == 0
    assert json.loads(result.output)['model'] == 'legacy'
    assert not (project / '.doxagon-presentation-v2').exists()
