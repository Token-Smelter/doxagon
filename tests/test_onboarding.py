from pathlib import Path
from types import MappingProxyType

from click.testing import CliRunner

from doxagon.onboarding import known_codes, remediation_for
from doxagon.workspace import (
    MetadataDiagnosticCode,
    Ready,
    WorkspaceOpenRequest,
    open_workspace,
)
from scripts.dox import cli


def _request(vault: Path | None, cwd: Path, *, mode: str | None = None) -> WorkspaceOpenRequest:
    return WorkspaceOpenRequest(
        cli_workspace=None,
        cli_vault=vault,
        cli_state=None,
        cli_artifacts=None,
        cli_config=None,
        cli_read_only=None,
        cli_mode=mode,
        environ=MappingProxyType({}),
        invocation_cwd=cwd,
        standard_config_path=cwd / "missing-config.toml",
    )


def test_every_metadata_diagnostic_code_has_human_guidance() -> None:
    """A new coarse code must not ship without something a person can act on."""

    assert {code.value for code in MetadataDiagnosticCode} <= known_codes()


def test_unknown_code_still_returns_guidance_rather_than_failing() -> None:
    assert remediation_for("not_a_real_code")
    assert remediation_for(None)


def test_demo_vault_serves_a_non_empty_example_graph(tmp_path: Path) -> None:
    """The zero-config path must show a working graph, not an empty one."""

    result = open_workspace(_request(None, tmp_path, mode="demo"))

    assert isinstance(result, Ready)
    graph = result.services.read_graph()
    assert graph.number_of_nodes() and graph.number_of_edges()
    result.services.close()


def test_dox_init_creates_a_vault_that_opens_read_write(tmp_path: Path) -> None:
    vault = tmp_path / "created"

    created = CliRunner().invoke(cli, ["init", str(vault)])

    assert created.exit_code == 0, created.output
    opened = open_workspace(_request(vault, tmp_path))
    assert isinstance(opened, Ready) and opened.config.access_mode == "read-write"
    opened.services.close()


def test_dox_workspace_without_a_vault_exits_nonzero_with_guidance(tmp_path: Path) -> None:
    result = CliRunner().invoke(cli, ["workspace"], env={"HOME": str(tmp_path)})

    assert result.exit_code == 1
    assert "dox init PATH" in result.output
