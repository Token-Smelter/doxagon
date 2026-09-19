"""Explicit, read-only project resolution for authored-document tools.

Unlike the legacy config module, these operations never infer a vault from the
platform installation. Canonical paths also make the UI's `theses` alias and an
agent's `projects` path identify the same input.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
from typing import Mapping


class DocumentWorkspaceError(ValueError):
    def __init__(self, code: str, message: str, *, status: int = 422):
        super().__init__(message)
        self.code = code
        self.status = status

    def as_dict(self) -> dict:
        return {"code": self.code, "message": str(self)}


def _vault_candidate(path: Path) -> bool:
    projects = path / "projects"
    knowledge = path / "knowledge"
    legacy = path / "library"
    if not projects.is_dir() or not projects.resolve().is_relative_to(path):
        return False
    if knowledge.is_dir() and knowledge.resolve().is_relative_to(path):
        return True
    # A legacy alias may point to a differently named, contained corpus. Never
    # follow an outside-vault link just to make discovery succeed.
    return legacy.is_dir() and legacy.resolve().is_relative_to(path)


def _ancestor_vault(cwd: Path) -> Path | None:
    return next((path for path in (cwd, *cwd.parents) if _vault_candidate(path)), None)


def resolve_vault_root(
    *, cwd: Path | None = None, environ: Mapping[str, str] | None = None,
) -> Path:
    current = (cwd or Path.cwd()).expanduser().resolve()
    environment = os.environ if environ is None else environ
    configured = environment.get("DOXAGON_ROOT")
    if configured:
        root = Path(configured).expanduser().resolve()
        if not _vault_candidate(root):
            raise DocumentWorkspaceError(
                "DOCUMENT_VAULT_INVALID", "DOXAGON_ROOT must name a vault containing projects/ and knowledge/ or library/",
            )
        inferred = _ancestor_vault(current)
        if inferred is not None and inferred != root:
            relative = current.relative_to(inferred)
            if len(relative.parts) >= 2 and relative.parts[0] == "projects":
                raise DocumentWorkspaceError(
                    "DOCUMENT_VAULT_CONFLICT",
                    "The current project belongs to a different vault than DOXAGON_ROOT; choose the intended scope explicitly",
                )
        return root
    root = _ancestor_vault(current)
    if root is None:
        raise DocumentWorkspaceError(
            "DOCUMENT_VAULT_UNSET", "Set DOXAGON_ROOT or run from a vault/project directory; the platform checkout is not a fallback vault",
        )
    return root


def contained_path(root: Path, relative: str, *, must_exist: bool = False) -> Path:
    if not isinstance(relative, str) or not relative or "\0" in relative or "\\" in relative:
        raise DocumentWorkspaceError("DOCUMENT_PATH_INVALID", "Expected a nonempty relative path")
    requested = Path(relative)
    if requested.is_absolute() or ".." in requested.parts:
        raise DocumentWorkspaceError("DOCUMENT_PATH_INVALID", "The path must stay inside its registered root")
    canonical_root = root.resolve()
    try:
        candidate = (canonical_root / requested).resolve()
    except (OSError, RuntimeError):
        raise DocumentWorkspaceError('DOCUMENT_PATH_INVALID', 'The path cannot be resolved safely') from None
    if not candidate.is_relative_to(canonical_root):
        raise DocumentWorkspaceError("DOCUMENT_PATH_ESCAPE", "A source path resolves outside its registered root")
    if must_exist and not candidate.exists():
        raise DocumentWorkspaceError("DOCUMENT_SOURCE_MISSING", "The registered source is missing", status=404)
    return candidate


@dataclass(frozen=True)
class DocumentProject:
    vault: Path
    root: Path
    slug: str

    def path(self, relative: str, *, must_exist: bool = False) -> Path:
        if self.root.resolve() != self.root or not self.root.is_relative_to(self.vault):
            raise DocumentWorkspaceError('DOCUMENT_PATH_ESCAPE', 'The resolved project root was redirected')
        return contained_path(self.root, relative, must_exist=must_exist)

    def locator(self, path: Path) -> str:
        candidate = path.resolve()
        if not candidate.is_relative_to(self.root):
            raise DocumentWorkspaceError("DOCUMENT_PATH_ESCAPE", "A project item resolves outside the project")
        return candidate.relative_to(self.vault).as_posix()


def resolve_document_project(
    slug: str | None = None, *, cwd: Path | None = None, environ: Mapping[str, str] | None = None,
) -> DocumentProject:
    current = (cwd or Path.cwd()).expanduser().resolve()
    vault = resolve_vault_root(cwd=current, environ=environ)
    projects = (vault / "projects").resolve()
    if slug is None and current.is_relative_to(projects):
        parts = current.relative_to(projects).parts
        slug = parts[0] if parts else None
    if slug is None:
        raise DocumentWorkspaceError("DOCUMENT_PROJECT_REQUIRED", "Name a project, or run from inside that project's directory")
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", slug) is None:
        raise DocumentWorkspaceError("DOCUMENT_PROJECT_INVALID", "A project name must be one path segment")
    root = contained_path(projects, slug, must_exist=True)
    if not root.is_dir():
        raise DocumentWorkspaceError("DOCUMENT_PROJECT_MISSING", "The requested project is not a directory", status=404)
    config = contained_path(root, "config.yaml", must_exist=True)
    if not config.is_file():
        raise DocumentWorkspaceError("DOCUMENT_PROJECT_INVALID", "The project config must be a file")
    return DocumentProject(vault, root, root.name)
