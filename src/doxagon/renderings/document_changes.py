"""Hash-checked authored-file plans, promoted through the vault WAL."""
from __future__ import annotations

import base64
from copy import deepcopy
import json
from pathlib import Path
import re
from typing import Mapping

from doxagon.wal import WriteAheadLog, WriterFence, RecoveryUnresolved
from .document_inspection import Inspection, barrier, inspect_document, sha, MAX_FILE, MAX_TOTAL
from .project import DocumentProject, DocumentWorkspaceError

PLAN_SCHEMA = 'doxagon.document-change/1'
REGISTRY_SCHEMA = 'doxagon.document-authoring/1'
REGISTRY_PATH = 'outputs/document/authoring.json'


def json_bytes(value: dict) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode()


def registry(view: Inspection) -> dict:
    raw = view.read(REGISTRY_PATH, 2 * 1024 * 1024)
    if raw is None:
        return {'schema': REGISTRY_SCHEMA, 'assets': {}, 'styles': {}, 'usages': {}, 'adoptions': [], 'validation': None}
    return parse_registry(raw)


def parse_registry(raw: bytes) -> dict:
    try:
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError()
        value = json.loads(raw)
        if not isinstance(value, dict) or value.get('schema') != REGISTRY_SCHEMA:
            raise ValueError()
        for key in ['assets', 'styles', 'usages']:
            if not isinstance(value.get(key), dict):
                raise ValueError()
        for category in ['assets', 'styles']:
            for key, entry in value[category].items():
                if not isinstance(entry, dict) or not isinstance(entry.get('definition'), str) or entry.get('dialect') not in {'legacy-bundle/1', 'stored-style/1', 'brief/1'}:
                    raise ValueError()
                if not isinstance(entry.get('references', []), list) or not all(isinstance(path, str) for path in entry.get('references', [])):
                    raise ValueError()
                if category == 'assets':
                    if not isinstance(entry.get('variants', {}), dict) or not isinstance(entry.get('encodings', {}), dict):
                        raise ValueError()
                    for variant in entry.get('variants', {}).values():
                        if not isinstance(variant, dict) or not isinstance(variant.get('path'), str) or not re.fullmatch(r'[a-f0-9]{64}', str(variant.get('sha256', ''))):
                            raise ValueError()
        for usage in value['usages'].values():
            if not isinstance(usage, dict) or not isinstance(usage.get('asset'), str) or not re.fullmatch(r'[a-f0-9]{64}', str(usage.get('embedded_sha256', ''))):
                raise ValueError()
        return value
    except (ValueError, UnicodeError):
        raise DocumentWorkspaceError('DOCUMENT_AUTHORING_INVALID', 'The private authoring record is invalid') from None


def mutable_path(view: Inspection, relative: str) -> Path:
    path = view.project.path(relative)
    document = view.summary['document']['path']
    notes = view.summary['notes']
    permitted = {document, f'projects/{view.project.slug}/{REGISTRY_PATH}'}
    if notes:
        permitted.add(notes['path'])
    if view.project.locator(path) not in permitted and not path.is_relative_to(view.project.path('assets')):
        raise DocumentWorkspaceError('DOCUMENT_CHANGE_SCOPE', 'Changes must target the selected document, notes, authoring record or canonical assets/')
    return path


def postimage_limit(view: Inspection, path: Path) -> int:
    notes = view.summary['notes']
    if path == view.project.path(REGISTRY_PATH) or notes and view.project.locator(path) == notes['path']:
        return 2 * 1024 * 1024
    return MAX_FILE


def make_plan(view: Inspection, replacements: Mapping[str, bytes], *, operation: str, details: dict | None = None) -> dict:
    if not replacements or len(replacements) > 512 or sum(map(len, replacements.values())) > MAX_TOTAL:
        raise DocumentWorkspaceError('DOCUMENT_CHANGE_LIMIT', 'A change requires 1..512 files within the total byte limit')
    changes = []
    for relative, payload in replacements.items():
        path = mutable_path(view, relative)
        if len(payload) > postimage_limit(view, path):
            raise DocumentWorkspaceError('DOCUMENT_CHANGE_LIMIT', f'{relative} exceeds its readable file limit')
        before = view.read(relative)
        if before == payload:
            continue
        if '/variants/' in relative and before is not None:
            raise DocumentWorkspaceError('DOCUMENT_IMMUTABLE_VARIANT', 'Original variants and their historical receipts cannot be overwritten')
        changes.append({'path': str(path.relative_to(view.project.root)), 'before': sha(before) if before is not None else None,
                        'after': sha(payload), 'bytes': len(payload), 'content_base64': base64.b64encode(payload).decode()})
    plan = {'schema': PLAN_SCHEMA, 'project': view.project.slug, 'snapshot': view.summary['snapshot'],
            'inputs': deepcopy(view.inputs), 'requests': deepcopy(view.requests), 'listings': deepcopy(view.listings),
            'operation': operation, 'details': details or {}, 'changes': changes}
    plan['id'] = sha(json_bytes(plan))
    return plan


def plan_summary(plan: dict) -> dict:
    return {**plan, 'changes': [{key: value for key, value in item.items() if key != 'content_base64'} for item in plan['changes']]}


