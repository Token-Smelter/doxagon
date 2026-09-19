"""Read-only migration-hazard checks over a project's style bundles.

The only write is `--fix-requires`, which mirrors inert `**Requires:**` body
markers into the frontmatter `requires:` that v2 assembly actually reads.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import difflib
from pathlib import Path
import re

from doxagon.presentations.generation import MAX_REFERENCES
from .document_assets import RASTERS, definition
from .document_changes import REGISTRY_PATH, parse_registry
from .project import DocumentProject, DocumentWorkspaceError

LINT_SCHEMA = 'doxagon.styles-lint/1'
ROOTS = ('outputs/presentation/styles', 'assets/styles')
REQUIRES_MARKER = re.compile(r'^\*\*Requires:\*\*(.*)$', re.M)
TAG_MARKER = re.compile(r'^\*\*Tag:\*\*(.*)$', re.M)
TAG_NAME = re.compile(r'\[([A-Za-z0-9_-]+)\]')


@dataclass
class Bundle:
    root: str
    name: str
    path: Path
    raw: str
    metadata: dict = field(default_factory=dict)
    body: str = ''
    invalid: str | None = None
    requires: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    on_disk: list[str] = field(default_factory=list)
    rasters: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    required_tags: list[str] = field(default_factory=list)

    @property
    def locator(self) -> str:
        return f'{self.root}/{self.name}'


def _source_names(metadata: dict) -> list[str]:
    items = metadata.get('sources', [])
    if not isinstance(items, list):
        raise ValueError('sources must be a list')
    names = []
    for item in items:
        if isinstance(item, str) and item:
            names.append(item)
        elif isinstance(item, dict) and isinstance(item.get('file'), str) and item['file']:
            names.append(item['file'])
        else:
            raise ValueError('sources items are file names or {file, role} objects')
    return names


def read_bundle(project: DocumentProject, root: str, path: Path) -> Bundle:
    name = path.parent.relative_to(project.path(root)).as_posix()
    raw = path.read_bytes()
    bundle = Bundle(root, name, path, raw.decode('utf-8', 'replace'))
    try:
        bundle.metadata, bundle.body = definition(raw)
        requires = bundle.metadata.get('requires', [])
        if not isinstance(requires, list) or not all(isinstance(item, str) and item for item in requires):
            raise ValueError('requires must be a list of bundle names')
        bundle.requires = requires
        bundle.sources = _source_names(bundle.metadata)
    except ValueError as error:  # DocumentWorkspaceError is a ValueError
        bundle.invalid = str(error)
        return bundle
    sources = path.parent / 'sources'
    if sources.is_dir():
        bundle.on_disk = sorted(child.name for child in sources.iterdir() if child.is_file())
        bundle.rasters = [child for child in bundle.on_disk if Path(child).suffix.lower() in RASTERS]
    bundle.tags = [tag for line in TAG_MARKER.findall(bundle.body) for tag in TAG_NAME.findall(line)]
    bundle.required_tags = [tag for line in REQUIRES_MARKER.findall(bundle.body) for tag in TAG_NAME.findall(line)]
    return bundle


def discover(project: DocumentProject) -> list[Bundle]:
    bundles = []
    for root in ROOTS:
        base = project.path(root)
        if not base.is_dir():
            continue
        for path in sorted(base.rglob('definition.md')):
            if 'sources' not in path.relative_to(base).parts:
                bundles.append(read_bundle(project, root, path))
    return bundles


def tag_owners(bundles: list[Bundle]) -> dict[tuple[str, str], str | None]:
    """A bundle owns the tag its first marker declares; a concatenated
    reference that re-declares many tags yields to the single-tag bundle."""
    claims: dict[tuple[str, str], list[Bundle]] = {}
    for bundle in bundles:
        if bundle.tags:
            claims.setdefault((bundle.root, bundle.tags[0]), []).append(bundle)
    owners = {}
    for key, candidates in claims.items():
        single = [bundle for bundle in candidates if len(set(bundle.tags)) == 1]
        chosen = single or candidates
        owners[key] = chosen[0].name if len(chosen) == 1 else None
    return owners


def requires_block(names: list[str]) -> str:
    return 'requires: []\n' if not names else 'requires:\n' + ''.join(f'  - {name}\n' for name in names)


def with_requires(raw: str, names: list[str]) -> str:
    """Insert requires: into existing frontmatter or open a new block; the body
    bytes are never touched."""
    lead = len(raw) - len(raw.lstrip())
    opening = re.match(r'---[ \t]*\n', raw[lead:])
    if opening and re.match(r'^---\s*\n(.*?)\n---\s*\n?', raw[lead:], re.S):
        cut = lead + opening.end()
        return raw[:cut] + requires_block(names) + raw[cut:]
    return '---\n' + requires_block(names) + '---\n\n' + raw


def fix_requires(project: DocumentProject, bundles: list[Bundle]) -> tuple[list[dict], list[dict]]:
    owners = tag_owners(bundles)
    fixed, findings = [], []
    for bundle in bundles:
        if bundle.invalid or 'requires' in bundle.metadata or not REQUIRES_MARKER.search(bundle.body):
            continue
        internal = set(bundle.tags)
        needed, unresolved = [], []
        for tag in bundle.required_tags:
            if tag in internal:
                continue
            owner = owners.get((bundle.root, tag))
            if owner is None:
                unresolved.append(tag)
            elif owner not in needed:
                needed.append(owner)
        if not bundle.required_tags:
            unresolved.append('(no [TAG] on the marker line)')
        if unresolved:
            findings.append(_finding(bundle, 'error', 'requires-unresolved',
                                     'cannot map body **Requires:** to a bundle: ' + ', '.join(unresolved)))
            continue
        updated = with_requires(bundle.raw, needed)
        relative = bundle.path.relative_to(project.root).as_posix()
        diff = ''.join(difflib.unified_diff(bundle.raw.splitlines(keepends=True), updated.splitlines(keepends=True),
                                            fromfile='a/' + relative, tofile='b/' + relative))
        bundle.path.write_bytes(updated.encode('utf-8'))
        fixed.append({'bundle': bundle.locator, 'requires': needed, 'diff': diff})
    return fixed, findings


def _finding(bundle: Bundle, severity: str, rule: str, message: str) -> dict:
    return {'bundle': bundle.locator, 'severity': severity, 'rule': rule, 'message': message}


def _registered(project: DocumentProject) -> tuple[dict | None, dict | None]:
    path = project.path(REGISTRY_PATH)
    if not path.is_file():
        return None, None
    try:
        return parse_registry(path.read_bytes()), None
    except DocumentWorkspaceError as error:
        return {'styles': {}}, {'bundle': REGISTRY_PATH, 'severity': 'error', 'rule': 'registry-invalid', 'message': str(error)}


def _closure(bundle: Bundle, by_name: dict[str, Bundle]) -> tuple[list[str], list[str] | None]:
    """Post-order requires closure and, when one exists, the first cycle."""
    ordered: list[str] = []
    active: list[str] = []
    cycle: list[str] | None = None

    def visit(name: str) -> None:
        nonlocal cycle
        if cycle or name in ordered:
            return
        if name in active:
            cycle = active[active.index(name):] + [name]
            return
        active.append(name)
        for dependency in by_name[name].requires if name in by_name else []:
            visit(dependency)
        active.pop()
        ordered.append(name)

    visit(bundle.name)
    return ordered, cycle


def check(project: DocumentProject, bundles: list[Bundle], *, max_references: int, capabilities_source: str) -> list[dict]:
    record, registry_error = _registered(project)
    findings = [registry_error] if registry_error else []
    for root in ROOTS:
        by_name = {bundle.name: bundle for bundle in bundles if bundle.root == root}
        for bundle in by_name.values():
            if bundle.invalid:
                findings.append(_finding(bundle, 'error', 'definition-invalid', bundle.invalid))
                continue
            if REQUIRES_MARKER.search(bundle.body):
                if 'requires' not in bundle.metadata:
                    findings.append(_finding(bundle, 'error', 'requires-body-tag',
                                             'body **Requires:** marker has no frontmatter requires:; v2 reads only frontmatter (run --fix-requires)'))
                else:
                    findings.append(_finding(bundle, 'info', 'body-marker', 'stale **Requires:** marker; frontmatter requires: is authoritative'))
            for name in bundle.requires:
                if name not in by_name:
                    findings.append(_finding(bundle, 'error', 'requires-unknown', f'requires: names a bundle that does not exist: {name}'))
            for name in bundle.sources:
                if name not in bundle.on_disk:
                    findings.append(_finding(bundle, 'error', 'sources-missing', f'sources: names a file absent from sources/: {name}'))
                elif record is not None and root == 'assets/styles':
                    locator = f'projects/{project.slug}/{root}/{bundle.name}/sources/{name}'
                    if locator not in record['styles'].get(bundle.name, {}).get('references', []):
                        findings.append(_finding(bundle, 'error', 'sources-unregistered', f'sources: file is on disk but not registered in {REGISTRY_PATH}: {name}'))
            ordered, cycle = _closure(bundle, by_name)
            if cycle:
                findings.append(_finding(bundle, 'error', 'dependency-cycle', 'requires cycle: ' + ' -> '.join(cycle)))
            count = sum(len(by_name[name].rasters) for name in ordered if name in by_name)
            if count > max_references:
                findings.append(_finding(bundle, 'error', 'closure-too-large',
                                         f'reference closure carries {count} images; the negotiated maximum is {max_references} (source: {capabilities_source})'))
            for tag in bundle.tags:
                findings.append(_finding(bundle, 'info', 'body-marker', f'stale **Tag:** marker [{tag}]; brief/1 ignores it'))
            if record is not None and 'dialect' not in bundle.metadata:
                findings.append(_finding(bundle, 'warning', 'dialect-missing', f'no dialect: in frontmatter while {REGISTRY_PATH} exists'))
    return findings


def lint_styles(project: DocumentProject, *, fix: bool = False, provider: dict | None = None) -> dict:
    if provider is None:
        from .document_generation import provider_capabilities
        provider = provider_capabilities()
    max_references = provider.get('max_references', MAX_REFERENCES)
    source = provider.get('capabilities_source', 'platform-default')
    bundles = discover(project)
    fixed, unresolved = ([], [])
    if fix:
        fixed, unresolved = fix_requires(project, bundles)
        if fixed:
            bundles = discover(project)
    findings = unresolved + check(project, bundles, max_references=max_references, capabilities_source=source)
    counts = {severity: sum(1 for item in findings if item['severity'] == severity) for severity in ('error', 'warning', 'info')}
    return {'schema': LINT_SCHEMA, 'project': project.slug, 'max_references': max_references, 'capabilities_source': source,
            'bundles': [bundle.locator for bundle in bundles], 'fixed': fixed, 'findings': findings, 'counts': counts}
