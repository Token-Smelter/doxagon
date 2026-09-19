from pathlib import Path

import pytest

from doxagon.compat import legacy
from doxagon.workspace import (
    NotConfigured,
    Ready,
    WorkspaceOpenRequest,
    initialize_empty_vault,
    open_workspace,
    workspace_request_for_vault,
)


def _request(vault: Path | None, cwd: Path) -> WorkspaceOpenRequest:
    return WorkspaceOpenRequest(
        cli_workspace=None,
        cli_vault=vault,
        cli_state=None,
        cli_artifacts=None,
        cli_config=None,
        cli_read_only=None,
        cli_mode=None,
        environ={},
        invocation_cwd=cwd,
        standard_config_path=cwd / "missing-config.toml",
    )


def _graph_vault(root: Path, slug: str) -> Path:
    vault = initialize_empty_vault(root)
    knowledge = vault / "knowledge"
    (knowledge / "doxai").mkdir()
    (knowledge / "doxai" / f"{slug}.md").write_text(
        f"---\nbelief: {slug} belief\ntags: [synthetic]\n---\n{slug} body\n", encoding="utf-8"
    )
    (knowledge / "schema.yaml").write_text("edge_types:\n  supports: {}\n", encoding="utf-8")
    return vault


def test_explicit_external_vault_graph_read_is_independent_of_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = _graph_vault(tmp_path / "vault", "d-external")
    unrelated_cwd = tmp_path / "unrelated"
    unrelated_cwd.mkdir()
    monkeypatch.chdir(unrelated_cwd)

    result = open_workspace(_request(vault, unrelated_cwd))

    assert isinstance(result, Ready)
    assert set(result.services.read_graph().nodes) == {"d-external"}
    result.services.close()


def test_relative_explicit_vault_opens_from_invocation_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    invocation_cwd = tmp_path / "invocation"
    invocation_cwd.mkdir()
    _graph_vault(invocation_cwd / "nested" / "vault", "d-relative")
    monkeypatch.chdir(invocation_cwd)

    result = open_workspace(workspace_request_for_vault(Path("nested/vault")))

    assert isinstance(result, Ready)
    assert set(result.services.read_graph().nodes) == {"d-relative"}
    result.services.close()


def test_two_opened_vaults_keep_graph_and_cache_state_isolated(tmp_path: Path) -> None:
    first = open_workspace(_request(_graph_vault(tmp_path / "first", "d-first"), tmp_path))
    second = open_workspace(_request(_graph_vault(tmp_path / "second", "d-second"), tmp_path))
    assert isinstance(first, Ready)
    assert isinstance(second, Ready)

    assert set(first.services.read_graph().nodes) == {"d-first"}
    assert set(second.services.read_graph().nodes) == {"d-second"}
    assert first.services.graph.authority_hash() != second.services.graph.authority_hash()

    first.services.close()
    with pytest.raises(RuntimeError, match="closed"):
        first.services.read_graph()
    assert set(second.services.read_graph().nodes) == {"d-second"}
    second.services.close()


def test_absent_explicit_selection_is_diagnostic_not_checkout_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    unrelated_cwd = tmp_path / "unrelated"
    unrelated_cwd.mkdir()
    monkeypatch.chdir(unrelated_cwd)
    request = _request(None, unrelated_cwd)

    assert isinstance(open_workspace(request), NotConfigured)


def test_legacy_adapter_requires_explicit_root_and_reads_only_synthetic_layout(tmp_path: Path) -> None:
    legacy_root = tmp_path / "legacy"
    knowledge = legacy_root / "library"
    (knowledge / "doxai").mkdir(parents=True)
    (knowledge / "doxai" / "d-legacy.md").write_text("---\nbelief: legacy\n---\nbody\n", encoding="utf-8")
    (knowledge / "logos.yaml").write_text("edges: []\n", encoding="utf-8")

    with pytest.warns(RuntimeWarning, match="legacy adapter"):
        services = legacy.open(legacy_root)
    assert set(services.read_graph().nodes) == {"d-legacy"}
    services.close()
