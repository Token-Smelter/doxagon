"""Explicit canonical asset creation, relocation and usage selection plans."""
from __future__ import annotations

from pathlib import Path
import re

import yaml

from .document_changes import REGISTRY_PATH, json_bytes, make_plan, registry
from .document_images import add_slots, adopt_slots, encode_variant, replace_slots
from .document_inspection import Inspection, sha
from .project import DocumentWorkspaceError

RASTERS = {'.png', '.jpg', '.jpeg', '.webp'}
DIALECTS = {'legacy-bundle/1', 'stored-style/1', 'brief/1'}


def key_name(key: str) -> str:
    if not isinstance(key, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,99}', key):
        raise DocumentWorkspaceError('DOCUMENT_ASSET_KEY', 'Asset keys use lowercase letters, digits, underscores and hyphens')
    return key


def relative(view: Inspection, locator: str) -> str:
    prefix = f'projects/{view.project.slug}/'
    if not isinstance(locator, str) or not locator.startswith(prefix):
        raise DocumentWorkspaceError('DOCUMENT_PATH_ESCAPE', 'Registered inputs must use canonical project locators')
    result = locator[len(prefix):]
    view.project.path(result)
    return result


def locator(view: Inspection, path: str) -> str:
    return view.project.locator(view.project.path(path))


def definition(raw: bytes) -> tuple[dict, str]:
    try:
        # Legacy load_file_content strips the whole file before frontmatter
        # parsing; retain that exact prompt behavior after relocation.
        text = raw.decode('utf-8').strip()
        match = re.match(r'^---\s*\n(.*?)\n---\s*\n?', text, re.S)
        if text.startswith('---') and not match:
            raise ValueError()
        metadata = yaml.safe_load(match[1]) if match else {}
        if not isinstance(metadata, dict):
            raise ValueError()
        return metadata, text[match.end():].strip() if match else text
    except (UnicodeError, ValueError, yaml.YAMLError):
        raise DocumentWorkspaceError('DOCUMENT_DEFINITION_INVALID', 'Invalid definition frontmatter') from None


def string_list(value, name: str) -> list[str]:
    if not isinstance(value, list) or len(value) > 200 or not all(isinstance(x, str) and x for x in value):
        raise DocumentWorkspaceError('DOCUMENT_DEFINITION_INVALID', f'{name} requires a bounded list of names')
    return value


def roled_sources(metadata: dict) -> list[tuple[str, str | None]]:
    """brief/1 `sources:` items: a bare file name or {file, role}."""
    items = metadata.get('sources', [])
    if not isinstance(items, list) or len(items) > 200:
        raise DocumentWorkspaceError('DOCUMENT_DEFINITION_INVALID', 'sources requires a bounded list')
    result = []
    for item in items:
        if isinstance(item, str) and item:
            result.append((item, None))
        elif (isinstance(item, dict) and set(item) <= {'file', 'role'} and isinstance(item.get('file'), str) and item['file']
              and (item.get('role') is None or isinstance(item['role'], str))):
            result.append((item['file'], item.get('role') or None))
        else:
            raise DocumentWorkspaceError('DOCUMENT_DEFINITION_INVALID', 'sources items are file names or {file, role} objects')
    return result


def declared_sources(metadata: dict, dialect: str) -> list[str]:
    """Reference file names the frontmatter declares, read the way its dialect will."""
    if dialect == 'brief/1':
        return [name for name, _ in roled_sources(metadata)]
    return string_list(metadata.get('sources', []), 'sources')


def required(view: Inspection, path: str) -> bytes:
    raw = view.read(path)
    if raw is None:
        raise DocumentWorkspaceError('DOCUMENT_INPUT_MISSING', f'Missing input: {path}')
    return raw


def source_order(view: Inspection, bundle: str) -> list[str]:
    # Capture the legacy assembler's actual iteration order explicitly. Once
    # relocated, the registry preserves that order across fresh checkouts.
    path = view.project.path(bundle + '/sources')
    view.directory(bundle + '/sources')
    if not path.exists():
        return []
    return [str(child.relative_to(view.project.root)) for child in path.iterdir() if child.is_file() and child.suffix.lower() in RASTERS]


