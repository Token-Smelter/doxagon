#!/usr/bin/env python3
"""dox.py - CLI for managing doxai (beliefs) and their relationships.

Doxagon is a personal epistemology infrastructure that stores beliefs as
markdown files and tracks their relationships in a knowledge graph.

Doxai are stored in library/doxai/ (prefix: d-)
Evidence is stored in library/evidence/ (prefix: e-)
Relationships are stored in library/logos.yaml
Schema is defined in library/schema.yaml
"""

import json
import os
import re
import subprocess
import sys
import html
import hashlib
from datetime import date, datetime
from pathlib import Path
from uuid import uuid4

import click
import frontmatter
import networkx as nx
import yaml

from doxagon.config import (
    ROOT_DIR, LIBRARY_DIR, DOXAI_DIR,
    DIEGESES_DIR, LOGOS_FILE, CACHE_DIR, INDEX_FILE
)
from doxagon.graph import (
    edge_records_between, load_graph, save_logos, invalidate_cache
)
from doxagon.storage import read_logos
from doxagon.validation import GraphIntegrityError, validate_library
from doxagon.prompts import load_prompt
from doxagon.schema import load_schema
from doxagon.extract import extract_from_phantasia
from doxagon.integrate import run_integration
from doxagon.audit import run_audit
from doxagon.onboarding import remediation_for
from doxagon.workspace import (
    WorkspaceOpenRequest,
    initialize_empty_vault,
    open_workspace,
)
from doxagon.html_editions.cli import html_edition_group
from doxagon.renderings.cli import rendering_group
from doxagon.renderings.document_cli import document_group


def save_index(index: dict) -> None:
    """Save number-to-ID index for quick reference."""
    CACHE_DIR.mkdir(exist_ok=True, parents=True)
    INDEX_FILE.write_text(json.dumps(index))


def load_index() -> dict:
    """Load number-to-ID index."""
    if INDEX_FILE.exists():
        return json.loads(INDEX_FILE.read_text())
    return {}


def resolve_doxa_id(ref: str) -> str:
    """Resolve a reference (number or ID) to a doxa ID."""
    if ref.isdigit():
        index = load_index()
        num = int(ref)
        if num in index or str(num) in index:
            return index.get(num) or index.get(str(num))
        click.echo(f"ERROR: No doxa at index {num}. Run 'dox list' first.", err=True)
        sys.exit(1)
    return ref


_DOCUMENT_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
  :root {{ --paper: #fdf8ec; --ink: #1a1613; --muted: #4a4238; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: var(--paper); color: var(--ink);
         font: 20px/1.5 Georgia, "Iowan Old Style", serif; }}
  h1, h2 {{ font-weight: 400; line-height: 1.1; text-wrap: balance; }}
  .chapter {{ padding: 8vh 6vw; }}
  .beat {{ max-width: 46ch; margin: 1.2em 0; }}
  /* Scaffolds are readable without JavaScript. The script below only adds
     cue reporting and navigation for the Doxagon player. */
  @media (prefers-reduced-motion: reduce) {{
    * {{ transition: none !important; scroll-behavior: auto !important; }}
  }}
</style>
</head>
<body>
<main>
{body}
</main>
<script>
(() => {{
  'use strict';
  const documentId = '{document_id}';
  const edition = '{edition}';
  const beats = [...document.querySelectorAll('[data-cue]')];
  const cues = beats.map(node => ({{
    id: node.dataset.cue,
    title: (node.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 80) || node.dataset.cue,
  }}));
  let index = 0;
  let port = null;

  const clamp = value => Math.max(0, Math.min(cues.length - 1, value));

  function notify() {{
    if (!port) return;
    port.postMessage({{
      type: 'position', documentId, edition,
      cue: cues[index].id, index, total: cues.length, progress: 0,
      chapter: beats[index].closest('.chapter')?.id,
    }});
  }}

  function go(id, options) {{
    const at = cues.findIndex(cue => cue.id === id);
    if (at < 0) return;
    index = at;
    beats[index].scrollIntoView({{
      behavior: options && options.instant ? 'auto' : 'smooth', block: 'center',
    }});
    notify();
  }}

  function move(step) {{ go(cues[clamp(index + step)].id); }}

  // Only the direct parent may drive this document.
  window.addEventListener('message', event => {{
    if (window.parent === window || event.source !== window.parent) return;
    if (event.data?.type !== 'doxagon:connect' || !event.ports[0]) return;
    if (port) port.close();
    port = event.ports[0];
    port.onmessage = ({{ data }}) => {{
      if (data?.type === 'next') move(1);
      else if (data?.type === 'previous') move(-1);
      else if (data?.type === 'go' && typeof data.cue === 'string') go(data.cue, {{ instant: true }});
      else if (data?.type === 'state') notify();
    }};
    port.start();
    port.postMessage({{ type: 'ready', documentId, edition, cues }});
    notify();
  }});

  // Standalone reading: the same cue set, driven by the keyboard.
  window.addEventListener('keydown', event => {{
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    if (['ArrowRight', 'ArrowDown', 'PageDown', ' '].includes(event.key)) {{
      event.preventDefault(); move(1);
    }} else if (['ArrowLeft', 'ArrowUp', 'PageUp'].includes(event.key)) {{
      event.preventDefault(); move(-1);
    }}
  }});

  window.doxagonDocument = {{ documentId, edition, cues, go, state: () => ({{ cue: cues[index].id, index }}) }};
}})();
</script>
</body>
</html>
"""


@click.group()
def cli():
    """Manage doxai (beliefs) and their relationships."""
    pass


cli.add_command(html_edition_group)
cli.add_command(rendering_group)
cli.add_command(document_group)


def _emit(value: dict, as_json: bool) -> None:
    if as_json:
        click.echo(json.dumps(value, indent=2, sort_keys=True))
        return
    for name, item in value.items():
        if name == 'ok':
            continue
        if name == 'frontend':
            click.echo(f"frontend: {item['status']}")
        elif name == 'skills':
            states = ', '.join(f"{skill}={record['status']}" for skill, record in sorted(item.items()))
            click.echo(f"skills: {states or 'unavailable'}")
        elif name == 'agents_md':
            click.echo(f"agents_md: {item['status']}")
        elif isinstance(item, dict) and 'ok' in item:
            click.echo(f"{name}: {'ok' if item['ok'] else 'failing'}")
        else:
            click.echo(f"{name}: {item}")


@cli.command()
@click.option('--json', 'as_json', is_flag=True)
def doctor(as_json: bool) -> None:
    """Report platform, vault, agent resource, provider, and frontend readiness."""
    from doxagon.toolchain import doctor as inspect_doctor
    report = inspect_doctor()
    _emit(report, as_json)
    if not report['ok']:
        raise click.exceptions.Exit(1)


@cli.group()
def skills() -> None:
    """Install platform-owned agent resources into a selected vault."""


@skills.command('sync')
@click.option('--vault', type=click.Path(path_type=Path))
@click.option('--force', is_flag=True)
@click.option('--json', 'as_json', is_flag=True)
def skills_sync(vault: Path | None, force: bool, as_json: bool) -> None:
    """Materialize packaged skills and AGENTS.md without overwriting local edits."""
    from doxagon.toolchain import sync_agent_resources
    selected = vault or (Path(os.environ['DOXAGON_ROOT']) if os.environ.get('DOXAGON_ROOT') else None)
    if selected is None:
        raise click.ClickException('DOXAGON_ROOT is unset; pass --vault PATH')
    report = sync_agent_resources(selected, force)
    if as_json:
        click.echo(json.dumps(report, indent=2, sort_keys=True))
    elif not report['changed'] and not report['foreign'] and not report['vault_only']:
        click.echo('No changes.')
    else:
        for key in ('created', 'updated', 'foreign', 'vault_only'):
            if report[key]:
                click.echo(f"{key}: {', '.join(report[key])}")


@cli.command('context')
@click.argument('project')
@click.option('--json', 'as_json', is_flag=True)
def presentation_context(project: str, as_json: bool) -> None:
    """Orient an agent before it edits a document or legacy slide project."""
    from doxagon.renderings.project import DocumentWorkspaceError
    from doxagon.toolchain import context as project_context
    try:
        report = project_context(project)
    except DocumentWorkspaceError as error:
        raise click.ClickException(f'{error.code}: {error}') from error
    if as_json:
        click.echo(json.dumps(report, indent=2, sort_keys=True))
    else:
        click.echo(f"{report['identity']['title']}\nProject: {report['identity']['project']}\nModel: {report['model']['name']}\nAuthoritative: {report['model']['authoritative']}\nCue/notes: {report['cue_notes_agreement']}\nInvoke: {report['skill']}")


@cli.group()
def provider() -> None:
    """Inspect and conformance-check the configured image provider."""


@provider.command('check')
@click.option('--executable')
@click.option('--live', is_flag=True)
@click.option('--yes', is_flag=True)
@click.option('--json', 'as_json', is_flag=True)
def provider_check_command(executable: str | None, live: bool, yes: bool, as_json: bool) -> None:
    """Check an adapter; --live makes one potentially paid provider call."""
    if live and not yes:
        raise click.UsageError('--live can have a paid effect; repeat with --yes')
    if live:
        click.echo('Warning: --live can have a paid effect; running one synthetic conformance request.', err=True)
    from doxagon.toolchain import provider_check
    report = provider_check(executable, live)
    if as_json:
        click.echo(json.dumps(report, indent=2, sort_keys=True))
    else:
        click.echo(json.dumps(report, indent=2, sort_keys=True))
    if not report['ok']:
        raise click.exceptions.Exit(1)


@cli.group()
def styles() -> None:
    """Lint a project's style bundles for migration hazards."""


@styles.command('lint')
@click.argument('project', required=False)
@click.option('--fix-requires', is_flag=True, help='Mirror body **Requires:** markers into frontmatter requires:, printing a diff.')
@click.option('--json', 'as_json', is_flag=True)
def styles_lint(project: str | None, fix_requires: bool, as_json: bool) -> None:
    """Report stale markers, broken dependencies, missing sources and oversized closures; exit 1 on errors."""
    from doxagon.renderings.project import DocumentWorkspaceError, resolve_document_project
    from doxagon.renderings.style_lint import lint_styles
    try:
        report = lint_styles(resolve_document_project(project), fix=fix_requires)
    except DocumentWorkspaceError as error:
        raise click.ClickException(f'{error.code}: {error}') from error
    if as_json:
        click.echo(json.dumps(report, indent=2, sort_keys=True))
    else:
        for fix in report['fixed']:
            click.echo(fix['diff'], nl=False)
        for finding in report['findings']:
            click.echo(f"{finding['bundle']}: {finding['severity']} {finding['rule']}: {finding['message']}")
        counts = report['counts']
        click.echo(f"{len(report['bundles'])} bundles; {len(report['fixed'])} fixed; {counts['error']} errors, {counts['warning']} warnings, {counts['info']} info "
                   f"(max_references {report['max_references']} from {report['capabilities_source']})")
    if report['counts']['error']:
        raise click.exceptions.Exit(1)


