
import pytest

from doxagon.renderings.project import (
    DocumentWorkspaceError, resolve_document_project, resolve_vault_root,
)


@pytest.fixture
def vault(tmp_path):
    root = tmp_path / "vault"
    project = root / "projects" / "example"
    project.mkdir(parents=True)
    (root / "knowledge").mkdir()
    (root / "theses").symlink_to("projects")
    (root / "library").symlink_to("knowledge")
    (project / "config.yaml").write_text("name: example\ndiegesis: n-shared\n")
    return root


def test_nested_project_context_resolves_without_platform_or_active_marker(vault):
    nested = vault / "projects/example/outputs/document"
    nested.mkdir(parents=True)
    result = resolve_document_project(cwd=nested, environ={})
    assert (result.vault, result.root, result.slug) == (vault, vault / "projects/example", "example")


def test_alias_and_canonical_path_return_identical_context(vault):
    assert resolve_document_project(cwd=vault / "theses/example", environ={}) == resolve_document_project(
        "example", cwd=vault, environ={},
    )


def test_platform_cwd_requires_an_explicit_vault(vault, tmp_path):
    platform = tmp_path / "platform"
    platform.mkdir()
    with pytest.raises(DocumentWorkspaceError, match="not a fallback") as error:
        resolve_document_project("example", cwd=platform, environ={})
    assert error.value.code == "DOCUMENT_VAULT_UNSET"


def test_explicit_root_works_from_platform_cwd(vault, tmp_path):
    assert resolve_document_project("example", cwd=tmp_path, environ={"DOXAGON_ROOT": str(vault)}).vault == vault


def test_invalid_explicit_root_does_not_fall_back_to_the_current_vault(vault, tmp_path):
    with pytest.raises(DocumentWorkspaceError) as error:
        resolve_vault_root(cwd=vault, environ={"DOXAGON_ROOT": str(tmp_path / "absent")})
    assert error.value.code == "DOCUMENT_VAULT_INVALID"


def test_project_cwd_and_different_explicit_vault_require_scope_resolution(vault, tmp_path):
    other = tmp_path / "other"
    (other / "projects").mkdir(parents=True)
    (other / "knowledge").mkdir()
    with pytest.raises(DocumentWorkspaceError) as error:
        resolve_document_project("example", cwd=vault / "projects/example", environ={"DOXAGON_ROOT": str(other)})
    assert error.value.code == "DOCUMENT_VAULT_CONFLICT"


def test_vault_root_does_not_guess_a_project(vault):
    with pytest.raises(DocumentWorkspaceError) as error:
        resolve_document_project(cwd=vault, environ={})
    assert error.value.code == "DOCUMENT_PROJECT_REQUIRED"


@pytest.mark.parametrize("slug", ["../example", "/example", "example/other", "example\\other", ".", ""])
def test_project_names_cannot_traverse(vault, slug):
    with pytest.raises(DocumentWorkspaceError) as error:
        resolve_document_project(slug, cwd=vault, environ={})
    assert error.value.code == "DOCUMENT_PROJECT_INVALID"


def test_project_symlink_cannot_escape_the_vault(vault, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "config.yaml").write_text("name: escape\n")
    (vault / "projects/escape").symlink_to(outside)
    with pytest.raises(DocumentWorkspaceError) as error:
        resolve_document_project("escape", cwd=vault, environ={})
    assert error.value.code == "DOCUMENT_PATH_ESCAPE"


def test_registered_file_symlink_cannot_escape_the_project(vault):
    project = resolve_document_project("example", cwd=vault, environ={})
    (vault / "private.txt").write_text("not a project source")
    (project.root / "escape.txt").symlink_to(vault / "private.txt")
    with pytest.raises(DocumentWorkspaceError) as error:
        project.path("escape.txt")
    assert error.value.code == "DOCUMENT_PATH_ESCAPE"


def test_resolution_is_read_only(vault):
    before = sorted(str(path.relative_to(vault)) for path in vault.rglob("*"))
    project = resolve_document_project("example", cwd=vault, environ={})
    project.path("outputs/document/authoring.json")
    assert sorted(str(path.relative_to(vault)) for path in vault.rglob("*")) == before


def test_item_locators_are_vault_relative_and_canonical(vault):
    project = resolve_document_project("example", cwd=vault, environ={})
    assert project.locator(vault / "theses/example/config.yaml") == "projects/example/config.yaml"
