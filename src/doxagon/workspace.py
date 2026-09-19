"""Explicit, instance-scoped vault workspace bootstrap contracts.

This module is deliberately not imported by legacy entrypoints.  It provides the
Stage I boundary without changing their checkout-derived behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from importlib import resources
from pathlib import Path, PurePosixPath
import hashlib
import json
import os
import re
import stat
import time
import tomllib
from types import MappingProxyType
from typing import Literal, Mapping, TypeAlias
from uuid import UUID

from doxagon.graph_service import GraphService
from doxagon.repositories import FilesystemEdgeRepository, FilesystemKnowledgeRepository
from doxagon.wal import (
    RecoveryUnresolved,
    WriteAheadLog,
    WriterFence,
    WriterFenceUnavailable,
    WriterFenceUnsupported,
    has_pending_transaction,
)


DeploymentMode: TypeAlias = Literal["local", "demo", "hosted-readonly", "developer"]
AccessMode: TypeAlias = Literal["read-only", "read-write"]

SUPPORTED_VAULT_FORMAT = 1
SUPPORTED_SCHEMA_MAJOR = 1
DEFAULT_PLATFORM_VERSION = "0.1.0"
EXTENSION_MANIFEST_PATH = ".doxagon/extensions/manifest-v1.json"
DEMO_MANIFEST_RESOURCE = "demo-vault.manifest-v1.json"
READ_ONLY_RECOVERY_WAIT_SECONDS = 2.0


class Capability(str, Enum):
    """The closed v1 capability vocabulary."""

    WORKSPACE_READ = "workspace:read"
    CONTENT_READ = "content:read"
    ASSET_READ = "asset:read"
    KNOWLEDGE_WRITE = "knowledge:write"
    PROJECT_WRITE = "project:write"
    JOB_RUN = "job:run"
    JOB_STREAM = "job:stream"
    ARTIFACT_PROMOTE = "artifact:promote"
    PUBLICATION_BUILD = "publication:build"
    DEVELOPER_RUN = "developer:run"


@dataclass(frozen=True)
class WorkspaceOpenRequest:
    """All inputs that participate in workspace resolution precedence."""

    cli_workspace: str | None
    cli_vault: Path | None
    cli_state: Path | None
    cli_artifacts: Path | None
    cli_config: Path | None
    cli_read_only: bool | None
    cli_mode: DeploymentMode | None
    environ: Mapping[str, str]
    invocation_cwd: Path
    standard_config_path: Path


@dataclass(frozen=True)
class WorkspaceConfig:
    vault_id: UUID
    vault_root: Path
    knowledge_root: Path
    projects_root: Path
    media_root: Path
    state_root: Path
    artifact_root: Path
    access_mode: AccessMode
    deployment_mode: DeploymentMode
    schema_version: str
    effective_schema_digest: str
    workspace_fingerprint: str
    capabilities: frozenset[Capability]


class VaultServices:
    """Closable, instance-scoped repositories for one ready vault."""

    def __init__(self, config: WorkspaceConfig) -> None:
        self.config = config
        self.closed = False
        self.knowledge = FilesystemKnowledgeRepository(config.knowledge_root)
        self.edges = FilesystemEdgeRepository(config.knowledge_root)
        self.graph = GraphService(self.knowledge, self.edges)
        self.fence = WriterFence(config.vault_root)
        self.wal = WriteAheadLog(config.vault_root, self.fence)

    def _require_open(self) -> None:
        if self.closed:
            raise RuntimeError("vault services are closed")

    def read_graph(self):
        self._require_open()
        return self.graph.read_graph()

    def graph_model(self):
        self._require_open()
        return self.graph.graph_model()

    def acquire_write_fence(self) -> str | None:
        """Take lifetime write ownership and converge any prepared transaction."""

        self._require_open()
        self.fence.acquire()
        return self.wal.recover()

    def write_edges(self, edges) -> str:
        """Replace this vault's authoritative edge set under the held fence."""

        self._require_open()
        if Capability.KNOWLEDGE_WRITE not in self.config.capabilities:
            raise PermissionError("knowledge:write is not granted for this workspace")
        return self.edges.write_edges(edges, doxa_ids=self.knowledge.doxa_ids(), wal=self.wal)

    def close(self) -> None:
        if not self.closed:
            self.graph.close()
            self.fence.release()
            self.closed = True

    def __enter__(self) -> "VaultServices":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


