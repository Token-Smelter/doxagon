"""Validation primitives for the Markdown/YAML knowledge graph."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import frontmatter


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    severity: str = "error"


@dataclass
class ValidationReport:
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity != "error"]

    @property
    def valid(self) -> bool:
        return not self.errors

    def extend(self, other: "ValidationReport") -> None:
        self.issues.extend(other.issues)


class GraphIntegrityError(ValueError):
    """Raised when graph state cannot be loaded or persisted without loss."""

    def __init__(self, report: ValidationReport):
        self.report = report
        details = "; ".join(issue.message for issue in report.errors[:5])
        if len(report.errors) > 5:
            details += f"; and {len(report.errors) - 5} more"
        super().__init__(details or "Graph integrity validation failed")


def normalize_edge(edge: Any) -> dict[str, Any] | None:
    """Return the canonical mapping form without dropping metadata."""
    if isinstance(edge, dict):
        return dict(edge)
    if isinstance(edge, list) and len(edge) >= 3:
        return {"source": edge[0], "target": edge[1], "type": edge[2]}
    return None


def validate_edge_records(
    edges: Iterable[Any],
    *,
    doxa_ids: set[str],
    valid_edge_types: set[str],
) -> ValidationReport:
    """Validate edge identity and endpoints while allowing distinct typed pairs."""
    report = ValidationReport()
    exact_counts: Counter[tuple[str, str, str]] = Counter()
    pair_types: dict[tuple[str, str], set[str]] = {}

    for index, raw_edge in enumerate(edges):
        edge = normalize_edge(raw_edge)
        if edge is None:
            report.issues.append(ValidationIssue("malformed_edge", f"Edge {index} has an unsupported shape"))
            continue

        source = edge.get("source")
        target = edge.get("target")
        edge_type = edge.get("type")
        if not all(isinstance(value, str) and value.strip() for value in (source, target, edge_type)):
            report.issues.append(
                ValidationIssue("malformed_edge", f"Edge {index} must have non-empty source, target, and type")
            )
            continue

        source = source.strip()
        target = target.strip()
        edge_type = edge_type.strip()

        for role, endpoint in (("source", source), ("target", target)):
            endpoint_upper = endpoint.upper()
            if endpoint_upper == "NEW" or endpoint_upper.startswith("NEW:") or endpoint_upper == "STALE" or endpoint_upper.startswith("STALE:"):
                report.issues.append(
                    ValidationIssue("placeholder_endpoint", f"Edge {index} has placeholder {role}: {endpoint}")
                )
            if endpoint.startswith("e-"):
                report.issues.append(
                    ValidationIssue("evidence_endpoint", f"Edge {index} uses evidence as {role}: {endpoint}")
                )
            if endpoint not in doxa_ids:
                report.issues.append(
                    ValidationIssue("dangling_endpoint", f"Edge {index} has dangling {role}: {endpoint}")
                )

        if edge_type not in valid_edge_types:
            report.issues.append(
                ValidationIssue("noncanonical_type", f"Edge {index} has noncanonical type: {edge_type}")
            )
        if source == target:
            report.issues.append(ValidationIssue("self_loop", f"Edge {index} is a self-loop: {source}"))

        exact_counts[(source, target, edge_type)] += 1
        pair_types.setdefault((source, target), set()).add(edge_type)

    for (source, target, edge_type), count in sorted(exact_counts.items()):
        if count > 1:
            report.issues.append(
                ValidationIssue(
                    "exact_duplicate",
                    f"Exact duplicate edge appears {count} times: {source} -> {target} ({edge_type})",
                )
            )

    for (source, target), types in sorted(pair_types.items()):
        if len(types) > 1:
            report.issues.append(
                ValidationIssue(
                    "parallel_typed_pair",
                    f"Intentional parallel typed pair: {source} -> {target} ({', '.join(sorted(types))})",
                    severity="warning",
                )
            )

    return report


def validate_doxai(
    doxai_dir: Path,
    *,
    valid_domains: set[str],
) -> ValidationReport:
    """Validate belief presence and controlled domain tags."""
    report = ValidationReport()
    if not doxai_dir.exists():
        return report

    for path in sorted(doxai_dir.glob("**/*.md")):
        if path.stem.upper() == "README":
            continue
        try:
            document = frontmatter.load(path)
        except Exception as exc:
            report.issues.append(ValidationIssue("invalid_frontmatter", f"{path.stem}: {exc}"))
            continue

        belief = document.get("belief")
        if not isinstance(belief, str) or not belief.strip():
            report.issues.append(ValidationIssue("missing_belief", f"{path.stem}: missing non-empty belief"))

        tags = document.get("tags", [])
        if not isinstance(tags, list):
            report.issues.append(ValidationIssue("malformed_domain", f"{path.stem}: tags must be a list"))
            continue
        for tag in tags:
            if not isinstance(tag, str):
                report.issues.append(ValidationIssue("malformed_domain", f"{path.stem}: non-string tag {tag!r}"))
                continue
            if not tag.startswith("domain:"):
                continue
            domain = tag.partition(":")[2]
            if not domain or domain not in valid_domains:
                report.issues.append(
                    ValidationIssue("malformed_domain", f"{path.stem}: unregistered domain tag {tag!r}")
                )

    return report


def validate_library(
    *,
    edges: Iterable[Any],
    doxai_dir: Path,
    valid_edge_types: set[str],
    valid_domains: set[str],
) -> ValidationReport:
    doxa_ids = {
        path.stem
        for path in doxai_dir.glob("**/*.md")
        if path.stem.upper() != "README"
    } if doxai_dir.exists() else set()
    report = validate_edge_records(edges, doxa_ids=doxa_ids, valid_edge_types=valid_edge_types)
    report.extend(validate_doxai(doxai_dir, valid_domains=valid_domains))
    return report
