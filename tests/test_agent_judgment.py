"""Integrate and audit hand context to the agent and refuse invalid answers before any write."""

import json
import re
import subprocess

import pytest
import yaml

from .test_knowledge_intake import REPO, dox

SKILLS = REPO / "src/doxagon/resources/skills"
POT = "d-baking-inside-a-preheated-lidded-pot-traps-steam"
OVEN = "d-home-ovens-lose-steam-too-quickly-for-a-good-oven"


@pytest.fixture
def vault(tmp_path):
    root = tmp_path / "vault"
    assert dox(root, "init", str(root)).returncode == 0
    for belief in ("Home ovens lose steam too quickly for a good oven spring",
                   "Baking inside a preheated lidded pot traps steam around the loaf"):
        assert dox(root, "capture", belief).returncode == 0
    assert dox(root, "link", POT, OVEN, "contradicts").returncode == 0
    return root


def edges(vault):
    return [(e["source"], e["target"], e["type"])
            for e in yaml.safe_load((vault / "knowledge/logos.yaml").read_text())["edges"]]


def respond(vault, tmp_path, command, text, *flags):
    answer = tmp_path / "answer.md"
    answer.write_text(text)
    return dox(vault, command, "--response", str(answer), *flags)


def test_integrate_lists_clusters_then_gives_a_unit_with_vocabulary(vault):
    overview = json.loads(dox(vault, "integrate", "--context").stdout)
    unit = json.loads(dox(vault, "integrate", "--context", "--cluster", "all").stdout)
    assert (overview["clusters"][0]["size"], len(unit["beliefs"]), "resolves" in unit["edge_types"]) == (2, 2, True)


def test_integrate_adds_a_valid_edge(vault, tmp_path):
    answer = f"===EDGE===\nsource: {POT}\ntarget: {OVEN}\ntype: resolves\nrationale: The lid keeps steam in.\n===END_EDGE===\n"
    assert respond(vault, tmp_path, "integrate", answer).returncode == 0
    assert (POT, OVEN, "resolves") in edges(vault)


@pytest.mark.parametrize("block", [
    f"source: {POT}\ntarget: d-not-a-belief\ntype: supports\nrationale: x",
    f"source: {POT}\ntarget: {OVEN}\ntype: inspires\nrationale: x",
    f"source: {POT}\ntarget: {OVEN}\ntype: supports",
])
def test_integrate_refuses_any_invalid_edge_and_writes_nothing(vault, tmp_path, block):
    before = edges(vault)
    good = f"===EDGE===\nsource: {OVEN}\ntarget: {POT}\ntype: requires\nrationale: fine\n===END_EDGE===\n"
    result = respond(vault, tmp_path, "integrate", good + f"===EDGE===\n{block}\n===END_EDGE===\n")
    assert (result.returncode, edges(vault)) == (1, before)


def test_audit_context_carries_both_endpoint_beliefs(vault):
    edge = json.loads(dox(vault, "audit", "--context").stdout)["edges"][0]
    assert (edge["type"], edge["source_belief"].startswith("Baking inside")) == ("contradicts", True)


def test_audit_correction_retypes_the_edge(vault, tmp_path):
    answer = (f"===AUDIT===\nsource: {POT}\ntarget: {OVEN}\ncurrent_type: contradicts\nverdict: CORRECT\n"
              "correct_type: resolves\nalias: offers a way out of\nconfidence: high\n"
              "rationale: The lid solves the lost-steam problem.\n===END_AUDIT===\n")
    before = edges(vault)
    dry = respond(vault, tmp_path, "audit", answer, "--dry-run")
    assert (dry.returncode, edges(vault)) == (0, before)
    assert respond(vault, tmp_path, "audit", answer).returncode == 0
    assert ((POT, OVEN, "resolves") in edges(vault), (POT, OVEN, "contradicts") in edges(vault)) == (True, False)


def test_audit_refuses_a_verdict_for_an_edge_that_does_not_exist(vault, tmp_path):
    answer = (f"===AUDIT===\nsource: {OVEN}\ntarget: {POT}\ncurrent_type: supports\nverdict: CONFIRM\n"
              "rationale: x\n===END_AUDIT===\n")
    result = respond(vault, tmp_path, "audit", answer)
    assert (result.returncode, "no edge" in result.stderr) == (1, True)


@pytest.mark.parametrize("reference,command,blocks", [
    ("extract.md", "extract", ("DOXA", "EVIDENCE", "EDGES", "DUPLICATE")),
    ("integrate.md", "integrate", ("EDGE",)),
    ("audit.md", "audit", ("AUDIT",)),
])
def test_each_reference_documents_the_blocks_its_command_parses(reference, command, blocks):
    text = (SKILLS / "dox-knowledge/references" / reference).read_text()
    assert all(f"==={name}===" in text and f"===END_{name}===" in text for name in blocks)


def test_extract_reference_example_validates(tmp_path):
    from doxagon.extract import parse_extraction_response, validate_extraction

    text = (SKILLS / "dox-knowledge/references/extract.md").read_text()
    example = re.search(r"```\n(===DOXA===.*?===END_DUPLICATE===)\n```", text, re.DOTALL).group(1)
    assert validate_extraction(parse_extraction_response(example)).errors == []


def test_adapter_template_reports_valid_capabilities_and_refuses_unsupported_mandates(tmp_path):
    from doxagon.renderings.document_generation import validate_provider_capabilities

    template = SKILLS / "image-provider/scripts/adapter_template.py"
    capabilities = json.loads(subprocess.run(["python3", str(template), "--capabilities"],
                                             capture_output=True, text=True, check=True).stdout)
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("x")
    refused = subprocess.run(["python3", str(template), "--prompt-file", str(prompt), "--output", str(tmp_path),
                              "--image-size", "4K", "--aspect-ratio", "1:1"], capture_output=True, text=True)
    assert (validate_provider_capabilities(capabilities)["schema"], refused.returncode) == (
        "doxagon.provider-capabilities/1", 2)
