"""Public synthetic proofs for the installed recipes and image machinery."""

from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re
import runpy
import sys

from click.testing import CliRunner
from PIL import Image
import pytest

from doxagon import toolchain
from doxagon.renderings.document_changes import registry
from doxagon.renderings.document_images import ImageDocument, decode_image
from doxagon.renderings.document_inspection import inspect_document
from doxagon.renderings.project import resolve_document_project
from scripts.dox import cli
from tests.authored_vault import write_authored_project

SKILLS = Path(__file__).parents[1] / "src/doxagon/resources/skills"
SKILL = SKILLS / "presentation-motion"


def test_installed_sample_builds_n_components_without_a_checkout_or_network(tmp_path):
    vault = tmp_path / "relocated"
    toolchain.sync_agent_resources(vault)
    installed = vault / ".pi/skills/presentation-motion"
    builder = runpy.run_path(str(installed / "scripts/build_sample.py"))
    report = builder["build"](tmp_path / "preview", installed / "samples/transfer.json")
    html = (tmp_path / "preview/index.html").read_text()
    assert (
        report["case"],
        len(report["images"]),
        all(x["provenance"] == "synthetic-code-fixture" for x in report["images"]),
        'src="http' in html,
        'href="http' in html,
        "data:image/" in (tmp_path / "preview/plate-shell.html").read_text(),
    ) == (
        "transfer.json",
        len(json.loads((installed / "samples/profiles.json").read_text())) * len(builder["COMPONENTS"]),
        True,
        False,
        False,
        False,
    )


def test_reviewed_component_images_replace_every_fixture(tmp_path):
    builder = runpy.run_path(str(SKILL / "scripts/build_sample.py"))
    profiles = json.loads((SKILL / "samples/profiles.json").read_text())
    for style in profiles:
        for component in builder["COMPONENTS"]:
            target = tmp_path / "assets" / style / f"{component}.png"
            target.parent.mkdir(parents=True, exist_ok=True)
            image = Image.new("RGBA", (32, 32), (10, 20, 30, 0))
            image.putpixel((1, 1), (10, 20, 30, 255))
            image.save(target)
    report = builder["build"](tmp_path / "preview", SKILL / "samples/inspection.json", tmp_path / "assets")
    assert {item["provenance"] for item in report["images"]} == {"user-supplied"}


def test_every_component_list_matches_the_choreography():
    script = (SKILL / "kit/choreography.js").read_text()
    javascript = re.findall(r"'(\w+)'", re.search(r"COMPONENTS = \[(.*?)\]", script)[1])
    python = runpy.run_path(str(SKILL / "scripts/build_sample.py"))["COMPONENTS"]
    cases = [
        [item["key"] for item in json.loads(path.read_text())["components"]]
        for path in (SKILL / "samples").glob("*.json")
        if path.name != "profiles.json"
    ]
    assert all(keys == javascript == python for keys in cases)


def test_skills_cross_reference_animation_and_image_components():
    """Every relative link resolves, and image skills point agents at animated components."""
    broken = []
    for skill in SKILLS.glob("*/SKILL.md"):
        text = skill.read_text()
        for target in re.findall(r"\]\((\./[^)#]+)", text):
            if not (skill.parent / target).resolve().exists():
                broken.append(f"{skill.parent.name}: {target}")
    mentions = {
        name: "./../presentation-motion/" in (SKILLS / name / "SKILL.md").read_text()
        for name in ["presentation-context", "presentation-document", "visual-definition", "visual-concept-brainstorm"]
    }
    motion = (SKILL / "SKILL.md").read_text()
    assert (broken, mentions, "./../visual-definition/SKILL.md" in motion) == (
        [],
        dict.fromkeys(mentions, True),
        True,
    )


def test_style_variation_changes_material_not_only_palette():
    profiles = json.loads((SKILL / "samples/profiles.json").read_text())
    assert (
        len(profiles) >= 6
        and len({p["font"] for p in profiles.values()}) == 3
        and all(
            len({p[field] for p in profiles.values()}) == len(profiles)
            for field in ["pattern", "stroke", "roughness", "image_direction"]
        )
    )


def test_vendor_manifest_matches_the_shipped_bytes():
    manifest = json.loads((SKILL / "vendor/manifest.json").read_text())
    assert all(
        sha256((SKILL / "vendor" / row["path"]).read_bytes()).hexdigest() == row["sha256"] for row in manifest["files"]
    )


