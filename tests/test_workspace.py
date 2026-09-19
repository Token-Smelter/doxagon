from dataclasses import fields
from pathlib import Path
from typing import get_args
from uuid import UUID

from doxagon.workspace import (
    DEFAULT_PLATFORM_VERSION,
    EXTENSION_MANIFEST_PATH,
    MetadataDiagnosticCode,
    MetadataOnly,
    NotConfigured,
    Ready,
    RecoveryDiagnostic,
    SchemaDiagnostic,
    WorkspaceOpenRequest,
    WorkspaceOpenResult,
    extension_manifest_bytes,
    initialize_empty_vault,
    open_workspace,
    verify_demo_vault,
    workspace_request_for_vault,
)


def _bootstrap_request(vault: Path) -> WorkspaceOpenRequest:
    return workspace_request_for_vault(vault)


def _metadata_result(vault: Path) -> MetadataOnly:
    result = open_workspace(_bootstrap_request(vault))
    assert isinstance(result, MetadataOnly)
    return result


def _write_metadata(vault: Path, body: str) -> None:
    metadata = vault / ".doxagon"
    metadata.mkdir(parents=True)
    (metadata / "vault.toml").write_text(body, encoding="utf-8")


def test_workspace_open_request_has_all_precedence_inputs() -> None:
    assert tuple(field.name for field in fields(WorkspaceOpenRequest)) == (
        "cli_workspace",
        "cli_vault",
        "cli_state",
        "cli_artifacts",
        "cli_config",
        "cli_read_only",
        "cli_mode",
        "environ",
        "invocation_cwd",
        "standard_config_path",
    )


def test_open_result_is_the_five_closed_discriminated_variants() -> None:
    assert set(get_args(WorkspaceOpenResult)) == {
        Ready,
        NotConfigured,
        MetadataOnly,
        SchemaDiagnostic,
        RecoveryDiagnostic,
    }


def test_ready_is_the_only_result_with_config_and_services() -> None:
    variants = (Ready, NotConfigured, MetadataOnly, SchemaDiagnostic, RecoveryDiagnostic)

    assert [variant for variant in variants if {"config", "services"} <= {field.name for field in fields(variant)}] == [Ready]