def copy_references(view: Inspection, base: str, selected: dict | None) -> tuple[dict[str, bytes], list[str]]:
    if selected is None:
        return {}, []
    if not isinstance(selected, dict) or len(selected) > 14:
        raise DocumentWorkspaceError('DOCUMENT_REFERENCE_LIMIT', 'Choose at most 14 named reference items')
    files, references = {}, []
    for name, identity in selected.items():
        if not isinstance(name, str) or Path(name).name != name or Path(name).suffix.lower() not in RASTERS:
            raise DocumentWorkspaceError('DOCUMENT_REFERENCE_INVALID', 'Reference names must be raster filenames without a directory')
        item = next((item for item in view.items if item['id'] == identity and item['kind'] in {'image', 'original', 'reference'}), None)
        if not item or identity not in view.contents:
            raise DocumentWorkspaceError('DOCUMENT_REFERENCE_INVALID', 'Select an available image item from this snapshot')
        target = f'{base}/sources/{name}'
        files[target] = view.contents[identity]
        references.append(locator(view, target))
    return files, references


def plan_create_asset(view: Inspection, key: str, raw: bytes, dialect: str | None = None, references: dict | None = None, *, style=False) -> dict:
    key_name(key)
    metadata, body = definition(raw)
    declared = metadata.get('dialect')
    if declared is not None and dialect is not None and declared != dialect:
        raise DocumentWorkspaceError('DOCUMENT_DEFINITION_INVALID', f'The definition declares dialect {declared}; the request asked for {dialect}')
    dialect = dialect or declared or 'legacy-bundle/1'
    if dialect not in DIALECTS:
        raise DocumentWorkspaceError('DOCUMENT_DIALECT_UNKNOWN', 'Choose legacy-bundle/1, stored-style/1 or brief/1')
    if not body:
        raise DocumentWorkspaceError('DOCUMENT_DEFINITION_INVALID', 'A visual description is required')
    record = registry(view)
    category = 'styles' if style else 'assets'
    if key in record[category]:
        raise DocumentWorkspaceError('DOCUMENT_ASSET_EXISTS', f'Asset {key} is already registered')
    base = f'assets/{"styles" if style else "visuals"}/{key}'
    path = base + '/definition.md'
    if view.read(path) is not None:
        raise DocumentWorkspaceError('DOCUMENT_ASSET_EXISTS', 'The definition already exists; explicitly adopt it')
    files, refs = copy_references(view, base, references)
    # Generation reads the registered reference list, not the bundle directory.
    # Accepting a definition whose sources: can never resolve would defer the
    # failure to generation-plan, long after the cause is recoverable here.
    available = {Path(reference).name for reference in refs}
    missing = [name for name in declared_sources(metadata, dialect) if name not in available]
    if missing:
        raise DocumentWorkspaceError(
            'DOCUMENT_REFERENCE_UNREGISTERED',
            f'{path} declares sources this request does not register: ' + ', '.join(missing)
            + '. Register each one in the request\'s "references" map as {"' + missing[0]
            + '": "ITEM_ID"}, naming an image, original or reference item id from this snapshot; '
            + f'placing a file in {base}/sources/ does not register it.')
    record[category][key] = {'label': str(metadata.get('label', key)), 'definition': locator(view, path),
                            'dialect': dialect, 'references': refs}
    if not style:
        record[category][key].update({'variants': {}, 'selected': None})
    files.update({path: raw, REGISTRY_PATH: json_bytes(record)})
    return make_plan(view, files, operation='create-style' if style else 'create-asset', details={'asset': key, 'dialect': dialect, 'references': refs})


