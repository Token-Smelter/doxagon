"""Read-only artifact inspection for skill-backed authoring agents."""

import json
import os
from pathlib import Path

import click

from .inspection import HtmlInspectionError, inspect_html_file


def _store(slug: str):
    from doxagon.presentations.vault import open_or_migrate

    root = os.environ.get("DOXAGON_ROOT")
    if not root:
        click.echo(json.dumps({"status": "refused", "code": "DOXAGON_ROOT_UNSET",
                               "message": "set DOXAGON_ROOT to the vault; no vault is guessed"}), err=True)
        raise click.exceptions.Exit(2)
    return open_or_migrate(Path(root), slug).store


def _refuse(error) -> None:
    click.echo(json.dumps({"status": "refused", "code": error.code, "message": str(error),
                           "diagnostics": [item.as_dict() for item in getattr(error, "diagnostics", ())]}, sort_keys=True))
    raise click.exceptions.Exit(1)


@click.group("rendering")
def rendering_group() -> None:
    """Inspect communication source without admitting or publishing it."""


@rendering_group.command("inspect-html")
@click.argument("source", type=click.Path(path_type=Path))
@click.option("--json", "as_json", is_flag=True, help="Emit a deterministic private intake report.")
def inspect_html(source: Path, as_json: bool) -> None:
    """Inventory SOURCE without executing scripts or reading dependencies.

    Exit zero means inspection completed, not that the artifact is safe,
    epistemically assessed, admitted to a vault, or approved for publication.
    """

    try:
        report = inspect_html_file(source)
    except HtmlInspectionError as error:
        if as_json:
            click.echo(json.dumps({"status": "refused", "code": error.code, "message": str(error)}, sort_keys=True))
            raise click.exceptions.Exit(1)
        raise click.ClickException(f"{error.code}: {error}") from error
    if as_json:
        click.echo(json.dumps(report, sort_keys=True, indent=2))
        return
    click.echo(f"Inspected: {report['title'] or '(untitled source)'}")
    click.echo(f"SHA-256: {report['source']['sha256']} ({report['source']['bytes']} bytes)")
    click.echo(f"{len(report['sections'])} section candidates; {len(report['cue_candidates'])} cue candidates")
    click.echo(f"{len(report['blocks'])} script/style blocks; {len(report['references'])} literal references")
    for finding in report["findings"]:
        click.echo(f"Line {finding['line']}: {finding['code']} — {finding['message']}")
    click.echo("Not admitted or assessed. No scripts executed, dependencies read, network used, or vault changed.")


@rendering_group.command("plan")
@click.option("--presentation", required=True, help="Vault presentation slug.")
@click.option("--change", "change_path", required=True, type=click.Path(path_type=Path), help="Change file (JSON).")
def plan(presentation: str, change_path: Path) -> None:
    """Validate a document change against HEAD without promoting it."""

    from doxagon.presentations.changes import plan_document_change, read_change_file
    from doxagon.presentations.errors import WorkspaceError

    try:
        result = plan_document_change(_store(presentation), read_change_file(change_path))
    except WorkspaceError as error:
        _refuse(error)
    click.echo(json.dumps(result, sort_keys=True, indent=2))
    if not result["ok"]:
        raise click.exceptions.Exit(1)


@rendering_group.command("apply")
@click.option("--presentation", required=True, help="Vault presentation slug.")
@click.option("--change", "change_path", required=True, type=click.Path(path_type=Path), help="Change file (JSON).")
def apply(presentation: str, change_path: Path) -> None:
    """Land one whole document change as one new revision, or refuse it whole."""

    from doxagon.presentations.changes import apply_document_change, read_change_file
    from doxagon.presentations.errors import WorkspaceError

    try:
        outcome = apply_document_change(_store(presentation), read_change_file(change_path))
    except WorkspaceError as error:
        _refuse(error)
    click.echo(json.dumps({"status": "promoted", **outcome.as_dict()}, sort_keys=True, indent=2))