def _workspace_request(vault: Path | None, demo: bool) -> WorkspaceOpenRequest:
    return WorkspaceOpenRequest(
        cli_workspace=None,
        cli_vault=vault,
        cli_state=None,
        cli_artifacts=None,
        cli_config=None,
        cli_read_only=None,
        cli_mode='demo' if demo else None,
        environ=os.environ,
        invocation_cwd=Path.cwd(),
        standard_config_path=Path.home() / '.config' / 'doxagon' / 'config.toml',
    )


@cli.command()
@click.argument('path', type=click.Path(path_type=Path))
def init(path):
    """Create a new, empty vault at PATH."""
    try:
        # A real vault gets a random identity. The library default is fixed so
        # test fixtures stay deterministic, which is the wrong choice here:
        # two vaults sharing an id would share a state namespace.
        created = initialize_empty_vault(path, vault_id=uuid4())
    except (OSError, ValueError) as error:
        raise click.ClickException(str(error))

    click.echo(f"Created empty vault at {created}")
    click.echo("Wrote AGENTS.md; run `dox skills sync` to install the skills beside it.")
    click.echo()
    click.echo(f"  dox skills sync --vault {created}")
    click.echo(f"  dox workspace --vault {created}")


@cli.command()
@click.option('--vault', type=click.Path(path_type=Path), help='Vault to open.')
@click.option('--demo', is_flag=True, help='Open the packaged synthetic sample vault.')
def workspace(vault, demo):
    """Report which workspace would open, and what to do when none does."""
    if demo and vault is not None:
        raise click.ClickException(
            "--demo and --vault are mutually exclusive; the demo vault is packaged, not selected."
        )

    result = open_workspace(_workspace_request(vault, demo))
    if result.state == 'ready':
        config = result.config
        graph = result.services.read_graph()
        click.echo("workspace  ready")
        click.echo(f"  vault    {config.vault_root}")
        click.echo(f"  mode     {config.deployment_mode} / {config.access_mode}")
        click.echo(f"  schema   {config.schema_version}")
        click.echo(f"  graph    {len(graph.nodes)} doxai, {len(graph.edges)} edges")
        result.services.close()
        return

    code = getattr(result, 'code', None) or getattr(result, 'diagnostic', None)
    click.echo(f"workspace  {result.state}", err=True)
    click.echo(f"  reason   {code}", err=True)
    click.echo(err=True)
    click.echo(remediation_for(code), err=True)
    sys.exit(1)


@cli.command()
@click.argument('doxa_ref')
def show(doxa_ref: str):
    """Show a doxa with its relationships. Use number from 'dox list' or full ID."""
    doxa_id = resolve_doxa_id(doxa_ref)
    G = load_graph()
    if doxa_id not in G:
        click.echo(f"ERROR: Doxa not found: {doxa_id}", err=True)
        sys.exit(1)

    node = G.nodes[doxa_id]
    click.echo(f"\n{doxa_id}")
    click.echo("=" * 60)

    belief_text = node.get('belief', 'N/A')
    click.echo(f"Belief: {belief_text}")
    click.echo(f"Status: {node.get('status', 'N/A')}")

    tags = node.get('tags', [])
    if tags:
        click.echo(f"Tags: {', '.join(tags)}")

    # Relationships
    schema = load_schema()
    edge_types = schema.get('edge_types', {})
    preds = list(G.predecessors(doxa_id))
    succs = list(G.successors(doxa_id))

    if preds or succs:
        click.echo("\nRelationships:")
        for pred in preds:
            for _, edge_data in edge_records_between(G, pred, doxa_id):
                edge_type = edge_data.get('type', '?')
                edge_alias = edge_data.get('alias')
                inverse = edge_types.get(edge_type, {}).get('inverse', edge_type)
                label = f"{inverse} [{edge_type}]" + (f" — {edge_alias}" if edge_alias else "")
                click.echo(f"  ← {label} ← {pred}")
        for succ in succs:
            for _, edge_data in edge_records_between(G, doxa_id, succ):
                edge_type = edge_data.get('type', '?')
                edge_alias = edge_data.get('alias')
                label = f"[{edge_type}]" + (f" {edge_alias}" if edge_alias else "")
                click.echo(f"  → {label} → {succ}")
    else:
        click.echo("\nRelationships: (none)")

    # Evidence
    evidence = node.get('evidence', [])
    if evidence:
        click.echo("\nEvidence:")
        for ev in evidence:
            if isinstance(ev, dict):
                source = ev.get('source', 'Unknown')
                quote = ev.get('quote', '')
                if quote:
                    click.echo(f"  * {source}: \"{quote[:60]}...\"")
                else:
                    click.echo(f"  * {source}")

    click.echo(f"\nFile: {node.get('path', 'N/A')}")
    click.echo("=" * 60)


@cli.command()
@click.argument('doxa_ref')
@click.option('--in', 'incoming', is_flag=True, help='Show only incoming edges')
@click.option('--out', 'outgoing', is_flag=True, help='Show only outgoing edges')
def related(doxa_ref: str, incoming: bool, outgoing: bool):
    """Show relationships for a doxa. Use number from 'dox list' or full ID."""
    doxa_id = resolve_doxa_id(doxa_ref)
    G = load_graph()
    if doxa_id not in G:
        click.echo(f"ERROR: Doxa not found: {doxa_id}", err=True)
        sys.exit(1)

    schema = load_schema()
    edge_types = schema.get('edge_types', {})

    click.echo(f"\n{doxa_id}")

    show_in = incoming or (not incoming and not outgoing)
    show_out = outgoing or (not incoming and not outgoing)

    edges = []

    if show_out:
        for succ in G.successors(doxa_id):
            for _, edge_data in edge_records_between(G, doxa_id, succ):
                edge_type = edge_data.get('type', '?')
                edge_alias = edge_data.get('alias')
                label = f"[{edge_type}]" + (f" {edge_alias}" if edge_alias else "")
                edges.append(f"├── → {label} → {succ}")

    if show_in:
        for pred in G.predecessors(doxa_id):
            for _, edge_data in edge_records_between(G, pred, doxa_id):
                edge_type = edge_data.get('type', '?')
                edge_alias = edge_data.get('alias')
                inverse = edge_types.get(edge_type, {}).get('inverse', edge_type)
                label = f"{inverse} [{edge_type}]" + (f" — {edge_alias}" if edge_alias else "")
                edges.append(f"├── ← {label} ← {pred}")

    if edges:
        for edge in edges[:-1]:
            click.echo(edge)
        click.echo(edges[-1].replace("├──", "└──"))
    else:
        click.echo("└── (no relationships)")


@cli.command()
@click.argument('source')
@click.argument('target')
@click.argument('edge_type')
@click.option('--alias', '-a', help='Human-readable label for this relationship')
def link(source: str, target: str, edge_type: str, alias: str):
    """Add a relationship between two doxai.

    The alias is an optional human-readable label that gives more semantic
    meaning while the type remains the rigid programmatic label.

    Example: dox link d-cost d-urgency grounds --alias "makes urgent"
    """
    schema = load_schema()
    valid_types = schema.get('edge_types', {})

    # Validate edge type
    if edge_type not in valid_types:
        click.echo(f"ERROR: Unknown edge type: {edge_type}. Valid types: {', '.join(valid_types.keys())}", err=True)
        sys.exit(1)

    G = load_graph()

    # Validate nodes exist
    missing = [n for n in [source, target] if n not in G]
    if missing:
        click.echo(f"ERROR: Doxa not found: {', '.join(missing)}", err=True)
        sys.exit(1)

    # Reject self-loops
    if source == target:
        click.echo("ERROR: Cannot link doxa to itself", err=True)
        sys.exit(1)

    # Reject only an exact typed duplicate; distinct types may share a pair.
    if G.has_edge(source, target, key=edge_type):
        click.echo(f"WARN: Edge already exists: {source} → {target} ({edge_type})", err=True)
        return

    edge_attrs = {'type': edge_type}
    if alias:
        edge_attrs['alias'] = alias
    G.add_edge(source, target, key=edge_type, **edge_attrs)

    # For symmetric edges (like contradicts), add reverse edge.
    if valid_types.get(edge_type, {}).get('symmetric', False):
        if not G.has_edge(target, source, key=edge_type):
            G.add_edge(target, source, key=edge_type, **edge_attrs)
            click.echo(f"Added (symmetric): {target} → {edge_type} → {source}")

    save_logos(G)
    invalidate_cache()

    label = alias if alias else edge_type
    click.echo(f"Added: {source} → {label} → {target}")


@cli.command()
@click.argument('source')
@click.argument('target')
@click.argument('edge_type')
def unlink(source: str, target: str, edge_type: str):
    """Remove a relationship between two doxai."""
    G = load_graph()

    if not G.has_edge(source, target, key=edge_type):
        click.echo(f"WARN: No {edge_type} edge from {source} to {target}", err=True)
        return

    schema = load_schema()
    valid_types = schema.get('edge_types', {})

    G.remove_edge(source, target, key=edge_type)
    click.echo(f"Removed: {source} → {edge_type} → {target}")

    # For symmetric edges, also remove the matching reverse type.
    if valid_types.get(edge_type, {}).get('symmetric', False):
        if G.has_edge(target, source, key=edge_type):
            G.remove_edge(target, source, key=edge_type)
            click.echo(f"Removed (symmetric): {target} → {edge_type} → {source}")

    save_logos(G)
    invalidate_cache()


@cli.command('list')
@click.option('--tag', help='Filter by tag')
@click.option('--status', type=click.Choice(['draft', 'canonical', 'archived']), help='Filter by status')
@click.option('-v', '--verbose', is_flag=True, help='Show belief excerpt and connection count')
def list_doxai(tag: str, status: str, verbose: bool):
    """List all doxai with numbered references.

    Use the number with other commands: dox show 1, dox related 5
    """
    G = load_graph()

    if not G.nodes():
        click.echo("No doxai found.")
        return

    # Build filtered list
    filtered = []
    for node_id, data in sorted(G.nodes(data=True)):
        if tag and tag not in data.get('tags', []):
            continue
        if status and data.get('status') != status:
            continue
        filtered.append((node_id, data))

    # Save index for quick reference
    index = {str(i): node_id for i, (node_id, _) in enumerate(filtered, 1)}
    save_index(index)

    # Display
    for i, (node_id, data) in enumerate(filtered, 1):
        if verbose:
            belief = data.get('belief', '')[:50]
            if len(data.get('belief', '')) > 50:
                belief += '...'
            in_count = G.in_degree(node_id)
            out_count = G.out_degree(node_id)
            ev_count = len(data.get('evidence', []))
            click.echo(f"{i:3}. {node_id}")
            click.echo(f"     \"{belief}\"")
            click.echo(f"     ↓{in_count} ↑{out_count} 📄{ev_count}")
        else:
            node_status = data.get('status', 'draft')
            in_count = G.in_degree(node_id)
            out_count = G.out_degree(node_id)
            click.echo(f"{i:3}. {node_id}  [{node_status}]  ↓{in_count} ↑{out_count}")

    if filtered:
        click.echo(f"\n{len(filtered)} doxai. Use number with: dox show 1, dox related 5")