@dataclass(frozen=True)
class BootstrapDiagnostic:
    mode: DeploymentMode
    requested_access_mode: AccessMode
    remediation: str


@dataclass(frozen=True)
class VaultEnvelope:
    vault_format: int
    platform_requires: str | None


class MetadataDiagnosticCode(str, Enum):
    UNKNOWN_VAULT_FORMAT = "unknown_vault_format"
    INCOMPATIBLE_PLATFORM = "incompatible_platform"
    SCHEMA_MAJOR_MISMATCH = "schema_major_mismatch"
    INVALID_FIXED_ENVELOPE = "invalid_fixed_envelope"


@dataclass(frozen=True)
class SupportedVaultMetadata:
    vault_id: UUID
    vault_root: Path
    schema_version: str
    envelope: VaultEnvelope


@dataclass(frozen=True)
class Ready:
    state: Literal["ready"]
    config: WorkspaceConfig
    services: VaultServices


@dataclass(frozen=True)
class NotConfigured:
    state: Literal["not_configured"]
    bootstrap: BootstrapDiagnostic
    code: Literal["vault_not_configured"] = "vault_not_configured"


@dataclass(frozen=True)
class MetadataOnly:
    state: Literal["metadata_only"]
    bootstrap: BootstrapDiagnostic
    envelope: VaultEnvelope
    code: MetadataDiagnosticCode


@dataclass(frozen=True)
class SchemaDiagnostic:
    state: Literal["schema_diagnostic"]
    bootstrap: BootstrapDiagnostic
    metadata: SupportedVaultMetadata
    diagnostic: str


@dataclass(frozen=True)
class RecoveryDiagnostic:
    state: Literal["recovery_diagnostic"]
    bootstrap: BootstrapDiagnostic
    metadata: SupportedVaultMetadata
    diagnostic: str


WorkspaceOpenResult: TypeAlias = Ready | NotConfigured | MetadataOnly | SchemaDiagnostic | RecoveryDiagnostic


@dataclass(frozen=True)
class _Selection:
    vault: Path | None
    state: Path | None
    artifacts: Path | None
    mode: DeploymentMode
    access_mode: AccessMode


def _version(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"(\d+)\.(\d+)(?:\.(\d+))?", value.strip())
    if match is None:
        raise ValueError(f"invalid semantic version: {value!r}")
    return int(match[1]), int(match[2]), int(match[3] or 0)


def _platform_is_compatible(requires: str, platform_version: str) -> bool:
    current = _version(platform_version)
    clauses = [part.strip() for part in requires.split(",") if part.strip()]
    if not clauses:
        return False
    for clause in clauses:
        match = re.fullmatch(r"(>=|<=|>|<|==)\s*(\d+\.\d+(?:\.\d+)?)", clause)
        if match is None:
            return False
        operator, required_text = match.groups()
        required = _version(required_text)
        if not {
            ">=": current >= required,
            "<=": current <= required,
            ">": current > required,
            "<": current < required,
            "==": current == required,
        }[operator]:
            return False
    return True


def _toml_string(line: str, key: str) -> str | None:
    match = re.fullmatch(rf"\s*{re.escape(key)}\s*=\s*\"([^\"]*)\"\s*(?:#.*)?", line)
    return match.group(1) if match else None


def _toml_int(line: str, key: str) -> int | None:
    match = re.fullmatch(rf"\s*{re.escape(key)}\s*=\s*(\d+)\s*(?:#.*)?", line)
    return int(match.group(1)) if match else None


