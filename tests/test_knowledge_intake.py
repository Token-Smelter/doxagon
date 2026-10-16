"""A fresh vault takes a first source from admission to validated graph with the agent as extractor."""

import os
from pathlib import Path
import subprocess
import sys

import frontmatter
import pytest
import yaml

from doxagon.config import knowledge_root

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "src/doxagon/resources/skills/dox-knowledge/evals/files/cold-proofing-notes.md"

ANSWER = """===DOXA===
---
belief: "Overnight cold proofing makes shaped loaves easier to score"
status: draft
tags: [{tag}]
provenance:
  method: extraction
  phantasia: p-cold-proofing-notes
---
Cold dough holds its shape under the blade.
===END_DOXA===

===DOXA===
---
belief: "Cold proofing for 14 hours thickens the crust"
status: draft
tags: []
provenance:
  method: extraction
  phantasia: p-cold-proofing-notes
---
===END_DOXA===

===EVIDENCE===
---
assertion: "Loaves proofed 14 hours at 4 C had 3.1 mm crust versus 2.4 mm same-day"
source: "Marsh Street Test Kitchen - Overnight Proof Trial (2021)"
type: empirical
strength: moderate
status: provisional
---
> "3.1 mm versus 2.4 mm on average"
===END_EVIDENCE===

===EDGES===
source|target|edge_type|confidence|rationale
NEW:2|NEW:1|{edge_type}|low|Both effects come from the dough staying cold and firm
===END_EDGES===
"""


def dox(vault: Path, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "DOXAGON_ROOT": str(vault)}
    return subprocess.run(
        [sys.executable, "-c", "from scripts.dox import cli; cli()", *args],
        cwd=cwd or REPO, env={**env, "PYTHONPATH": str(REPO)}, capture_output=True, text=True, timeout=120,
    )


@pytest.fixture
def vault(tmp_path):
    root = tmp_path / "vault"
    result = dox(root, "init", str(root))
    assert result.returncode == 0, result.stderr
    added = dox(root, "phantasia", "add", str(FIXTURE), "--title", "Cold proofing notes")
    assert added.returncode == 0, added.stderr
    return root


def answer(tmp_path: Path, *, tag: str = "", edge_type: str = "elaborates") -> Path:
    path = tmp_path / "answer.md"
    path.write_text(ANSWER.format(tag=tag, edge_type=edge_type))
    return path


def test_init_installs_schema_and_skills_for_both_agent_layouts(vault):
    schema = yaml.safe_load((vault / "knowledge/schema.yaml").read_text())
    assert (
        {"supports", "elaborates"} <= set(schema["edge_types"]),
        (vault / ".claude/skills/dox-knowledge/SKILL.md").is_file(),
        (vault / ".claude/skills/doxagon-onboarding/SKILL.md").is_file(),
        (vault / "CLAUDE.md").read_text(),
    ) == (True, True, True, "@AGENTS.md\n")


def test_prompt_carries_the_admitted_source(vault):
    result = dox(vault, "extract", "p-cold-proofing-notes", "--prompt")
    assert "Marsh Street Test Kitchen" in result.stdout


def test_dry_run_writes_nothing(vault, tmp_path):
    result = dox(vault, "extract", "p-cold-proofing-notes", "--response", str(answer(tmp_path)), "--dry-run")
    assert (result.returncode, list((vault / "knowledge").glob("doxai/*.md"))) == (0, [])


def test_applied_extraction_lands_in_the_declared_knowledge_root_and_validates(vault, tmp_path):
    applied = dox(vault, "extract", "p-cold-proofing-notes", "--response", str(answer(tmp_path)))
    phantasia = frontmatter.load(vault / "knowledge/phantasiai/p-cold-proofing-notes.md")
    edges = yaml.safe_load((vault / "knowledge/logos.yaml").read_text())["edges"]
    assert (
        applied.returncode,
        len(list((vault / "knowledge/doxai").glob("d-*.md"))),
        len(list((vault / "knowledge/evidence").glob("e-*.md"))),
        [edge["type"] for edge in edges],
        phantasia["status"],
        (vault / "library").exists(),
        dox(vault, "validate").returncode,
    ) == (0, 2, 1, ["elaborates"], "processed", False, 0)


@pytest.mark.parametrize("bad", [{"edge_type": "inspires"}, {"tag": "domain:baking"}])
def test_invalid_candidate_is_refused_before_any_write(vault, tmp_path, bad):
    result = dox(vault, "extract", "p-cold-proofing-notes", "--response", str(answer(tmp_path, **bad)))
    assert (result.returncode, "nothing was written" in result.stderr,
            list((vault / "knowledge").glob("doxai/*.md"))) == (1, True, [])


def test_extract_requires_an_explicit_mode(vault):
    result = dox(vault, "extract", "p-cold-proofing-notes")
    assert "choose exactly one of --prompt, --response FILE or --gemini" in result.stderr


def test_knowledge_root_follows_vault_metadata_and_falls_back_to_library(tmp_path):
    (tmp_path / "v/.doxagon").mkdir(parents=True)
    (tmp_path / "v/.doxagon/vault.toml").write_text('[paths]\nknowledge = "notes"\n')
    assert (knowledge_root(tmp_path / "v"), knowledge_root(tmp_path)) == (tmp_path / "v/notes", tmp_path / "library")