@cli.command()
@click.argument('query')
def search(query: str):
    """Search doxai by content."""
    G = load_graph()
    query_lower = query.lower()
    found = False

    for node_id, data in G.nodes(data=True):
        belief = data.get('belief', '')
        tags = data.get('tags', [])
        path = Path(data.get('path', ''))

        # Search in belief, ID, tags, and body content
        matches = (
            query_lower in belief.lower() or
            query_lower in node_id.lower() or
            any(query_lower in t.lower() for t in tags)
        )

        # Also search body content if file exists
        if not matches and path.exists():
            try:
                content = path.read_text().lower()
                matches = query_lower in content
            except Exception:
                pass

        if matches:
            if len(belief) > 60:
                belief = belief[:57] + "..."
            click.echo(f"{node_id}: {belief}")
            found = True

    if not found:
        click.echo(f"No doxai matching '{query}'")


@cli.command()
def validate():
    """Validate endpoints, types, domains, beliefs, duplicates, and parallel pairs."""
    schema = load_schema()
    try:
        edges = read_logos(LOGOS_FILE)["edges"]
    except (GraphIntegrityError, yaml.YAMLError) as exc:
        click.echo(f"ERROR [malformed_logos]: {exc}")
        raise click.exceptions.Exit(1) from exc

    report = validate_library(
        edges=edges,
        doxai_dir=DOXAI_DIR,
        valid_edge_types=set(schema.get('edge_types', {})),
        valid_domains=set(schema.get('tag_prefixes', {}).get('domain', {}).get('values', [])),
    )
    for issue in report.errors:
        click.echo(f"ERROR [{issue.code}]: {issue.message}")
    for issue in report.warnings:
        click.echo(f"WARN [{issue.code}]: {issue.message}")

    if report.errors:
        raise click.exceptions.Exit(1)
    if report.warnings:
        click.echo("\nValidation passed with warnings.")
    else:
        click.echo("Validation passed.")


@cli.command()
def orphans():
    """Find doxai with no relationships."""
    G = load_graph()
    found = False

    for node_id in sorted(G.nodes()):
        if G.degree(node_id) == 0:
            click.echo(node_id)
            found = True

    if not found:
        click.echo("No orphaned doxai.")


@cli.command()
def types():
    """List registered edge types."""
    schema = load_schema()
    edge_types = schema.get('edge_types', {})

    for type_name, type_info in edge_types.items():
        desc = type_info.get('description', '')
        symmetric = type_info.get('symmetric', False)
        sym_label = " [symmetric]" if symmetric else ""
        click.echo(f"{type_name}: {desc}{sym_label}")


def generate_slug(text: str, max_length: int = 50) -> str:
    """Generate a valid filename slug from belief text."""
    # Lowercase and normalize
    slug = text.lower()
    # Replace common punctuation
    slug = re.sub(r"['\"]", "", slug)
    slug = re.sub(r"[:\-–—]", " ", slug)
    # Replace non-alphanumeric with hyphens
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    # Remove leading/trailing hyphens
    slug = slug.strip("-")
    # Collapse multiple hyphens
    slug = re.sub(r"-+", "-", slug)
    # Truncate to max length at word boundary
    if len(slug) > max_length:
        slug = slug[:max_length].rsplit("-", 1)[0]
    return slug


@cli.command()
@click.argument('belief')
def capture(belief: str):
    """Quick capture a belief as a new doxa."""
    slug = generate_slug(belief)
    base_filename = f"d-{slug}"
    filename = f"{base_filename}.md"

    # Handle collisions
    counter = 2
    target_path = DOXAI_DIR / filename
    while target_path.exists():
        filename = f"{base_filename}-{counter}.md"
        target_path = DOXAI_DIR / filename
        counter += 1

    # Generate title from slug
    title = slug.replace("-", " ").title()

    # Create file content
    today = date.today().isoformat()
    content = f"""---
belief: "{belief}"
status: draft
tags: []
evidence: []
created: {today}
updated: {today}
---

# {title}

(Body placeholder)
"""

    # Write file
    DOXAI_DIR.mkdir(parents=True, exist_ok=True)
    target_path.write_text(content)
    invalidate_cache()

    click.echo(f"Created: {target_path}")
    click.echo(f"  ID: {target_path.stem}")
    click.echo("  Status: draft")
    click.echo("\nNext steps:")
    click.echo(f"  dox edit {target_path.stem}     # Add evidence and body")
    click.echo(f"  dox link {target_path.stem} ... # Connect to related doxai")


@cli.command()
@click.argument('source')
@click.argument('target')
@click.option(
    '--direction',
    type=click.Choice(['directed', 'undirected']),
    default='directed',
    show_default=True,
    help='Traverse asserted direction or explicitly ignore direction.',
)
def path(source: str, target: str, direction: str):
    """Find directed or explicitly undirected paths between two doxai."""
    G = load_graph()

    for node in [source, target]:
        if node not in G:
            click.echo(f"ERROR: Doxa not found: {node}", err=True)
            sys.exit(1)

    search_graph = G if direction == 'directed' else G.to_undirected()
    arrow = '→' if direction == 'directed' else '—'
    try:
        raw_paths = nx.all_simple_paths(search_graph, source, target, cutoff=5)
        paths = [list(items) for items in dict.fromkeys(tuple(items) for items in raw_paths)]
        if paths:
            click.echo(f"\n{direction.title()} paths from {source} to {target}:")
            for index, items in enumerate(paths[:5], 1):
                click.echo(f"  {index}. {f' {arrow} '.join(items)}")
            if len(paths) > 5:
                click.echo(f"  ... and {len(paths) - 5} more")
        else:
            click.echo(f"No {direction} path found from {source} to {target}")
    except nx.NetworkXError as exc:
        click.echo(f"Error finding path: {exc}", err=True)
        sys.exit(1)


@cli.command()
def stats():
    """Show logos statistics."""
    G = load_graph()

    click.echo("\nLogos Statistics")
    click.echo("=" * 40)
    click.echo(f"Doxai: {G.number_of_nodes()}")
    click.echo(f"Relationships: {G.number_of_edges()}")

    if G.number_of_nodes() > 0:
        orphan_count = sum(1 for n in G.nodes() if G.degree(n) == 0)
        click.echo(f"Orphaned doxai: {orphan_count}")

        # Edge type distribution
        type_counts = {}
        for _, _, d in G.edges(data=True):
            edge_type = d.get('type', 'unknown')
            type_counts[edge_type] = type_counts.get(edge_type, 0) + 1

        if type_counts:
            click.echo("\nEdge types:")
            for edge_type, count in sorted(type_counts.items(), key=lambda x: -x[1]):
                click.echo(f"  {edge_type}: {count}")


@cli.command()
@click.option('--domain', help='Filter to specific domain')
@click.option('--root', help='Start from a specific doxa (shows its neighborhood)')
@click.option('--depth', default=2, help='Depth of neighborhood to show (default 2)')
def graph(domain: str, root: str, depth: int):
    """Output graph as Mermaid diagram.

    Examples:
      dox graph                    # Full graph
      dox graph --domain ai-economics  # Filter to domain
      dox graph --root 1 --depth 3 # Neighborhood of doxa #1
    """
    G = load_graph()

    # Filter by domain if specified
    if domain:
        domain_tag = f"domain:{domain}"
        nodes_to_keep = [n for n, d in G.nodes(data=True)
                        if domain_tag in d.get('tags', [])]
        G = G.subgraph(nodes_to_keep).copy()

    # Filter to neighborhood if root specified
    if root:
        root_id = resolve_doxa_id(root)
        if root_id not in G:
            click.echo(f"ERROR: Doxa not found: {root_id}", err=True)
            sys.exit(1)

        # Get nodes within depth
        neighborhood = {root_id}
        frontier = {root_id}
        for _ in range(depth):
            next_frontier = set()
            for node in frontier:
                next_frontier.update(G.predecessors(node))
                next_frontier.update(G.successors(node))
            neighborhood.update(next_frontier)
            frontier = next_frontier
        G = G.subgraph(neighborhood).copy()

    if not G.nodes():
        click.echo("No nodes to display.")
        return

    # Output Mermaid
    click.echo("```mermaid")
    click.echo("graph TD")

    # Shorten IDs for readability
    def short_id(full_id: str) -> str:
        return full_id.replace('d-', '').replace('-', '_')[:20]

    # Output nodes with labels
    for node_id, data in G.nodes(data=True):
        belief = data.get('belief', node_id)[:40]
        if len(data.get('belief', '')) > 40:
            belief += '...'
        safe_belief = belief.replace('"', "'")
        sid = short_id(node_id)
        click.echo(f'    {sid}["{safe_belief}"]')

    click.echo()

    # Output edges with canonical type always visible.
    for source, target, data in G.edges(data=True):
        edge_type = data.get('type', 'relates')
        edge_alias = data.get('alias')
        label = edge_type + (f" — {edge_alias}" if edge_alias else "")
        src = short_id(source)
        tgt = short_id(target)
        click.echo(f'    {src} -->|{label}| {tgt}')

    click.echo("```")
    click.echo(f"\n{G.number_of_nodes()} nodes, {G.number_of_edges()} edges")


@cli.command()
@click.argument('doxa_ref')
@click.option('--depth', default=3, help='Maximum depth to show (default 3)')
@click.option('--direction', type=click.Choice(['down', 'up', 'both']), default='down',
              help='Direction to traverse (down=what this grounds, up=what grounds this)')
