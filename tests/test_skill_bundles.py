"""Nested agent resources retain the same ownership rules as SKILL.md."""

from hashlib import sha256
import json

import pytest

from doxagon import toolchain


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    source = tmp_path / "source" / "motion"
    (source / "samples").mkdir(parents=True)
    (source / "SKILL.md").write_text("Motion skill")
    (source / "samples" / "plate.png").write_bytes(b"\x89PNG\x00fixture")
    monkeypatch.setattr(toolchain, "SKILL_ROOT", source.parent)
    monkeypatch.setattr(toolchain, "platform_sha", lambda: "platform-one")
    vault = tmp_path / "vault"
    toolchain.sync_agent_resources(vault)
    return source, vault, vault / ".pi/skills/motion"


def test_nested_resources_update_and_report_skill_freshness(bundle):
    source, vault, installed = bundle
    (source / "samples/plate.png").write_bytes(b"new bytes")
    assert toolchain.skill_status(vault)["motion"]["status"] == "stale"
    result = toolchain.sync_agent_resources(vault)
    assert (
        "motion/samples/plate.png" in result["updated"],
        (installed / "samples/plate.png").read_bytes(),
        toolchain.skill_status(vault)["motion"]["status"],
        toolchain.sync_agent_resources(vault)["changed"],
    ) == (True, b"new bytes", "current", False)


def test_foreign_nested_file_keeps_its_ownership_digest_until_forced(bundle):
    source, vault, installed = bundle
    target = installed / "samples/plate.png"
    original = target.read_bytes()
    target.write_bytes(b"vault edit")
    (source / "samples/plate.png").write_bytes(b"new platform version")
    for _ in range(2):
        report = toolchain.sync_agent_resources(vault)
        assert "motion/samples/plate.png" in report["foreign"]
    manifest = json.loads((vault / toolchain.MANIFEST_PATH).read_text())
    assert manifest["resources"]["motion/samples/plate.png"]["sha256"] == sha256(original).hexdigest()
    toolchain.sync_agent_resources(vault, force=True)
    assert target.read_bytes() == b"new platform version"


@pytest.mark.parametrize("edited", [False, True])
def test_retirement_removes_only_unchanged_owned_files(bundle, edited):
    source, vault, installed = bundle
    target = installed / "samples/plate.png"
    custom = installed / "samples/custom.txt"
    custom.write_text("Not managed")
    if edited:
        target.write_text("Keep this")
    (source / "samples/plate.png").unlink()
    result = toolchain.sync_agent_resources(vault, force=True)
    assert (target.exists(), custom.read_text(), result["foreign"], result["removed"]) == (
        edited,
        "Not managed",
        ["motion/samples/plate.png"] if edited else [],
        [] if edited else ["motion/samples/plate.png"],
    )


@pytest.mark.parametrize("link_parent", [False, True])
def test_sync_never_follows_nested_destination_symlinks(bundle, tmp_path, link_parent):
    _, vault, installed = bundle
    target = installed / "samples/plate.png"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "plate.png").write_bytes(b"Outside vault")
    target.unlink()
    if link_parent:
        target.parent.rmdir()
        target.parent.symlink_to(outside, target_is_directory=True)
    else:
        target.symlink_to(outside / "plate.png")
    report = toolchain.sync_agent_resources(vault, force=True)
    assert (
        report["foreign"],
        (outside / "plate.png").read_bytes(),
        toolchain.skill_status(vault)["motion"]["status"],
    ) == (["motion/samples/plate.png"], b"Outside vault", "foreign")


def test_unknown_nested_collision_is_not_adopted_or_pruned(bundle):
    source, vault, installed = bundle
    (source / "samples/local.txt").write_text("Platform file")
    target = installed / "samples/local.txt"
    target.write_text("Already mine")
    toolchain.sync_agent_resources(vault)
    (source / "samples/local.txt").unlink()
    toolchain.sync_agent_resources(vault)
    assert target.read_text() == "Already mine"


def test_retired_manifest_path_cannot_escape_the_skills_directory(bundle, tmp_path):
    _, vault, _ = bundle
    path = vault / toolchain.MANIFEST_PATH
    manifest = json.loads(path.read_text())
    outside = tmp_path / "keep.txt"
    outside.write_text("Keep")
    manifest["resources"][str(outside)] = {"sha256": sha256(outside.read_bytes()).hexdigest()}
    path.write_text(json.dumps(manifest))
    toolchain.sync_agent_resources(vault)
    assert outside.read_text() == "Keep"
