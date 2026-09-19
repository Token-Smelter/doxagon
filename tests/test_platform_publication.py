"""A public checkout must reject private files even if extraction omits them."""

from pathlib import Path
import re
import subprocess

import pytest
import yaml

from scripts.build_platform_tree import CONTENT_RULES, check_repository


@pytest.fixture
def repository(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    policy = repo / "policy.yaml"
    policy.write_text(yaml.safe_dump({
        "format": 1,
        "include": ["src/**", "README.md", "policy.yaml"],
        "forbidden": ["projects/**", "src/.env"],
        "deferred": [{"path": "internal.md", "reason": "Pending review"}],
        "required_before_public": [{"path": "README.md"}],
    }))
    (repo / "README.md").write_text("Public setup\n")
    (repo / "src").mkdir()
    (repo / "src/main.py").write_text("print('example')\n")
    stage(repo)
    return repo, policy


def stage(repo):
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)


def test_ignored_scratch_is_excluded_but_staged_private_files_fail(repository):
    repo, policy = repository
    (repo / "scratch.txt").write_text("Untracked local notes")
    assert check_repository(repo, policy) == []
    for name in ["projects/example/notes.json", "src/.env", "internal.md"]:
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic private material")
        subprocess.run(["git", "-C", str(repo), "add", name], check=True)
    issues = check_repository(repo, policy)
    assert "forbidden: projects/example/notes.json" in issues
    assert "forbidden: src/.env" in issues  # Even though src/** is included.
    assert "not reviewed for publication: internal.md" in issues


def test_reviewed_internal_links_pass_but_external_or_untracked_targets_fail(repository, tmp_path):
    repo, policy = repository
    (repo / "src/alias.py").symlink_to("main.py")
    stage(repo)
    assert check_repository(repo, policy) == []
    (tmp_path / "private.txt").write_text("Synthetic private material")
    (repo / "src/outside.txt").symlink_to(tmp_path / "private.txt")
    subprocess.run(["git", "-C", str(repo), "add", "src/outside.txt"], check=True)
    (repo / "src/local.txt").write_text("Local only")
    (repo / "src/untracked.txt").symlink_to("local.txt")
    subprocess.run(["git", "-C", str(repo), "add", "src/untracked.txt"], check=True)
    issues = check_repository(repo, policy)
    assert "missing file or link outside repository: src/outside.txt" in issues
    assert "target is not a reviewed tracked file: src/untracked.txt" in issues


def test_reviewed_path_still_fails_on_credential_and_identity_content(repository):
    repo, policy = repository
    (repo / "src/main.py").write_text(
        "KEY = 'AKIA0123456789ABCDEF'\n"
        "HOME = '/home/operator/vault/notes.md'\n"
        "TRAILER = 'Sourcerer-Brew: brew-16ec4884'\n"
    )
    stage(repo)
    issues = check_repository(repo, policy)
    assert "aws-access-key: src/main.py:1: AWS access key id." in issues
    assert any(issue.startswith("operator-home-path: src/main.py:2:") for issue in issues)
    assert any(issue.startswith("orchestration-id: src/main.py:3:") for issue in issues)


def test_allowance_silences_only_its_own_rule_and_rejects_unknown_rules(repository):
    repo, policy = repository
    (repo / "src/main.py").write_text(
        "FIXTURE = '/home/someone/secret'\nKEY = 'AKIA0123456789ABCDEF'\n"
    )
    stage(repo)
    document = yaml.safe_load(policy.read_text())
    document["content_allowances"] = [
        {"path": "src/main.py", "rule": "operator-home-path"},
        {"path": "src/main.py", "rule": "renamed-rule"},
    ]
    policy.write_text(yaml.safe_dump(document))
    stage(repo)
    issues = check_repository(repo, policy)
    assert not any(issue.startswith("operator-home-path:") for issue in issues)
    assert "aws-access-key: src/main.py:2: AWS access key id." in issues
    assert "unknown content rule in allowance: src/main.py: renamed-rule" in issues


def test_every_content_rule_detects_its_own_documented_example():
    examples = {
        "pem-private-key": "-----BEGIN RSA PRIVATE KEY-----",
        "aws-access-key": "AKIA0123456789ABCDEF",
        "github-token": "ghp_" + "a" * 36,
        "slack-token": "xoxb-0123456789-abcdefghij",
        "google-api-key": "AIza" + "b" * 35,
        "model-provider-key": "sk-ant-0123456789abcdefghij",
        "cloud-project-id": 'PROJECT_ID = "acme-prod-8a0c"',
        "operator-home-path": "/home/operator/notes.md",
        "internal-identity": "worker@doxagon.local",
        "orchestration-id": "wo-4c367d89",
        "orchestration-trailer": "Sourcerer-WOs: wo-65a27b7a",
    }
    assert set(examples) == set(CONTENT_RULES)
    for rule, example in examples.items():
        assert re.search(CONTENT_RULES[rule][0], example), rule


def test_deleted_required_file_fails(repository):
    repo, policy = repository
    (repo / "README.md").unlink()
    stage(repo)
    assert "missing required public file: README.md" in check_repository(repo, policy)


def test_check_cli_resolves_policy_from_selected_repository_without_writing(repository, tmp_path):
    repo, _ = repository
    script = Path(__file__).resolve().parents[1] / "scripts/build_platform_tree.py"
    before = sorted(path.relative_to(repo).as_posix() for path in repo.rglob("*"))
    import sys
    result = subprocess.run(
        [sys.executable, str(script), "--repo", str(repo), "--policy", "policy.yaml", "--check"],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert sorted(path.relative_to(repo).as_posix() for path in repo.rglob("*")) == before
