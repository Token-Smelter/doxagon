"""Shared Click handlers for the headless HTML Edition CLI."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import stat
from pathlib import Path
from types import MappingProxyType

import click

from doxagon.workspace import Capability, Ready, WorkspaceOpenRequest, open_workspace

from .compiler import HtmlEditionCompiler
from .contracts import load_content_document_from_fd
from .errors import HtmlEditionError
from .inspector import inspect_edition, inspect_edition_bytes


def _request(vault: Path | None, workspace: str | None, read_only: bool | None) -> WorkspaceOpenRequest:
    return WorkspaceOpenRequest(
        cli_workspace=workspace,
        cli_vault=vault,
        cli_state=None,
        cli_artifacts=None,
        cli_config=None,
        cli_read_only=read_only,
        cli_mode=None,
        environ=MappingProxyType(dict(os.environ)),
        # HTML Edition paths must be explicit absolute selections; this package
        # deliberately does not discover the checkout or process cwd.
        invocation_cwd=Path("/"),
        standard_config_path=Path.home() / ".config" / "doxagon" / "config.toml",
    )


def _ready(vault: Path | None, workspace: str | None, read_only: bool | None, required: set[Capability]) -> Ready:
    result = open_workspace(_request(vault, workspace, read_only))
    if not isinstance(result, Ready):
        code = {
            "not_configured": "HTML_EDITION_NOT_CONFIGURED",
            "metadata_only": "HTML_EDITION_METADATA_ONLY",
            "schema_diagnostic": "HTML_EDITION_SCHEMA_DIAGNOSTIC",
            "recovery_diagnostic": "HTML_EDITION_RECOVERY_PENDING",
        }[result.state]
        raise HtmlEditionError(code, code)
    if not required.issubset(result.config.capabilities):
        result.services.close()
        if result.config.access_mode == "read-only":
            raise HtmlEditionError("HTML_EDITION_READ_ONLY", "HTML_EDITION_READ_ONLY")
        raise HtmlEditionError("HTML_EDITION_CAPABILITY_DENIED", "HTML_EDITION_CAPABILITY_DENIED")
    return result


_DOCUMENT_NAMES = ("document.yaml", "document.yml", "document.json")


@dataclass
class _DocumentLocation:
    """Retained source descriptors rooted beneath the configured projects root."""

    root_fd: int
    source_fd: int
    source_suffix: str

    def close(self) -> None:
        os.close(self.source_fd)
        os.close(self.root_fd)


def _document_location(document_path: Path, ready: Ready) -> _DocumentLocation:
    document_path = Path(os.path.abspath(document_path))
    projects_root = Path(os.path.abspath(ready.config.projects_root))
    source_name = document_path.name if document_path.name in _DOCUMENT_NAMES else None
    document_root = document_path.parent if source_name else document_path
    try:
        relative_root = document_root.relative_to(projects_root)
    except ValueError as error:
        raise HtmlEditionError("HTML_EDITION_SOURCE_CONTAINMENT", "document is outside the configured project root") from error
    if len(relative_root.parts) < 3 or relative_root.parts[-3:-1] != ("outputs", "content-documents"):
        raise HtmlEditionError("HTML_EDITION_SOURCE_CONTAINMENT", "document is not in the Content Document source root")

    root_fd: int | None = None
    source_fd: int | None = None
    try:
        root_fd = os.open(projects_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        for component in relative_root.parts:
            child_fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
            os.close(root_fd)
            root_fd = child_fd
        names = (source_name,) if source_name else _DOCUMENT_NAMES
        for name in names:
            try:
                source_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=root_fd)
            except FileNotFoundError:
                continue
            source_stat = os.fstat(source_fd)
            if not stat.S_ISREG(source_stat.st_mode) or source_stat.st_nlink != 1:
                os.close(source_fd)
                source_fd = None
                continue
            location = _DocumentLocation(root_fd, source_fd, Path(name).suffix.lower())
            root_fd = None
            source_fd = None
            return location
        raise HtmlEditionError("HTML_EDITION_SCHEMA_DIAGNOSTIC", "document must be a private regular document file")
    except HtmlEditionError:
        raise
    except OSError as error:
        raise HtmlEditionError("HTML_EDITION_SOURCE_CONTAINMENT", "document is unavailable or not contained") from error
    finally:
        if source_fd is not None:
            os.close(source_fd)
        if root_fd is not None:
            os.close(root_fd)


def _safe_output(output: Path, ready: Ready, *, force: bool) -> Path:
    if not output.is_absolute():
        raise HtmlEditionError("HTML_EDITION_OUTPUT_UNSAFE", "output must be an absolute path")
    destination = Path(os.path.normpath(output))
    if destination.suffix.lower() != ".html" or destination.name != "edition.html":
        raise HtmlEditionError("HTML_EDITION_OUTPUT_UNSAFE", "output must be named edition.html")
    try:
        destination.parent.resolve(strict=False).relative_to(ready.config.projects_root.resolve())
    except ValueError:
        return destination
    raise HtmlEditionError("HTML_EDITION_OUTPUT_UNSAFE", "output cannot be inside project source")


def _open_output_parent(destination: Path) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        directory_fd = os.open(destination.anchor, flags)
        for component in destination.parent.relative_to(destination.anchor).parts:
            try:
                child_fd = os.open(component, flags, dir_fd=directory_fd)
            except FileNotFoundError:
                os.mkdir(component, 0o755, dir_fd=directory_fd)
                child_fd = os.open(component, flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = child_fd
        return directory_fd
    except OSError as error:
        raise HtmlEditionError("HTML_EDITION_OUTPUT_UNSAFE", "output parent could not be safely opened") from error


def _write_output(destination: Path, data: bytes, *, force: bool) -> None:
    directory_fd: int | None = None
    fd: int | None = None
    try:
        directory_fd = _open_output_parent(destination)
        try:
            existing = os.stat(destination.name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            existing = None
        if existing is not None:
            if not force or not stat.S_ISREG(existing.st_mode) or existing.st_nlink != 1:
                raise HtmlEditionError("HTML_EDITION_OUTPUT_UNSAFE", "output already exists or is not a private regular file")
            fd = os.open(destination.name, os.O_WRONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
            opened = os.fstat(fd)
            if (opened.st_dev, opened.st_ino, opened.st_mode, opened.st_nlink) != (existing.st_dev, existing.st_ino, existing.st_mode, existing.st_nlink):
                raise HtmlEditionError("HTML_EDITION_OUTPUT_UNSAFE", "output changed while opening")
            os.ftruncate(fd, 0)
        else:
            fd = os.open(destination.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=directory_fd)
            opened = os.fstat(fd)
            if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
                raise HtmlEditionError("HTML_EDITION_OUTPUT_UNSAFE", "output is not a private regular file")
        offset = 0
        while offset < len(data):
            offset += os.write(fd, data[offset:])
        os.fsync(fd)
    except HtmlEditionError:
        raise
    except OSError as error:
        raise HtmlEditionError("HTML_EDITION_OUTPUT_UNSAFE", "output could not be safely written") from error
    finally:
        if fd is not None:
            os.close(fd)
        if directory_fd is not None:
            os.close(directory_fd)


@click.group("html-edition")
def html_edition_group() -> None:
    """Validate, build, and inspect offline HTML Editions."""


@html_edition_group.command("validate")
@click.option("--vault", type=click.Path(path_type=Path), required=True)
@click.option("--workspace")
@click.option("--document", type=click.Path(path_type=Path), required=True)
def validate_command(vault: Path, workspace: str | None, document: Path) -> None:
    """Resolve and validate a Content Document without writing an artifact."""
    ready: Ready | None = None
    try:
        ready = _ready(vault, workspace, True, {Capability.WORKSPACE_READ, Capability.CONTENT_READ, Capability.ASSET_READ})
        location = _document_location(document, ready)
        try:
            result = HtmlEditionCompiler().compile(load_content_document_from_fd(location.source_fd, location.source_suffix), location.root_fd)
        finally:
            location.close()
        inspect_edition_bytes(result.html)
        click.echo(json.dumps({"authoring_revision": result.authoring_revision, "compile_input_hash": result.compile_input_hash}, sort_keys=True))
    except HtmlEditionError as error:
        raise click.ClickException(f"{error.code}: {error}") from error
    finally:
        if ready is not None:
            ready.services.close()


@html_edition_group.command("build")
@click.option("--vault", type=click.Path(path_type=Path), required=True)
@click.option("--workspace")
@click.option("--document", type=click.Path(path_type=Path), required=True)
@click.option("--output", type=click.Path(path_type=Path), required=True)
@click.option("--force", is_flag=True)
def build_command(vault: Path, workspace: str | None, document: Path, output: Path, force: bool) -> None:
    """Compile exactly one inspected offline HTML file."""
    ready: Ready | None = None
    try:
        needed = {Capability.WORKSPACE_READ, Capability.CONTENT_READ, Capability.ASSET_READ, Capability.PUBLICATION_BUILD, Capability.JOB_RUN, Capability.ARTIFACT_PROMOTE}
        ready = _ready(vault, workspace, None, needed)
        location = _document_location(document, ready)
        try:
            destination = _safe_output(output, ready, force=force)
            result = HtmlEditionCompiler().compile(load_content_document_from_fd(location.source_fd, location.source_suffix), location.root_fd)
        finally:
            location.close()
        report = inspect_edition_bytes(result.html)
        _write_output(destination, result.html, force=force)
        click.echo(json.dumps({"edition_id": report.edition_id, "compile_input_hash": report.compile_input_hash, "file_sha256": report.file_sha256}, sort_keys=True))
    except HtmlEditionError as error:
        raise click.ClickException(f"{error.code}: {error}") from error
    finally:
        if ready is not None:
            ready.services.close()


@html_edition_group.command("inspect")
@click.argument("edition", type=click.Path(path_type=Path))
def inspect_command(edition: Path) -> None:
    """Inspect one standalone Edition without opening a workspace."""
    try:
        report = inspect_edition(edition)
        click.echo(json.dumps({"edition_id": report.edition_id, "compile_input_hash": report.compile_input_hash, "file_sha256": report.file_sha256, "sections": list(report.section_ids)}, sort_keys=True))
    except HtmlEditionError as error:
        raise click.ClickException(f"{error.code}: {error}") from error
