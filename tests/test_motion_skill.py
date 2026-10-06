"""Platform-side proofs for presentation-motion. The skill's own checks live in its self-test."""

from pathlib import Path
import re
import runpy
import shutil
import sys

from doxagon import toolchain

ROOT = Path(__file__).parents[1]
SKILLS = ROOT / "src/doxagon/resources/skills"
SKILL = SKILLS / "presentation-motion"
DOX = [sys.executable, str(ROOT / "scripts/dox.py")]


def test_installed_skill_self_test_passes_without_the_checkout(tmp_path):
    toolchain.sync_agent_resources(tmp_path / "vault")
    installed = tmp_path / "vault/.pi/skills/presentation-motion/scripts/selftest.py"
    report = runpy.run_path(str(installed))["run"](tmp_path / "evidence", with_pipeline=True, dox=DOX)
    assert [row for row in report["checks"] if not row["pass"]] == []


def test_self_test_reports_a_broken_identity_and_a_tampered_dependency(tmp_path):
    # Copy the sibling skills too: cross-skill links are part of the contract.
    shutil.copytree(SKILLS, tmp_path / "skills", ignore=shutil.ignore_patterns("__pycache__"))
    copy = tmp_path / "skills/presentation-motion"
    model = copy / "kit/math/space-model.js"
    model.write_text(
        model.read_text().replace("[[1, 1, 2], [2, 1, 1], [1, 2, 1]]", "[[1, 1, 2], [2, 1, 1], [1, 2, 2]]", 1)
    )
    vendor = copy / "vendor/gsap.min.js"
    vendor.write_text(vendor.read_text() + "\n")
    report = runpy.run_path(str(copy / "scripts/selftest.py"))["run"](tmp_path / "evidence")
    failed = {row["name"] for row in report["checks"] if not row["pass"]}
    assert failed == {
        "space-path-ends-at-A-keeps-diagonal-and-volume",
        "space-cayley-hamilton-cubic",
        "vendor-bytes-match-manifest",
    }


def test_skills_cross_reference_animation_and_image_components():
    """Every relative link resolves, and image skills point agents at animated components."""
    broken = []
    for skill in SKILLS.glob("*/SKILL.md"):
        for target in re.findall(r"\]\((\./[^)#]+)", skill.read_text()):
            if not (skill.parent / target).resolve().exists():
                broken.append(f"{skill.parent.name}: {target}")
    mentions = {
        name: "./../presentation-motion/" in (SKILLS / name / "SKILL.md").read_text()
        for name in ["presentation-context", "presentation-document", "visual-definition", "visual-concept-brainstorm"]
    }
    motion = (SKILL / "SKILL.md").read_text()
    assert (broken, mentions, "./../visual-definition/SKILL.md" in motion) == ([], dict.fromkeys(mentions, True), True)