def tree(doxa_ref: str, depth: int, direction: str):
    """Show tree view starting from a doxa.

    Examples:
      dox tree 1              # What does doxa #1 ground?
      dox tree 1 --direction up   # What grounds doxa #1?
      dox tree 1 --direction both # Both directions
    """
    doxa_id = resolve_doxa_id(doxa_ref)
    G = load_graph()

    if doxa_id not in G:
        click.echo(f"ERROR: Doxa not found: {doxa_id}", err=True)
        sys.exit(1)

    def get_belief_short(nid: str) -> str:
        """Get short belief text for display."""
        if nid in G.nodes:
            belief = G.nodes[nid].get('belief', '')[:35]
            if len(G.nodes[nid].get('belief', '')) > 35:
                belief += '...'
            return belief
        return ''

    def print_tree(node: str, prefix: str, visited: set, current_depth: int, go_up: bool):
        """Recursively print every typed edge."""
        if current_depth > depth or node in visited:
            return
        visited.add(node)

        if go_up:
            relationships = [
                (source, data)
                for source, _, _, data in G.in_edges(node, keys=True, data=True)
            ]
            arrow = "←"
        else:
            relationships = [
                (target, data)
                for _, target, _, data in G.out_edges(node, keys=True, data=True)
            ]
            arrow = "→"
        relationships.sort(key=lambda item: (item[0], item[1].get('type', '')))

        for index, (child, edge_data) in enumerate(relationships):
            is_last = index == len(relationships) - 1
            connector = "└── " if is_last else "├── "
            child_prefix = "    " if is_last else "│   "
            edge_type = edge_data.get('type', '?')
            edge_alias = edge_data.get('alias')
            label = f"{arrow} [{edge_type}]" + (f" {edge_alias}" if edge_alias else "")

            belief = get_belief_short(child)
            click.echo(f"{prefix}{connector}{label} {child}")
            if belief:
                click.echo(f"{prefix}{child_prefix}     \"{belief}\"")
            print_tree(child, prefix + child_prefix, visited.copy(), current_depth + 1, go_up)

    # Print root
    belief = get_belief_short(doxa_id)
    click.echo(f"\n{doxa_id}")
    if belief:
        click.echo(f'  "{belief}"')

    if direction in ['down', 'both']:
        out_count = G.out_degree(doxa_id)
        if out_count > 0:
            click.echo(f"\n↓ Outgoing typed relationships ({out_count}):")
            print_tree(doxa_id, "", set(), 1, go_up=False)

    if direction in ['up', 'both']:
        in_count = G.in_degree(doxa_id)
        if in_count > 0:
            click.echo(f"\n↑ Incoming typed relationships ({in_count}):")
            print_tree(doxa_id, "", set(), 1, go_up=True)


@cli.command()
def overview():
    """Show high-level graph overview with entry points."""
    G = load_graph()

    click.echo("\n=== Doxagon Overview ===\n")
    click.echo(f"Total: {G.number_of_nodes()} doxai, {G.number_of_edges()} relationships")

    # Find roots (nodes with no incoming edges)
    roots = [n for n in G.nodes() if G.in_degree(n) == 0 and G.out_degree(n) > 0]
    if roots:
        click.echo("\n📌 Foundational doxai (ground others, not grounded by any):")
        for r in sorted(roots)[:10]:
            belief = G.nodes[r].get('belief', '')[:50]
            out = G.out_degree(r)
            click.echo(f"   • {r} (→{out})")
            click.echo(f"     \"{belief}...\"")
        if len(roots) > 10:
            click.echo(f"   ... and {len(roots) - 10} more")

    # Find leaves (nodes with no outgoing edges)
    leaves = [n for n in G.nodes() if G.out_degree(n) == 0 and G.in_degree(n) > 0]
    if leaves:
        click.echo("\n🍂 Derived doxai (grounded by others, ground nothing):")
        for leaf in sorted(leaves)[:5]:
            belief = G.nodes[leaf].get('belief', '')[:50]
            inc = G.in_degree(leaf)
            click.echo(f"   • {leaf} (←{inc})")
        if len(leaves) > 5:
            click.echo(f"   ... and {len(leaves) - 5} more")

    # Find hubs (highly connected)
    hubs = sorted(G.nodes(), key=lambda n: G.degree(n), reverse=True)[:5]
    if hubs:
        click.echo("\n🔗 Most connected doxai:")
        for h in hubs:
            belief = G.nodes[h].get('belief', '')[:50]
            deg = G.degree(h)
            click.echo(f"   • {h} ({deg} connections)")

    # Domain breakdown
    domains = {}
    for n, d in G.nodes(data=True):
        for tag in d.get('tags', []):
            if tag.startswith('domain:'):
                domain = tag.split(':')[1]
                domains[domain] = domains.get(domain, 0) + 1
    if domains:
        click.echo("\n📂 By domain:")
        for domain, count in sorted(domains.items(), key=lambda x: -x[1]):
            click.echo(f"   • {domain}: {count}")


@cli.command()
@click.argument('thesis')
@click.option('--verbose', '-v', is_flag=True, help='Show slide-by-slide coverage')
def drift(thesis: str, verbose: bool):
    """Show how presentation diverges from thesis doxai.

    Compares the diegesis (canonical narrative) against actual slides.
    Reports which doxai are covered, missing, or added.
    """
    # Paths
    thesis_dir = ROOT_DIR / "theses" / thesis
    diegesis_file = LIBRARY_DIR / "diegeses" / f"n-{thesis}.md"
    slides_dir = thesis_dir / "outputs" / "presentation" / "slides"

    if not diegesis_file.exists():
        click.echo(f"ERROR: No diegesis found: {diegesis_file}", err=True)
        click.echo(f"Create one at: library/diegeses/n-{thesis}.md")
        sys.exit(1)

    if not slides_dir.exists():
        click.echo(f"ERROR: No slides directory: {slides_dir}", err=True)
        sys.exit(1)

    # Load diegesis sections and collect all referenced doxai
    diegesis = frontmatter.load(diegesis_file)
    sections = diegesis.get('sections', {})
    canonical_doxai = set()
    for section in sections.values():
        for d in section.get('doxai', []):
            canonical_doxai.add(d)

    if not canonical_doxai:
        click.echo("ERROR: Diegesis has no doxai in 'sections'", err=True)
        sys.exit(1)

    # Load graph for belief text matching
    G = load_graph()

    # Build keyword index for fuzzy matching
    def get_keywords(doxa_id: str) -> set:
        """Extract keywords from doxa belief for matching."""
        if doxa_id not in G.nodes:
            return set()
        belief = G.nodes[doxa_id].get('belief', '').lower()
        # Extract significant words (4+ chars, not common)
        stopwords = {'that', 'this', 'with', 'from', 'have', 'been', 'more', 'than', 'into', 'when', 'will', 'they', 'what', 'which', 'their', 'there', 'would', 'could', 'should', 'being', 'about'}
        words = re.findall(r'\b[a-z]{4,}\b', belief)
        return {w for w in words if w not in stopwords}

    doxa_keywords = {d: get_keywords(d) for d in canonical_doxai}

    # Analyze each slide
    slide_coverage = {}  # slide_name -> set of doxai covered
    slide_dirs = sorted([d for d in slides_dir.iterdir() if d.is_dir()])

    for slide_dir in slide_dirs:
        slide_file = slide_dir / "slide.md"
        if not slide_file.exists():
            continue

        slide_name = slide_dir.name
        slide = frontmatter.load(slide_file)

        # Check for explicit covers: field first
        explicit_covers = slide.get('covers', [])
        if explicit_covers:
            slide_coverage[slide_name] = set(explicit_covers)
            continue

        # Fall back to content matching
        text = slide.get('text', {})
        title = text.get('title', '').lower() if isinstance(text, dict) else ''
        body = text.get('body', '').lower() if isinstance(text, dict) else ''
        notes = slide.get('speaker_notes', '').lower()
        content = f"{title} {body} {notes}"
        content_words = set(re.findall(r'\b[a-z]{4,}\b', content))

        # Find doxai with keyword overlap
        matched = set()
        for doxa_id, keywords in doxa_keywords.items():
            if keywords and len(keywords & content_words) >= 2:  # At least 2 keyword matches
                matched.add(doxa_id)

        slide_coverage[slide_name] = matched

    # Calculate coverage
    all_covered = set()
    for doxai in slide_coverage.values():
        all_covered.update(doxai)

    covered_canonical = all_covered & canonical_doxai
    missing = canonical_doxai - all_covered
    extra = all_covered - canonical_doxai  # In slides but not in diegesis

    # Report
    click.echo(f"\n=== Drift Report: {thesis} ===\n")
    click.echo(f"Diegesis: {len(canonical_doxai)} doxai")
    click.echo(f"Slides: {len(slide_coverage)}")
    click.echo(f"Coverage: {len(covered_canonical)}/{len(canonical_doxai)} ({100*len(covered_canonical)//len(canonical_doxai)}%)")

    if missing:
        click.echo(f"\n❌ Missing from slides ({len(missing)}):")
        for d in sorted(missing):
            belief = G.nodes[d].get('belief', '')[:50] if d in G.nodes else ''
            click.echo(f"   • {d}")
            if belief:
                click.echo(f"     \"{belief}...\"")

    if extra:
        click.echo(f"\n➕ In slides but not in diegesis ({len(extra)}):")
        for d in sorted(extra):
            click.echo(f"   • {d}")

    if verbose:
        click.echo("\n📊 Slide-by-slide coverage:")
        for slide_name, doxai in sorted(slide_coverage.items()):
            click.echo(f"\n{slide_name}:")
            if doxai:
                for d in sorted(doxai):
                    marker = "✓" if d in canonical_doxai else "+"
                    click.echo(f"   {marker} {d}")
            else:
                click.echo("   (no doxai matched)")

    # Suggestions
    if missing:
        click.echo("\n💡 To improve coverage:")
        click.echo("   1. Add 'covers:' field to slide frontmatter for explicit mapping")
        click.echo("   2. Or ensure slide content includes key terms from missing doxai")