@pytest.mark.parametrize("transparent", [False, True])
def test_alpha_checker_distinguishes_opaque_png_from_cutout(tmp_path, transparent):
    source = tmp_path / "component.png"
    image = Image.new("RGBA", (20, 20), (100, 120, 140, 0 if transparent else 255))
    image.putpixel((10, 10), (100, 120, 140, 255))
    image.save(source)
    checker = runpy.run_path(str(SKILL / "scripts/check_alpha.py"))
    assert checker["inspect"](source)["ok"] is transparent


def test_sample_builder_refuses_to_write_selected_document_paths(tmp_path):
    builder = runpy.run_path(str(SKILL / "scripts/build_sample.py"))
    with pytest.raises(ValueError, match="not outputs/document"):
        builder["build"](tmp_path / "outputs/document", SKILL / "samples/inspection.json")


@pytest.mark.parametrize("style", ["studio", "porcelain", "stencil", "textile"])
def test_n_component_requests_generate_and_select_through_doxagon(tmp_path, monkeypatch, style):
    vault = tmp_path / "vault"
    project_path = write_authored_project(vault)
    toolchain.sync_agent_resources(vault)
    installed = vault / ".pi/skills/presentation-motion"
    provider = installed / "scripts/fixture-executable"
    text = (installed / "scripts/fixture_provider.py").read_text().split("\n", 1)[1]
    provider.write_text(f"#!{sys.executable}\n" + text)
    provider.chmod(0o700)
    monkeypatch.setenv("DOXAGON_ROOT", str(vault))
    monkeypatch.setenv("DOXAGON_IMAGE_GENERATOR", str(provider))
    project = resolve_document_project(project_path.name)
    runner = CliRunner()

    def command(args):
        result = runner.invoke(cli, args)
        assert result.exit_code == 0, result.output
        return json.loads(result.output)

    def asset_request(request, name):
        view = inspect_document(project)
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(request))
        plan = tmp_path / f"{name}-plan.json"
        command(
            ["document", "asset-plan", "--project", project.slug, "--snapshot", view.summary["snapshot"]]
            + ["--request", str(path), "--output", str(plan)]
        )
        command(["document", "apply", "--project", project.slug, str(plan)])

    helper = runpy.run_path(str(installed / "scripts/asset_requests.py"))
    case = json.loads((installed / "samples/inspection.json").read_text())
    whole = next(item["id"] for item in inspect_document(project).items if item["kind"] == "image")
    slots = {"core": "slot-0", "scanner": "slot-1"}
    files = helper["requests"](case, style, "study", slots, whole)
    assert "bind-slots.template.json" in files and len([name for name in files if name.startswith("create-")]) == 7
    for name, request in files.items():
        if name.startswith("create-"):
            asset_request(request, name.removesuffix(".json"))
    registered = registry(inspect_document(project))["assets"]
    assert len([key for key in registered if key.startswith("study-")]) == len(case["components"])
    assert registered["study-core"]["references"] and not registered["study-scanner"]["references"]
    original = project.path("outputs/document/observatory.html").read_bytes()
    for component in slots:
        plan_file = tmp_path / f"{component}-generation.json"
        command(
            ["document", "generation-plan", "--project", project.slug]
            + ["--snapshot", inspect_document(project).summary["snapshot"], "--asset", f"study-{component}"]
            + ["--variants", "1", "--output", str(plan_file)]
        )
        plan = json.loads(plan_file.read_text())
        assert plan["provider"]["model"] == "motion-fixture-no-generation"
        job = command(["document", "generation-run", "--project", project.slug, "--key", component, str(plan_file)])
        assert job["status"] == "succeeded"
    assert project.path("outputs/document/observatory.html").read_bytes() == original
    asset_request(
        {"operation": "bind-slots", "associations": {slot: f"study-{name}" for name, slot in slots.items()}}, "bind"
    )
    selected = {}
    for component, slot in slots.items():
        variants = registry(inspect_document(project))["assets"][f"study-{component}"]["variants"]
        variant, candidate = next(iter(variants.items()))
        assert candidate["provenance"] == "generated"
        asset_request(
            {"operation": "select-image", "key": f"study-{component}", "variant": variant, "slots": [slot]},
            f"select-{component}",
        )
        document = ImageDocument(project.path("outputs/document/observatory.html").read_bytes())
        raw, _ = decode_image(document.url(next(item for item in document.slots if item.attrs.get("id") == slot)))
        selected[component] = Image.open(BytesIO(raw)).convert("RGBA").getchannel("A").getextrema()
    assert selected == {"core": (0, 255), "scanner": (0, 255)}
