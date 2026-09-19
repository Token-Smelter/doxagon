"""Integration tests for dox export CLI commands."""

import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

# Add scripts to path for import
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from dox import cli


@pytest.fixture
def fixtures_dir():
    """Path to test fixtures directory."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def runner():
    """Click test runner."""
    return CliRunner()


@pytest.fixture
def fixtures_env(fixtures_dir, monkeypatch):
    """Configure environment to use fixtures library."""
    lib_path = fixtures_dir / "library"
    monkeypatch.setattr("doxagon.config.LIBRARY_DIR", lib_path)
    monkeypatch.setattr("doxagon.config.DOXAI_DIR", lib_path / "doxai")
    monkeypatch.setattr("doxagon.config.EVIDENCE_DIR", lib_path / "evidence")
    monkeypatch.setattr("doxagon.config.DIEGESES_DIR", lib_path / "diegeses")
    monkeypatch.setattr("doxagon.config.LOGOS_FILE", lib_path / "logos.yaml")
    monkeypatch.setattr("doxagon.config.SCHEMA_FILE", lib_path / "schema.yaml")
    # Storage module
    monkeypatch.setattr("doxagon.storage.LIBRARY_DIR", lib_path)
    monkeypatch.setattr("doxagon.storage.DOXAI_DIR", lib_path / "doxai")
    monkeypatch.setattr("doxagon.storage.DIEGESES_DIR", lib_path / "diegeses")
    monkeypatch.setattr("doxagon.storage.LOGOS_FILE", lib_path / "logos.yaml")
    # Graph module
    monkeypatch.setattr("doxagon.graph.DOXAI_DIR", lib_path / "doxai")
    monkeypatch.setattr("doxagon.graph.DIEGESES_DIR", lib_path / "diegeses")
    monkeypatch.setattr("doxagon.graph.LOGOS_FILE", lib_path / "logos.yaml")
    # Without this the graph module validates these fixtures' edges against the
    # real corpus schema. This fixture is a near-copy of test_export.py's, and
    # the omission was duplicated with it.
    monkeypatch.setattr("doxagon.graph.SCHEMA_FILE", lib_path / "schema.yaml")
    monkeypatch.setattr("doxagon.graph.CACHE_DIR", lib_path / ".cache")
    monkeypatch.setattr("doxagon.graph.CACHE_FILE", lib_path / ".cache" / "graph.pkl")
    monkeypatch.setattr("doxagon.graph.HASH_FILE", lib_path / ".cache" / "hash.txt")
    # Export module
    monkeypatch.setattr("doxagon.export.LIBRARY_DIR", lib_path)
    monkeypatch.setattr("doxagon.export.DOXAI_DIR", lib_path / "doxai")
    monkeypatch.setattr("doxagon.export.EVIDENCE_DIR", lib_path / "evidence")
    monkeypatch.setattr("doxagon.export.DIEGESES_DIR", lib_path / "diegeses")
    monkeypatch.setattr("doxagon.export.LOGOS_FILE", lib_path / "logos.yaml")
    monkeypatch.setattr("doxagon.export.SCHEMA_FILE", lib_path / "schema.yaml")
    # Invalidate cache
    from doxagon.graph import invalidate_cache
    invalidate_cache()
    return lib_path


# =============================================================================
# Export Command Group Tests
# =============================================================================


def test_export_group_help(runner):
    """Export group shows help."""
    result = runner.invoke(cli, ["export", "--help"])
    assert result.exit_code == 0
    assert "platform" in result.output
    assert "library" in result.output
    assert "subgraph" in result.output


# =============================================================================
# Import Command Group Tests
# =============================================================================


def test_import_group_registers_subcommands(runner):
    """Import group keeps both supported workflows registered."""
    result = runner.invoke(cli, ["import", "--help"])

    assert result.exit_code == 0
    assert "library" in result.output
    assert "subgraph" in result.output


# =============================================================================
# Library Export Tests
# =============================================================================


def test_export_library_zip(runner, fixtures_env):
    """Library ZIP export works."""
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["export", "library", "-o", "test.zip"])
        assert result.exit_code == 0, result.output
        assert "Library export complete" in result.output
        assert Path("test.zip").exists()

        # Verify ZIP contents
        with zipfile.ZipFile("test.zip", "r") as zf:
            names = zf.namelist()
            assert any("doxai" in n for n in names)
            assert "manifest.yaml" in names


def test_export_library_yaml(runner, fixtures_env):
    """Library YAML export works."""
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["export", "library", "--format", "yaml", "-o", "test.yaml"])
        assert result.exit_code == 0, result.output

        content = yaml.safe_load(Path("test.yaml").read_text())
        assert "_meta" in content
        assert content["_meta"]["export_type"] == "library"
        assert "doxai" in content


def test_export_library_json(runner, fixtures_env):
    """Library JSON export works."""
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["export", "library", "--format", "json", "-o", "test.json"])
        assert result.exit_code == 0, result.output

        content = json.loads(Path("test.json").read_text())
        assert "_meta" in content
        assert "doxai" in content


# =============================================================================
# Subgraph Export Tests
# =============================================================================


def test_export_subgraph_requires_selection(runner, fixtures_env):
    """Subgraph export requires selection mode."""
    result = runner.invoke(cli, ["export", "subgraph", "-o", "test.zip"])
    assert result.exit_code == 1
    assert "Must specify" in result.output


def test_export_subgraph_rejects_multiple_modes(runner, fixtures_env):
    """Subgraph export rejects multiple selection modes."""
    result = runner.invoke(
        cli,
        ["export", "subgraph", "-d", "n-test", "-r", "d-root", "-o", "test.zip"],
    )
    assert result.exit_code == 1
    assert "only one" in result.output.lower()


def test_export_subgraph_diegesis_mode(runner, fixtures_env):
    """Subgraph diegesis export works."""
    with runner.isolated_filesystem():
        result = runner.invoke(
            cli,
            ["export", "subgraph", "-d", "n-test-narrative", "-w", "canonical", "--format", "json", "-o", "test.json"],
        )
        assert result.exit_code == 0, result.output
        assert "Subgraph export complete" in result.output

        content = json.loads(Path("test.json").read_text())
        assert "d-root" in content["doxai"]


def test_export_subgraph_root_mode(runner, fixtures_env):
    """Subgraph neighborhood export works."""
    with runner.isolated_filesystem():
        result = runner.invoke(
            cli,
            ["export", "subgraph", "-r", "d-root", "--hops", "1", "--format", "json", "-o", "test.json"],
        )
        assert result.exit_code == 0, result.output

        content = json.loads(Path("test.json").read_text())
        assert "d-root" in content["doxai"]


def test_export_subgraph_tag_mode(runner, fixtures_env):
    """Subgraph tag export works."""
    with runner.isolated_filesystem():
        result = runner.invoke(
            cli,
            ["export", "subgraph", "-t", "domain:orphan", "--format", "json", "-o", "test.json"],
        )
        assert result.exit_code == 0, result.output

        content = json.loads(Path("test.json").read_text())
        assert "d-orphan" in content["doxai"]
        assert "d-root" not in content["doxai"]


def test_export_subgraph_multiple_tags(runner, fixtures_env):
    """Subgraph export with multiple tags works."""
    with runner.isolated_filesystem():
        result = runner.invoke(
            cli,
            [
                "export",
                "subgraph",
                "-t",
                "domain:orphan",
                "-t",
                "domain:secondary",
                "--format",
                "json",
                "-o",
                "test.json",
            ],
        )
        assert result.exit_code == 0, result.output

        content = json.loads(Path("test.json").read_text())
        # Should match d-orphan (domain:orphan) and d-child-b (domain:secondary)
        assert "d-orphan" in content["doxai"]
        assert "d-child-b" in content["doxai"]


def test_export_subgraph_no_evidence(runner, fixtures_env):
    """Subgraph export with --no-evidence excludes evidence."""
    with runner.isolated_filesystem():
        result = runner.invoke(
            cli,
            [
                "export",
                "subgraph",
                "-d",
                "n-test-narrative",
                "--no-evidence",
                "--format",
                "json",
                "-o",
                "test.json",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "Evidence: 0" in result.output

        content = json.loads(Path("test.json").read_text())
        assert len(content["evidence"]) == 0


def test_export_subgraph_auto_generates_filename(runner, fixtures_env):
    """Subgraph export auto-generates filename when not specified."""
    with runner.isolated_filesystem():
        result = runner.invoke(
            cli,
            ["export", "subgraph", "-d", "n-test-narrative", "--format", "json"],
        )
        assert result.exit_code == 0, result.output
        # Check that a file was created
        json_files = list(Path(".").glob("doxagon-subgraph-*.json"))
        assert len(json_files) == 1


# =============================================================================
# Platform Export Tests
# =============================================================================


def test_export_platform_help(runner):
    """Platform export shows help."""
    result = runner.invoke(cli, ["export", "platform", "--help"])
    assert result.exit_code == 0
    assert "--include-skills" in result.output
    assert "--include-docs" in result.output


# Platform export tests are harder to run in isolation because they need
# the full project structure. These would be better as manual verification.
