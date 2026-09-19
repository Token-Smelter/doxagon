"""Human-facing guidance for workspace bootstrap outcomes.

The API surface deliberately emits coarse machine codes and never prose, paths,
or vault identity, because a diagnostic response must not leak what it could not
open. This module is the other half of that split: it maps those codes to text a
person can act on. Keeping it separate is what lets the wire format stay coarse
while the command line stays usable.
"""

from __future__ import annotations


_UNKNOWN = (
    "The workspace could not be opened, and this build has no specific guidance\n"
    "for that outcome. Run `dox workspace` for the raw diagnostic code."
)

_REMEDIATION: dict[str, str] = {
    "vault_not_configured": (
        "No vault is configured.\n"
        "\n"
        "  dox init PATH            create a vault and start using it\n"
        "  dox workspace --demo     look at the packaged sample vault first\n"
        "\n"
        "A vault is never created implicitly. From inside the process a missing\n"
        "vault and a mistyped --vault path look identical, so inventing one would\n"
        "hide the typo behind an empty graph."
    ),
    "unknown_vault_format": (
        "This vault was written by a newer Doxagon than the one installed.\n"
        "Upgrade the platform, or open the vault with the release that wrote it.\n"
        "Nothing was read beyond the format marker."
    ),
    "incompatible_platform": (
        "This vault declares a platform requirement the installed release does\n"
        "not satisfy. Install a version inside its declared range.\n"
        "Nothing was read beyond the version marker."
    ),
    "schema_major_mismatch": (
        "This vault's knowledge schema is a different major version than the\n"
        "installed platform supports. Install a compatible release, or run an\n"
        "explicit migration. Startup never migrates a vault on its own."
    ),
    "invalid_fixed_envelope": (
        "The vault metadata file could not be parsed far enough to identify it.\n"
        "Check that .doxagon/vault.toml is present and well-formed."
    ),
    "invalid_supported_metadata": (
        "The vault metadata parsed, but its declared paths are wrong: a required\n"
        "root is missing or not a directory. Compare .doxagon/vault.toml against\n"
        "the directories actually present."
    ),
    "extension_missing": (
        "A schema extension named in the manifest is absent from the vault.\n"
        "Restore it, or remove its entry from .doxagon/extensions/manifest-v1.json\n"
        "and from the extensions list in .doxagon/vault.toml."
    ),
    "extension_checksum_mismatch": (
        "A schema extension's contents no longer match its recorded checksum.\n"
        "Either the file was edited outside a schema transaction, or it is\n"
        "damaged. Repair it on a copy and re-record the manifest."
    ),
    "extension_manifest_invalid": (
        "The extension manifest is not a valid v1 manifest. Repair it on a copy;\n"
        "the vault will not serve content while its schema is unverifiable."
    ),
    "extension_manifest_order_mismatch": (
        "The extension manifest lists the same extensions as vault.toml but in a\n"
        "different order. Order is part of the effective schema, so the two must\n"
        "agree exactly."
    ),
    "extension_manifest_path_mismatch": (
        "An extension path in the manifest is not a valid vault-relative path.\n"
        "Extension paths may not escape the vault or traverse links."
    ),
    "writer_fence_unavailable": (
        "Another process holds this vault's writer fence. Close the other server\n"
        "or command and retry. Two writers are never allowed to proceed at once."
    ),
    "writer_fence_unsupported": (
        "This filesystem cannot prove exclusive write ownership, so the vault\n"
        "will not open for writing. Move it to a local filesystem that supports\n"
        "flock and atomic no-replace renames. Read-only access still works."
    ),
    "recovery_unresolved": (
        "This vault has an interrupted write that cannot be proven to converge,\n"
        "so it will not serve. Restore a coherent snapshot. Keep the current\n"
        "state for diagnosis; recovery never guesses at a rollback."
    ),
    "recovery_pending_read_only": (
        "This vault has a write in flight and was opened read-only, which may not\n"
        "recover it. Wait for the writer to finish, or open it read-write so the\n"
        "interrupted transaction can roll forward."
    ),
}


def remediation_for(code: str | None) -> str:
    """Return actionable guidance for a coarse bootstrap diagnostic code."""

    if code is None:
        return _UNKNOWN
    return _REMEDIATION.get(code, _UNKNOWN)


def known_codes() -> frozenset[str]:
    """Return every code this module can explain."""

    return frozenset(_REMEDIATION)
