"""Document-target jobs over the shared generator seam and durable job store."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess

from PIL import Image
import yaml

from doxagon.presentation_backends import (
    PartialImageGeneration,
    provider_command,
    resolve_image_generator,
    resolve_image_generator_path,
)
from doxagon.presentations.generation import (ASPECT_RATIOS, MAX_REFERENCES, RESOLUTIONS, AssembledPrompt,
                                            GenerationSettings, Style, assemble_prompt)
from doxagon.presentations.errors import WorkspaceError
from doxagon.presentations.jobs import JobStore, fingerprint_of
from doxagon.presentations.store import write_bytes, fsync_directory
from .document_assets import definition, relative, required, roled_sources, string_list
from .document_changes import REGISTRY_PATH, apply_plan, json_bytes, make_plan, registry
from .document_inspection import MAX_FILE, MAX_PIXELS, Inspection, inspect_document, sha
from .project import DocumentProject, DocumentWorkspaceError

GENERATION_SCHEMA = 'doxagon.document-generation/1'
BRIEF_SCHEMA = 'doxagon.image-brief/1'
# Above this many words of prose, early instructions measurably lose weight;
# brief/1 warns so the plan reviewer sees it, and never refuses on length.
BRIEF_WORD_CAP = 600
RENDERED_TEXT_RULE = '''<rendered_text_rule>
CRITICAL: Only render text that appears inside <rendered_text> blocks.
Everything outside these blocks is instruction metadata - do NOT render it as visible text.
Do NOT add text that "seems appropriate" or render words from style descriptions.
</rendered_text_rule>'''


CAPABILITIES_SCHEMA = 'doxagon.provider-capabilities/1'


def _executable_digest(path: Path | None) -> str | None:
    try:
        return sha(path.read_bytes()) if path else None
    except OSError:
        return None


def _platform_capabilities(command: str, path: Path | None, environ) -> dict:
    digest = _executable_digest(path)
    return {'configured': bool(path and digest and os.access(path, os.X_OK)),
            'provider': f'subprocess:{path.name}' if path else (f'subprocess:{Path(command).name}' if command else None),
            'resolved_path': str(path) if path else None,
            'model': environ.get('DOXAGON_IMAGE_MODEL') or 'provider-configured (not reported)',
            'executable_sha256': digest,
            'resolutions': list(RESOLUTIONS.values()), 'aspect_ratios': sorted(ASPECT_RATIOS),
            'max_references': MAX_REFERENCES, 'text_rendering': True,
            'max_variants': 8, 'dialects': ['legacy-bundle/1', 'stored-style/1', 'brief/1'], 'paid_effect': True,
            'capabilities_source': 'platform-default'}


def validate_provider_capabilities(value: object) -> dict:
    if not isinstance(value, dict) or value.get('schema') != CAPABILITIES_SCHEMA:
        raise ValueError(f'schema must be {CAPABILITIES_SCHEMA}')
    maximum = value.get('max_references')
    resolutions = value.get('resolutions')
    ratios = value.get('aspect_ratios')
    if not isinstance(maximum, int) or isinstance(maximum, bool) or not 0 <= maximum <= MAX_REFERENCES:
        raise ValueError(f'max_references must be an integer from 0 to {MAX_REFERENCES}')
    if not isinstance(resolutions, list) or not resolutions or any(item not in RESOLUTIONS.values() for item in resolutions):
        raise ValueError('resolutions must be a nonempty subset of platform resolutions')
    if not isinstance(ratios, list) or not ratios or any(item not in ASPECT_RATIOS for item in ratios):
        raise ValueError('aspect_ratios must be a nonempty subset of platform aspect ratios')
    if not isinstance(value.get('model'), str) or not isinstance(value.get('text_rendering'), bool):
        raise ValueError('model must be a string and text_rendering must be a boolean')
    return {'schema': CAPABILITIES_SCHEMA, 'max_references': maximum, 'resolutions': resolutions,
            'aspect_ratios': ratios, 'model': value['model'], 'text_rendering': value['text_rendering']}


_CAPABILITIES_CACHE: dict[tuple[str, str, str], dict] = {}


def provider_capabilities(environ=None) -> dict:
    """Negotiate once per process; malformed adapters retain platform defaults."""
    env = os.environ if environ is None else environ
    command = provider_command(env)
    path = resolve_image_generator_path(command)
    executable_digest = _executable_digest(path) or ''
    cache_key = (str(path) if path else command, executable_digest, env.get('DOXAGON_IMAGE_MODEL', ''))
    if cache_key in _CAPABILITIES_CACHE:
        return deepcopy(_CAPABILITIES_CACHE[cache_key])
    result = _platform_capabilities(command, path, env)
    if path:
        try:
            completed = subprocess.run([str(path), '--capabilities'], capture_output=True, text=True, timeout=10, check=False)
            if not completed.returncode:
                adapter = validate_provider_capabilities(json.loads(completed.stdout))
                result.update({key: adapter[key] for key in ('max_references', 'resolutions', 'aspect_ratios')})
                result.update({'model': adapter['model'], 'text_rendering': adapter['text_rendering'], 'capabilities_source': 'adapter'})
        except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError):
            pass
    _CAPABILITIES_CACHE[cache_key] = deepcopy(result)
    return result


def yaml_scalar(value: str, *, quote: bool = False) -> str:
    """Plain YAML only when the text reads back as itself; JSON quoting otherwise."""
    try:
        plain = (not quote and value and value == value.strip() and value[0] not in '-?:,[]{}#&*!|>\'"%@`'
                 and not any(mark in value for mark in ('\n', '\r', '\t', ': ', ' #', ',', '[', ']', '{', '}'))
                 and yaml.safe_load(value) == value)
    except yaml.YAMLError:
        plain = False
    return value if plain else json.dumps(value, ensure_ascii=False)


def brief_header(intent: str, settings: GenerationSettings, references: list[dict]) -> str:
    """The tabular half of a brief/1 prompt, in the shape documented for review.

    Roles are free prose and aspect ratios look sexagesimal to YAML 1.1, so both
    are always quoted; identifiers stay plain while they read back unchanged.

    No emitted line begins with a space. A block sequence would be equivalent
    YAML, but some providers accept a prompt through a text composer that
    rewrites a line-leading space to U+00A0; the prompt is hashed and sent
    verbatim, so an adapter cannot repair that and correctly refuses to send.
    One flow mapping per line keeps a reference reviewable on its own line
    without ever starting one with whitespace.
    """
    lines = ['---', f'schema: {BRIEF_SCHEMA}', f'intent: {yaml_scalar(intent)}',
             f'settings: {{resolution: {yaml_scalar(settings.api_resolution)}, aspect_ratio: {yaml_scalar(settings.aspect_ratio, quote=True)}}}',
             *([] if references else ['references: []'])]
    for position, entry in enumerate(references):
        opener = 'references: [' if position == 0 else ''
        closer = ']' if position == len(references) - 1 else ','
        lines.append(f'{opener}{{index: {entry["index"]}, file: {yaml_scalar(entry["file"])}, from: {yaml_scalar(entry["from"])}, role: {yaml_scalar(entry["role"], quote=True)}}}{closer}')
    lines.append('---')
    return '\n'.join(lines)


@dataclass(frozen=True)
class DocumentVariant:
    asset_key: str
    variant_index: int
    label: str
    alt: str
    prompt: AssembledPrompt
    settings: GenerationSettings


@dataclass(frozen=True)
class DocumentSpec:
    label: str
    description: str
    styles: tuple[str, ...]
    references: tuple[str, ...]
    settings: GenerationSettings


def assemble_asset(view: Inspection, asset: dict, styles_registry: dict, overrides: dict | None = None, *, key: str = 'Image', max_references: int = MAX_REFERENCES, capabilities_source: str = 'platform-default') -> dict:
    """Resolve the same current prompt for inspection and generation, without a provider call."""
    dependencies = {}

    def read(path):
        raw = required(view, relative(view, path))
        dependencies[path] = sha(raw)
        return raw

    metadata, body = definition(read(asset['definition']))
    if not isinstance(metadata.get('config', {}), dict):
        raise DocumentWorkspaceError('DOCUMENT_DEFINITION_INVALID', 'Generation config must be an object')
    try:
        settings = GenerationSettings.resolve(metadata.get('config', {}), overrides)
    except WorkspaceError as error:
        raise DocumentWorkspaceError(error.code, error.message) from error
    names = string_list(metadata.get('styles', []), 'styles')
    active, ordered = set(), []
    style_bodies = {}
    references = []
    style_bindings = {}

    def bundle(name):
        style = styles_registry.get(name)
        if not isinstance(style, dict) or style.get('dialect') != asset['dialect']:
            raise DocumentWorkspaceError('DOCUMENT_STYLE_UNKNOWN', f'Unknown style or incompatible dialect: {name}')
        style_bindings[name] = style
        meta, text = definition(read(style['definition']))
        return style, meta, text

    def refs(bundle, metadata=None, origin=None):
        result = string_list(bundle.get('references', []), 'references')
        declared = string_list((metadata or {}).get('sources', []), 'sources')
        available = {Path(path).name for path in result}
        missing = [name for name in declared if name not in available]
        if missing:
            raise DocumentWorkspaceError('DOCUMENT_INPUT_MISSING', 'Declared references are not registered: ' + ', '.join(missing))
        for path in result:
            read(path)
        return result

    def brief_refs(bundle, metadata, origin):
        if origin != 'asset' and metadata.get('dialect') not in (None, 'brief/1'):
            raise DocumentWorkspaceError('DOCUMENT_STYLE_UNKNOWN', f'Style {origin} declares dialect {metadata["dialect"]}; brief/1 expected')
        result = string_list(bundle.get('references', []), 'references')
        declared = roled_sources(metadata)
        available = {Path(path).name for path in result}
        missing = [name for name, _ in declared if name not in available]
        if missing:
            raise DocumentWorkspaceError('DOCUMENT_INPUT_MISSING', 'Declared references are not registered: ' + ', '.join(missing))
        roles = dict(declared)
        for path in result:
            read(path)
        return [(path, origin, roles.get(Path(path).name)) for path in result]

    def visit(name, collect=refs):
        if name in active:
            raise DocumentWorkspaceError('DOCUMENT_STYLE_CYCLE', f'Style dependency cycle at {name}')
        if name in ordered:
            return
        if len(active) + len(ordered) >= 200:
            raise DocumentWorkspaceError('DOCUMENT_STYLE_LIMIT', 'Style closure exceeds 200 entries')
        active.add(name)
        style, meta, text = bundle(name)
        for dependency in string_list(meta.get('requires', []), 'requires'):
            visit(dependency, collect)
        style_bodies[name] = (text, collect(style, meta, name))
        ordered.append(name)
        active.remove(name)

    warnings = []

    if asset['dialect'] == 'legacy-bundle/1':
        sections = [RENDERED_TEXT_RULE]
        if 'constraints/layout' in styles_registry:
            style, meta, text = bundle('constraints/layout')
            sections.append(f'<global_constraints>\n{text}\n</global_constraints>')
            references.extend(refs(style, meta))
        if any('diagram' in name for name in names):
            for palette in ['global/palette-2025', 'global/palette']:
                if palette in styles_registry:
                    _, _, text = bundle(palette)
                    sections.append(f'<color_system>\n{text}\n</color_system>')
                    break
        if metadata.get('custom_constraints'):
            sections.append(f'<image_constraints>\n{metadata["custom_constraints"]}\n</image_constraints>')
        sections.append(f'<visual_description>\n{body}\n</visual_description>')
        for name in names:
            visit(name)
        texts = []
        for name in ordered:
            text, images = style_bodies[name]
            if text:
                texts.append(text)
            references.extend(images)
        if texts:
            sections.append('<style_definitions>\n' + '\n\n'.join(texts) + '\n</style_definitions>')
        references.extend(refs(asset, metadata))
        sections.append(f'<generation_settings>\nresolution: {settings.api_resolution}\naspect_ratio: {settings.aspect_ratio}\n</generation_settings>')
        prompt = AssembledPrompt('\n\n---\n\n'.join(sections).strip(), tuple(references))
    elif asset['dialect'] == 'stored-style/1':
        # Stored styles are the existing flat ordered prompt fragments. Reject
        # undeclared dependency semantics instead of subtly changing assembly.
        styles = {}
        for name in names:
            style, meta, text = bundle(name)
            if meta.get('requires'):
                raise DocumentWorkspaceError('DOCUMENT_STYLE_INVALID', 'Stored-style dialect has no implicit dependency expansion')
            styles[name] = Style(name, text, tuple(refs(style, meta)))
        spec = DocumentSpec(asset.get('label', key), body, tuple(names), tuple(refs(asset, metadata)), settings)
        prompt = assemble_prompt(spec, styles)
        references = list(prompt.references)
    elif asset['dialect'] == 'brief/1':
        # Nothing is injected by name here: constraints and palettes take part
        # only when listed in styles:, and every reference reaches the provider
        # with its declared role at the index of its --source position.
        intent = metadata.get('intent')
        if not isinstance(intent, str) or not intent.strip():
            raise DocumentWorkspaceError('DOCUMENT_DEFINITION_INVALID', 'brief/1 requires an asset-level intent')
        if metadata.get('dialect') not in (None, 'brief/1'):
            raise DocumentWorkspaceError('DOCUMENT_DEFINITION_INVALID', f'Definition declares dialect {metadata["dialect"]}; the asset is registered as brief/1')
        constraints = metadata.get('custom_constraints')
        if constraints is not None and not isinstance(constraints, str):
            raise DocumentWorkspaceError('DOCUMENT_DEFINITION_INVALID', 'custom_constraints must be text')
        for name in names:
            visit(name, brief_refs)
        roled, texts = [], []
        for name in ordered:
            text, images = style_bodies[name]
            if text:
                texts.append((name, text))
            roled.extend(images)
        roled.extend(brief_refs(asset, metadata, 'asset'))
        labeled = [{'index': index, 'file': Path(path).name, 'from': origin, 'role': role or 'unspecified'}
                   for index, (path, origin, role) in enumerate(roled)]
        for entry in labeled:
            if entry['role'] == 'unspecified':
                warnings.append(f'Reference {entry["file"]} from {entry["from"]} has no role; unlabeled references tend to be copied as composition')
        sections = [RENDERED_TEXT_RULE]
        if constraints and constraints.strip():
            sections.append(f'<image_constraints>\n{constraints.strip()}\n</image_constraints>')
        sections.append(f'<visual_description>\n{body}\n</visual_description>')
        if texts:
            sections.append('<style_definitions>\n' + '\n'.join(f'<style name="{name}">\n{text}\n</style>' for name, text in texts) + '\n</style_definitions>')
        prose = '\n\n'.join(sections)
        words = len(prose.split())
        if words > BRIEF_WORD_CAP:
            warnings.append(f'brief/1 prose is {words} words; prompts over {BRIEF_WORD_CAP} words tend to lose early instructions')
        prompt = AssembledPrompt(brief_header(intent.strip(), settings, labeled) + '\n\n' + prose, tuple(path for path, _, _ in roled))
        references = list(prompt.references)
    else:
        raise DocumentWorkspaceError('DOCUMENT_DIALECT_UNKNOWN', 'Unknown generation assembly dialect')
    if len(references) > max_references:
        raise DocumentWorkspaceError('DOCUMENT_REFERENCE_LIMIT', f'Resolved reference closure exceeds {max_references} images (source: {capabilities_source}); no references were dropped')
    return {'style_bindings': style_bindings, 'dependencies': dependencies,
            'prompt': prompt.text, 'prompt_sha256': prompt.sha256,
            'references': [{'path': path, 'sha256': dependencies[path]} for path in references],
            'settings': settings.as_dict(), 'warnings': warnings}


def generation_plan(view: Inspection, key: str, overrides: dict | None = None, *, provider: dict | None = None) -> dict:
    record = registry(view)
    asset = record['assets'].get(key)
    if not asset:
        raise DocumentWorkspaceError('DOCUMENT_ASSET_UNKNOWN', f'Unknown asset {key}')
    negotiated = provider or provider_capabilities()
    assembled = assemble_asset(view, asset, record['styles'], overrides, key=key,
                               max_references=negotiated.get('max_references', MAX_REFERENCES),
                               capabilities_source=negotiated.get('capabilities_source', 'platform-default'))
    for reference in assembled['references']:
        raster(required(view, relative(view, reference['path'])))
    binding = {name: asset.get(name) for name in ('definition', 'dialect', 'references', 'label')}
    plan = {'schema': GENERATION_SCHEMA, 'project': view.project.slug, 'snapshot': view.summary['snapshot'], 'asset': key,
            'asset_binding': binding, **assembled, 'provider': negotiated,
            'html_sha256': view.summary['document']['sha256'], 'selection': 'candidate-only'}
    plan['id'] = sha(json_bytes(plan))
    return plan


def raster(raw: bytes) -> str:
    if len(raw) > MAX_FILE:
        raise DocumentWorkspaceError('DOCUMENT_IMAGE_LIMIT', 'Generated image exceeds 32 MiB')
    try:
        with Image.open(BytesIO(raw)) as image:
            if image.width * image.height > MAX_PIXELS or image.format not in {'PNG', 'JPEG', 'WEBP'} or getattr(image, 'n_frames', 1) != 1:
                raise ValueError()
            image.load()
            return Image.MIME[image.format]
    except (ValueError, OSError, Image.DecompressionBombError):
        raise DocumentWorkspaceError('DOCUMENT_GENERATION_IMAGE_INVALID', 'Generator inputs and results must be bounded single-frame rasters') from None


def resolved_input(view: Inspection, plan: dict) -> tuple[GenerationSettings, AssembledPrompt, list[bytes]]:
    if plan.get('schema') != GENERATION_SCHEMA or plan.get('project') != view.project.slug or plan.get('id') != sha(json_bytes({k: v for k, v in plan.items() if k != 'id'})):
        raise DocumentWorkspaceError('DOCUMENT_GENERATION_PLAN_INVALID', 'Invalid project generation plan')
    record = registry(view)
    asset = record['assets'].get(plan['asset'], {})
    if plan['asset_binding'] != {name: asset.get(name) for name in ('definition', 'dialect', 'references', 'label')} or any(record['styles'].get(name) != value for name, value in plan['style_bindings'].items()):
        raise DocumentWorkspaceError('DOCUMENT_SNAPSHOT_CONFLICT', 'Registered generation bindings changed', status=409)
    for path, digest in plan['dependencies'].items():
        if sha(required(view, relative(view, path))) != digest:
            raise DocumentWorkspaceError('DOCUMENT_SNAPSHOT_CONFLICT', f'Reread changed generation input: {path}', status=409)
    prompt = AssembledPrompt(plan['prompt'], tuple(entry['path'] for entry in plan['references']))
    if prompt.sha256 != plan['prompt_sha256'] or len(prompt.references) > plan.get('provider', {}).get('max_references', MAX_REFERENCES):
        raise DocumentWorkspaceError('DOCUMENT_GENERATION_PLAN_INVALID', 'Prompt or reference closure disagrees')
    references = []
    for entry in plan['references']:
        raw = required(view, relative(view, entry['path']))
        if sha(raw) != entry['sha256']:
            raise DocumentWorkspaceError('DOCUMENT_SNAPSHOT_CONFLICT', f'Reread reference {entry["path"]}', status=409)
        raster(raw)
        references.append(raw)
    return GenerationSettings.resolve(plan['settings']), prompt, references


def job_store(project: DocumentProject) -> JobStore:
    return JobStore(project.path('.doxagon/document-generation'))


def generate(project: DocumentProject, plan: dict, idempotency_key: str, *, retry_of: str | None = None, generator=None, provider=None) -> dict:
    """Explicit bounded external effect. Holding this project job lock never
    holds the vault writer fence; candidate promotion takes it only afterward.
    """
    store = job_store(project)
    lock = project.path('.doxagon/document-generation/execution.lock')
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open('a+b') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise DocumentWorkspaceError('DOCUMENT_GENERATION_BUSY', 'Another document generation is running for this project', status=409) from None
        existing = store.get(retry_of) if retry_of else store.lookup(idempotency_key)
        if existing and existing.fingerprint != fingerprint_of('generation', plan, plan['snapshot']) and not retry_of:
            raise DocumentWorkspaceError('DOCUMENT_JOB_KEY_CONFLICT', 'This key names a different generation plan', status=409)
        if existing and not retry_of:
            if existing.status == 'running':
                raise DocumentWorkspaceError('DOCUMENT_JOB_INTERRUPTED', f'Job {existing.job_id} was interrupted; explicitly recover it before retrying', status=409)
            if existing.status != 'pending':
                return existing.as_dict()
        if retry_of and existing.request != plan:
            raise DocumentWorkspaceError('DOCUMENT_JOB_KEY_CONFLICT', 'A retry must retain the exact original plan', status=409)
        view = inspect_document(project)
        settings, prompt, references = resolved_input(view, plan)
        current_provider = provider or provider_capabilities()
        if current_provider != plan['provider'] or not current_provider['configured']:
            raise DocumentWorkspaceError('DOCUMENT_GENERATOR_UNAVAILABLE', 'The planned provider is unavailable or its executable/model changed')
        if not retry_of and not existing and view.summary['snapshot'] != plan['snapshot']:
            raise DocumentWorkspaceError('DOCUMENT_SNAPSHOT_CONFLICT', 'Reread context before starting this generation', status=409)
        generator = generator or resolve_image_generator(provider_command())
        job = store.retry(retry_of, plan['snapshot']) if retry_of else store.submit('generation', idempotency_key, plan, plan['snapshot'])
        if job.status != 'pending':
            return job.as_dict()
        job = store.start(job.job_id)
        outputs = list(existing.outputs) if retry_of else []
        completed = {entry['variant_index'] for entry in outputs}
        failures = [failure for failure in existing.failures if failure.get('retained_candidate')] if retry_of else []
        for index in range(settings.variants):
            if index in completed:
                continue
            moment = datetime.now(timezone.utc).isoformat()
            try:
                provider_errors = []
                variant = DocumentVariant(plan['asset'], index, plan['asset_binding'].get('label', plan['asset']), '', prompt, settings)
                spool = project.path(f'.doxagon/document-generation/pending/{job.lineage_id}/{index}')
                saved = spool / 'receipt.json'
                if saved.exists():
                    receipt = json.loads(saved.read_bytes())
                    data = (spool / 'candidate').read_bytes()
                    provider_errors = receipt.get('errors', [])
                    if receipt['result']['sha256'] != sha(data) or receipt['prompt']['sha256'] != prompt.sha256 or receipt['provider'] != current_provider:
                        raise DocumentWorkspaceError('DOCUMENT_CANDIDATE_DRIFT', 'Pending candidate or receipt changed')
                else:
                    # An unreceipted file may have been returned immediately
                    # before a crash. Require operator inspection instead of
                    # charging again or inventing its lineage.
                    if (spool / 'candidate').exists():
                        raise DocumentWorkspaceError('DOCUMENT_CANDIDATE_UNRESOLVED', 'Unreceipted candidate requires explicit inspection')
                    try:
                        data = generator(variant, references).data
                    except PartialImageGeneration as error:
                        data = error.image.data
                        provider_errors = [{'code': error.code, 'message': error.message}]
                media = raster(data)
                variant_id = 'generated-' + sha(f'{job.lineage_id}:{index}:{sha(data)}'.encode())[:24]
                suffix = {'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp'}[media]
                base = f'assets/visuals/{plan["asset"]}/variants/{variant_id}'
                prefix = f'projects/{project.slug}/'
                proposed_receipt = {'schema': 'doxagon.document-generation-receipt/1', 'lineage': job.lineage_id, 'job': job.job_id, 'variant_index': index,
                           'provider': current_provider, 'settings': settings.as_dict(), 'created_at': moment,
                           'prompt': {'path': prefix + base + '.prompt.md', 'sha256': prompt.sha256},
                           'references': plan['references'], 'dependencies': plan['dependencies'],
                           'result': {'sha256': sha(data), 'media_type': media}, 'errors': provider_errors}
                # Durable pending admission survives a concurrent authoring
                # conflict or process exit. A retry never repeats a paid call
                # merely to reconstruct bytes already returned.
                if not saved.exists():
                    receipt = proposed_receipt
                    spool.mkdir(parents=True, exist_ok=True)
                    write_bytes(spool / 'candidate', data)
                    write_bytes(spool / 'prompt.md', prompt.text.encode())
                    write_bytes(saved, json_bytes(receipt))
                    fsync_directory(spool)
                    fsync_directory(spool.parent)
                current = inspect_document(project)
                record = registry(current)
                candidate = {'path': prefix + base + '.' + suffix, 'sha256': sha(data),
                             'receipt': prefix + base + '.provenance.json', 'provenance': 'partial_generation' if provider_errors else 'generated'}
                record['assets'][plan['asset']]['variants'][variant_id] = candidate
                changes = {base + '.' + suffix: data, base + '.prompt.md': prompt.text.encode(),
                           base + '.provenance.json': json_bytes(receipt), REGISTRY_PATH: json_bytes(record)}
                apply_plan(project, make_plan(current, changes, operation='admit-candidate', details={'asset': plan['asset'], 'variant': variant_id}))
                outputs.append({'asset_id': variant_id, 'variant_index': index, **candidate})
                if provider_errors:
                    failures.append({'variant_index': index, 'time': moment, 'code': 'PRES_GENERATION_PARTIAL',
                                     'message': 'Provider failed; retained candidate is available for explicit inspection and selection',
                                     'retained_candidate': variant_id, 'prompt_sha256': prompt.sha256, 'provider': current_provider,
                                     'settings': settings.as_dict(), 'references': plan['references']})
                store.progress(job.job_id, outputs=outputs, failures=failures)
            except Exception as error:
                failure = {'variant_index': index, 'time': moment, 'code': getattr(error, 'code', 'DOCUMENT_GENERATION_FAILED'),
                           'message': 'Generation or candidate admission failed; retained results require inspection before retry',
                           'prompt_sha256': prompt.sha256, 'provider': current_provider, 'settings': settings.as_dict(), 'references': plan['references']}
                failures.append(failure)
                store.progress(job.job_id, outputs=outputs, failures=failures)
        if failures:
            return store.fail(job.job_id, 'DOCUMENT_GENERATION_PARTIAL', 'One or more variants failed', outputs=outputs, failures=failures).as_dict()
        return store.succeed(job.job_id, outputs=outputs).as_dict()


def recover_job(project: DocumentProject, identity: str) -> dict:
    """Mark an abandoned attempt failed; recovery never calls the provider."""
    store = job_store(project)
    job = store.get(identity)
    lock = project.path('.doxagon/document-generation/execution.lock')
    with lock.open('a+b') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise DocumentWorkspaceError('DOCUMENT_GENERATION_BUSY', 'The provider job is still running', status=409) from None
        if job.status == 'running':
            job = store.fail(identity, 'DOCUMENT_JOB_INTERRUPTED', 'Explicit recovery marked this interrupted job failed', outputs=job.outputs, failures=job.failures)
        return job.as_dict()