def decode_plan(view: Inspection, plan: dict) -> dict[Path, bytes]:
    if not isinstance(plan, dict) or plan.get('schema') != PLAN_SCHEMA or plan.get('project') != view.project.slug:
        raise DocumentWorkspaceError('DOCUMENT_PLAN_INVALID', 'The plan does not name this project and supported schema')
    identity = plan.get('id')
    if identity != sha(json_bytes({key: value for key, value in plan.items() if key != 'id'})):
        raise DocumentWorkspaceError('DOCUMENT_PLAN_INVALID', 'The plan content hash disagrees')
    if plan.get('snapshot') != view.summary['snapshot']:
        raise DocumentWorkspaceError('DOCUMENT_SNAPSHOT_CONFLICT', 'Reread context for the current project snapshot', status=409)
    entries = plan.get('changes')
    if not isinstance(entries, list) or len(entries) > 512:
        raise DocumentWorkspaceError('DOCUMENT_PLAN_INVALID', 'Invalid change list')
    payloads = {}
    total = 0
    for entry in entries:
        try:
            path = mutable_path(view, entry['path'])
            raw = base64.b64decode(entry['content_base64'], validate=True)
            if sha(raw) != entry['after'] or len(raw) != entry['bytes'] or path in payloads:
                raise ValueError()
            if len(raw) > postimage_limit(view, path):
                raise ValueError()
            total += len(raw)
            if total > MAX_TOTAL:
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise DocumentWorkspaceError('DOCUMENT_PLAN_INVALID', 'A postimage is invalid or exceeds the change budget') from None
        payloads[path] = raw
        if '/variants/' in entry['path']:
            prior = view.read(entry['path'])
            if prior is not None and prior != raw:
                raise DocumentWorkspaceError('DOCUMENT_IMMUTABLE_VARIANT', 'Original variant material cannot be overwritten')
    return payloads


def validate_inputs(view: Inspection, plan: dict) -> None:
    """Recheck plan inputs including extra source files discovered by planning."""
    for relative in plan['requests']:
        view.read(relative)
    for relative in plan['listings']:
        view.directory(relative)
    changed = [path for path, expected in plan['inputs'].items() if view.inputs.get(path) != expected]
    changed += [path for path, expected in plan['listings'].items() if view.listings.get(path) != expected]
    if changed or plan['requests'] != {key: view.requests.get(key) for key in plan['requests']}:
        raise DocumentWorkspaceError('DOCUMENT_SNAPSHOT_CONFLICT', 'Reread changed inputs: ' + ', '.join(changed[:20]), status=409)


def apply_plan(project: DocumentProject, plan: dict) -> dict:
    # Expensive parsing and postimage validation happen before the vault fence.
    view = inspect_document(project)
    payloads = decode_plan(view, plan)
    validate_inputs(view, plan)
    if not payloads:
        return {'plan': plan['id'], 'status': 'unchanged', 'files': []}
    from .document_validation import validate_change
    proof = validate_change(view, payloads)
    fence = WriterFence(project.vault)
    fence.acquire()
    try:
        current = Inspection(project)
        if barrier(project) != view.summary['authority_generation']:
            raise DocumentWorkspaceError('DOCUMENT_SNAPSHOT_CONFLICT', 'Reread context after a concurrent change', status=409)
        validate_inputs(current, plan)
        # Checking explicit preimages also protects files absent from the
        # original inspection, such as newly registered candidates.
        for item in plan['changes']:
            raw = current.read(item['path'])
            if (sha(raw) if raw is not None else None) != item['before']:
                raise DocumentWorkspaceError('DOCUMENT_SNAPSHOT_CONFLICT', f"Reread {item['path']}", status=409)
        journal = WriteAheadLog(project.vault, fence)
        journal.initialize()
        transaction = journal.commit_replace_many(payloads)
    except RecoveryUnresolved as error:
        raise DocumentWorkspaceError('DOCUMENT_RECOVERY_PENDING', str(error), status=409) from error
    finally:
        fence.release()
    return {'plan': plan['id'], 'transaction': transaction, 'status': 'applied',
            'files': [{'path': project.locator(path), 'sha256': sha(raw)} for path, raw in payloads.items()], 'validation': proof}


def plan_text_change(view: Inspection, patches: list[dict]) -> dict:
    if not isinstance(patches, list) or not patches or len(patches) > 200 or not all(isinstance(patch, dict) for patch in patches):
        raise DocumentWorkspaceError('DOCUMENT_PATCH_INVALID', 'Supply 1..200 bounded patches')
    replacements = {}
    for patch in patches:
        item = next((item for item in view.items if item['id'] == patch.get('item')), None)
        if not item or item['kind'] not in {'document', 'notes', 'definition', 'generation_style'} or not item.get('path'):
            raise DocumentWorkspaceError('DOCUMENT_PATCH_UNSUPPORTED', 'Select a mutable file from the context; inline blocks are inspected through their document')
        relative = str(Path(item['path']).relative_to(Path('projects') / view.project.slug))
        mutable_path(view, relative)
        before, after = patch.get('before'), patch.get('after')
        if not isinstance(before, str) or not before or not isinstance(after, str):
            raise DocumentWorkspaceError('DOCUMENT_PATCH_INVALID', 'A patch requires nonempty before text and replacement text')
        raw = replacements.get(relative, view.contents[item['id']])
        text = raw.decode('utf-8')
        if text.count(before) != 1:
            raise DocumentWorkspaceError('DOCUMENT_PATCH_AMBIGUOUS', 'The exact before text must occur once in the selected file')
        if 'data:image/' in before or 'data:image/' in after:
            raise DocumentWorkspaceError('DOCUMENT_PATCH_UNSUPPORTED', 'Use image selection to change embedded payloads')
        replacements[relative] = text.replace(before, after, 1).encode()
    return make_plan(view, replacements, operation='text', details={'patches': len(patches)})