@cli.command()
@click.argument('thesis')
@click.option('--output', '-o', help='Output directory (default: projects/{thesis}/outputs/document)')
@click.option('--dry-run', is_flag=True, help='Show what would be created without writing files')
@click.option('--force', is_flag=True, help='Overwrite an existing scaffold')
def scaffold(thesis: str, output: str, dry_run: bool, force: bool):
    """Generate a single-page presentation document from a diegesis.

    Writes one self-contained HTML file plus its companion notes. Each
    diegesis section becomes a chapter; each doxa becomes a cue whose id is
    stable, so notes stay keyed to it as the deck is edited.

    Example:
      dox scaffold observatory --dry-run
      dox scaffold observatory
    """
    diegesis_file = LIBRARY_DIR / "diegeses" / f"n-{thesis}.md"
    if not diegesis_file.exists():
        click.echo(f"ERROR: No diegesis found: {diegesis_file}", err=True)
        sys.exit(1)

    document_dir = Path(output) if output else ROOT_DIR / "projects" / thesis / "outputs" / "document"
    diegesis = frontmatter.load(diegesis_file)

    # Structure comes from frontmatter `sections`, which is where every
    # diegesis actually declares it. An earlier version parsed `##` headings
    # for `[[d-*]]` links; most diegeses carry none in the body, so it failed
    # on them regardless of what it would have emitted.
    sections = diegesis.get('sections') or {}
    if not isinstance(sections, dict) or not sections:
        click.echo("ERROR: Diegesis frontmatter has no 'sections' mapping", err=True)
        click.echo("Expected: sections: {key: {title: ..., doxai: [d-...]}}", err=True)
        sys.exit(1)

    chapters = []
    for key, section in sections.items():
        if not isinstance(section, dict):
            continue
        ids = [str(item) for item in (section.get('doxai') or [])]
        if not ids:
            continue
        chapters.append({
            'id': re.sub(r'[^a-z0-9]+', '-', str(key).lower()).strip('-'),
            'title': section.get('title') or str(key).replace('_', ' ').title(),
            'doxai': ids,
        })
    if not chapters:
        click.echo("ERROR: No section in this diegesis lists any doxai", err=True)
        sys.exit(1)

    def belief_of(doxa_id: str) -> str:
        path = DOXAI_DIR / f"{doxa_id}.md"
        if not path.exists():
            return ""
        try:
            return str(frontmatter.load(path).get('belief') or "").strip()
        except Exception:
            return ""

    cues = []
    for chapter in chapters:
        for index, doxa_id in enumerate(chapter['doxai']):
            # The doxa id is already stable and unique, so it is the cue id.
            # Notes and deep links key on these; renaming one breaks both.
            cues.append({
                'id': doxa_id,
                'chapter': chapter['id'],
                'title': chapter['title'],
                'belief': belief_of(doxa_id) or f"({doxa_id} has no belief text)",
                'first': index == 0,
            })

    title = diegesis.get('title') or thesis
    edition = hashlib.sha256(
        "\u0000".join(f"{cue['chapter']}/{cue['id']}" for cue in cues).encode()
    ).hexdigest()[:20]
    document_id = f"{thesis}-document"
    html_name = f"{thesis}.html"

    if dry_run:
        click.echo(f"Would scaffold: {document_dir}")
        click.echo(f"  {html_name}  {len(chapters)} chapters, {len(cues)} cues")
        click.echo(f"  notes.json    {len(cues)} entries")
        click.echo("  presentation.json  selects the two above")
        for chapter in chapters:
            click.echo(f"\n  {chapter['id']}: {chapter['title']}")
            for doxa_id in chapter['doxai']:
                click.echo(f"    cue {doxa_id}")
        click.echo("\n(dry run - no files created)")
        return

    existing = document_dir / "presentation.json"
    if existing.exists() and not force:
        click.echo(f"ERROR: {existing} exists. Use --force to overwrite.", err=True)
        sys.exit(1)
    document_dir.mkdir(parents=True, exist_ok=True)

    body = []
    for chapter in chapters:
        owned = [cue for cue in cues if cue['chapter'] == chapter['id']]
        beats = "\n".join(
            f'        <p class="beat" data-cue="{cue["id"]}">{html.escape(cue["belief"])}</p>'
            for cue in owned
        )
        body.append(
            f'    <section class="chapter" id="{chapter["id"]}">\n'
            f'      <div class="scene">\n'
            f'        <h2>{html.escape(chapter["title"])}</h2>\n'
            f'{beats}\n'
            f'      </div>\n'
            f'    </section>'
        )

    (document_dir / html_name).write_text(
        _DOCUMENT_TEMPLATE.format(
            title=html.escape(str(title)),
            document_id=document_id,
            edition=edition,
            body="\n".join(body),
        ),
        encoding='utf-8',
    )
    (document_dir / "notes.json").write_text(
        json.dumps(
            {
                'documentId': document_id,
                'edition': edition,
                'cues': [{'id': cue['id'], 'notes': f"[{cue['title']}] {cue['belief']}"} for cue in cues],
            },
            indent=2,
            ensure_ascii=False,
        ) + "\n",
        encoding='utf-8',
    )
    (document_dir / "presentation.json").write_text(
        json.dumps(
            {'schema': 'doxagon.authored-document/1', 'document': html_name, 'notes': 'notes.json'},
            indent=2,
        ) + "\n",
        encoding='utf-8',
    )

    click.echo(f"\u2713 Scaffolded {len(chapters)} chapters and {len(cues)} cues in {document_dir}")
    click.echo("\nThis is a skeleton: real imagery, layout and animation are authored into the HTML.")
    click.echo("\nNext steps:")
    click.echo("  1. Read .pi/skills/presentation-document/SKILL.md before editing")
    click.echo(f"  2. Open it: /presentations?thesis={thesis}")
    click.echo(f"  3. Check coverage: dox drift {thesis}")


# =============================================================================
# DIEGESIS COMMANDS
# =============================================================================


@cli.group()
def diegesis():
    """Manage diegeses (narrative walks through doxai)."""
    pass


@diegesis.command('list')
@click.option('-v', '--verbose', is_flag=True, help='Show walks preview')
def diegesis_list(verbose: bool):
    """List all diegeses in the library.

    Example:
      dox diegesis list
      dox diegesis list -v
    """
    if not DIEGESES_DIR.exists():
        click.echo("No diegeses directory found.")
        return

    diegeses_files = sorted(DIEGESES_DIR.glob("n-*.md"))
    if not diegeses_files:
        click.echo("No diegeses found.")
        return

    click.echo(f"\n=== Diegeses ({len(diegeses_files)}) ===\n")

    for i, f in enumerate(diegeses_files, 1):
        d = frontmatter.load(f)
        name = f.stem  # n-observatory
        title = d.get('title', name)
        walks = d.get('walks', [])

        click.echo(f"  {i}. {name}")
        click.echo(f"     Title: {title}")
        click.echo(f"     Walks: {len(walks)} doxai")

        if verbose and walks:
            preview = walks[:5]
            for w in preview:
                click.echo(f"       • {w}")
            if len(walks) > 5:
                click.echo(f"       ... and {len(walks) - 5} more")

        click.echo()


@diegesis.command('show')
@click.argument('name')
def diegesis_show(name: str):
    """Show details of a diegesis.

    NAME can be full (n-observatory) or short (observatory).

    Example:
      dox diegesis show observatory
      dox diegesis show n-observatory
    """
    # Normalize name
    if not name.startswith('n-'):
        name = f'n-{name}'

    diegesis_file = DIEGESES_DIR / f"{name}.md"
    if not diegesis_file.exists():
        click.echo(f"ERROR: Diegesis not found: {diegesis_file}", err=True)
        sys.exit(1)

    d = frontmatter.load(diegesis_file)
    title = d.get('title', name)
    subtitle = d.get('subtitle', '')
    walks = d.get('walks', [])
    created = d.get('created', '')
    updated = d.get('updated', '')

    G = load_graph()

    click.echo(f"\n=== {name} ===\n")
    click.echo(f"Title: {title}")
    if subtitle:
        click.echo(f"Subtitle: {subtitle}")
    click.echo(f"Created: {created}")
    click.echo(f"Updated: {updated}")
    click.echo(f"\nWalks: {len(walks)} doxai")

    # Check which doxai exist vs missing
    missing = [w for w in walks if w not in G.nodes]

    if missing:
        click.echo(f"  ⚠ Missing from graph: {len(missing)}")
        for m in missing:
            click.echo(f"    • {m}")

    click.echo("\n--- Walk Order ---\n")
    for i, w in enumerate(walks, 1):
        if w in G.nodes:
            belief = G.nodes[w].get('belief', '(no belief)')
            belief_preview = belief[:60] + '...' if len(belief) > 60 else belief
            click.echo(f"  {i:2}. {w}")
            click.echo(f"      \"{belief_preview}\"")
        else:
            click.echo(f"  {i:2}. {w} [MISSING]")


@diegesis.command('walk')
@click.argument('name')
@click.option('--format', 'fmt', type=click.Choice(['full', 'beliefs', 'narrative']),
              default='full', help='Output format')
@click.option('--output', '-o', type=click.Path(), help='Write to file instead of stdout')
def diegesis_walk(name: str, fmt: str, output: str):
    """Walk through a diegesis, concatenating content from each doxa.

    Formats:
      full      - Full doxa content (belief + body)
      beliefs   - Just the belief statements
      narrative - Diegesis prose with doxa content interleaved

    Example:
      dox diegesis walk observatory
      dox diegesis walk observatory --format beliefs
      dox diegesis walk observatory --format narrative -o output.md
    """
    # Normalize name
    if not name.startswith('n-'):
        name = f'n-{name}'

    diegesis_file = DIEGESES_DIR / f"{name}.md"
    if not diegesis_file.exists():
        click.echo(f"ERROR: Diegesis not found: {diegesis_file}", err=True)
        sys.exit(1)

    d = frontmatter.load(diegesis_file)
    title = d.get('title', name)
    walks = d.get('walks', [])
    narrative_content = d.content

    G = load_graph()

    lines = []

    if fmt == 'narrative':
        # Parse narrative and expand [[doxa-id]] references
        lines.append(f"# {title}\n")

        # Process narrative, expanding wiki-links
        current_content = narrative_content
        for doxa_id in walks:
            wiki_link = f"[[{doxa_id}]]"
            if wiki_link in current_content:
                # Build replacement content
                if doxa_id in G.nodes:
                    belief = G.nodes[doxa_id].get('belief', '')
                    doxa_file = DOXAI_DIR / f"{doxa_id}.md"
                    if doxa_file.exists():
                        doxa_data = frontmatter.load(doxa_file)
                        body = doxa_data.content.strip()
                        # Create blockquote with belief and body preview
                        replacement = f"\n> **{belief}**\n"
                        if body:
                            # Get first paragraph of body
                            first_para = body.split('\n\n')[0]
                            if first_para.startswith('#'):
                                # Skip header, get next paragraph
                                paras = body.split('\n\n')
                                first_para = paras[1] if len(paras) > 1 else ''
                            if first_para:
                                replacement += f"> \n> {first_para[:200]}{'...' if len(first_para) > 200 else ''}\n"
                    else:
                        replacement = f"\n> **{belief}**\n"
                else:
                    replacement = f"\n> [Missing: {doxa_id}]\n"
                current_content = current_content.replace(wiki_link, replacement, 1)

        lines.append(current_content)

    elif fmt == 'beliefs':
        lines.append(f"# {title} - Belief Statements\n")
        for i, doxa_id in enumerate(walks, 1):
            if doxa_id in G.nodes:
                belief = G.nodes[doxa_id].get('belief', '(no belief)')
                lines.append(f"{i}. **{belief}**")
            else:
                lines.append(f"{i}. [Missing: {doxa_id}]")

    else:  # full
        lines.append(f"# {title}\n")
        for i, doxa_id in enumerate(walks, 1):
            lines.append(f"\n---\n\n## {i}. {doxa_id}\n")
            if doxa_id in G.nodes:
                belief = G.nodes[doxa_id].get('belief', '')
                lines.append(f"**{belief}**\n")

                # Load full doxa content
                doxa_file = DOXAI_DIR / f"{doxa_id}.md"
                if doxa_file.exists():
                    doxa_data = frontmatter.load(doxa_file)
                    body = doxa_data.content.strip()
                    if body:
                        lines.append(f"\n{body}\n")

                # Show evidence summary
                evidence = G.nodes[doxa_id].get('evidence', [])
                if evidence:
                    lines.append(f"\n**Evidence ({len(evidence)}):**")
                    for ev in evidence:
                        if isinstance(ev, dict):
                            source = ev.get('source', '')
                            lines.append(f"  - {source}")
                else:
                    lines.append("\n**Evidence:** None")
            else:
                lines.append(f"[Missing doxa: {doxa_id}]")

    result = '\n'.join(lines)

    if output:
        Path(output).write_text(result)
        click.echo(f"Written to {output}")
    else:
        click.echo(result)


