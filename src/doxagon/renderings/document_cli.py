"""Local client of the workspace inspection producer."""
import json
from pathlib import Path
import click

from doxagon.renderings.document_inspection import inspect_document, read_item
from doxagon.renderings.project import DocumentWorkspaceError, resolve_document_project


@click.group('document')
def document_group():
    """Inspect, plan and author the explicitly selected single-file document.

    Generation-run is a bounded, potentially paid external effect. Generation
    creates candidates; selecting an image requires a separate asset plan.
    """


@document_group.command('context')
@click.option('--project')
@click.option('--json', 'as_json', is_flag=True)
def context(project, as_json):
    """Read bounded project context; image bytes and note bodies are excluded."""
    try:
        from .document_context import context as project_context
        result = project_context(project)
    except DocumentWorkspaceError as error:
        raise click.ClickException(f'{error.code}: {error}') from error
    if as_json:
        click.echo(json.dumps(result, indent=2))
    elif result.get('project') is None:
        click.echo('Projects: ' + ', '.join(result['projects']) + '\n' + result['next'])
    else:
        selected = result.get('document') or {}
        click.echo(f"{result['title']}\nProject: {result['project']}\nModel: {result['model']}\nSelected HTML: {selected.get('path', 'none')}\nSnapshot: {result['snapshot']}")
        click.echo(json.dumps({'environment': result['environment'], 'generation': result['generation'], 'capabilities': result['capabilities'], 'machinery': result['machinery']}, indent=2))
        click.echo(f"{len(result['cues'])} declared cues; {len(result['usages'])} image usages; inspection coverage: {result['coverage']}")
        for check in result['checks']:
            click.echo(f"{check['code']}: {check['message']}")


@document_group.command('inspect')
@click.option('--project')
@click.option('--item', 'identity')
@click.option('--snapshot')
@click.option('--offset', type=click.IntRange(min=0), default=0)
def inspect(project, identity, snapshot, offset):
    """Read the JSON index or a bounded item page from a known snapshot."""
    if identity and not snapshot:
        raise click.UsageError('--item requires --snapshot from document context')
    try:
        from .document_context import inspect_project
        view = inspect_project(resolve_document_project(project), snapshot)
        click.echo(json.dumps(read_item(view, identity, offset) if identity else view.summary, indent=2))
    except DocumentWorkspaceError as error:
        raise click.ClickException(f'{error.code}: {error}') from error


def read_json(path: Path) -> dict:
    try:
        with path.open('rb') as stream:
            raw = stream.read(360 * 1024 * 1024 + 1)
        if len(raw) > 360 * 1024 * 1024:
            raise ValueError('file exceeds the plan size limit')
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError('expected a JSON object')
        return value
    except (ValueError, OSError) as error:
        raise click.ClickException(f'Cannot read {path}: {error}') from error


def write_plan(plan: dict, output: Path) -> None:
    from .document_changes import json_bytes, plan_summary
    try:
        with output.open('xb') as handle:
            handle.write(json_bytes(plan))
    except OSError as error:
        raise click.ClickException(f'Cannot create plan {output}: {error}') from error
    click.echo(json.dumps(plan_summary(plan) if 'changes' in plan else plan, indent=2))


@document_group.command('plan')
@click.option('--project')
@click.option('--snapshot', required=True)
@click.option('--change', type=click.Path(exists=True, path_type=Path), required=True)
@click.option('--output', type=click.Path(path_type=Path), required=True)
def plan(project, snapshot, change, output):
    """Plan exact text/source patches from context item IDs without applying."""
    from .document_changes import plan_text_change
    try:
        view = inspect_document(resolve_document_project(project), snapshot)
        write_plan(plan_text_change(view, read_json(change).get('patches', [])), output)
    except DocumentWorkspaceError as error:
        raise click.ClickException(f'{error.code}: {error}') from error


@document_group.command('apply')
@click.option('--project')
@click.argument('plan_file', type=click.Path(exists=True, path_type=Path))
def apply(project, plan_file):
    """Validate and promote a reviewed plan against its recorded inputs."""
    from .document_changes import apply_plan
    try:
        click.echo(json.dumps(apply_plan(resolve_document_project(project), read_json(plan_file)), indent=2))
    except DocumentWorkspaceError as error:
        raise click.ClickException(f'{error.code}: {error}') from error