def test_unknown_vault_format_returns_metadata_only_before_poisoned_platform(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write_metadata(vault, 'vault_format = 99\n[platform\nrequires = "not-read"\n')

    assert _metadata_result(vault).code is MetadataDiagnosticCode.UNKNOWN_VAULT_FORMAT


def test_incompatible_platform_returns_metadata_only_before_poisoned_schema(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write_metadata(
        vault,
        'vault_format = 1\n[platform]\nrequires = ">=9.0,<10.0"\n[schema\nbase = "not-read"\n',
    )

    assert _metadata_result(vault).code is MetadataDiagnosticCode.INCOMPATIBLE_PLATFORM


def test_schema_major_mismatch_returns_metadata_only_before_inaccessible_extension(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write_metadata(
        vault,
        '''vault_format = 1
[platform]
requires = ">=0.1,<0.2"
[schema]
base = "2.0.0"
extensions = ["unreadable.toml"]
''',
    )
    unreadable = vault / "unreadable.toml"
    unreadable.write_text("poison", encoding="utf-8")
    unreadable.chmod(0)
    try:
        assert _metadata_result(vault).code is MetadataDiagnosticCode.SCHEMA_MAJOR_MISMATCH
    finally:
        unreadable.chmod(0o600)


def test_metadata_only_never_exposes_schema_version(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write_metadata(
        vault,
        'vault_format = 1\n[platform]\nrequires = ">=0.1,<0.2"\n[schema]\nbase = "2.0.0"\n',
    )

    assert "schema_version" not in _metadata_result(vault).__dataclass_fields__


def test_empty_synthetic_vault_opens_ready_without_cwd_or_checkout(tmp_path: Path) -> None:
    vault = initialize_empty_vault(tmp_path / "synthetic", vault_id=UUID("11111111-1111-7111-8111-111111111111"))
    request = WorkspaceOpenRequest(
        cli_workspace=None,
        cli_vault=vault,
        cli_state=None,
        cli_artifacts=None,
        cli_config=None,
        cli_read_only=None,
        cli_mode=None,
        environ={},
        invocation_cwd=tmp_path / "not-a-checkout",
        standard_config_path=tmp_path / "no-config.toml",
    )

    result = open_workspace(request, platform_version=DEFAULT_PLATFORM_VERSION)

    assert isinstance(result, Ready)


def test_empty_synthetic_vault_writes_packaged_authority_and_empty_manifests(tmp_path: Path) -> None:
    vault = initialize_empty_vault(tmp_path / "synthetic")

    assert (vault / "knowledge" / "logos.yaml").read_text(encoding="utf-8") == "edges: []\n"
    assert (vault / ".doxagon" / "extensions" / "manifest-v1.json").read_text(encoding="utf-8") == '{"format":1,"extensions":[]}\n'
    assert (vault / ".doxagon" / "project-output-inventory-v1.json").read_text(encoding="utf-8") == '{"format":1,"outputs":[]}\n'
    assert (vault / ".doxagon" / "authority-generation.json").read_text(encoding="utf-8") == '{"format":1,"generation":0,"active_txid":null}\n'


def _extension_vault(tmp_path: Path) -> Path:
    vault = initialize_empty_vault(tmp_path / "synthetic")
    extensions = vault / "extensions"
    extensions.mkdir()
    (extensions / "one.yaml").write_text("namespace: org.example.one\n", encoding="utf-8")
    (extensions / "two.yaml").write_text("namespace: org.example.two\n", encoding="utf-8")
    metadata_path = vault / ".doxagon" / "vault.toml"
    metadata_path.write_text(
        metadata_path.read_text(encoding="utf-8").replace(
            "extensions = []", 'extensions = ["extensions/one.yaml", "extensions/two.yaml"]'
        ),
        encoding="utf-8",
    )
    (vault / EXTENSION_MANIFEST_PATH).write_bytes(
        extension_manifest_bytes(vault, ("extensions/one.yaml", "extensions/two.yaml"))
    )
    return vault


def _schema_diagnostic(vault: Path) -> str:
    result = open_workspace(_bootstrap_request(vault))
    assert isinstance(result, SchemaDiagnostic)
    return result.diagnostic


def test_extension_manifest_is_ordered_checksum_bound_and_serving_when_authoritative(tmp_path: Path) -> None:
    vault = _extension_vault(tmp_path)

    assert isinstance(open_workspace(_bootstrap_request(vault)), Ready)
    assert (vault / EXTENSION_MANIFEST_PATH).read_bytes() == extension_manifest_bytes(
        vault, ("extensions/one.yaml", "extensions/two.yaml")
    )


def test_extension_manifest_rejects_symlinked_control_parent(tmp_path: Path) -> None:
    vault = _extension_vault(tmp_path)
    extensions = vault / ".doxagon" / "extensions"
    external_extensions = tmp_path / "external-extensions"
    external_extensions.mkdir()
    (external_extensions / "manifest-v1.json").write_bytes(
        (extensions / "manifest-v1.json").read_bytes()
    )
    (extensions / "manifest-v1.json").unlink()
    extensions.rmdir()
    extensions.symlink_to(external_extensions, target_is_directory=True)

    assert _schema_diagnostic(vault) == "extension_manifest_missing"


def test_extension_manifest_rejects_symlinked_extension_parent(tmp_path: Path) -> None:
    vault = _extension_vault(tmp_path)
    extensions = vault / "extensions"
    alternate_extensions = vault / "alternate-extensions"
    alternate_extensions.mkdir()
    for extension in extensions.iterdir():
        (alternate_extensions / extension.name).write_bytes(extension.read_bytes())
        extension.unlink()
    extensions.rmdir()
    extensions.symlink_to(alternate_extensions, target_is_directory=True)

    assert _schema_diagnostic(vault) == "extension_missing"


def test_extension_manifest_rejects_missing_reordered_path_and_checksum_entries(tmp_path: Path) -> None:
    vault = _extension_vault(tmp_path)
    manifest = vault / EXTENSION_MANIFEST_PATH

    manifest.unlink()
    assert _schema_diagnostic(vault) == "extension_manifest_missing"

    manifest.write_bytes(extension_manifest_bytes(vault, ("extensions/two.yaml", "extensions/one.yaml")))
    assert _schema_diagnostic(vault) == "extension_manifest_order_mismatch"

    metadata = vault / ".doxagon" / "vault.toml"
    metadata.write_text(
        metadata.read_text(encoding="utf-8").replace(EXTENSION_MANIFEST_PATH, ".doxagon/extensions/elsewhere.json"),
        encoding="utf-8",
    )
    assert _schema_diagnostic(vault) == "extension_manifest_path_mismatch"

    metadata.write_text(
        metadata.read_text(encoding="utf-8").replace(".doxagon/extensions/elsewhere.json", EXTENSION_MANIFEST_PATH),
        encoding="utf-8",
    )
    manifest.write_text(
        '{"format":1,"extensions":[{"path":"extensions/one.yaml","sha256":"' + "0" * 64 + '"}]}\n',
        encoding="utf-8",
    )
    assert _schema_diagnostic(vault) == "extension_checksum_mismatch"


def test_packaged_demo_fixture_has_exact_bidirectional_manifest_and_opens_without_external_vault(tmp_path: Path) -> None:
    vault = verify_demo_vault()
    request = WorkspaceOpenRequest(
        cli_workspace=None,
        cli_vault=None,
        cli_state=None,
        cli_artifacts=None,
        cli_config=None,
        cli_read_only=None,
        cli_mode="demo",
        environ={},
        invocation_cwd=tmp_path,
        standard_config_path=tmp_path / "no-config.toml",
    )

    assert vault.name == "demo-vault"
    assert isinstance(open_workspace(request), Ready)
