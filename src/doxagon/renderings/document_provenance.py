"""Private image-to-prompt inspection over the same bounded source snapshot.

Current assembly uses the generator's implementation. Saved bundle prompts
without a matching receipt remain useful evidence, never an exact-image claim.
No provider, filesystem mutation, or authored-frame execution is involved.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

from .document_assets import definition, relative, source_order, string_list
from .document_generation import assemble_asset
from .document_inspection import MAX_ITEMS, MAX_TOTAL, Inspection, opaque, sha
from .project import DocumentWorkspaceError

TAG = re.compile(r'\[([A-Z][A-Z0-9_-]{0,99})\]')


def inspect_generation_details(view: Inspection, authoring: dict, registry: dict) -> None:
    items = {item['id']: item for item in view.items}
    contexts = {}

    def file(path, kind, *, optional=False):
        item = view.file(relative(view, path), kind, optional=optional)
        if item:
            items[item['id']] = item
        return item

    def fragment(path, label, text):
        identity = opaque('generation', path)
        if identity not in items:
            raw = text.encode()
            if len(view.items) >= MAX_ITEMS or view.total + len(raw) > MAX_TOTAL:
                raise DocumentWorkspaceError('DOCUMENT_LIMIT', 'Generation details exceed inspection limits')
            view.total += len(raw)
            item = {'id': identity, 'kind': 'prompt_fragment', 'label': label,
                    'status': 'derived', 'bytes': len(raw), 'sha256': sha(raw)}
            view.items.append(item)
            items[identity] = item
            view.contents[identity] = raw
        return identity

    def legacy_binding(path):
        bundle = str(Path(relative(view, path)).parent)
        references = []
        for ref in source_order(view, bundle):
            item = view.file(ref, 'reference')
            items[item['id']] = item
            references.append(item['path'])
        return {'definition': path, 'dialect': 'legacy-bundle/1', 'references': references}

    def context(asset, styles):
        cache_key = json.dumps([asset, styles], sort_keys=True)
        if cache_key in contexts:
            return contexts[cache_key]
        result = {'definition': None, 'image_prompt': None, 'constraints': None,
                  'image_tags': [], 'components': [], 'references': [], 'unresolved_tags': [],
                  'current_assembled': None, 'current_settings': None, 'issues': []}
        contexts[cache_key] = result
        active, visited = set(), set()

        def read_bundle(binding):
            if not isinstance(binding, dict):
                raise DocumentWorkspaceError('DOCUMENT_DEFINITION_INVALID', 'Invalid style binding')
            item = file(binding.get('definition'), 'definition')
            if item['status'] != 'current':
                raise DocumentWorkspaceError('DOCUMENT_INPUT_MISSING', f"Missing definition: {item['path']}")
            meta, body = definition(view.contents[item['id']])
            refs = []
            for path in string_list(binding.get('references', []), 'references'):
                ref = file(path, 'reference')
                refs.append(ref['id'])
            return item, meta, body, refs

        def visit(name, role):
            if name in active:
                result['issues'].append(f'Style dependency cycle: {name}')
                return
            if name in visited:
                return
            if len(visited) + len(active) >= 200:
                raise DocumentWorkspaceError('DOCUMENT_LIMIT', 'Style closure exceeds 200 entries')
            active.add(name)
            binding = styles.get(name)
            if not binding:
                result['components'].append({'key': name, 'role': role, 'tags': [], 'requires': [],
                                             'definition': None, 'body': None, 'references': [], 'status': 'missing'})
            else:
                try:
                    item, meta, body, refs = read_bundle(binding)
                    requires = string_list(meta.get('requires', []), 'requires')
                    if asset['dialect'] == 'legacy-bundle/1' and role != 'global':
                        for dependency in requires:
                            visit(dependency, 'inherited')
                    declared = '\n'.join(line for line in body.splitlines() if re.search(r'\bTags?\s*:', line, re.I))
                    tags = list(dict.fromkeys(TAG.findall(declared)))[:200]
                    result['components'].append({'key': name, 'role': role, 'tags': tags, 'requires': requires,
                                                 'definition': item['id'], 'body': fragment(item['path'] + '#body', name, body),
                                                 'references': refs, 'status': 'current'})
                except DocumentWorkspaceError as error:
                    if error.code == 'DOCUMENT_LIMIT':
                        raise
                    result['issues'].append(str(error))
            active.remove(name)
            visited.add(name)

        try:
            item, meta, body, refs = read_bundle(asset)
            result.update({'definition': item['id'], 'image_prompt': fragment(item['path'] + '#body', 'Image-specific prompt', body),
                           'image_tags': list(dict.fromkeys(TAG.findall(body)))[:200], 'references': refs})
            if meta.get('custom_constraints'):
                result['constraints'] = fragment(item['path'] + '#constraints', 'Image-specific constraints', str(meta['custom_constraints']))
            names = string_list(meta.get('styles', []), 'styles')
            if asset['dialect'] == 'legacy-bundle/1':
                if 'constraints/layout' in styles:
                    visit('constraints/layout', 'global')
                if any('diagram' in name for name in names):
                    for palette in ['global/palette-2025', 'global/palette']:
                        if palette in styles:
                            visit(palette, 'global')
                            break
            for name in names:
                visit(name, 'direct')
            declared = {tag for component in result['components'] for tag in component['tags']}
            result['unresolved_tags'] = [tag for tag in result['image_tags'] if tag not in declared]
            assembled = assemble_asset(view, asset, styles)
            # Shared definition files can have different labels/bindings in
            # separate assets; their assembled prompts have distinct identities.
            result['current_assembled'] = fragment(item['path'] + '#assembled-' + sha(cache_key.encode()),
                                                   'Assembled prompt from current inputs', assembled['prompt'])
            result['current_settings'] = assembled['settings']
        except DocumentWorkspaceError as error:
            if error.code == 'DOCUMENT_LIMIT':
                raise
            result['issues'].append(str(error))
        return result

    legacy_styles = {}
    for item in list(view.items):
        prefix = f'projects/{view.project.slug}/outputs/presentation/styles/'
        if item['kind'] == 'generation_style' and item.get('path', '').startswith(prefix):
            key = item['path'][len(prefix):-len('/definition.md')]
            legacy_styles[key] = legacy_binding(item['path'])

    origins = {}

    def origin(image, asset, styles, candidate=None):
        current = context(asset, styles)
        result = {**current, 'label': asset.get('label') or Path(asset.get('definition') or 'Image').parent.name,
                  'saved_prompts': [], 'receipt': None, 'provider': None, 'saved_settings': None,
                  'current_definition': 'unknown', 'recorded_references': [], 'issues': list(current['issues'])}
        receipt = file(candidate['receipt'], 'receipt') if candidate and candidate.get('receipt') else None
        if receipt and receipt['status'] == 'current':
            result['receipt'] = receipt['id']
            try:
                record = json.loads(view.contents[receipt['id']])
                if (record.get('schema') != 'doxagon.document-generation-receipt/1'
                        or record['result']['sha256'] != image.get('sha256')
                        or image.get('sha256') != candidate.get('sha256')):
                    raise ValueError()
                prompt = file(record['prompt']['path'], 'prompt')
                status = 'verified' if prompt.get('sha256') == record['prompt']['sha256'] else 'changed_or_missing'
                provider = record.get('provider', {})
                if not isinstance(provider, dict) or not isinstance(record.get('settings'), dict):
                    raise ValueError()
                dependencies = record['dependencies']
                if not isinstance(dependencies, dict) or len(dependencies) > 200:
                    raise ValueError()
                unchanged = all(file(path, 'generation_input').get('sha256') == digest for path, digest in dependencies.items())
                refs = record.get('references', [])
                if not isinstance(refs, list) or len(refs) > 200:
                    raise ValueError()
                recorded_references = []
                for ref in refs:
                    item = file(ref['path'], 'reference')
                    recorded_references.append({'item': item['id'], 'sha256': ref['sha256'],
                                                'status': 'matches_receipt' if item.get('sha256') == ref['sha256'] else 'changed_or_missing'})
                result.update({'saved_prompts': [{'item': prompt['id'], 'status': status}],
                               'provider': {key: str(provider[key])[:1000] for key in ('provider', 'model') if key in provider},
                               'saved_settings': record['settings'],
                               'current_definition': 'matches_receipt' if unchanged else 'changed',
                               'recorded_references': recorded_references})
            except (ValueError, KeyError, TypeError, AttributeError, DocumentWorkspaceError) as error:
                if isinstance(error, DocumentWorkspaceError) and error.code == 'DOCUMENT_LIMIT':
                    raise
                result['issues'].append('The generation receipt could not be verified against this image.')
        else:
            # Conventional bundle artifacts are inspectable, but a shared
            # assembled_prompt.md may describe a different generation.
            for path in [str(Path(image['path']).with_suffix('.prompt.md')),
                         str(Path(image['path']).parent / 'assembled_prompt.md')]:
                prompt = file(path, 'prompt', optional=True)
                if prompt:
                    result['saved_prompts'].append({'item': prompt['id'], 'status': 'unverified'})
            config = file(str(Path(image['path']).parent / 'generation_config.json'), 'generation_config', optional=True)
            if config:
                result['saved_config'] = config['id']
        return result

    if authoring['status'] == 'registered':
        for asset in authoring['assets']:
            binding = {**registry['assets'][asset['key']], 'label': asset['label']}
            for variant in asset['variants']:
                image = items.get(variant['image'])
                if image:
                    detail = origin(image, binding, registry['styles'], binding.get('variants', {}).get(variant['id']))
                    detail['label'] = f"{asset['label']} · {variant['id']}"
                    origins.setdefault(image['id'], []).append(detail)
    for image in list(view.items):
        if image['kind'] == 'original' and image.get('definition') and image['id'] not in origins:
            item = items[image['definition']]
            origins[image['id']] = [origin(image, legacy_binding(item['path']), legacy_styles)]
    for item in view.items:
        if item['kind'] in {'image', 'original'}:
            linked = origins.get(item.get('original') if item['kind'] == 'image' else item['id'], [])
            message = ('Current inputs describe the linked source bundle. Historical inputs are verified only when a receipt matches this image.'
                       if linked else 'No unique source bundle is linked to this image; generation inputs are unknown.')
            view.generation_details[item['id']] = {'origins': linked, 'message': message, 'association': item.get('provenance', 'source')}
