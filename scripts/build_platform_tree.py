#!/usr/bin/env python3
"""Materialize the public platform tree from the reviewed allow-list.

Selection is opt-in and sourced from Git-tracked files only, so untracked
scratch in a working copy can never reach the staging tree. Every selected path
is checked against the forbidden list before anything is copied, which makes a
carelessly widened include glob fail loudly instead of shipping private files.

The staging tree this produces is the only thing that may become a public
commit. The working repository is never pushed to a public origin.

Path review alone cannot tell a synthetic fixture from real private material,
so reviewed files are also scanned for credential and operator-identity
patterns. Rules live in code rather than the policy file: adding an allow-list
entry is a routine edit, and weakening the content scan should not be.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml


# A finding is evidence of a credential, an operator's identity, or internal
# orchestration state. Each rule carries what it protects, because a reviewer
# deciding whether a hit is a false positive needs to know what is at stake.
CONTENT_RULES: dict[str, tuple[str, str]] = {
    "pem-private-key": (
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
        "Private key material.",
    ),
    "aws-access-key": (
        r"AKIA[0-9A-Z]{16}",
        "AWS access key id.",
    ),
    "github-token": (
        r"gh[pousr]_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{50,}",
        "GitHub access token.",
    ),
    "slack-token": (
        r"xox[baprs]-[A-Za-z0-9-]{10,}",
        "Slack API token.",
    ),
    "google-api-key": (
        r"AIza[0-9A-Za-z_-]{35}",
        "Google API key.",
    ),
    "model-provider-key": (
        r"\bsk-(?:ant-)?[A-Za-z0-9_-]{20,}",
        "Model provider API key.",
    ),
    "cloud-project-id": (
        r"(?i)\bproject[_ ]?id\b\s*[:=]\s*[\"'][A-Za-z0-9][A-Za-z0-9-]{5,}[\"']",
        "A named cloud project belonging to one deployment.",
    ),
    "operator-home-path": (
        r"/(?:home|Users)/[A-Za-z0-9._-]+/",
        "An operator's home directory; also breaks every other install.",
    ),
    "internal-identity": (
        r"@doxagon\.local|\bt@e\.com\b",
        "Internal or placeholder committer identity.",
    ),
    "orchestration-id": (
        r"\b(?:wo|brew)-[0-9a-f]{8}\b",
        "Private orchestration work-order or brew id.",
    ),
    "orchestration-trailer": (
        r"Sourcerer-(?:Brew|WOs?|Session)",
        "Private orchestration trailer.",
    ),
}


def _tracked_files(repo: Path) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "-z"], capture_output=True, check=True
    )
    return [path for path in result.stdout.decode("utf-8").split("\0") if path]


def _matches(path: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        if pattern.endswith("/**"):
            if path.startswith(pattern[:-2]):
                return True
        elif path == pattern or fnmatch.fnmatch(path, pattern):
            return True
    return False


def _entry_paths(policy: dict, section: str) -> list[str]:
    return [entry["path"] for entry in policy.get(section, [])]


def _allowed_rules(policy: dict) -> dict[str, set[str]]:
    """Reviewed per-path exceptions, each naming the single rule it silences."""
    allowances: dict[str, set[str]] = {}
    for entry in policy.get("content_allowances", []):
        allowances.setdefault(entry["path"], set()).add(entry["rule"])
    return allowances


def scan_content(repo: Path, policy: dict, paths: list[str]) -> list[str]:
    """Report credential and identity evidence in the files that would publish.

    Binary files are skipped: the rules describe text, and decoding arbitrary
    bytes yields noise rather than findings. An unknown rule name in an
    allowance is itself reported, so a renamed rule cannot silently disarm one.
    """
    allowances = _allowed_rules(policy)
    compiled = {rule: re.compile(pattern) for rule, (pattern, _) in CONTENT_RULES.items()}
    findings = []
    for path, rules in sorted(allowances.items()):
        for rule in sorted(rules - set(CONTENT_RULES)):
            findings.append(f"unknown content rule in allowance: {path}: {rule}")
    for path in paths:
        source = repo / path
        if source.is_symlink() or not source.is_file():
            continue
        data = source.read_bytes()
        if b"\0" in data:
            continue
        exempt = allowances.get(path, set())
        for number, line in enumerate(data.decode("utf-8", "replace").splitlines(), 1):
            for rule, expression in compiled.items():
                if rule not in exempt and expression.search(line):
                    findings.append(f"{rule}: {path}:{number}: {CONTENT_RULES[rule][1]}")
    return findings


def check_repository(repo: Path, policy_path: Path) -> list[str]:
    """Check that the entire tracked repository satisfies the public boundary.

    Unlike extraction, this refuses even excluded private files: changing a
    repository's visibility exposes every tracked path. Contents are scanned for
    credential and identity evidence; history and hosting metadata still need a
    separate review, because neither is visible from a working tree.
    """
    repo = repo.resolve()
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    if policy.get("format") != 1:
        raise SystemExit(f"{policy_path}: unsupported allow-list format")
    tracked = set(_tracked_files(repo))
    include, forbidden = policy.get("include", []), policy.get("forbidden", [])
    issues = []
    for path in sorted(tracked):
        if _matches(path, forbidden):
            issues.append(f"forbidden: {path}")
        elif not _matches(path, include):
            issues.append(f"not reviewed for publication: {path}")
        source = repo / path
        try:
            target = source.resolve(strict=True).relative_to(repo).as_posix()
        except (OSError, RuntimeError, ValueError):
            issues.append(f"missing file or link outside repository: {path}")
            continue
        if target not in tracked or not _matches(target, include) or _matches(target, forbidden):
            issues.append(f"target is not a reviewed tracked file: {path}")
    for path in _entry_paths(policy, "required_before_public"):
        if path not in tracked or not (repo / path).is_file():
            issues.append(f"missing required public file: {path}")
    issues.extend(scan_content(repo, policy, sorted(tracked)))
    return issues


def build(repo: Path, destination: Path, policy_path: Path) -> dict:
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    if policy.get("format") != 1:
        raise SystemExit(f"{policy_path}: unsupported allow-list format")

    include = policy.get("include", [])
    forbidden = policy.get("forbidden", [])
    deferred = _entry_paths(policy, "deferred")

    tracked = _tracked_files(repo)
    selected = sorted(path for path in tracked if _matches(path, include))
    unclassified = sorted(
        path
        for path in tracked
        if not _matches(path, include)
        and not _matches(path, forbidden)
        and not _matches(path, deferred)
    )
    if not selected:
        raise SystemExit("allow-list selected no files; refusing to build an empty tree")

    leaked = [path for path in selected if _matches(path, forbidden)]
    if leaked:
        raise SystemExit(
            "allow-list selects forbidden paths; refusing to build:\n  "
            + "\n  ".join(leaked)
        )

    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)

    entries = []
    for path in selected:
        source = repo / path
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        entries.append(
            {"path": path, "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
        )

    produced = sorted(
        item.relative_to(destination).as_posix()
        for item in destination.rglob("*")
        if item.is_file()
    )
    if produced != selected:
        raise SystemExit("staging tree does not match the selection; refusing to continue")

    manifest = {"format": 1, "files": entries}
    (destination / ".platform-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )

    return {
        "selected": selected,
        "unclassified": unclassified,
        "required": policy.get("required_before_public", []),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path, nargs="?")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check the complete tracked repository for publication without copying files.",
    )
    parser.add_argument(
        "--policy", type=Path, default=Path("publication/platform-files.yaml")
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Refuse to build while any tracked path is unclassified.",
    )
    args = parser.parse_args()

    repo = args.repo.resolve()
    policy_path = args.policy if args.policy.is_absolute() else repo / args.policy
    if args.check:
        if args.destination:
            parser.error("--check does not accept a destination")
        issues = check_repository(repo, policy_path)
        for issue in issues:
            print(issue)
        print(f"Publication boundary: {len(issues)} issue(s)")
        return 1 if issues else 0
    if args.destination is None:
        parser.error("destination is required unless --check is used")

    report = build(repo, args.destination.resolve(), policy_path)

    print(f"selected {len(report['selected'])} files -> {args.destination}")
    by_top: dict[str, int] = {}
    for path in report["selected"]:
        by_top[path.split("/", 1)[0]] = by_top.get(path.split("/", 1)[0], 0) + 1
    for top, count in sorted(by_top.items(), key=lambda item: -item[1]):
        print(f"  {count:>5}  {top}")

    if report["required"]:
        print("\nRequired before the repository may be public:")
        for entry in report["required"]:
            print(f"  {entry['path']}: {entry['reason'].strip()}")

    unclassified = report["unclassified"]
    if unclassified:
        print(f"\nUNCLASSIFIED ({len(unclassified)} tracked paths matched no section):")
        for path in unclassified[:40]:
            print(f"  {path}")
        if len(unclassified) > 40:
            print(f"  ... and {len(unclassified) - 40} more")
        if args.strict:
            print("\nrefusing to build under --strict")
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