@diegesis.command('evidence')
@click.argument('name')
@click.option('--missing-only', is_flag=True, help='Only show doxai without evidence')
def diegesis_evidence(name: str, missing_only: bool):
    """Analyze evidence strength across a diegesis.

    Shows which doxai have strong evidence backing, which need research,
    and identifies gaps in the argument's support structure.

    Example:
      dox diegesis evidence observatory
      dox diegesis evidence observatory --missing-only
    """
    # Normalize name
    if not name.startswith('n-'):
        name = f'n-{name}'

    diegesis_file = DIEGESES_DIR / f"{name}.md"
    if not diegesis_file.exists():
        click.echo(f"ERROR: Diegesis not found: {diegesis_file}", err=True)
        sys.exit(1)

    d = frontmatter.load(diegesis_file)
    title = d.get('title', name)
    walks = d.get('walks', [])

    G = load_graph()

    # Categorize doxai by evidence strength
    strong = []       # 3+ evidence sources
    moderate = []     # 1-2 evidence sources
    unsupported = []  # 0 evidence sources
    missing_doxai = []  # Not in graph

    evidence_sources = set()  # Track all referenced evidence

    for doxa_id in walks:
        if doxa_id not in G.nodes:
            missing_doxai.append(doxa_id)
            continue

        evidence = G.nodes[doxa_id].get('evidence', [])
        ev_count = len(evidence) if evidence else 0

        # Track sources
        for ev in (evidence or []):
            if isinstance(ev, dict):
                evidence_sources.add(ev.get('source', ''))

        entry = {
            'id': doxa_id,
            'belief': G.nodes[doxa_id].get('belief', ''),
            'evidence_count': ev_count,
            'evidence': evidence or []
        }

        if ev_count >= 3:
            strong.append(entry)
        elif ev_count >= 1:
            moderate.append(entry)
        else:
            unsupported.append(entry)

    click.echo(f"\n=== Evidence Analysis: {title} ===\n")
    click.echo(f"Total doxai in walk: {len(walks)}")
    click.echo(f"Unique evidence sources: {len(evidence_sources)}")
    click.echo()

    # Summary stats
    click.echo("--- Strength Distribution ---")
    click.echo(f"  🟢 Strong (3+ sources):    {len(strong):3} ({100*len(strong)//len(walks) if walks else 0}%)")
    click.echo(f"  🟡 Moderate (1-2 sources): {len(moderate):3} ({100*len(moderate)//len(walks) if walks else 0}%)")
    click.echo(f"  🔴 Unsupported (0):        {len(unsupported):3} ({100*len(unsupported)//len(walks) if walks else 0}%)")
    if missing_doxai:
        click.echo(f"  ⚫ Missing from graph:     {len(missing_doxai):3}")
    click.echo()

    if not missing_only:
        if strong:
            click.echo("--- 🟢 Strong Evidence ---")
            for entry in strong:
                click.echo(f"\n  {entry['id']} ({entry['evidence_count']} sources)")
                belief_preview = entry['belief'][:50] + '...' if len(entry['belief']) > 50 else entry['belief']
                click.echo(f"    \"{belief_preview}\"")
                for ev in entry['evidence'][:3]:
                    if isinstance(ev, dict):
                        click.echo(f"    • {ev.get('source', 'unknown')}")

        if moderate:
            click.echo("\n--- 🟡 Moderate Evidence ---")
            for entry in moderate:
                click.echo(f"\n  {entry['id']} ({entry['evidence_count']} sources)")
                belief_preview = entry['belief'][:50] + '...' if len(entry['belief']) > 50 else entry['belief']
                click.echo(f"    \"{belief_preview}\"")
                for ev in entry['evidence']:
                    if isinstance(ev, dict):
                        click.echo(f"    • {ev.get('source', 'unknown')}")

    if unsupported:
        click.echo("\n--- 🔴 Needs Research ---")
        for entry in unsupported:
            click.echo(f"\n  {entry['id']}")
            click.echo(f"    \"{entry['belief']}\"")

    if missing_doxai:
        click.echo("\n--- ⚫ Missing Doxai ---")
        for d in missing_doxai:
            click.echo(f"  • {d}")

    # Research recommendations
    if unsupported:
        click.echo("\n--- Research Priorities ---")
        click.echo(f"\n{len(unsupported)} doxai need evidence. Consider:")
        for entry in unsupported[:5]:
            click.echo(f"\n  • {entry['id']}")
            click.echo(f"    Belief: \"{entry['belief'][:80]}...\"" if len(entry['belief']) > 80 else f"    Belief: \"{entry['belief']}\"")
            click.echo("    Research: Find empirical studies, expert quotes, or case studies")