@document_group.command('validate')
@click.option('--project')
@click.option('--record', is_flag=True, help='Explicitly record a successful hash-bound validation in private authoring metadata.')
def validate(project, record):
    """Check the selected HTML, bridge, navigation and private notes in a browser."""
    from .document_validation import validate_change
    try:
        view = inspect_document(resolve_document_project(project))
        path = view.project.vault / view.summary['document']['path']
        proof = validate_change(view, {path: view.contents[view.summary['document']['id']]})
        if record:
            from .document_changes import REGISTRY_PATH, apply_plan, json_bytes, make_plan, registry
            authoring = registry(view)
            authoring['validation'] = {'command': 'dox document validate --record', 'result': proof,
                'dependencies': {path: item.get('sha256') for path, item in view.inputs.items() if not path.endswith('/' + REGISTRY_PATH)}}
            result = apply_plan(view.project, make_plan(view, {REGISTRY_PATH: json_bytes(authoring)}, operation='record-validation'))
            proof['record'] = result
        click.echo(json.dumps(proof, indent=2))
    except DocumentWorkspaceError as error:
        raise click.ClickException(f'{error.code}: {error}') from error


@document_group.command('recover')
@click.option('--project')
def recover(project):
    """Explicitly roll a pending authored-file transaction forward."""
    from doxagon.wal import WriteAheadLog, WriterFence, RecoveryUnresolved
    try:
        selected = resolve_document_project(project)
        fence = WriterFence(selected.vault)
        fence.acquire()
        try:
            journal = WriteAheadLog(selected.vault, fence)
            recovered = journal.recover()
        finally:
            fence.release()
        click.echo(json.dumps({'transaction': recovered, 'status': 'recovered' if recovered else 'current'}))
    except (DocumentWorkspaceError, RecoveryUnresolved) as error:
        raise click.ClickException(str(error)) from error


@document_group.command('asset-plan')
@click.option('--project')
@click.option('--snapshot', required=True)
@click.option('--request', type=click.Path(exists=True, path_type=Path), required=True)
@click.option('--output', type=click.Path(path_type=Path), required=True)
def asset_plan(project, snapshot, request, output):
    """Plan create, create-style, adopt, admit-image, bind-slots or select-image.

    Create: {operation:create, key, definition (text), dialect, references:{filename:item-id}}.
    Dialect defaults to the definition's frontmatter dialect, else legacy-bundle/1.
    Create-style uses the same fields with operation:create-style.
    Adopt: {operation:adopt, key, source (project-relative bundle)}.
    Admit: {operation:admit-image, key, source (project-relative file)} or
    {operation:admit-image, key, item (inspection item id)}.
    Bind: {operation:bind-slots, associations:{slot:asset}}.
    Select: {operation:select-image, key, variant, slots:[slot], quality:88}.
    Add slots: {operation:add-slots, container, slots:[{id, alt, key, variant}],
    quality:88} appends new stable <img id> slots inside the existing element
    whose id is container, filled from registered variants with select-image's
    encoding receipts. Add the container itself with an ordinary text patch.
    Inspect the written plan, then use document apply.

    Admit-image registers artwork you already have as a variant of an asset
    that is already registered, for the case where the image exists and no
    generation produced it. Use generation-run when the provider is to make the
    image; use admit-image when the bytes already exist. An admitted variant
    records provenance "admitted", the source path or item id it came from and
    the sha256 of the admitted bytes, and carries no prompt, provider identity
    or receipt, because no provider call happened. It is otherwise an ordinary
    variant: select-image accepts it exactly as it accepts a generated one.

    References are bound by item id from the snapshot: each "references" value
    is an inspection item id of kind image, original or reference, and the plan
    copies that item's bytes into the new bundle's sources/ directory under the
    name you give it. An image becomes a referenceable item only by being
    embedded in the selected HTML; placing a file in a bundle's sources/
    directory does NOT register it, and a definition whose sources: names a
    file this request does not register is refused here as
    DOCUMENT_REFERENCE_UNREGISTERED rather than at generation-plan.

    Bind-slots and select-image name stable slots. A stable slot is an image
    element carrying an id attribute; bind-slots assigns deterministic ids to
    image elements that lack one. data-slot on a figure is a document's own CSS
    convention and produces no stable slot. See docs/document-authoring.md.
    """
    from .document_assets import plan_add_slots, plan_admit_image, plan_create_asset, plan_adopt_bundle, plan_bind_slots, plan_select_image
    try:
        view = inspect_document(resolve_document_project(project), snapshot)
        value = read_json(request)
        operation = value.get('operation')
        if operation in {'create', 'create-style'}:
            result = plan_create_asset(view, value['key'], value['definition'].encode(), value.get('dialect'), value.get('references'), style=operation == 'create-style')
        elif operation == 'adopt':
            result = plan_adopt_bundle(view, value['key'], value['source'])
        elif operation == 'admit-image':
            result = plan_admit_image(view, value['key'], value.get('source'), value.get('item'))
        elif operation == 'bind-slots':
            result = plan_bind_slots(view, value['associations'])
        elif operation == 'select-image':
            result = plan_select_image(view, value['key'], value['variant'], value['slots'], quality=value.get('quality', 88))
        elif operation == 'add-slots':
            result = plan_add_slots(view, value['container'], value['slots'], quality=value.get('quality', 88))
        else:
            raise click.UsageError('Unknown asset operation; see asset-plan --help')
        write_plan(result, output)
    except (KeyError, TypeError, AttributeError) as error:
        raise click.ClickException(f'Invalid asset request: {error}') from error
    except DocumentWorkspaceError as error:
        raise click.ClickException(f'{error.code}: {error}') from error