def plan_adopt_bundle(view: Inspection, key: str, source: str) -> dict:
    """Copy the complete bundle and used style closure; public bytes stay put."""
    key_name(key)
    root = view.project.path(source)
    legacy_roots = [view.project.path(path) for path in ['outputs/presentation/slides', 'outputs/presentation/archive/slides']]
    if not any(root.is_relative_to(legacy) and root != legacy for legacy in legacy_roots):
        raise DocumentWorkspaceError('DOCUMENT_ADOPTION_SCOPE', 'Adoption source must be a legacy visual bundle under outputs/presentation/slides/ or archive/slides/')
    source = str(root.relative_to(view.project.root))
    record = registry(view)
    prior = next((entry for entry in record.get('adoptions', []) if entry.get('asset') == key and entry.get('source') == locator(view, source)), None)
    if prior:
        for old, mapped in prior['files'].items():
            if sha(required(view, relative(view, mapped['path']))) != mapped['sha256']:
                raise DocumentWorkspaceError('DOCUMENT_ADOPTION_DRIFT', f'Adopted file changed: {mapped["path"]}')
        return make_plan(view, {REGISTRY_PATH: json_bytes(record)}, operation='adopt-bundle', details={'asset': key, 'already_adopted': True})
    if key in record['assets']:
        raise DocumentWorkspaceError('DOCUMENT_ASSET_EXISTS', 'Choose a new asset key for this bundle')
    metadata, _ = definition(required(view, source + '/definition.md'))
    replacements = {}
    mappings = {}

    def copy_bundle(origin: str, target: str, *, visual=False):
        files = view.directory(origin)
        if origin + '/definition.md' not in files:
            raise DocumentWorkspaceError('DOCUMENT_INPUT_MISSING', f'No definition in {origin}')
        for old in files:
            tail = str(Path(old).relative_to(origin))
            if visual and tail.startswith('outputs/'):
                remainder = tail[len('outputs/'):]
                tail = ('derived/' if Path(remainder).name.startswith('.thumb') else 'variants/') + remainder
            new = f'{target}/{tail}'
            raw = required(view, old)
            existing = view.read(new)
            if existing is not None and existing != raw:
                raise DocumentWorkspaceError('DOCUMENT_ADOPTION_CONFLICT', f'Different bytes already exist at {new}')
            replacements[new] = raw
            mappings[locator(view, old)] = {'path': locator(view, new), 'sha256': sha(raw)}
        return [mappings[locator(view, path)]['path'] for path in source_order(view, origin)]

    references = copy_bundle(source, f'assets/visuals/{key}', visual=True)
    active, done = set(), set()

    def visit(style: str):
        if style in active:
            raise DocumentWorkspaceError('DOCUMENT_STYLE_CYCLE', f'Style cycle at {style}')
        if style in done:
            return
        if len(done) + len(active) >= 200 or not re.fullmatch(r'[a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_-]+)*', style):
            raise DocumentWorkspaceError('DOCUMENT_STYLE_INVALID', 'Invalid style key or oversized closure')
        active.add(style)
        origin = 'outputs/presentation/styles/' + style
        meta, _ = definition(required(view, origin + '/definition.md'))
        dependencies = string_list(meta.get('requires', []), 'requires')
        for dependency in dependencies:
            visit(dependency)
        refs = copy_bundle(origin, 'assets/styles/' + style)
        proposed = {'definition': locator(view, f'assets/styles/{style}/definition.md'), 'dialect': 'legacy-bundle/1', 'requires': dependencies, 'references': refs}
        if style in record['styles'] and record['styles'][style] != proposed:
            raise DocumentWorkspaceError('DOCUMENT_ADOPTION_CONFLICT', f'Registered style {style} has different inputs')
        record['styles'][style] = proposed
        active.remove(style)
        done.add(style)

    styles = string_list(metadata.get('styles', []), 'styles')
    for style in styles:
        visit(style)
    if view.read('outputs/presentation/styles/constraints/layout/definition.md') is not None:
        visit('constraints/layout')
    if any('diagram' in style for style in styles):
        for palette in ['global/palette-2025', 'global/palette']:
            if view.read(f'outputs/presentation/styles/{palette}/definition.md') is not None:
                visit(palette)
                break
    variants = {}
    for old, mapped in mappings.items():
        if old.startswith(locator(view, source) + '/outputs/') and '/variants/' in mapped['path'] and Path(old).suffix.lower() in RASTERS:
            variant = 'import-' + sha(old.encode())[:20]
            variants[variant] = {**mapped, 'provenance': 'historical_unknown', 'historical_path': old}
    record['assets'][key] = {'label': str(metadata.get('label', key)), 'definition': locator(view, f'assets/visuals/{key}/definition.md'),
                             'dialect': 'legacy-bundle/1', 'references': references, 'variants': variants, 'selected': None}
    record.setdefault('adoptions', []).append({'asset': key, 'source': locator(view, source), 'files': mappings})
    replacements[REGISTRY_PATH] = json_bytes(record)
    return make_plan(view, replacements, operation='adopt-bundle', details={'asset': key, 'files': mappings, 'styles': sorted(done), 'public_html_unchanged': True})