def call_gemini(prompt: str, model: str = "gemini-2.5-pro") -> str:
    """Call gemini CLI with a prompt and return the response."""
    result = subprocess.run(
        ["gemini", "-m", model, prompt],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Gemini CLI error: {result.stderr}")
    return result.stdout.strip()


def get_existing_beliefs() -> list[dict]:
    """Load all existing doxai beliefs for comparison."""
    beliefs = []
    for f in DOXAI_DIR.glob("d-*.md"):
        try:
            post = frontmatter.load(f)
            belief = post.get("belief", "")
            if belief:
                beliefs.append({
                    "slug": f.stem,
                    "belief": belief,
                })
        except Exception:
            continue
    return beliefs


@cli.command()
@click.argument('candidate')
@click.option('--json', 'as_json', is_flag=True, help='Output as JSON')
def dedup(candidate: str, as_json: bool):
    """Check if a belief is semantically unique or duplicates an existing doxa.

    Uses Gemini to compare the candidate belief against all existing beliefs.

    Returns one of:
      UNIQUE - No semantic duplicate found
      DUPLICATE:<slug> - Semantically equivalent to existing doxa
      RELATED:<slug> - Different but closely related (consider linking)

    Examples:
      dox dedup "AI will transform software development"
      dox dedup "Machine learning is changing how we write code" --json
    """
    existing = get_existing_beliefs()

    if not existing:
        if as_json:
            click.echo(json.dumps({"result": "UNIQUE", "reason": "No existing doxai"}))
        else:
            click.echo("UNIQUE (no existing doxai to compare)")
        return

    # Build the comparison prompt
    beliefs_list = "\n".join(
        f"- {b['slug']}: \"{b['belief']}\""
        for b in existing
    )

    prompt = load_prompt("dedup", candidate=candidate, beliefs_list=beliefs_list)

    try:
        response = call_gemini(prompt)
        # Parse the response - get the last non-empty line (skip gemini startup messages)
        lines = [line.strip() for line in response.split('\n') if line.strip()]
        result_line = lines[-1] if lines else ""

        # Parse result
        parts = result_line.split('|')
        result_type = parts[0].upper() if parts else "ERROR"

        if as_json:
            output = {"result": result_type}
            if result_type == "UNIQUE":
                output["reason"] = parts[1] if len(parts) > 1 else ""
            elif result_type in ("DUPLICATE", "RELATED"):
                output["slug"] = parts[1] if len(parts) > 1 else ""
                output["reason"] = parts[2] if len(parts) > 2 else ""
            else:
                output["raw"] = result_line
            click.echo(json.dumps(output))
        else:
            if result_type == "UNIQUE":
                click.echo(f"UNIQUE: {parts[1] if len(parts) > 1 else 'No match found'}")
            elif result_type == "DUPLICATE":
                slug = parts[1] if len(parts) > 1 else "?"
                reason = parts[2] if len(parts) > 2 else ""
                click.echo(f"DUPLICATE: {slug}")
                if reason:
                    click.echo(f"  Reason: {reason}")
                click.echo(f"\n  Consider using existing doxa: dox show {slug}")
            elif result_type == "RELATED":
                slug = parts[1] if len(parts) > 1 else "?"
                reason = parts[2] if len(parts) > 2 else ""
                click.echo(f"RELATED: {slug}")
                if reason:
                    click.echo(f"  Reason: {reason}")
                click.echo(f"\n  Consider linking after creation: dox link <new> {slug} <type>")
            else:
                click.echo(f"Unexpected response: {result_line}", err=True)
                sys.exit(1)

    except subprocess.TimeoutExpired:
        click.echo("ERROR: Gemini request timed out", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.argument('phantasia_slug')
@click.option('--focus', help='Focus areas to emphasize during extraction')
@click.option('--instructions', help='Additional custom instructions')
@click.option('--dry-run', is_flag=True, help='Validate without writing files')
def extract(phantasia_slug: str, focus: str, instructions: str, dry_run: bool):
    """Extract doxai and evidence from a phantasia.

    Uses Gemini to analyze the source document and extract:
    - Atomic beliefs (doxai) with reasoning
    - Evidence artifacts with citations
    - Edges connecting to existing beliefs

    Includes automatic deduplication against existing doxai.

    Examples:
      dox extract p-my-source
      dox extract p-chat-thread --focus "AI economics"
      dox extract p-research-notes --dry-run
    """
    click.echo(f"Extracting from: {phantasia_slug}")
    if dry_run:
        click.echo("(dry run - no files will be written)")

    try:
        results = extract_from_phantasia(
            phantasia_slug,
            focus=focus,
            instructions=instructions,
            dry_run=dry_run,
        )

        # Report results
        if results['created_doxai']:
            click.echo(f"\nCreated {len(results['created_doxai'])} doxai:")
            for slug in results['created_doxai']:
                click.echo(f"  + {slug}")

        if results['created_evidence']:
            click.echo(f"\nCreated {len(results['created_evidence'])} evidence:")
            for slug in results['created_evidence']:
                click.echo(f"  + {slug}")

        if results['created_edges']:
            click.echo(f"\nCreated {len(results['created_edges'])} edges:")
            for edge in results['created_edges']:
                # Handle both ExtractedEdge objects (dry-run) and tuples (normal)
                if hasattr(edge, 'source'):
                    click.echo(f"  {edge.source} --[{edge.edge_type}]--> {edge.target}")
                else:
                    source, target, edge_type = edge[:3]
                    click.echo(f"  {source} --[{edge_type}]--> {target}")

        if results['skipped']:
            click.echo(f"\nSkipped {len(results['skipped'])} duplicates:")
            for dup in results['skipped']:
                click.echo(f"  ~ \"{dup.get('belief', '?')[:50]}...\"")
                click.echo(f"    matches: {dup.get('matches', '?')}")

        if results['suggested_links']:
            click.echo(f"\nSuggested {len(results['suggested_links'])} links (from related beliefs):")
            for source, target, edge_type in results['suggested_links']:
                click.echo(f"  {source} --[{edge_type}]--> {target}")

        if results['errors']:
            click.echo(f"\nErrors ({len(results['errors'])}):", err=True)
            for error in results['errors']:
                click.echo(f"  ! {error}", err=True)

        # Summary
        total_created = len(results['created_doxai']) + len(results['created_evidence'])
        if total_created > 0:
            click.echo(f"\nDone! Created {total_created} artifact(s).")
        else:
            click.echo("\nNo new artifacts created.")

    except FileNotFoundError as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"ERROR: Extraction failed: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option('--focus', help='Focus area (e.g., "tensions", "AI economics")')
@click.option('--apply', 'apply_edges', is_flag=True, help='Automatically add proposed edges')
@click.option('--batch', is_flag=True, help='Batch by graph clusters for deeper coverage')
@click.option('--recent', type=int, default=None, help='Select N clusters with most recent doxai (implies --batch)')
def integrate(focus: str, apply_edges: bool, batch: bool, recent: int):
    """Run deep integration pass on the doxai library.

    Analyzes the complete belief graph to find:
    - Missing relationships between beliefs
    - Tensions and contradictions
    - Evidence gaps
    - Potential narrative clusters (diegeses)

    Uses Gemini with full library context (1M tokens).

    With --batch, partitions the graph into communities and runs a separate
    integration pass on each cluster, then a cross-cluster pass for bridging
    edges. Produces significantly more edge proposals.

    With --recent N, selects the N clusters containing the most recently-added
    doxai and runs batched integration on just those.

    Examples:
      dox integrate                    # Full analysis (single pass)
      dox integrate --batch            # Batched by cluster (deeper)
      dox integrate --batch --apply    # Batched + auto-apply
      dox integrate --recent 3 --apply # 3 newest clusters + auto-apply
      dox integrate --focus tensions   # Focus on contradictions
    """
    if recent:
        click.echo(f"Running batched integration on {recent} most recent clusters...")
    elif batch:
        click.echo("Running batched integration pass...")
    else:
        click.echo("Running deep integration pass...")
    if focus:
        click.echo(f"Focus: {focus}")

    def progress(msg):
        click.echo(msg)

    try:
        result = run_integration(
            focus=focus,
            apply_edges=apply_edges,
            batch=batch,
            recent=recent,
            progress_callback=progress,
        )

        # Report proposed edges
        if result.proposed_edges:
            click.echo(f"\n=== Proposed Edges ({len(result.proposed_edges)}) ===")
            for edge in result.proposed_edges:
                click.echo(f"\n  {edge.source} --[{edge.edge_type}]--> {edge.target}")
                click.echo(f"  Strength: {edge.strength}")
                if edge.annotation:
                    # Truncate annotation for display
                    annotation = edge.annotation[:100] + "..." if len(edge.annotation) > 100 else edge.annotation
                    click.echo(f"  {annotation}")

            if apply_edges:
                click.echo("\n  (Edges applied to logos.yaml)")
            else:
                click.echo("\n  Run with --apply to add these edges")

        # Report tensions
        if result.tensions:
            click.echo(f"\n=== Tensions ({len(result.tensions)}) ===")
            for tension in result.tensions:
                beliefs = ", ".join(tension.beliefs)
                click.echo(f"\n  [{tension.severity.upper()}] {beliefs}")
                if tension.description:
                    desc = tension.description[:150] + "..." if len(tension.description) > 150 else tension.description
                    click.echo(f"  {desc}")
                if tension.resolution_options:
                    click.echo("  Possible resolutions:")
                    for opt in tension.resolution_options[:2]:
                        click.echo(f"    - {opt}")

        # Report evidence gaps
        if result.gaps:
            click.echo(f"\n=== Evidence Gaps ({len(result.gaps)}) ===")
            for gap in result.gaps:
                click.echo(f"\n  {gap.belief} ({gap.gap_type})")
                if gap.description:
                    desc = gap.description[:100] + "..." if len(gap.description) > 100 else gap.description
                    click.echo(f"  {desc}")

        # Report cluster opportunities
        if result.clusters:
            click.echo(f"\n=== Cluster Opportunities ({len(result.clusters)}) ===")
            for cluster in result.clusters:
                click.echo(f"\n  \"{cluster.name}\"")
                click.echo(f"  Beliefs: {', '.join(cluster.beliefs[:5])}")
                if len(cluster.beliefs) > 5:
                    click.echo(f"           ... and {len(cluster.beliefs) - 5} more")

        # Report errors
        if result.errors:
            click.echo("\n=== Notes ===")
            for error in result.errors:
                click.echo(f"  {error}")

        # Summary
        total_findings = (
            len(result.proposed_edges) +
            len(result.tensions) +
            len(result.gaps) +
            len(result.clusters)
        )
        click.echo("\n=== Summary ===")
        click.echo(f"  Proposed edges: {len(result.proposed_edges)}")
        click.echo(f"  Tensions: {len(result.tensions)}")
        click.echo(f"  Evidence gaps: {len(result.gaps)}")
        click.echo(f"  Cluster opportunities: {len(result.clusters)}")

        if total_findings == 0:
            click.echo("\nNo findings. The graph appears well-integrated.")

    except Exception as e:
        click.echo(f"ERROR: Integration failed: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option('--apply', 'apply_corrections', is_flag=True, help='Apply corrections to logos.yaml')
@click.option('--model', default='gemini-2.5-pro', help='Gemini model to use (default: gemini-2.5-pro)')
def audit(apply_corrections: bool, model: str):
    """Audit all edges for correct typing and rationales.

    Uses Gemini with full belief context to evaluate every edge in the graph.
    For each edge, the audit will:
    - CONFIRM the type is correct, or CORRECT it to the right type
    - Provide a rationale explaining WHY the relationship exists
    - Assign a confidence level (high/medium/low)

    This is especially useful for:
    - Reviewing edges created by extraction passes
    - Ensuring 'contradicts' edges are truly contradictions (not resolutions)
    - Hydrating edges with substantive rationales

    Examples:
      dox audit                    # Review all edges (no changes)
      dox audit --apply            # Apply corrections to logos.yaml
      dox audit --model gemini-2.0-flash  # Use different model
    """
    click.echo("Running edge audit pass...")
    click.echo(f"Model: {model}")
    if apply_corrections:
        click.echo("(will apply corrections)")

    try:
        result = run_audit(apply=apply_corrections, model=model)

        # Report results
        if result.errors:
            for error in result.errors:
                click.echo(f"  ! {error}", err=True)
            if not result.audits:
                sys.exit(1)

        if not result.audits:
            click.echo("\nNo edges audited.")
            return

        # Summary counts
        click.echo("\n=== Audit Results ===")
        click.echo(f"Total audited: {len(result.audits)}")
        click.echo(f"Confirmed: {result.confirmed}")
        click.echo(f"Corrections: {result.corrected}")

        # Show corrections
        corrections = [a for a in result.audits if a.verdict == 'CORRECT']
        if corrections:
            click.echo(f"\n=== Corrections ({len(corrections)}) ===")
            for audit in corrections:
                click.echo(f"\n  {audit.source} → {audit.target}")
                click.echo(f"  {audit.current_type} → {audit.correct_type}")
                if audit.alias:
                    click.echo(f"  Alias: \"{audit.alias}\"")
                click.echo(f"  Confidence: {audit.confidence}")
                if audit.rationale:
                    rationale = audit.rationale[:150] + "..." if len(audit.rationale) > 150 else audit.rationale
                    click.echo(f"  Rationale: {rationale}")
                if audit.flags:
                    click.echo(f"  Flags: {', '.join(audit.flags)}")

            if not apply_corrections:
                click.echo("\n  Run with --apply to apply these corrections")

        # Show sample confirmations
        confirmations = [a for a in result.audits if a.verdict == 'CONFIRM']
        if confirmations:
            click.echo(f"\n=== Sample Confirmations (showing 5/{len(confirmations)}) ===")
            for audit in confirmations[:5]:
                click.echo(f"\n  {audit.source} → {audit.target} [{audit.current_type}]")
                if audit.alias:
                    click.echo(f"  Alias: \"{audit.alias}\"")
                click.echo(f"  Confidence: {audit.confidence}")
                if audit.rationale:
                    rationale = audit.rationale[:100] + "..." if len(audit.rationale) > 100 else audit.rationale
                    click.echo(f"  Rationale: {rationale}")

        # Final summary
        if apply_corrections and corrections:
            click.echo(f"\n✓ Applied {len(corrections)} correction(s) to logos.yaml")
        elif corrections:
            click.echo(f"\n⚠ {len(corrections)} correction(s) pending. Use --apply to fix.")
        else:
            click.echo(f"\n✓ All {len(confirmations)} edges confirmed correct.")

    except Exception as e:
        click.echo(f"ERROR: Audit failed: {e}", err=True)
        sys.exit(1)


# =============================================================================
# EXPORT COMMANDS
# =============================================================================


@cli.group()
def export():
    """Export doxagon content in various formats.

    Three export modes:
    - platform: Share framework without personal content
    - library: Full backup/migration
    - subgraph: Share specific arguments

    Examples:
      dox export platform -o doxagon-starter.zip
      dox export library --format yaml -o backup.yaml
      dox export subgraph -d n-observatory -w canonical
    """
    pass


@export.command('platform')
@click.option('--output', '-o', default='doxagon-platform.zip',
              help='Output file path (default: doxagon-platform.zip)')
@click.option('--include-skills/--no-skills', default=True,
              help='Include .pi/agent/skills/ directory')
@click.option('--include-docs/--no-docs', default=True,
              help='Include docs/ directory')
def export_platform_cmd(output: str, include_skills: bool, include_docs: bool):
    """Export framework as starter kit (no personal content).

    Creates a clean export of the Doxagon framework suitable for
    sharing or setting up new instances. Excludes all personal
    doxai, evidence, and diegeses.

    Examples:
      dox export platform
      dox export platform -o ~/Downloads/doxagon.zip
      dox export platform --no-skills
    """
    from doxagon.export import export_platform

    output_path = Path(output).resolve()
    click.echo(f"Exporting platform to: {output_path}")

    try:
        result = export_platform(
            output_path,
            include_skills=include_skills,
            include_docs=include_docs,
        )
        click.echo("\n✓ Platform export complete")
        click.echo(f"  Files: {result['files']}")
        click.echo(f"  Output: {output_path}")
    except Exception as e:
        click.echo(f"ERROR: Export failed: {e}", err=True)
        sys.exit(1)


@export.command('library')
@click.option('--output', '-o',
              help='Output file path (auto-generated if not specified)')
@click.option('--format', '-f', 'fmt',
              type=click.Choice(['zip', 'yaml', 'json']), default='zip',
              help='Export format (default: zip)')
@click.option('--include-inbox', is_flag=True,
              help='Include inbox items')
def export_library_cmd(output: str, fmt: str, include_inbox: bool):
    """Export complete knowledge graph for backup.

    Creates a full export of all doxai, evidence, diegeses, and edges.
    Useful for backups, migration, or sharing complete knowledge bases.

    Examples:
      dox export library
      dox export library --format yaml -o backup.yaml
      dox export library --include-inbox
    """
    from doxagon.export import export_full_library

    # Generate default output path
    if not output:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        ext = fmt if fmt != 'zip' else 'zip'
        output = f"doxagon-library-{timestamp}.{ext}"

    output_path = Path(output).resolve()
    click.echo(f"Exporting library to: {output_path}")
    click.echo(f"Format: {fmt}")

    try:
        result = export_full_library(
            output_path,
            format=fmt,
            include_inbox=include_inbox,
        )
        click.echo("\n✓ Library export complete")
        click.echo(f"  Doxai: {result['doxai']}")
        click.echo(f"  Evidence: {result['evidence']}")
        click.echo(f"  Diegeses: {result['diegeses']}")
        click.echo(f"  Edges: {result['edges']}")
        click.echo(f"  Output: {output_path}")
    except Exception as e:
        click.echo(f"ERROR: Export failed: {e}", err=True)
        sys.exit(1)


@export.command('subgraph')
@click.option('--diegesis', '-d',
              help='Export by diegesis (e.g., n-observatory)')
@click.option('--walk', '-w',
              help='Specific walk within diegesis')
@click.option('--root', '-r',
              help='Export neighborhood from root doxa')
@click.option('--hops', '-n', type=int, default=2,
              help='Hop distance for neighborhood (default: 2)')
@click.option('--tag', '-t', multiple=True,
              help='Export doxai matching tags (can specify multiple)')
@click.option('--include-evidence/--no-evidence', default=True,
              help='Include referenced evidence')
@click.option('--include-diegeses/--no-diegeses', default=True,
              help='Include containing diegeses')
@click.option('--format', '-f', 'fmt',
              type=click.Choice(['zip', 'yaml', 'json']), default='zip',
              help='Export format (default: zip)')
@click.option('--output', '-o',
              help='Output file path (auto-generated if not specified)')
def export_subgraph_cmd(
    diegesis: str,
    walk: str,
    root: str,
    hops: int,
    tag: tuple,
    include_evidence: bool,
    include_diegeses: bool,
    fmt: str,
    output: str,
):
    """Export specific portion of knowledge graph.

    Supports three selection modes:
    - Diegesis: Export all doxai in a narrative structure
    - Neighborhood: Export doxai within N hops of a root
    - Tags: Export doxai matching specific tags

    Examples:
      dox export subgraph -d n-observatory -w canonical
      dox export subgraph -r d-observe-stars --hops 3
      dox export subgraph -t domain:astronomy -t domain:observation
      dox export subgraph -d n-observatory --no-evidence --format json
    """
    from doxagon.export import export_subgraph

    # Validate selection mode
    modes_specified = sum([bool(diegesis), bool(root), bool(tag)])
    if modes_specified == 0:
        click.echo("ERROR: Must specify --diegesis, --root, or --tag", err=True)
        sys.exit(1)
    if modes_specified > 1:
        click.echo("ERROR: Specify only one of --diegesis, --root, or --tag", err=True)
        sys.exit(1)

    # Generate default output path
    if not output:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if diegesis:
            slug = diegesis.removeprefix("n-")
            name = f"{slug}-{walk}" if walk else slug
        elif root:
            name = root.removeprefix("d-")
        else:
            name = "tags"
        ext = fmt if fmt != 'zip' else 'zip'
        output = f"doxagon-subgraph-{name}-{timestamp}.{ext}"

    output_path = Path(output).resolve()

    # Report what we're doing
    if diegesis:
        mode_desc = f"diegesis: {diegesis}"
        if walk:
            mode_desc += f" (walk: {walk})"
    elif root:
        mode_desc = f"neighborhood: {root} (hops: {hops})"
    else:
        mode_desc = f"tags: {', '.join(tag)}"

    click.echo("Exporting subgraph")
    click.echo(f"  Mode: {mode_desc}")
    click.echo(f"  Format: {fmt}")
    click.echo(f"  Output: {output_path}")

    try:
        result = export_subgraph(
            output_path,
            format=fmt,
            diegesis=diegesis,
            walk=walk,
            root=root,
            hops=hops,
            tags=list(tag) if tag else None,
            include_evidence=include_evidence,
            include_diegeses=include_diegeses,
        )
        click.echo("\n✓ Subgraph export complete")
        click.echo(f"  Doxai: {result['doxai']}")
        click.echo(f"  Evidence: {result['evidence']}")
        click.echo(f"  Diegeses: {result['diegeses']}")
        click.echo(f"  Edges: {result['edges']}")
    except ValueError as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"ERROR: Export failed: {e}", err=True)
        sys.exit(1)


@export.command('presentation')
@click.argument('name')
@click.option('--output', '-o',
              help='Output file path (auto-generated if not specified)')
@click.option('--all-outputs', is_flag=True, default=False,
              help='Include all generated images, not just selected')
@click.option('--no-sources', is_flag=True, default=False,
              help='Exclude image source/reference files')
@click.option('--no-styles', is_flag=True, default=False,
              help='Exclude style definitions')
@click.option('--hops', '-n', type=int, default=1,
              help='Doxai neighborhood expansion hops (default: 1)')
def export_presentation_cmd(
    name: str,
    output: str,
    all_outputs: bool,
    no_sources: bool,
    no_styles: bool,
    hops: int,
):
    """Export presentation with associated doxai subgraph.

    Bundles slide content, images, styles, and the knowledge graph
    nodes referenced by slides.

    Examples:
      dox export presentation observatory
      dox export presentation observatory --all-outputs
      dox export presentation observatory --hops 2 -o backup.zip
      dox export presentation observatory --no-sources --no-styles
    """
    from doxagon.export import export_presentation

    # Generate default output path
    if not output:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output = f"presentation-{name}-{timestamp}.zip"

    output_path = Path(output).resolve()

    click.echo(f"Exporting presentation: {name}")
    click.echo(f"  Output: {output_path}")
    click.echo(f"  All outputs: {all_outputs}")
    click.echo(f"  Sources: {not no_sources}")
    click.echo(f"  Styles: {not no_styles}")
    click.echo(f"  Doxai hops: {hops}")

    try:
        result = export_presentation(
            presentation_name=name,
            output_path=output_path,
            include_all_outputs=all_outputs,
            include_sources=not no_sources,
            include_styles=not no_styles,
            hops=hops,
        )
        click.echo("\n✓ Presentation export complete")
        click.echo(f"  Slides: {result['slides']}")
        click.echo(f"  Doxai: {result['doxai']}")
        click.echo(f"  Evidence: {result['evidence']}")
        click.echo(f"  Edges: {result['edges']}")
        click.echo(f"\n  File: {output_path}")
    except ValueError as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"ERROR: Export failed: {e}", err=True)
        sys.exit(1)


# =============================================================================
# IMPORT COMMANDS
# =============================================================================


@cli.group('import')
def import_group():
    """Import doxagon content from export files.

    Two import modes:
    - subgraph: Merge a subgraph export (default: skip conflicts)
    - library: Restore from full backup (default: overwrite conflicts)

    Examples:
      dox import subgraph export.zip
      dox import subgraph export.yaml --strategy overwrite
      dox import library backup.zip --dry-run
    """
    pass


@import_group.command('subgraph')
@click.argument('file', type=click.Path(exists=True))
@click.option('--strategy', '-s',
              type=click.Choice(['skip', 'overwrite', 'newer']), default='skip',
              help='Conflict resolution strategy (default: skip)')
@click.option('--dry-run', is_flag=True, default=False,
              help='Preview what would happen without writing')
@click.option('--no-validate', is_flag=True, default=False,
              help='Skip validation warnings')
def import_subgraph_cmd(file: str, strategy: str, dry_run: bool, no_validate: bool):
    """Import a subgraph or general export.

    Default strategy is 'skip' — only adds new entities, keeps existing
    ones unchanged. Use 'overwrite' to replace conflicts with incoming
    content, or 'newer' to keep whichever has a later updated date.

    Examples:
      dox import subgraph export.zip
      dox import subgraph export.yaml --strategy overwrite
      dox import subgraph data.json --dry-run
    """
    from doxagon.intake import import_subgraph

    file_path = Path(file).resolve()

    if dry_run:
        click.echo("DRY RUN — no files will be written\n")

    click.echo(f"Importing subgraph from: {file_path}")
    click.echo(f"Strategy: {strategy}")

    try:
        result, warnings = import_subgraph(
            file_path,
            strategy=strategy,
            dry_run=dry_run,
            validate=not no_validate,
        )

        if warnings:
            click.echo(f"\n⚠ {len(warnings)} validation warning(s):", err=True)
            for w in warnings:
                click.echo(f"  - {w}", err=True)

        _print_import_result(result, dry_run)

    except ValueError as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"ERROR: Import failed: {e}", err=True)
        sys.exit(1)


