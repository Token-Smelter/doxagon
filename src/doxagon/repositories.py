"""Filesystem repositories bound to one opened vault instance."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import frontmatter
import yaml

if TYPE_CHECKING:  # pragma: no cover - typing only
    from doxagon.wal import WriteAheadLog

from doxagon.validation import GraphIntegrityError, ValidationIssue, ValidationReport, normalize_edge, validate_edge_records


@dataclass(frozen=True)
class FilesystemKnowledgeRepository:
    """Read graph authority from an explicit vault knowledge root."""

    knowledge_root: Path

    @property
    def doxai_root(self) -> Path:
        return self.knowledge_root / "doxai"

    @property
    def diegeses_root(self) -> Path:
        return self.knowledge_root / "diegeses"

    def doxai(self) -> list[tuple[str, dict[str, Any], str]]:
        if not self.doxai_root.is_dir():
            return []
        records: list[tuple[str, dict[str, Any], str]] = []
        for path in sorted(self.doxai_root.glob("**/*.md")):
            if path.stem.upper() == "README":
                continue
            try:
                document = frontmatter.load(path)
            except Exception as error:
                raise GraphIntegrityError(
                    ValidationReport([ValidationIssue("invalid_frontmatter", f"{path.name}: {error}")])
                ) from error
            records.append((path.stem, dict(document.metadata), document.content))
        return records

    def diegeses(self) -> list[tuple[str, dict[str, Any]]]:
        if not self.diegeses_root.is_dir():
            return []
        records: list[tuple[str, dict[str, Any]]] = []
        for path in sorted(self.diegeses_root.glob("*.md")):
            try:
                records.append((path.stem.removeprefix("n-"), dict(frontmatter.load(path).metadata)))
            except Exception as error:
                raise GraphIntegrityError(
                    ValidationReport([ValidationIssue("invalid_frontmatter", f"{path.name}: {error}")])
                ) from error
        return records

    def doxa_ids(self) -> set[str]:
        """Return node identities without loading record bodies."""

        if not self.doxai_root.is_dir():
            return set()
        return {path.stem for path in self.doxai_root.glob("**/*.md") if path.stem.upper() != "README"}

    def authority_files(self) -> list[Path]:
        files: list[Path] = []
        for directory in (self.doxai_root, self.knowledge_root / "evidence", self.diegeses_root):
            if directory.is_dir():
                files.extend(sorted(directory.glob("**/*.md")))
        for name in ("logos.yaml", "schema.yaml"):
            path = self.knowledge_root / name
            if path.is_file():
                files.append(path)
        return files


@dataclass(frozen=True)
class FilesystemEdgeRepository:
    """Read validated edge records from an explicit vault knowledge root."""

    knowledge_root: Path

    @property
    def logos_path(self) -> Path:
        return self.knowledge_root / "logos.yaml"

    @property
    def schema_path(self) -> Path:
        return self.knowledge_root / "schema.yaml"

    def edge_types(self) -> set[str]:
        """Return the edge-type vocabulary this vault's own schema declares."""

        if not self.schema_path.is_file():
            return set()
        schema = yaml.safe_load(self.schema_path.read_text(encoding="utf-8")) or {}
        return set(schema.get("edge_types", {})) if isinstance(schema, dict) else set()

    def edge_records(self, doxa_ids: set[str]) -> list[dict[str, Any]]:
        if not self.logos_path.is_file():
            raw: dict[str, Any] = {"edges": []}
        else:
            loaded = yaml.safe_load(self.logos_path.read_text(encoding="utf-8"))
            raw = {"edges": []} if loaded is None else loaded
        if not isinstance(raw, dict) or not isinstance(raw.get("edges"), list):
            raise GraphIntegrityError(ValidationReport([ValidationIssue("malformed_logos", "logos.yaml must contain an edges list")]))

        report = validate_edge_records(raw["edges"], doxa_ids=doxa_ids, valid_edge_types=self.edge_types())
        if not report.valid:
            raise GraphIntegrityError(report)
        return [edge for raw_edge in raw["edges"] if (edge := normalize_edge(raw_edge)) is not None]

    def edge_document(self, edges: list[dict[str, Any]]) -> bytes:
        """Serialize edge records to the canonical on-disk logos representation."""

        return yaml.safe_dump(
            {"edges": edges}, default_flow_style=False, allow_unicode=True, sort_keys=False
        ).encode("utf-8")

    def write_edges(self, edges: Any, *, doxa_ids: set[str], wal: WriteAheadLog) -> str:
        """Validate edges against this vault's schema, then durably replace logos.yaml.

        Validation happens before any staging so a rejected edge set never
        reaches the write-ahead log and never opens a transaction.
        """

        if not isinstance(edges, list):
            raise GraphIntegrityError(
                ValidationReport([ValidationIssue("malformed_logos", "logos.yaml must contain an edges list")])
            )
        report = validate_edge_records(edges, doxa_ids=doxa_ids, valid_edge_types=self.edge_types())
        if not report.valid:
            raise GraphIntegrityError(report)
        return wal.commit_replace(self.logos_path, self.edge_document(edges))
