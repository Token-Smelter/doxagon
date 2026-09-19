"""Read-only model dispatch and agent entry context, with no ambient selection."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import yaml

from .document_inspection import Inspection, barrier, inspect_document, sha
from .project import DocumentProject, DocumentWorkspaceError, resolve_document_project, resolve_vault_root


def inspect_project(project: DocumentProject, expected: str | None = None) -> Inspection:
    selection = project.path('outputs/document/presentation.json')
    if selection.exists() or selection.is_symlink():
        return inspect_document(project, expected)
    generation = barrier(project)
    view = Inspection(project)
    config = view.file('config.yaml', 'config', limit=256 * 1024)
    try:
        metadata = yaml.safe_load(view.contents[config['id']])
        if not isinstance(metadata, dict):
            raise ValueError()
    except (ValueError, KeyError, yaml.YAMLError):
        raise DocumentWorkspaceError('DOCUMENT_CONFIG_INVALID', 'Invalid project configuration') from None
    argument = view.file('thesis/core.md', 'argument', optional=True)
    head_path = '.doxagon-presentation-v2/store/HEAD'
    head_raw = view.read(head_path)
    model, selected = 'legacy', None
    cues = []
    slides = []
    if head_raw is not None:
        head = view.json(head_path, required=True)
        revision = head.get('revision', '')
        if head.get('schema') != 'doxagon.presentation-head/2' or not re.fullmatch(r'sha256:[a-f0-9]{64}', revision):
            raise DocumentWorkspaceError('DOCUMENT_STEP_INVALID', 'Invalid selected Step head')
        root = f'.doxagon-presentation-v2/store/revisions/{revision[7:]}'
        manifest = view.json(root + '/presentation.json', required=True)
        model, selected = 'step', {'revision': revision, 'manifest': project.locator(project.path(root + '/presentation.json'))}
        for item in manifest.get('checkpoints', [])[:1000]:
            cues.append({'id': item.get('id'), 'title': item.get('label')})
        view.file(root + '/presentation.json', 'step_manifest')
        view.check('step_model', 'Use the existing Step workspace for editing and generation; document mutations require an authored selection')
    else:
        files = view.directory('outputs/presentation')
        for path in files:
            if path.endswith('/slide.md') or path.endswith('/definition.md') or path == 'outputs/presentation/config.yaml':
                item = view.file(path, 'legacy_source')
                if path.endswith('/slide.md'):
                    slides.append({'id': item['id'], 'path': item['path']})
        view.check('legacy_model', 'Legacy source inventory only; reading context does not migrate the project or generate thumbnails')
    verify = Inspection(project)
    for path in view.requests:
        verify.read(path)
    for path in view.listings:
        verify.directory(path)
    if generation != barrier(project) or view.inputs != verify.inputs or view.requests != verify.requests or view.listings != verify.listings:
        raise DocumentWorkspaceError('DOCUMENT_SNAPSHOT_CONFLICT', 'Project changed while reading context', status=409)
    snapshot = sha(json.dumps({'project': project.slug, 'inputs': view.inputs, 'listings': view.listings, 'generation': generation}, sort_keys=True).encode())
    if expected is not None and expected != snapshot:
        raise DocumentWorkspaceError('DOCUMENT_SNAPSHOT_CONFLICT', 'Refresh project context', status=409)
    view.summary = {'schema': 'doxagon.document-inspection/1', 'snapshot': snapshot, 'project': project.slug,
                    'title': str(metadata.get('title', project.slug))[:2000], 'audience': str(metadata.get('audience', ''))[:2000],
                    'model': model, 'selection': selected, 'document': None, 'notes': None,
                    'links': {key: str(metadata[key])[:2000] for key in ['diegesis', 'walk', 'fork_of'] if key in metadata},
                    'argument': {'source': argument['path'] if argument else None,
                                 'diegesis': f"knowledge/diegeses/{metadata['diegesis']}.md" if isinstance(metadata.get('diegesis'), str) and re.fullmatch(r'[A-Za-z0-9_-]+', metadata['diegesis']) else None},
                    'items': view.items, 'cues': cues, 'slides': slides, 'usages': [], 'checks': view.checks, 'coverage': 'partial',
                    'capabilities': {'inspect': True, 'edit': False, 'generate': False}}
    return view


def environment_context(project: DocumentProject) -> dict:
    install = Path(__file__).resolve().parents[3]
    state = {'status': 'unavailable', 'files': []}
    env = {**os.environ, 'GIT_OPTIONAL_LOCKS': '0'}
    platform_sha = None
    try:
        changed = subprocess.run(['git', 'status', '--porcelain=v1', '-z', '--untracked-files=normal', '--', f'projects/{project.slug}'], cwd=project.vault, env=env, capture_output=True, timeout=5)
        if changed.returncode == 0 and len(changed.stdout) < 1024 * 1024:
            paths = changed.stdout.decode(errors='replace').split('\0')
            state = {'status': 'dirty' if changed.stdout else 'clean', 'files': paths[:200], 'truncated': len(paths) > 200}
        result = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=install, env=env, capture_output=True, timeout=5)
        if result.returncode == 0:
            platform_sha = result.stdout.decode().strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return {'cwd': str(Path.cwd().resolve()), 'vault': str(project.vault), 'project_root': str(project.root),
            'platform_command': shutil.which('dox'), 'platform_module': str(Path(__file__).resolve()),
            'python': sys.executable, 'platform_sha': platform_sha, 'working_tree': state}


def context(project_name: str | None = None) -> dict:
    try:
        project = resolve_document_project(project_name)
    except DocumentWorkspaceError as error:
        if error.code != 'DOCUMENT_PROJECT_REQUIRED':
            raise
        root = resolve_vault_root()
        names = []
        for path in sorted((root / 'projects').iterdir()):
            if len(names) >= 2000:
                break
            if path.is_dir() and path.resolve().is_relative_to(root) and (path / 'config.yaml').is_file():
                names.append(path.name)
        return {'schema': 'doxagon.document-context/1', 'project': None, 'vault': str(root), 'cwd': str(Path.cwd()),
                'projects': names, 'next': 'Choose the project explicitly with --project NAME'}
    view = inspect_project(project)
    from .document_generation import provider_capabilities
    return {**view.summary, 'environment': environment_context(project), 'generation': provider_capabilities(),
            'machinery': {'help': 'dox document --help', 'source': 'dox document inspect --project NAME --item ITEM --snapshot SNAPSHOT',
                          'design': 'docs/document-inspection.md',
                          'operations': 'docs/document-authoring.md'},
            'inputs': [{'path': path, **metadata} for path, metadata in view.inputs.items()]}
