"""Explicit, read-only adapter for the pre-vault co-located layout."""

from __future__ import annotations

from pathlib import Path
from uuid import NAMESPACE_URL, uuid5
import warnings

from doxagon.workspace import Capability, VaultServices, WorkspaceConfig

_legacy_adapter_open_total = 0
_warned = False


def legacy_adapter_open_total() -> int:
    """Return local adapter-use count for headless compatibility observability."""

    return _legacy_adapter_open_total


def open(root: Path) -> VaultServices:
    """Open a legacy root only when the caller explicitly names it.

    This adapter maps the historical ``library/`` and ``theses/`` layout to the
    same instance-scoped graph repositories. It never participates in normal
    vault selection and performs no migration or rewrite.
    """

    global _legacy_adapter_open_total, _warned
    legacy_root = root.resolve()
    knowledge_root = legacy_root / "library"
    if not knowledge_root.is_dir():
        raise ValueError("legacy root must contain library/")

    _legacy_adapter_open_total += 1
    if not _warned:
        warnings.warn("legacy adapter enabled for explicit root", RuntimeWarning, stacklevel=2)
        _warned = True

    config = WorkspaceConfig(
        vault_id=uuid5(NAMESPACE_URL, legacy_root.as_uri()),
        vault_root=legacy_root,
        knowledge_root=knowledge_root,
        projects_root=legacy_root / "theses",
        media_root=legacy_root / "media",
        state_root=legacy_root / ".cache",
        artifact_root=legacy_root / ".artifacts",
        access_mode="read-only",
        deployment_mode="local",
        schema_version="legacy",
        effective_schema_digest="legacy-adapter",
        workspace_fingerprint=f"legacy:{legacy_root}",
        capabilities=frozenset({Capability.WORKSPACE_READ, Capability.CONTENT_READ, Capability.ASSET_READ}),
    )
    return VaultServices(config)
