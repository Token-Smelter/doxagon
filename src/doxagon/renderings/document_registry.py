"""Read authoring associations while keeping current and historical facts apart."""
from __future__ import annotations

import json

from .document_assets import DIALECTS, relative
from .document_changes import REGISTRY_SCHEMA
from .document_inspection import Inspection
from .project import DocumentWorkspaceError


def inspect_registry(view: Inspection, record: dict, usages: list[dict]) -> dict:
    result = {'status': 'absent', 'assets': [], 'styles': [], 'validation': 'unverified'}
    if not record:
        return result
    if record.get('schema') != REGISTRY_SCHEMA or any(not isinstance(record.get(key), dict) for key in ('assets', 'styles', 'usages')):
        view.check('invalid_authoring', 'Unsupported or invalid private authoring record')
        result['status'] = 'invalid'
        return result
    if sum(len(record[key]) for key in ('assets', 'styles', 'usages')) > 2000:
        raise DocumentWorkspaceError('DOCUMENT_LIMIT', 'Authoring registry exceeds the item budget')
    result['status'] = 'registered'
    images = {item['id']: item for item in view.items if item['kind'] == 'image'}
    actual = {usage['id']: usage for usage in usages}

    def file(path, kind):
        try:
            return view.file(relative(view, path), kind)
        except DocumentWorkspaceError as error:
            if error.code == 'DOCUMENT_PATH_ESCAPE':
                view.check('unavailable_input', 'A registered input is outside this project')
                return None
            raise

    for category, kind in [('styles', 'generation_style'), ('assets', 'definition')]:
        for key, asset in record[category].items():
            if not isinstance(asset, dict) or asset.get('dialect') not in DIALECTS:
                view.check('invalid_authoring', f'Invalid registered {category} entry {key[:100]}')
                continue
            definition = file(asset.get('definition'), kind)
            entry = {'key': key, 'label': str(asset.get('label', key))[:1000], 'dialect': asset['dialect'],
                     'definition': definition['id'] if definition else None, 'references': [], 'variants': [], 'usages': []}
            references = asset.get('references', [])
            if not isinstance(references, list) or len(references) > 200:
                view.check('invalid_authoring', f'Invalid reference list for {key}')
                continue
            for reference in references:
                item = file(reference, 'reference')
                if item:
                    entry['references'].append(item['id'])
            if definition:
                definition['references'] = list(dict.fromkeys(entry['references'] + definition.get('references', [])))
                definition['dialect'] = asset['dialect']
            variants = asset.get('variants', {})
            if not isinstance(variants, dict) or len(variants) > 1000:
                view.check('invalid_authoring', f'Invalid variant list for {key}')
                continue
            for variant, candidate in variants.items():
                if not isinstance(candidate, dict):
                    view.check('invalid_authoring', f'Invalid candidate for {key}')
                    continue
                item = file(candidate.get('path'), 'original')
                status = 'source_missing' if not item or item['status'] != 'current' else 'current' if item['sha256'] == candidate.get('sha256') else 'source_changed'
                summary = {'id': variant, 'image': item['id'] if item else None, 'status': status,
                           'provenance': candidate.get('provenance', 'historical_unknown'), 'generated_with': None, 'current_definition': 'unknown'}
                receipt_item = file(candidate['receipt'], 'receipt') if candidate.get('receipt') else None
                if receipt_item and receipt_item['status'] == 'current':
                    try:
                        receipt = json.loads(view.contents[receipt_item['id']])
                        dependencies = receipt['dependencies']
                        if not isinstance(dependencies, dict) or len(dependencies) > 200:
                            raise ValueError()
                        changed = []
                        for path, digest in dependencies.items():
                            dependency = file(path, 'generation_input')
                            if not dependency or dependency.get('sha256') != digest:
                                changed.append(path)
                        prompt = file(receipt['prompt']['path'], 'prompt')
                        if not prompt or prompt.get('sha256') != receipt['prompt']['sha256']:
                            view.check('receipt_drift', f'Exact prompt unavailable or changed for {variant}')
                        summary.update({'receipt': receipt_item['id'], 'generated_with': receipt.get('provider'),
                                        'current_definition': 'changed' if changed else 'matches_receipt', 'changed_inputs': changed})
                    except (ValueError, KeyError, TypeError, AttributeError):
                        view.check('invalid_receipt', f'Invalid generation receipt for {variant}')
                entry['variants'].append(summary)
            result[category].append(entry)
    for slot, association in record['usages'].items():
        if not isinstance(association, dict):
            view.check('invalid_authoring', f'Invalid usage association {slot[:100]}')
            continue
        usage = actual.get(slot)
        image = images.get(usage['image']) if usage else None
        asset = record['assets'].get(association.get('asset'), {})
        if not usage or not usage['stable'] or not image or image['sha256'] != association.get('embedded_sha256'):
            view.check('usage_drift', f'Registered slot {slot[:100]} is missing or its payload changed')
            continue
        usage['asset'] = association.get('asset')
        for entry in result['assets']:
            if entry['key'] == usage['asset']:
                entry['usages'].append(slot)
        variant = asset.get('variants', {}).get(association.get('variant'))
        encoding = asset.get('encodings', {}).get(association.get('encoding'))
        if variant and encoding and encoding.get('original_sha256') == variant.get('sha256') and encoding.get('embedded_sha256') == image['sha256']:
            original = file(variant['path'], 'original')
            if original:
                original.setdefault('usages', []).append(slot)
            image.update({'provenance': 'encoded_variant', 'original': original['id'] if original else None,
                          'asset': usage['asset'], 'encoding': encoding})
    proof = record.get('validation')
    if isinstance(proof, dict) and isinstance(proof.get('dependencies'), dict):
        from .document_validation import validation_identity
        current = (isinstance(proof.get('result'), dict)
                   and proof['result'].get('implementation') == validation_identity()
                   and all(view.inputs.get(path, {}).get('sha256') == digest for path, digest in proof['dependencies'].items()))
        result['validation'] = 'current' if current else 'stale'
    return result