@import_group.command('library')
@click.argument('file', type=click.Path(exists=True))
@click.option('--strategy', '-s',
              type=click.Choice(['skip', 'overwrite', 'newer']), default='overwrite',
              help='Conflict resolution strategy (default: overwrite)')
@click.option('--dry-run', is_flag=True, default=False,
              help='Preview what would happen without writing')
@click.option('--no-validate', is_flag=True, default=False,
              help='Skip validation warnings')
def import_library_cmd(file: str, strategy: str, dry_run: bool, no_validate: bool):
    """Import a full library backup.

    Default strategy is 'overwrite' — restores all content from the
    backup, replacing any local conflicts. Use 'skip' to only add
    missing entities without touching existing ones.

    Examples:
      dox import library backup.zip
      dox import library backup.yaml --strategy skip
      dox import library backup.json --dry-run
    """
    from doxagon.intake import import_library

    file_path = Path(file).resolve()

    if dry_run:
        click.echo("DRY RUN — no files will be written\n")

    click.echo(f"Importing library from: {file_path}")
    click.echo(f"Strategy: {strategy}")

    try:
        result, warnings = import_library(
            file_path,
            strategy=strategy,
            dry_run=dry_run,
            validate=not no_validate,
        )

        if warnings:
            click.echo(f"\n⚠ {len(warnings)} validation warning(s):", err=True)
            for w in warnings:
                click.echo(f"  - {w}", err=True)

        _print_import_result(result, dry_run)

    except ValueError as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"ERROR: Import failed: {e}", err=True)
        sys.exit(1)


def _print_import_result(result, dry_run: bool):
    """Format and print import results."""
    prefix = "Would create" if dry_run else "Created"
    click.echo(f"\n{'✓ Import preview' if dry_run else '✓ Import complete'}")

    total_created = sum(result.created.values())
    total_updated = sum(result.updated.values())
    total_skipped = sum(result.skipped.values())

    if total_created:
        click.echo(f"\n  {prefix}:")
        for key, count in result.created.items():
            if count:
                click.echo(f"    {key}: {count}")

    if total_updated:
        label = "Would update" if dry_run else "Updated"
        click.echo(f"\n  {label}:")
        for key, count in result.updated.items():
            if count:
                click.echo(f"    {key}: {count}")

    if total_skipped:
        click.echo("\n  Skipped (conflicts):")
        for key, count in result.skipped.items():
            if count:
                click.echo(f"    {key}: {count}")

    if not total_created and not total_updated and not total_skipped:
        click.echo("  Nothing to import — all content already exists.")

    if result.errors:
        click.echo(f"\n  ✗ {len(result.errors)} error(s):")
        for e in result.errors:
            click.echo(f"    - {e}")


if __name__ == '__main__':
    cli()