def admitted_raster(name: str, raw: bytes) -> str:
    """Admitted bytes must pass exactly the raster rule generated bytes pass."""
    from .document_generation import raster
    try:
        return raster(raw)
    except DocumentWorkspaceError as error:
        cause = ('exceeds the 32 MiB image limit' if error.code == 'DOCUMENT_IMAGE_LIMIT'
                 else 'is not a bounded single-frame PNG, JPEG or WebP raster')
        raise DocumentWorkspaceError('DOCUMENT_ADMISSION_IMAGE_INVALID', f'{name} {cause}; admission accepts only supported rasters') from None


def plan_admit_image(view: Inspection, key: str, source: str | None = None, item: str | None = None) -> dict:
    """Register existing bytes as a variant of an already registered asset.

    A generated variant carries a receipt binding it to a prompt, a provider
    identity and an executable digest. Admitted bytes have no such chain, so
    this records only what is true of them: the source they came from and their
    hash, under a provenance that is not `generated`.
    """
    record = registry(view)
    asset = record['assets'].get(key)
    if not asset:
        raise DocumentWorkspaceError('DOCUMENT_ASSET_UNKNOWN', f'Unknown asset {key}; register the asset before admitting an image into it')
    if (source is None) == (item is None):
        raise DocumentWorkspaceError('DOCUMENT_ADMISSION_SOURCE', 'Name exactly one of source (a project-relative path) or item (an inspection item id)')
    if source is not None:
        raw = required(view, source)
        origin = {'path': locator(view, source)}
        name = origin['path']
    else:
        found = next((entry for entry in view.items if entry['id'] == item and entry['kind'] in {'image', 'original', 'reference'}), None)
        if not found or item not in view.contents:
            raise DocumentWorkspaceError('DOCUMENT_ADMISSION_SOURCE', f'{item} is not an available image, original or reference item in this snapshot')
        raw = view.contents[item]
        origin = {'item': found['id'], **({'path': found['path']} if found.get('path') else {})}
        name = found['id']
    media = admitted_raster(name, raw)
    digest = sha(raw)
    variant = 'admitted-' + digest[:24]
    if variant in asset.get('variants', {}):
        raise DocumentWorkspaceError('DOCUMENT_VARIANT_EXISTS', f'Asset {key} already holds variant {variant} admitted from these exact bytes')
    path = f'assets/visuals/{key}/variants/{variant}.' + {'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp'}[media]
    # No receipt, prompt or provider identity is recorded: nothing generated
    # these bytes, and the record must not imply a provider call that never ran.
    candidate = {'path': locator(view, path), 'sha256': digest, 'provenance': 'admitted', 'admitted_from': origin}
    asset.setdefault('variants', {})[variant] = candidate
    return make_plan(view, {path: raw, REGISTRY_PATH: json_bytes(record)}, operation='admit-image',
                     details={'asset': key, 'variant': variant, 'media_type': media, **candidate})


def plan_bind_slots(view: Inspection, associations: dict[str, str]) -> dict:
    record = registry(view)
    html, slots = adopt_slots(view.contents[view.summary['document']['id']])
    if not associations or len(associations) > 1000:
        raise DocumentWorkspaceError('DOCUMENT_USAGE_INVALID', 'Name the slots and logical assets to associate')
    for slot, asset in associations.items():
        if slot not in slots or asset not in record['assets']:
            raise DocumentWorkspaceError('DOCUMENT_USAGE_INVALID', f'Unknown slot or asset: {slot}')
        record['usages'][slot] = {'asset': asset, 'embedded_sha256': slots[slot], 'provenance': 'association_only'}
    return make_plan(view, {relative(view, view.summary['document']['path']): html, REGISTRY_PATH: json_bytes(record)},
                     operation='bind-slots', details={'associations': associations, 'slots': slots})