def _metadata_only(
    bootstrap: BootstrapDiagnostic,
    vault_format: int,
    platform_requires: str | None,
    code: MetadataDiagnosticCode,
) -> MetadataOnly:
    return MetadataOnly(
        state="metadata_only",
        bootstrap=bootstrap,
        envelope=VaultEnvelope(vault_format=vault_format, platform_requires=platform_requires),
        code=code,
    )


def parse_v1_metadata(
    metadata_path: Path,
    bootstrap: BootstrapDiagnostic,
    *,
    platform_version: str = DEFAULT_PLATFORM_VERSION,
) -> SupportedVaultMetadata | MetadataOnly:
    """Read only the next metadata field necessary to choose an open branch.

    The line-oriented fixed-envelope scan intentionally does not invoke a TOML
    parser until vault format, platform compatibility, and schema major have
    passed.  Thus a malformed schema section or inaccessible extension manifest
    cannot change an earlier ``MetadataOnly`` result.
    """

    section = ""
    vault_format: int | None = None
    platform_requires: str | None = None
    schema_base: str | None = None

    with metadata_path.open("r", encoding="utf-8") as metadata_file:
        for raw_line in metadata_file:
            line = raw_line.split("#", 1)[0].strip()
            if not line:
                continue
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1]
                if section not in {"", "platform", "schema"} and vault_format is None:
                    return _metadata_only(
                        bootstrap, 0, None, MetadataDiagnosticCode.INVALID_FIXED_ENVELOPE
                    )
                continue
            if section == "" and vault_format is None:
                vault_format = _toml_int(line, "vault_format")
                if vault_format is None:
                    return _metadata_only(
                        bootstrap, 0, None, MetadataDiagnosticCode.INVALID_FIXED_ENVELOPE
                    )
                if vault_format != SUPPORTED_VAULT_FORMAT:
                    return _metadata_only(
                        bootstrap, vault_format, None, MetadataDiagnosticCode.UNKNOWN_VAULT_FORMAT
                    )
                continue
            if section == "platform" and platform_requires is None:
                platform_requires = _toml_string(line, "requires")
                if platform_requires is None:
                    return _metadata_only(
                        bootstrap, vault_format or 0, None, MetadataDiagnosticCode.INVALID_FIXED_ENVELOPE
                    )
                if not _platform_is_compatible(platform_requires, platform_version):
                    return _metadata_only(
                        bootstrap,
                        vault_format or 0,
                        platform_requires,
                        MetadataDiagnosticCode.INCOMPATIBLE_PLATFORM,
                    )
                continue
            if section == "schema" and schema_base is None:
                schema_base = _toml_string(line, "base")
                if schema_base is None:
                    return _metadata_only(
                        bootstrap,
                        vault_format or 0,
                        platform_requires,
                        MetadataDiagnosticCode.INVALID_FIXED_ENVELOPE,
                    )
                try:
                    schema_major = _version(schema_base)[0]
                except ValueError:
                    return _metadata_only(
                        bootstrap,
                        vault_format or 0,
                        platform_requires,
                        MetadataDiagnosticCode.SCHEMA_MAJOR_MISMATCH,
                    )
                if schema_major != SUPPORTED_SCHEMA_MAJOR:
                    return _metadata_only(
                        bootstrap,
                        vault_format or 0,
                        platform_requires,
                        MetadataDiagnosticCode.SCHEMA_MAJOR_MISMATCH,
                    )
                break

    if vault_format is None or platform_requires is None or schema_base is None:
        return _metadata_only(
            bootstrap,
            vault_format or 0,
            platform_requires,
            MetadataDiagnosticCode.INVALID_FIXED_ENVELOPE,
        )

    parsed = tomllib.loads(metadata_path.read_text(encoding="utf-8"))
    try:
        return SupportedVaultMetadata(
            vault_id=UUID(parsed["vault_id"]),
            vault_root=metadata_path.parent.parent.resolve(),
            schema_version=schema_base,
            envelope=VaultEnvelope(vault_format=vault_format, platform_requires=platform_requires),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("invalid supported vault metadata") from error


def _configuration(path: Path | None) -> dict[str, object]:
    if path is None or not path.is_file():
        return {}
    with path.open("rb") as config_file:
        parsed = tomllib.load(config_file)
    return parsed if isinstance(parsed, dict) else {}


def _normalized_vault_relative_path(path: str) -> PurePosixPath:
    candidate = PurePosixPath(path)
    if (
        not path
        or candidate.is_absolute()
        or str(candidate) != path
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        raise ValueError("invalid extension path")
    return candidate


def _read_regular_vault_file(vault_root: Path, relative: PurePosixPath) -> bytes | None:
    """Read a vault-relative regular file without traversing symlinked components."""

    root = vault_root.resolve()
    candidate = root.joinpath(*relative.parts)
    if not candidate.resolve().is_relative_to(root):
        return None
    directory_fd: int | None = None
    file_fd: int | None = None
    try:
        directory_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        for component in relative.parts[:-1]:
            next_directory_fd = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=directory_fd,
            )
            os.close(directory_fd)
            directory_fd = next_directory_fd
        file_fd = os.open(relative.parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
        if not stat.S_ISREG(os.fstat(file_fd).st_mode):
            return None
        with os.fdopen(file_fd, "rb", closefd=False) as file:
            return file.read()
    except OSError:
        return None
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if directory_fd is not None:
            os.close(directory_fd)


def extension_manifest_bytes(vault_root: Path, extension_paths: tuple[str, ...]) -> bytes:
    """Build canonical bytes for an authoritative extension update.

    The schema-extension command must commit these bytes and the matching
    metadata list in one fenced WAL transaction. This helper has no write side
    effect, so callers cannot mistake a direct edit for that workflow.
    """

    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw_path in extension_paths:
        relative = _normalized_vault_relative_path(raw_path)
        if raw_path in seen:
            raise ValueError("duplicate extension path")
        seen.add(raw_path)
        extension = _read_regular_vault_file(vault_root, relative)
        if extension is None:
            raise ValueError("extension must be a regular vault-relative file")
        entries.append({"path": raw_path, "sha256": hashlib.sha256(extension).hexdigest()})
    return (json.dumps({"format": 1, "extensions": entries}, separators=(",", ":")) + "\n").encode()


def _extension_manifest_diagnostic(vault_root: Path, parsed: dict[str, object]) -> str | None:
    schema = parsed.get("schema")
    if not isinstance(schema, dict) or schema.get("extension_manifest") != EXTENSION_MANIFEST_PATH:
        return "extension_manifest_path_mismatch"
    declared = schema.get("extensions")
    if not isinstance(declared, list) or not all(isinstance(item, str) for item in declared):
        return "extension_manifest_entries_invalid"
    manifest_bytes = _read_regular_vault_file(vault_root, PurePosixPath(EXTENSION_MANIFEST_PATH))
    if manifest_bytes is None:
        return "extension_manifest_missing"
    try:
        manifest = json.loads(manifest_bytes)
    except json.JSONDecodeError:
        return "extension_manifest_invalid"
    entries = manifest.get("extensions") if isinstance(manifest, dict) else None
    if (
        not isinstance(manifest, dict)
        or set(manifest) != {"format", "extensions"}
        or manifest.get("format") != 1
        or not isinstance(entries, list)
    ):
        return "extension_manifest_invalid"
    paths: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256"}:
            return "extension_manifest_invalid"
        raw_path, digest = entry["path"], entry["sha256"]
        if not isinstance(raw_path, str) or not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
            return "extension_manifest_invalid"
        try:
            relative = _normalized_vault_relative_path(raw_path)
        except ValueError:
            return "extension_manifest_path_mismatch"
        extension = _read_regular_vault_file(vault_root, relative)
        if extension is None:
            return "extension_missing"
        if hashlib.sha256(extension).hexdigest() != digest:
            return "extension_checksum_mismatch"
        paths.append(raw_path)
    if len(paths) != len(set(paths)) or paths != declared:
        return "extension_manifest_order_mismatch"
    return None


def verify_demo_vault() -> Path:
    """Verify the packaged synthetic fixture's exact reviewed inventory."""

    resource_root = Path(resources.files("doxagon.resources"))
    vault_root = resource_root / "demo-vault"
    manifest_path = resource_root / DEMO_MANIFEST_RESOURCE
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entries = manifest["files"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("invalid packaged demo manifest") from error
    if not isinstance(entries, list) or manifest.get("format") != 1 or manifest.get("root") != "demo-vault":
        raise ValueError("invalid packaged demo manifest")
    expected: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256"}:
            raise ValueError("invalid packaged demo manifest")
        path, digest = entry["path"], entry["sha256"]
        if not isinstance(path, str) or not isinstance(digest, str):
            raise ValueError("invalid packaged demo manifest")
        relative = _normalized_vault_relative_path(path)
        if path in expected or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ValueError("invalid packaged demo manifest")
        expected[path] = digest
        file_path = vault_root.joinpath(*relative.parts)
        if file_path.is_symlink() or not file_path.is_file() or hashlib.sha256(file_path.read_bytes()).hexdigest() != digest:
            raise ValueError("packaged demo manifest mismatch")
    actual = {
        file_path.relative_to(vault_root).as_posix()
        for file_path in vault_root.rglob("*")
        if file_path.is_file() and not file_path.is_symlink()
    }
    if actual != set(expected):
        raise ValueError("packaged demo manifest is not bidirectional")
    return vault_root


def _absolute(path: Path, *, invocation_cwd: Path, allow_relative: bool) -> Path:
    if path.is_absolute():
        return path.resolve()
    if not allow_relative:
        raise ValueError("persisted and environment paths must be absolute")
    return (invocation_cwd / path).resolve()


def _selection(request: WorkspaceOpenRequest) -> _Selection:
    environ = request.environ
    config_path = request.cli_config
    if config_path is not None:
        config_path = _absolute(config_path, invocation_cwd=request.invocation_cwd, allow_relative=True)
    elif environ.get("DOXAGON_CONFIG"):
        config_path = _absolute(Path(environ["DOXAGON_CONFIG"]), invocation_cwd=request.invocation_cwd, allow_relative=False)
    else:
        config_path = request.standard_config_path
    configuration = _configuration(config_path)

    workspace_settings: dict[str, object] = {}
    workspace_name = request.cli_workspace
    if workspace_name is None:
        active = configuration.get("active_workspace")
        workspace_name = active if isinstance(active, str) else None
    workspaces = configuration.get("workspaces")
    if workspace_name and isinstance(workspaces, dict):
        candidate = workspaces.get(workspace_name)
        if isinstance(candidate, dict):
            workspace_settings = candidate

    config_mode = workspace_settings.get("mode")
    mode = request.cli_mode or environ.get("DOXAGON_MODE") or config_mode or "local"
    if mode not in {"local", "demo", "hosted-readonly", "developer"}:
        raise ValueError("invalid deployment mode")

    def choose(cli_value: Path | None, env_name: str, config_name: str) -> Path | None:
        if cli_value is not None:
            return _absolute(cli_value, invocation_cwd=request.invocation_cwd, allow_relative=True)
        if environ.get(env_name):
            return _absolute(Path(environ[env_name]), invocation_cwd=request.invocation_cwd, allow_relative=False)
        configured = workspace_settings.get(config_name)
        if isinstance(configured, str):
            return _absolute(Path(configured), invocation_cwd=config_path.parent, allow_relative=True)
        return None

    vault = choose(request.cli_vault, "DOXAGON_VAULT", "vault")
    if mode == "demo" and vault is not None:
        raise ValueError("demo_external_vault_forbidden")
    if mode == "demo":
        vault = verify_demo_vault()
    read_only = request.cli_read_only
    if read_only is None:
        read_only = environ.get("DOXAGON_READ_ONLY", "").lower() in {"1", "true", "yes"}
    return _Selection(
        vault=vault,
        state=choose(request.cli_state, "DOXAGON_STATE", "state"),
        artifacts=choose(request.cli_artifacts, "DOXAGON_ARTIFACTS", "artifacts"),
        mode=mode,
        access_mode="read-only" if read_only or mode in {"demo", "hosted-readonly"} else "read-write",
    )


def _bootstrap(selection: _Selection) -> BootstrapDiagnostic:
    return BootstrapDiagnostic(
        mode=selection.mode,
        requested_access_mode=selection.access_mode,
        remediation="configure_vault",
    )


def _capabilities(mode: DeploymentMode, access_mode: AccessMode) -> frozenset[Capability]:
    capabilities = {Capability.WORKSPACE_READ, Capability.CONTENT_READ, Capability.ASSET_READ}
    if access_mode == "read-write":
        capabilities.update(
            {
                Capability.KNOWLEDGE_WRITE,
                Capability.PROJECT_WRITE,
                Capability.JOB_RUN,
                Capability.ARTIFACT_PROMOTE,
                Capability.PUBLICATION_BUILD,
            }
        )
    if mode == "developer":
        capabilities.add(Capability.DEVELOPER_RUN)
    return frozenset(capabilities)


def _converge_authority(services: VaultServices, access_mode: AccessMode) -> str | None:
    """Fence and roll forward in write mode; observe only in read-only mode.

    Returns a coarse diagnostic code when the vault cannot be served, else None.
    """

    if access_mode == "read-write":
        try:
            services.acquire_write_fence()
        except WriterFenceUnsupported:
            return "writer_fence_unsupported"
        except WriterFenceUnavailable:
            return "writer_fence_unavailable"
        except RecoveryUnresolved:
            return "recovery_unresolved"
        return None

    # A read-only open may not fence, and unfenced mutation is forbidden, so it
    # can only wait for a live writer to return the generation to even.
    deadline = time.monotonic() + READ_ONLY_RECOVERY_WAIT_SECONDS
    while has_pending_transaction(services.config.vault_root):
        if time.monotonic() >= deadline:
            return "recovery_pending_read_only"
        time.sleep(0.05)
    return None


def open_workspace(
    request: WorkspaceOpenRequest, *, platform_version: str = DEFAULT_PLATFORM_VERSION
) -> WorkspaceOpenResult:
    """Open an explicit vault without consulting cwd, checkout, or legacy roots."""

    selection = _selection(request)
    bootstrap = _bootstrap(selection)
    if selection.vault is None:
        return NotConfigured(state="not_configured", bootstrap=bootstrap)

    metadata_path = selection.vault / ".doxagon" / "vault.toml"
    if not metadata_path.is_file():
        return NotConfigured(state="not_configured", bootstrap=bootstrap)
    metadata = parse_v1_metadata(metadata_path, bootstrap, platform_version=platform_version)
    if isinstance(metadata, MetadataOnly):
        return metadata

    try:
        parsed = tomllib.loads(metadata_path.read_text(encoding="utf-8"))
        paths = parsed["paths"]
        knowledge_root = selection.vault / paths["knowledge"]
        projects_root = selection.vault / paths["projects"]
        media_root = selection.vault / paths["media"]
        state_root = selection.state or selection.vault / paths["state"]
        artifact_root = selection.artifacts or selection.vault / paths["artifacts"]
        required_roots = (knowledge_root, projects_root, media_root, state_root, artifact_root)
        if not all(root.is_dir() for root in required_roots):
            raise ValueError("required vault root is missing")
    except (KeyError, TypeError, ValueError, tomllib.TOMLDecodeError):
        return SchemaDiagnostic(
            state="schema_diagnostic", bootstrap=bootstrap, metadata=metadata, diagnostic="invalid_supported_metadata"
        )

    config = WorkspaceConfig(
        vault_id=metadata.vault_id,
        vault_root=selection.vault.resolve(),
        knowledge_root=knowledge_root.resolve(),
        projects_root=projects_root.resolve(),
        media_root=media_root.resolve(),
        state_root=state_root.resolve(),
        artifact_root=artifact_root.resolve(),
        access_mode=selection.access_mode,
        deployment_mode=selection.mode,
        schema_version=metadata.schema_version,
        effective_schema_digest="stage-i-empty-schema",
        workspace_fingerprint=f"stage-i:{selection.vault.resolve()}",
        capabilities=_capabilities(selection.mode, selection.access_mode),
    )
    services = VaultServices(config)

    # Recovery precedes schema validation. An interrupted authoritative write
    # leaves exactly the order/checksum mismatch the extension check rejects,
    # so gating recovery behind that check would strand a roll-forward-eligible
    # transaction as a permanent SchemaDiagnostic.
    recovery = _converge_authority(services, selection.access_mode)
    if recovery is not None:
        services.close()
        return RecoveryDiagnostic(
            state="recovery_diagnostic", bootstrap=bootstrap, metadata=metadata, diagnostic=recovery
        )

    diagnostic = _extension_manifest_diagnostic(selection.vault, parsed)
    if diagnostic is not None:
        services.close()
        return SchemaDiagnostic(
            state="schema_diagnostic", bootstrap=bootstrap, metadata=metadata, diagnostic=diagnostic
        )

    return Ready(state="ready", config=config, services=services)


def initialize_empty_vault(destination: Path, *, vault_id: UUID | None = None) -> Path:
    """Create a serving synthetic vault from reviewed package-owned empties."""

    destination = destination.resolve()
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("vault destination must be empty")
    destination.mkdir(parents=True, exist_ok=True)
    vault_id = vault_id or UUID("00000000-0000-7000-8000-000000000001")
    control = destination / ".doxagon"
    for directory in (
        destination / "knowledge",
        destination / "projects",
        destination / "media",
        control / "extensions",
        control / "state",
        control / "artifacts",
    ):
        directory.mkdir(parents=True, exist_ok=True)

    empty_logos = resources.files("doxagon.resources").joinpath("empty-logos.yaml").read_text(encoding="utf-8")
    (destination / "knowledge" / "logos.yaml").write_text(empty_logos, encoding="utf-8")
    # Orientation is written here, not left to sync: an agent may open a fresh
    # vault before any sync runs. Imported locally so bootstrap does not pull in
    # the toolchain's provider machinery.
    from doxagon.toolchain import packaged_agents_md

    (destination / "AGENTS.md").write_bytes(packaged_agents_md())
    (control / "extensions" / "manifest-v1.json").write_text(
        json.dumps({"format": 1, "extensions": []}, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    (control / "project-output-inventory-v1.json").write_text(
        json.dumps({"format": 1, "outputs": []}, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    (control / "authority-generation.json").write_text(
        json.dumps({"format": 1, "generation": 0, "active_txid": None}, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    (control / "vault.toml").write_text(
        f'''vault_format = {SUPPORTED_VAULT_FORMAT}
vault_id = "{vault_id}"
name = "synthetic-empty"

[platform]
requires = ">=0.1,<0.2"

[schema]
base = "1.0.0"
extensions = []
extension_manifest = ".doxagon/extensions/manifest-v1.json"

[paths]
knowledge = "knowledge"
projects = "projects"
media = "media"
state = ".doxagon/state"
artifacts = ".doxagon/artifacts"

[features]
presentations = false
''',
        encoding="utf-8",
    )
    return destination


def workspace_request_for_vault(vault: Path) -> WorkspaceOpenRequest:
    """Convenience constructor for explicit callers and focused tests."""

    return WorkspaceOpenRequest(
        cli_workspace=None,
        cli_vault=vault,
        cli_state=None,
        cli_artifacts=None,
        cli_config=None,
        cli_read_only=None,
        cli_mode=None,
        environ=MappingProxyType({}),
        invocation_cwd=Path.cwd(),
        standard_config_path=Path.home() / ".config" / "doxagon" / "config.toml",
    )
