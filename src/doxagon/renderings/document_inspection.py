"""Bounded, nonexecuting inspection of the selected authored HTML.

The same snapshot is used by the private workspace and local CLI. No store is
opened, files created, remote references fetched, or document script executed.
Item IDs are locators within a hash-bound snapshot, never filesystem authority.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
import hashlib
from html.parser import HTMLParser
from io import BytesIO
import json
from pathlib import Path
import re
import warnings

from PIL import Image
import yaml

from doxagon.renderings.project import DocumentProject, DocumentWorkspaceError
from doxagon.wal import read_authority_generation, RecoveryUnresolved

MAX_HTML = 32 * 1024 * 1024
MAX_FILE = 32 * 1024 * 1024
MAX_TOTAL = 256 * 1024 * 1024
MAX_ITEMS = 2000
MAX_PIXELS = 40_000_000
PAGE_SIZE = 16_000
DATA_URL = re.compile(r"data:image/[-+.\w]+;base64,[A-Za-z0-9+/=\s]+")
VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def opaque(kind: str, locator: str) -> str:
    return kind + '-' + sha(locator.encode())[:24]


def text_source(raw: bytes) -> str:
    return DATA_URL.sub('[embedded image payload]', raw.decode('utf-8', errors='replace'))


@dataclass
class Inspection:
    project: DocumentProject
    items: list[dict] = field(default_factory=list)
    contents: dict[str, bytes] = field(default_factory=dict)
    inputs: dict[str, dict] = field(default_factory=dict)
    requests: dict[str, str] = field(default_factory=dict)
    listings: dict[str, list[str]] = field(default_factory=dict)
    checks: list[dict] = field(default_factory=list)
    total: int = 0
    summary: dict = field(default_factory=dict)
    generation_details: dict[str, dict] = field(default_factory=dict)

    def check(self, code: str, message: str) -> None:
        if len(self.checks) < 100 and not any(x['code'] == code and x['message'] == message for x in self.checks):
            self.checks.append({'code': code, 'message': message})

    def read(self, relative: str, limit: int = MAX_FILE) -> bytes | None:
        path = self.project.path(relative)
        locator = self.project.locator(path)
        self.requests[relative] = locator
        if locator in self.inputs:
            return self.contents.get(opaque('file', locator))
        if len(self.inputs) >= MAX_ITEMS:
            raise DocumentWorkspaceError('DOCUMENT_LIMIT', 'Too many registered inputs to inspect safely')
        try:
            with path.open('rb') as stream:
                raw = stream.read(limit + 1)
        except FileNotFoundError:
            self.inputs[locator] = {'status': 'missing'}
            return None
        except OSError:
            self.inputs[locator] = {'status': 'unreadable'}
            self.check('unreadable', f'{locator} could not be read')
            return None
        if len(raw) > limit or self.total + len(raw) > MAX_TOTAL:
            raise DocumentWorkspaceError('DOCUMENT_LIMIT', f'{locator} exceeds the inspection byte budget')
        self.total += len(raw)
        self.inputs[locator] = {'sha256': sha(raw), 'bytes': len(raw), 'status': 'current'}
        self.contents[opaque('file', locator)] = raw
        return raw

    def directory(self, relative: str) -> list[str]:
        root = self.project.path(relative)
        files = []
        for index, path in enumerate(root.rglob('*')):
            if index >= MAX_ITEMS:
                raise DocumentWorkspaceError('DOCUMENT_LIMIT', 'Too many files in an authoring bundle directory')
            if path.is_file() and '.doxagon-stage' not in path.parts:
                # Validate every discovered path before it becomes an item.
                self.project.path(str(path.relative_to(self.project.root)))
                files.append(str(path.relative_to(self.project.root)))
        self.listings[relative] = sorted(files)
        return self.listings[relative]

    def file(self, relative: str, kind: str, *, optional: bool = False, limit: int = MAX_FILE) -> dict | None:
        raw = self.read(relative, limit)
        locator = self.project.locator(self.project.path(relative))
        if raw is None and optional:
            return None
        item = {'id': opaque('file', locator), 'kind': kind, 'label': Path(relative).name,
                'path': locator, **self.inputs[locator]}
        existing = next((x for x in self.items if x['id'] == item['id']), None)
        if existing is not None:
            return existing
        self.items.append(item)
        return item

    def json(self, relative: str, *, required: bool = False) -> dict:
        raw = self.read(relative, 2 * 1024 * 1024)
        try:
            value = json.loads(raw) if raw is not None else None
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except (ValueError, UnicodeError):
            if required:
                raise DocumentWorkspaceError('DOCUMENT_SELECTION_INVALID', f'Invalid {relative}') from None
            self.check('missing' if raw is None else 'invalid_metadata', f'{relative} is missing or invalid')
            return {}

    def image(self, url: str) -> dict | None:
        if not url.startswith('data:image/') or ';base64,' not in url:
            self.check('unresolved_image', 'An image uses a nonembedded or unsupported source; it was not fetched')
            return None
        try:
            raw = base64.b64decode(re.sub(r'\s+', '', url.split(',', 1)[1]), validate=True)
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(BytesIO(raw)) as image:
                    if image.width * image.height > MAX_PIXELS or image.format not in {'PNG', 'JPEG', 'WEBP', 'GIF'}:
                        raise ValueError()
                    width, height, media = image.width, image.height, Image.MIME[image.format]
        except (ValueError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
            self.check('unsupported_image', 'An embedded image could not be inspected within raster limits; inspect its source')
            return None
        digest = sha(raw)
        identity = opaque('image', digest)
        prior = next((x for x in self.items if x['id'] == identity), None)
        if prior is not None:
            return prior
        item = {'id': identity, 'kind': 'image', 'label': 'Embedded image', 'sha256': digest,
                'bytes': len(raw), 'width': width, 'height': height, 'media_type': media,
                'status': 'observed', 'provenance': 'unknown', 'usages': []}
        self.items.append(item)
        self.contents[identity] = raw
        return item


class Inventory(HTMLParser):
    def __init__(self, inspection: Inspection):
        super().__init__(convert_charrefs=True)
        self.inspection = inspection
        self.stack: list[tuple[str, dict]] = []
        self.usages: list[dict] = []
        self.payloads: dict[str, str] = {}
        self.cues: list[dict] = []
        self.sections: list[dict] = []
        self.elements = 0
        self.blocks: list[tuple[str, list[str]]] = []
        self.active_block: tuple[str, list[str]] | None = None

    def handle_starttag(self, tag: str, attrs: list) -> None:
        self.elements += 1
        count = len(self.inspection.items) + len(self.usages) + len(self.cues) + len(self.sections) + len(self.blocks)
        if self.elements > 100_000 or count >= MAX_ITEMS:
            raise DocumentWorkspaceError('DOCUMENT_LIMIT', 'Document structure exceeds inspection limits')
        data = dict(attrs)
        if data.get('style'):
            self.blocks.append(('inline_style', [data['style']]))
        if self.active_block and self.active_block[0] in {'svg', 'canvas'}:
            self.active_block[1].append(self.get_starttag_text())
        ancestors = [x[1] for x in self.stack]
        section = next((x.get('id') for x in reversed(ancestors) if 'chapter' in (x.get('class') or '').split()), None)
        if tag == 'section' and data.get('id'):
            self.sections.append({'id': data['id'][:1000], 'title': (data.get('aria-label') or data['id'])[:1000], 'line': self.getpos()[0]})
        if data.get('data-cue'):
            self.cues.append({'id': data['data-cue'][:1000], 'title': '', 'section': section, 'line': self.getpos()[0]})
        if tag in {'script', 'style', 'svg', 'canvas'}:
            self.active_block = (tag, [])
            self.blocks.append(self.active_block)
            if tag in {'svg', 'canvas'}:
                self.active_block[1].append(self.get_starttag_text())
            if tag == 'canvas':
                self.inspection.check('unresolved_dynamic', 'Canvas drawing is visible as source; its generated contents are unknown')
        if tag in {'img', 'image'}:
            payload = next((x.get('data-dox-source') for x in reversed(ancestors) if x.get('data-dox-source')), None)
            source = data.get('src') or data.get('href') or data.get('xlink:href')
            image = self.inspection.image(source) if source else None
            if payload:
                if image:
                    if payload in self.payloads:
                        self.inspection.check('duplicate_payload', f'Duplicate payload key {payload[:100]}')
                    self.payloads[payload] = image['id']
            else:
                usage = {'id': (data.get('id') or f'observed-slot-{len(self.usages)+1}')[:1000],
                         'stable': bool(data.get('id')), 'alt': (data.get('alt') or '')[:2000],
                         'section': section, 'line': self.getpos()[0], 'payload': data.get('data-dox-asset'),
                         'image': image['id'] if image else None}
                self.usages.append(usage)
        if tag not in VOID:
            self.stack.append((tag, data))

    def handle_startendtag(self, tag: str, attrs: list) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag, literal=False)

    def handle_endtag(self, tag: str, *, literal: bool = True) -> None:
        if literal and self.active_block and self.active_block[0] in {'svg', 'canvas'}:
            self.active_block[1].append(f'</{tag}>')
        if self.active_block and self.active_block[0] == tag:
            self.active_block = None
        for i in range(len(self.stack)-1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data: str) -> None:
        if self.active_block:
            self.active_block[1].append(data)
        elif self.cues and any(x.get('data-cue') == self.cues[-1]['id'] for _, x in self.stack):
            self.cues[-1]['title'] = (self.cues[-1]['title'] + data)[:1000]

    def finish(self) -> None:
        for index, (kind, parts) in enumerate(self.blocks):
            if kind in {'style', 'inline_style'}:
                for found in DATA_URL.finditer(''.join(parts)):
                    image = self.inspection.image(found[0])
                    self.usages.append({'id': f'observed-css-{index}-{len(self.usages)}', 'stable': False,
                                        'section': None, 'alt': 'CSS image', 'line': None, 'payload': None,
                                        'image': image['id'] if image else None})
        seen: set[str] = set()
        for usage in self.usages:
            if usage['id'] in seen:
                self.inspection.check('duplicate_slot', f"Duplicate image slot {usage['id'][:100]}")
            seen.add(usage['id'])
            usage['image'] = usage['image'] or self.payloads.get(usage.pop('payload'))
            image = next((x for x in self.inspection.items if x['id'] == usage['image']), None)
            if image:
                image['usages'].append(usage['id'])
                image['label'] = image.get('alt') or usage['alt'] or image['label']
                image['alt'] = image.get('alt') or usage['alt']
            else:
                self.inspection.check('unresolved_image', f"No observed embedded payload for {usage['id'][:100]}")
        for index, (kind, parts) in enumerate(self.blocks):
            raw = ''.join(parts).encode()
            identity = opaque('block', f'{kind}:{index}')
            self.inspection.items.append({'id': identity, 'kind': kind, 'label': f'{kind} block {index+1}',
                                          'bytes': len(raw), 'sha256': sha(raw), 'status': 'observed'})
            self.inspection.contents[identity] = raw
        for cue in self.cues:
            cue['title'] = cue['title'].strip() or cue['id']
        self.inspection.check('static_inspection', 'Script-generated visuals and dependencies are not evaluated; runtime cues are verified separately by the player')


def barrier(project: DocumentProject) -> tuple | None:
    path = project.vault / '.doxagon' / 'authority-generation.json'
    if not path.exists():
        if any((project.vault / '.doxagon' / 'wal').glob('*.json')):
            raise DocumentWorkspaceError('DOCUMENT_RECOVERY_PENDING', 'The vault needs write recovery', status=409)
        return None
    try:
        value = read_authority_generation(project.vault)
        if value[0] % 2 or value[1] is not None:
            raise RecoveryUnresolved('write in progress')
        return value
    except RecoveryUnresolved:
        raise DocumentWorkspaceError('DOCUMENT_RECOVERY_PENDING', 'The vault has an unresolved or pending write', status=409) from None


def inspect_document(project: DocumentProject, expected: str | None = None) -> Inspection:
    initial = barrier(project)
    view = Inspection(project)
    config_item = view.file('config.yaml', 'config', limit=256 * 1024)
    try:
        config = yaml.safe_load(view.contents[config_item['id']])
        if not isinstance(config, dict):
            raise ValueError()
    except (ValueError, KeyError, yaml.YAMLError):
        raise DocumentWorkspaceError('DOCUMENT_CONFIG_INVALID', 'The project config is invalid') from None
    directory = 'outputs/document/'
    argument = view.file('thesis/core.md', 'argument', optional=True)
    selection = view.json(directory + 'presentation.json', required=True)
    if selection.get('schema') != 'doxagon.authored-document/1' or set(selection) - {'schema', 'document', 'notes'}:
        raise DocumentWorkspaceError('DOCUMENT_SELECTION_INVALID', 'Unsupported authored document selection')
    for key, suffixes in [('document', {'.html', '.htm'}), ('notes', {'.json'})]:
        name = selection.get(key)
        if name is None and key == 'notes':
            continue
        if not isinstance(name, str) or '/' in name or '\\' in name or Path(name).suffix.lower() not in suffixes:
            raise DocumentWorkspaceError('DOCUMENT_SELECTION_INVALID', f'Invalid selected {key} filename')
        if not project.path(directory + name).is_relative_to(project.path(directory)):
            raise DocumentWorkspaceError('DOCUMENT_PATH_ESCAPE', 'Selected files must stay inside the rendering directory')
    view.file(directory + 'presentation.json', 'selection')
    document = view.file(directory + selection['document'], 'document', limit=MAX_HTML)
    raw = view.contents.get(document['id'])
    if not raw:
        raise DocumentWorkspaceError('DOCUMENT_SOURCE_MISSING', 'The selected HTML is missing or empty')
    inventory = Inventory(view)
    inventory.feed(raw.decode('utf-8', errors='replace'))
    inventory.close()
    inventory.finish()
    notes = view.file(directory + selection['notes'], 'notes', limit=2 * 1024 * 1024) if selection.get('notes') else None
    notes_metadata = None
    if notes is None or notes['status'] != 'current':
        view.check('missing_notes', 'Companion notes are missing; playback remains available')
    else:
        try:
            companion = json.loads(view.contents[notes['id']])
            if not isinstance(companion, dict) or not all(isinstance(companion.get(k), str) and 0 < len(companion[k]) <= 1000 for k in ['documentId', 'edition']):
                raise ValueError()
            cues = companion.get('cues')
            if not isinstance(cues, list) or len(cues) > 1000 or not all(isinstance(cue, dict) and isinstance(cue.get('id'), str) and 0 < len(cue['id']) <= 1000 for cue in cues):
                raise ValueError()
            if len({cue['id'] for cue in cues}) != len(cues) or not all(isinstance(cue.get('notes'), str) for cue in cues):
                raise ValueError()
            notes_metadata = {'documentId': companion['documentId'], 'edition': companion['edition'], 'cues': [cue['id'] for cue in cues]}
        except (ValueError, UnicodeError):
            view.check('invalid_notes', 'Companion notes have invalid identity or cue metadata')
    assets = view.json(directory + 'assets.json')
    view.file(directory + 'assets.json', 'provenance', optional=True)
    registry = view.json(directory + 'authoring.json')
    view.file(directory + 'authoring.json', 'authoring', optional=True)
    entries = assets.get('assets', [])
    if not isinstance(entries, list) or len(entries) > MAX_ITEMS:
        view.check('invalid_metadata', 'The legacy asset index is invalid or oversized')
        entries = []
    definitions: set[str] = set()
    for root, kind in [('assets/visuals', 'definition'), ('assets/styles', 'generation_style'),
                       ('outputs/presentation/styles', 'generation_style')]:
        for relative in view.directory(root):
            if relative.endswith('/definition.md'):
                view.file(relative, kind)
                definitions.add(relative)
    view.file('outputs/presentation/config.yaml', 'legacy_config', optional=True)
    for item in list(view.items):
        if item['kind'] != 'image':
            continue
        hints = [entry for entry in entries if isinstance(entry, dict) and entry.get('embedded_sha256') == item['sha256']]
        if len(hints) != 1:
            item['provenance'] = 'ambiguous' if hints else 'unknown'
            continue
        hint = hints[0]
        locator = hint.get('source')
        prefix = f'projects/{project.slug}/'
        if isinstance(locator, str) and locator.startswith(f'theses/{project.slug}/'):
            locator = prefix + locator[len(f'theses/{project.slug}/'):]
        if not isinstance(locator, str) or not locator.startswith(prefix):
            item['provenance'] = 'unavailable'
            continue
        relative = locator[len(prefix):]
        source = view.file(relative, 'original')
        item['original'] = source['id']
        item['provenance'] = ('missing_original' if source['status'] != 'current' else
                              'verified_hash_pair' if source.get('sha256') == hint.get('source_sha256') else 'stale_original')
        definition = str(Path(relative).parent.parent / 'definition.md')
        definition_item = view.file(definition, 'definition', optional=True)
        if definition_item:
            source['definition'] = definition_item['id']
            definitions.add(definition)
    # Only known definition bundles and their explicit style closure are read.
    # The legacy index provides historical locations, never an inferred receipt.
    pending = list(sorted(definitions))
    visited: set[str] = set()
    while pending:
        relative = pending.pop(0)
        if relative in visited:
            continue
        visited.add(relative)
        if len(visited) > 200:
            view.check('reference_limit', 'Definition/style closure exceeds 200 bundles')
            break
        raw_definition = view.read(relative)
        if not raw_definition:
            continue
        match = re.match(r'^---\s*\n(.*?)\n---', raw_definition.decode('utf-8', errors='replace'), re.S)
        try:
            metadata = yaml.safe_load(match[1]) if match else {}
            if not isinstance(metadata, dict):
                raise ValueError()
        except (ValueError, yaml.YAMLError):
            view.check('invalid_metadata', f'{relative} has invalid definition metadata')
            continue
        dependencies = metadata.get('styles', []) if 'styles' in metadata else metadata.get('requires', [])
        if not isinstance(dependencies, list) or len(dependencies) > 200:
            view.check('invalid_metadata', f'{relative} has invalid style dependencies')
            continue
        record = next(x for x in view.items if x.get('path') == project.locator(project.path(relative)))
        record['dependencies'] = dependencies
        references = metadata.get('sources', [])
        if not isinstance(references, list) or len(references) > 200:
            view.check('invalid_metadata', f'{relative} has invalid reference inputs')
            references = []
        record['references'] = []
        for reference in references:
            if isinstance(reference, str):
                target = str(Path(relative).parent / 'sources' / reference)
                ref_item = view.file(target, 'reference')
                record['references'].append(ref_item['id'])
                if ref_item['status'] != 'current':
                    view.check('missing_reference', f'{target} is missing')
        for key in dependencies:
            if not isinstance(key, str):
                continue
            style_root = 'assets/styles' if relative.startswith('assets/') else 'outputs/presentation/styles'
            target = f'{style_root}/{key}/definition.md'
            style = view.file(target, 'generation_style')
            if style and style['status'] != 'current':
                view.check('missing_style', f'{target} is missing')
            if style and target not in visited:
                pending.append(target)
    from .document_registry import inspect_registry
    authoring = inspect_registry(view, registry, inventory.usages)
    from .document_provenance import inspect_generation_details
    inspect_generation_details(view, authoring, registry)
    # Rehash every included input, including absences. An edit during assembly
    # produces a conflict rather than a supposedly current mixed snapshot.
    verify_inspection(view, initial)
    snapshot = sha(json.dumps({'project': project.slug, 'inputs': view.inputs, 'listings': view.listings,
                              'generation': initial}, sort_keys=True).encode())
    if expected is not None and snapshot != expected:
        raise DocumentWorkspaceError('DOCUMENT_SNAPSHOT_CONFLICT', 'A new revision is available; refresh the workspace', status=409)
    view.summary = {
        'schema': 'doxagon.document-inspection/1', 'snapshot': snapshot, 'model': 'authored',
        'authority_generation': initial,
        'project': project.slug, 'title': str(config.get('title') or project.slug)[:2000],
        'audience': str(config.get('audience') or '')[:2000],
        'links': {key: str(config[key])[:2000] for key in ['diegesis', 'walk', 'fork_of'] if key in config},
        'argument': {'source': argument['path'] if argument else None,
                     'diegesis': f"knowledge/diegeses/{config['diegesis']}.md" if isinstance(config.get('diegesis'), str) and re.fullmatch(r'[A-Za-z0-9_-]+', config['diegesis']) else None},
        'document': document, 'notes': notes, 'notes_metadata': notes_metadata, 'items': view.items,
        'cues': inventory.cues, 'sections': inventory.sections, 'usages': inventory.usages,
        'checks': view.checks, 'coverage': 'partial',
        'authoring': authoring,
        'capabilities': {'inspect': True, 'edit': True, 'generate': True, 'adopt_assets': True, 'select_image': True,
                         'commands': ['context', 'inspect', 'plan', 'asset-plan', 'apply', 'validate', 'recover', 'generation-plan', 'generation-run', 'generation-job']},
    }
    return view


def verify_inspection(view: Inspection, expected: tuple | None) -> None:
    """Rehash a parsed view before reuse; cache identity never replaces evidence."""
    if barrier(view.project) != expected:
        raise DocumentWorkspaceError('DOCUMENT_SNAPSHOT_CONFLICT', 'Authority changed; refresh the workspace', status=409)
    verify = Inspection(view.project)
    for relative in view.requests:
        verify.read(relative)
    for relative in view.listings:
        verify.directory(relative)
    if (verify.inputs != view.inputs or verify.requests != view.requests
            or verify.listings != view.listings or barrier(view.project) != expected):
        raise DocumentWorkspaceError('DOCUMENT_SNAPSHOT_CONFLICT', 'Inputs changed during inspection; refresh the workspace', status=409)


def read_item(view: Inspection, identity: str, offset: int = 0) -> dict:
    item = next((item for item in view.items if item['id'] == identity), None)
    if item is None:
        raise DocumentWorkspaceError('DOCUMENT_ITEM_UNKNOWN', 'Unknown inspection item', status=404)
    if item['kind'] in {'image', 'original', 'reference'}:
        return {'item': item, 'generation': view.generation_details.get(identity, {
            'origins': [], 'message': 'No generation inputs are linked to this image.'})}
    body = text_source(view.contents.get(identity, b''))
    offset = max(0, offset)
    return {'item': item, 'text': body[offset:offset+PAGE_SIZE], 'offset': offset,
            'next': offset+PAGE_SIZE if offset+PAGE_SIZE < len(body) else None, 'total': len(body)}


def image_bytes(view: Inspection, identity: str, thumbnail: bool = False) -> tuple[bytes, str]:
    item = next((x for x in view.items if x['id'] == identity and x['kind'] in {'image', 'original', 'reference'}), None)
    if item is None or identity not in view.contents:
        raise DocumentWorkspaceError('DOCUMENT_ITEM_UNKNOWN', 'Image is unavailable', status=404)
    raw = view.contents[identity]
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as image:
                if image.width * image.height > MAX_PIXELS or image.format not in {'PNG', 'JPEG', 'WEBP', 'GIF'}:
                    raise ValueError()
                if not thumbnail:
                    return raw, Image.MIME[image.format]
                image.thumbnail((320, 240))
                output = BytesIO()
                image.convert('RGB').save(output, format='JPEG', quality=75)
                return output.getvalue(), 'image/jpeg'
    except (ValueError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise DocumentWorkspaceError('DOCUMENT_IMAGE_UNSUPPORTED', 'The image cannot be previewed safely') from None
