"""Run a bounded fresh Pi/Claude skill exercise in a disposable synthetic vault.

Uses the user's configured harness model. Only the image exercise configures a
local deterministic image provider. The output retains transcripts and artifacts.
"""
import argparse
import base64
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skills-vault', type=Path, required=True)
    parser.add_argument('--harness', choices=['pi', 'claude'], required=True)
    parser.add_argument('--cwd', choices=['root', 'nested'], default='nested')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--timeout', type=int, default=180)
    parser.add_argument('--pi-transport', choices=['sse', 'websocket', 'auto'])
    parser.add_argument('--workflow', choices=['caption', 'image', 'style-cues'], default='caption')
    args = parser.parse_args()
    from tests.authored_vault import write_authored_project
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    vault = output / 'vault'
    write_authored_project(vault)
    for name in ['AGENTS.md', 'CLAUDE.md']:
        shutil.copy2(args.skills_vault / name, vault / name)
    for name in ['presentation-context', 'presentation-document', 'visual-definition', 'visual-concept-brainstorm']:
        shutil.copytree(args.skills_vault / '.pi/skills' / name, vault / '.pi/skills' / name)
        links = vault / '.claude/skills'
        links.mkdir(parents=True, exist_ok=True)
        (links / name).symlink_to('../../.pi/skills/' + name)
    (vault / '.agents').mkdir()
    (vault / '.agents/skills').symlink_to('../.pi/skills')
    shutil.copytree(args.skills_vault / '.claude/hooks', vault / '.claude/hooks')
    settings = json.loads((args.skills_vault / '.claude/settings.json').read_text())
    settings.pop('enabledPlugins', None)  # Unrelated plugins do not participate in this exercise.
    (vault / '.claude/settings.json').write_text(json.dumps(settings))
    if args.pi_transport:
        (vault / '.pi/settings.json').write_text(json.dumps({'transport': args.pi_transport}))
    if args.workflow != 'caption':
        from doxagon.renderings.document_assets import plan_create_asset
        from doxagon.renderings.document_changes import apply_plan
        from doxagon.renderings.document_inspection import inspect_document
        from doxagon.renderings.project import resolve_document_project
        project = resolve_document_project('observatory', cwd=vault, environ={})
        view = inspect_document(project)
        image = next(item for item in view.summary['items'] if item['kind'] == 'image')
        apply_plan(project, plan_create_asset(view, 'ink', b'Fine ink drawing.', references={'plate.png': image['id']}, style=True))
        apply_plan(project, plan_create_asset(inspect_document(project), 'telescope', b'---\nstyles: [ink]\n---\nA telescope under the stars.'))
    selected = vault / 'projects/observatory/outputs/document/observatory.html'
    before = selected.read_bytes()
    notes = vault / 'projects/observatory/outputs/document/notes.json'
    notes_before = notes.read_bytes()
    unrelated = vault / 'projects/observatory/unrelated-draft.txt'
    unrelated.write_text('Unrelated work in progress. Preserve this file.\n')
    subprocess.run(['git', 'init', '-q', '-b', 'test/document-skills', str(vault)], check=True)
    prompt = ('In the observatory presentation, change the image label "Plate 1" to "Telescope plate". '
              'Use the project\'s presentation workflow and verify the resulting document. '
              'Preserve unrelated work. Work only in this disposable vault; do not publish, call image providers, '
              'change platform code or change installed tools. Report what changed and how you verified it.')
    if args.workflow == 'image':
        prompt = ('In the observatory presentation, use the registered telescope asset and ink style with its reference to generate '
                  'exactly one candidate using the configured deterministic local test provider. Inspect the candidate and use it '
                  'only for image slot-0. Keep the reused image in slot-reused and all other usages unchanged. '
                  'Follow the project presentation skills and verify the result. The configured provider is free and local; this '
                  'request authorizes that one test candidate. Preserve unrelated work and notes. Work only in this disposable '
                  'vault; do not change provider, installed tools or platform code, or publish. Report your verification.')
    elif args.workflow == 'style-cues':
        prompt = ('In the observatory presentation, change the ink generation style from "Fine ink drawing." to '
                  '"Detailed ink drawing." and add a final reachable cue titled Stars with private presenter notes '
                  '"Show the stars.". Keep all five existing cue IDs and notes, update the document edition coherently, '
                  'and preserve all images and unrelated work. Follow the project presentation workflow and verify preview '
                  'and presentation navigation. Work only in this disposable vault; do not call an image provider, publish, '
                  'change platform code or installed tools. Report what changed and how you verified it.')
    (output / 'prompt.txt').write_text(prompt)
    env = {**os.environ, 'DOXAGON_PLATFORM': str(ROOT), 'PATH': str(ROOT / '.venv/bin') + os.pathsep + os.environ['PATH']}
    for key in ['DOXAGON_ROOT', 'DOXAGON_IMAGE_GENERATOR', 'DOXAGON_IMAGE_MODEL', 'CLAUDECODE']:
        env.pop(key, None)
    env['CLAUDE_PROJECT_DIR'] = str(vault)
    if args.workflow == 'image':
        from tests.synthetic_vault import png
        generator = output / 'test-image-provider'
        generator.write_text('#!/usr/bin/env python3\nimport argparse,base64\nfrom pathlib import Path\n'
                             'p=argparse.ArgumentParser()\np.add_argument("--prompt-file");p.add_argument("--output");'
                             'p.add_argument("--image-size");p.add_argument("--aspect-ratio");p.add_argument("--source",action="append")\n'
                             'a=p.parse_args()\nassert len(a.source)==1\nassert Path(a.source[0]).read_bytes()\n'
                             'Path(a.output,"result.png").write_bytes(base64.b64decode(' + repr(base64.b64encode(png((200, 30, 60))).decode()) + '))\n'
                             'with Path(__file__).with_suffix(".calls").open("a") as stream: stream.write("one\\n")\n')
        generator.chmod(0o700)
        env.update(DOXAGON_IMAGE_GENERATOR=str(generator), DOXAGON_IMAGE_MODEL='deterministic-fixture')
    cwd = vault if args.cwd == 'root' else selected.parent
    if args.harness == 'pi':
        command = ['pi', '--print', '--mode', 'json', '--no-session', '--no-extensions', '--approve', '--tools', 'read,bash,edit,write', prompt]
    else:
        command = ['claude', '--print', '--output-format', 'stream-json', '--verbose', '--no-session-persistence', '--max-budget-usd', '3',
                   '--permission-mode', 'acceptEdits', '--allowedTools', 'Read,Edit,Write,Bash,Skill',
                   '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}', '--', prompt]
    started = time.monotonic()
    with (output / 'transcript.jsonl').open('w') as stdout, (output / 'stderr.log').open('w') as stderr:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdout=stdout, stderr=stderr, start_new_session=True)
        try:
            code = process.wait(timeout=args.timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            code = 'timeout'
    after = selected.read_bytes()
    report = {'harness': args.harness, 'cwd': args.cwd, 'returncode': code, 'seconds': round(time.monotonic() - started, 1),
              'workflow': args.workflow,
              'pi_transport': args.pi_transport,
              'html_before': sha256(before).hexdigest(), 'html_after': sha256(after).hexdigest(),
              'requested_edit_only': after == before.replace(b'Plate 1', b'Telescope plate', 1),
              'notes_unchanged': notes.read_bytes() == notes_before,
              'unrelated_unchanged': unrelated.read_text() == 'Unrelated work in progress. Preserve this file.\n'}
    if args.workflow != 'caption':
        from doxagon.renderings.document_changes import registry
        from doxagon.renderings.document_images import ImageDocument
        from doxagon.renderings.document_validation import validate_change
        old, new = ImageDocument(before), ImageDocument(after)
        old_slots = {slot.attrs['id']: old.digest(slot) for slot in old.slots}
        new_slots = {slot.attrs['id']: new.digest(slot) for slot in new.slots}
        report['validation'] = validate_change(inspect_document(project), {selected: after})
        if args.workflow == 'image':
            calls = generator.with_suffix('.calls')
            record = registry(inspect_document(project))
            report['provider_calls'] = calls.read_text().splitlines() if calls.exists() else []
            report['requested_edit_only'] = (old_slots['slot-0'] != new_slots['slot-0']
                and {k: v for k, v in old_slots.items() if k != 'slot-0'} == {k: v for k, v in new_slots.items() if k != 'slot-0'}
                and len(record['assets']['telescope']['variants']) == 1 and report['provider_calls'] == ['one'])
        else:
            old_notes, new_notes = json.loads(notes_before), json.loads(notes.read_bytes())
            report['existing_notes_preserved'] = new_notes['cues'][:5] == old_notes['cues']
            report['requested_edit_only'] = (old_slots == new_slots and len(report['validation']['cues']) == 6
                and report['validation']['cues'][-1]['title'] == 'Stars'
                and new_notes['edition'] != old_notes['edition'] and new_notes['cues'][-1]['notes'] == 'Show the stars.'
                and project.path('assets/styles/ink/definition.md').read_text() == 'Detailed ink drawing.')
    elif report['requested_edit_only']:
        from doxagon.renderings.document_validation import validate_html
        report['validation'] = validate_html(after)
    (output / 'report.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2), flush=True)
    notes_ok = report.get('existing_notes_preserved', report['notes_unchanged'])
    return 0 if code == 0 and report['requested_edit_only'] and notes_ok and report['unrelated_unchanged'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