@document_group.command('generation-plan')
@click.option('--project')
@click.option('--snapshot', required=True)
@click.option('--asset', required=True)
@click.option('--variants', type=click.IntRange(1, 8), default=1, show_default=True)
@click.option('--resolution', type=click.Choice(['1k', '2k', '4k']))
@click.option('--aspect-ratio')
@click.option('--output', type=click.Path(path_type=Path), required=True)
def generation_plan_command(project, snapshot, asset, variants, resolution, aspect_ratio, output):
    """Resolve exact prompt, references and configured provider without calling it."""
    from .document_generation import generation_plan
    try:
        view = inspect_document(resolve_document_project(project), snapshot)
        plan = generation_plan(view, asset, {'variants': variants, 'resolution': resolution, 'aspect_ratio': aspect_ratio})
        write_plan(plan, output)
        for warning in plan['warnings']:
            click.echo(f'warning: {warning}', err=True)
    except DocumentWorkspaceError as error:
        raise click.ClickException(f'{error.code}: {error}') from error


@document_group.command('generation-run')
@click.option('--project')
@click.option('--key', required=True, help='Stable idempotency key for this bounded request.')
@click.option('--retry-of', help='Explicitly retry a failed job, retaining its prompt and lineage.')
@click.argument('plan_file', type=click.Path(exists=True, path_type=Path))
def generation_run(project, key, retry_of, plan_file):
    """Execute a reviewed generation plan; this may incur provider charges."""
    from .document_generation import generate
    from doxagon.presentations.errors import WorkspaceError
    try:
        result = generate(resolve_document_project(project), read_json(plan_file), key, retry_of=retry_of)
        click.echo(json.dumps(result, indent=2))
    except (DocumentWorkspaceError, WorkspaceError) as error:
        raise click.ClickException(f'{error.code}: {error}') from error


@document_group.command('generation-job')
@click.option('--project')
@click.option('--recover', is_flag=True, help='Mark an interrupted attempt failed; never calls the provider.')
@click.argument('identity')
def generation_job(project, recover, identity):
    """Inspect a durable generation job and its partial results."""
    from .document_generation import job_store, recover_job
    from doxagon.presentations.errors import WorkspaceError
    try:
        selected = resolve_document_project(project)
        result = recover_job(selected, identity) if recover else job_store(selected).get(identity).as_dict()
        click.echo(json.dumps(result, indent=2))
    except (DocumentWorkspaceError, WorkspaceError) as error:
        raise click.ClickException(f'{error.code}: {error}') from error