def plan_select_image(view: Inspection, key: str, variant: str, slots: list[str], *, quality: int = 88) -> dict:
    record = registry(view)
    asset = record['assets'].get(key)
    candidate = asset.get('variants', {}).get(variant) if asset else None
    if not candidate or not isinstance(slots, list) or not slots or len(slots) != len(set(slots)):
        raise DocumentWorkspaceError('DOCUMENT_VARIANT_UNKNOWN', 'Choose a registered variant and distinct stable slots')
    raw = required(view, relative(view, candidate['path']))
    if sha(raw) != candidate['sha256']:
        raise DocumentWorkspaceError('DOCUMENT_VARIANT_DRIFT', 'Original variant bytes changed')
    expected = {}
    for slot in slots:
        usage = record['usages'].get(slot, {})
        if usage.get('asset') != key:
            raise DocumentWorkspaceError('DOCUMENT_USAGE_INVALID', f'Slot {slot} is not associated with {key}')
        expected[slot] = usage['embedded_sha256']
    encoded, receipt = encode_variant(raw, quality=quality)
    html = replace_slots(view.contents[view.summary['document']['id']], expected, encoded)
    receipt_id = 'encoding-' + sha(json_bytes(receipt))
    asset.setdefault('encodings', {})[receipt_id] = receipt
    all_slots = {slot for slot, usage in record['usages'].items() if usage.get('asset') == key}
    if set(slots) == all_slots:
        asset['selected'] = variant
    for slot in slots:
        record['usages'][slot].update({'variant': variant, 'encoding': receipt_id, 'embedded_sha256': sha(encoded), 'provenance': 'encoded_variant'})
    record['validation'] = None
    return make_plan(view, {relative(view, view.summary['document']['path']): html, REGISTRY_PATH: json_bytes(record)}, operation='select-image',
                     details={'asset': key, 'variant': variant, 'slots': slots, 'previous_payloads': expected, 'encoding': receipt})


def plan_add_slots(view: Inspection, container: str, slots: list[dict], *, quality: int = 88) -> dict:
    """Insert new stable slots filled from registered variants, recording the same encoding receipts as select-image."""
    record = registry(view)
    if not isinstance(container, str) or not container or not isinstance(slots, list) or not 1 <= len(slots) <= 200:
        raise DocumentWorkspaceError('DOCUMENT_USAGE_INVALID', 'Name an existing container id and 1..200 new slots')
    encodings: dict[tuple[str, str], tuple[bytes, str, dict]] = {}
    added = []
    for slot in slots:
        if not isinstance(slot, dict) or not isinstance(slot.get('id'), str) or not isinstance(slot.get('alt', ''), str):
            raise DocumentWorkspaceError('DOCUMENT_USAGE_INVALID', 'Each new slot needs an id, a key, a variant and optional alt text')
        identity, key, variant = slot['id'], slot.get('key'), slot.get('variant')
        if identity in record['usages']:
            raise DocumentWorkspaceError('DOCUMENT_USAGE_INVALID', f'Slot {identity} already has a recorded usage')
        asset = record['assets'].get(key)
        candidate = asset.get('variants', {}).get(variant) if asset else None
        if not candidate:
            raise DocumentWorkspaceError('DOCUMENT_VARIANT_UNKNOWN', f'Choose a registered variant for {identity}')
        if (key, variant) not in encodings:
            raw = required(view, relative(view, candidate['path']))
            if sha(raw) != candidate['sha256']:
                raise DocumentWorkspaceError('DOCUMENT_VARIANT_DRIFT', 'Original variant bytes changed')
            encoded, receipt = encode_variant(raw, quality=quality)
            receipt_id = 'encoding-' + sha(json_bytes(receipt))
            asset.setdefault('encodings', {})[receipt_id] = receipt
            encodings[(key, variant)] = (encoded, receipt_id, receipt)
        encoded, receipt_id, _ = encodings[(key, variant)]
        added.append({'id': identity, 'alt': slot.get('alt', ''), 'encoded': encoded})
        record['usages'][identity] = {'asset': key, 'variant': variant, 'encoding': receipt_id,
                                      'embedded_sha256': sha(encoded), 'provenance': 'encoded_variant'}
    html = add_slots(view.contents[view.summary['document']['id']], container, added)
    for key in {key for key, _ in encodings}:
        variants = {usage.get('variant') for usage in record['usages'].values() if usage.get('asset') == key}
        if len(variants) == 1 and None not in variants:
            record['assets'][key]['selected'] = variants.pop()
    record['validation'] = None
    return make_plan(view, {relative(view, view.summary['document']['path']): html, REGISTRY_PATH: json_bytes(record)}, operation='add-slots',
                     details={'container': container,
                              'slots': [{'id': s['id'], 'asset': record['usages'][s['id']]['asset'], 'variant': record['usages'][s['id']]['variant'],
                                         'encoding': record['usages'][s['id']]['encoding']} for s in added],
                              'encodings': {receipt_id: receipt for _, receipt_id, receipt in encodings.values()}})
