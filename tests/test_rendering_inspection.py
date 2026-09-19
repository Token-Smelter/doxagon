"""Source intake must inform an agent without becoming an execution/admission path."""

import hashlib
import json
import os
from pathlib import Path

from click.testing import CliRunner
import pytest

from doxagon.renderings import inspection
from doxagon.renderings.inspection import HtmlInspectionError, inspect_html_bytes, inspect_html_file
from scripts.dox import cli

SOURCE = b'''<!doctype html>
<title>A shared scene</title>
<link rel="stylesheet" href="https://example.invalid/fonts.css">
<style>.stage { position: sticky; background: url('assets/plate.png'); }</style>
<section id="opening">
  <p class="step">One assertion.</p>
  <p class="step">Another assertion.</p>
  <canvas id="visual"></canvas>
</section>
<section id="closing"><p data-cue="done">A conclusion.</p></section>
<audio controls src="https://example.invalid/voice.mp3"></audio>
<script>
const text = "fetch() is text, not a network call";
function frame() {
  const now = performance.now();
  const progress = scrollY / innerHeight;
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);
</script>
'''


def test_inspection_records_structure_and_motion_hints_without_inventing_states() -> None:
    report = inspect_html_bytes(SOURCE)
    assert (
        report["source"],
        [(section["id"], section["cue_candidates"]) for section in report["sections"]],
        {item["hint"] for item in report["lexical_hints"]},
        report["assurance"]["admission"],
    ) == (
        {"sha256": hashlib.sha256(SOURCE).hexdigest(), "bytes": len(SOURCE), "encoding": "utf-8"},
        [("opening", 2), ("closing", 1)],
        {"animation_frames", "scroll_input", "viewport_geometry", "time_input"},
        "not-assessed",
    )


def test_literal_dependencies_and_block_identity_are_preserved_without_resolution() -> None:
    report = inspect_html_bytes(SOURCE)
    script = SOURCE.split(b"<script>", 1)[1].split(b"</script>", 1)[0]
    assert (
        [(item["value"], item["kind"], item["line"]) for item in report["references"]],
        report["blocks"][1]["sha256"],
    ) == (
        [("https://example.invalid/fonts.css", "network", 3), ("assets/plate.png", "relative", 4),
         ("https://example.invalid/voice.mp3", "network", 11)],
        hashlib.sha256(script).hexdigest(),
    )


def test_agent_cli_inspects_without_vault_services_or_dependency_reads(tmp_path: Path, monkeypatch) -> None:
    import scripts.dox as command

    def forbidden(*args, **kwargs):
        pytest.fail("intake must not open a vault or load its graph")

    monkeypatch.setattr(command, "open_workspace", forbidden)
    monkeypatch.setattr(command, "load_graph", forbidden)
    source = tmp_path / "source.html"
    source.write_bytes(SOURCE.replace(b"</script>", b"while (true) {}\n</script>"))
    before = source.read_bytes()
    result = CliRunner().invoke(cli, ["rendering", "inspect-html", str(source), "--json"])
    assert (result.exit_code, json.loads(result.output)["assurance"], source.read_bytes(), list(tmp_path.iterdir())) == (
        0,
        {"executed": False, "resources_read": False, "network_used": False, "vault_changed": False,
         "admission": "not-assessed", "dependency_closure": "not-proven"},
        before, [source],
    )


def test_same_source_has_same_report_independent_of_file_location(tmp_path: Path) -> None:
    first, second = tmp_path / "first.html", tmp_path / "second.html"
    first.write_bytes(SOURCE)
    second.write_bytes(SOURCE)
    assert inspect_html_file(first) == inspect_html_file(second)


def test_inert_json_and_script_comments_do_not_become_executable_hints() -> None:
    source = b'''<script type="application/json">{"text":"requestAnimationFrame()"}</script>
<script>// fetch('private')\nconst text = 'localStorage';</script>'''
    report = inspect_html_bytes(source)
    assert ([item["kind"] for item in report["blocks"]], report["lexical_hints"]) == (["data", "classic"], [])


def test_module_and_compound_resource_candidates_are_not_silently_resolved() -> None:
    source = b'''<script type="module">import { draw } from './draw.js';</script>
<style>@import "theme.css";</style>
<img srcset="small.png 1x, large.png 2x">'''
    report = inspect_html_bytes(source)
    assert [(item["attribute"], item["value"], item["kind"]) for item in report["references"]] == [
        ("module-specifier", "./draw.js", "relative"),
        ("literal-url", "theme.css", "relative"),
        ("srcset", "small.png 1x, large.png 2x", "compound"),
    ]


def test_parser_failures_are_reported_without_a_traceback(tmp_path: Path, monkeypatch) -> None:
    def unsupported(*args):
        raise AssertionError("unsupported parser syntax")

    monkeypatch.setattr(inspection._Inventory, "feed", unsupported)
    source = tmp_path / "source.html"
    source.write_bytes(SOURCE)
    result = CliRunner().invoke(cli, ["rendering", "inspect-html", str(source), "--json"])
    assert (result.exit_code, json.loads(result.output)["code"]) == (1, "HTML_INTAKE_PARSE")


def test_svg_self_closing_shapes_do_not_produce_html_adaptation_findings() -> None:
    report = inspect_html_bytes(b'<svg><defs><linearGradient><stop offset="0"/></linearGradient></defs><rect/></svg>\n<div/>')
    assert [(item["code"], item["line"]) for item in report["findings"]] == [("HTML_INTAKE_NONVOID_SELF_CLOSE", 2)]


def test_embedded_resources_are_hashed_not_dumped_into_the_report() -> None:
    value = "data:image/png;base64," + "A" * 100000
    report = inspect_html_bytes(f'<img src="{value}">'.encode())
    item = report["references"][0]
    assert (item["kind"], item["abridged"], item["sha256"], len(json.dumps(report)) < 2000) == (
        "embedded", True, hashlib.sha256(value.encode()).hexdigest(), True,
    )


def test_unclosed_scripts_are_reported_as_incomplete_not_safe() -> None:
    report = inspect_html_bytes(b"<script>requestAnimationFrame(work)")
    assert (report["blocks"][0]["closed"], report["blocks"][0]["sha256"], report["findings"][0]["code"]) == (
        False, None, "HTML_INTAKE_UNCLOSED_BLOCK",
    )


def test_duplicate_anchors_and_event_handlers_require_author_review() -> None:
    report = inspect_html_bytes(b'<p id="same"></p><button id="same" onclick="work()">Go</button>')
    assert {item["code"] for item in report["findings"]} == {"HTML_INTAKE_DUPLICATE_ID", "HTML_INTAKE_EVENT_HANDLER"}


@pytest.mark.parametrize("source", [b"\xff", b"<p>\x00</p>"])
def test_non_text_sources_are_refused(source: bytes) -> None:
    with pytest.raises(HtmlInspectionError, match="UTF-8|NUL"):
        inspect_html_bytes(source)


@pytest.mark.parametrize("kind", ["missing", "directory", "symlink", "fifo"])
def test_only_explicit_regular_files_are_read(tmp_path: Path, kind: str) -> None:
    path = tmp_path / "input"
    if kind == "directory":
        path.mkdir()
    elif kind == "symlink":
        other = tmp_path / "other"
        other.write_bytes(SOURCE)
        path.symlink_to(other)
    elif kind == "fifo":
        os.mkfifo(path)
    with pytest.raises(HtmlInspectionError) as error:
        inspect_html_file(path)
    assert error.value.code == "HTML_INTAKE_SOURCE"


def test_file_changed_during_read_is_refused(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "input.html"
    source.write_bytes(SOURCE)
    original = os.fstat
    calls = 0

    def fstat(descriptor):
        nonlocal calls
        calls += 1
        if calls == 2:
            source.write_bytes(SOURCE + b"changed")
        return original(descriptor)

    monkeypatch.setattr(inspection.os, "fstat", fstat)
    with pytest.raises(HtmlInspectionError) as error:
        inspect_html_file(source)
    assert error.value.code == "HTML_INTAKE_SOURCE_CHANGED"


@pytest.mark.parametrize("limit", ["bytes", "elements", "items"])
def test_source_and_report_growth_are_bounded(monkeypatch, limit: str) -> None:
    if limit == "bytes":
        monkeypatch.setattr(inspection, "MAX_HTML_BYTES", 16)
    elif limit == "elements":
        monkeypatch.setattr(inspection, "MAX_ELEMENTS", 2)
    else:
        monkeypatch.setattr(inspection, "MAX_ITEMS", 2)
    with pytest.raises(HtmlInspectionError) as error:
        inspect_html_bytes(SOURCE)
    assert error.value.code == "HTML_INTAKE_LIMIT"


def test_json_cli_distinguishes_failed_inspection_from_admission_findings(tmp_path: Path) -> None:
    result = CliRunner().invoke(cli, ["rendering", "inspect-html", str(tmp_path / "absent"), "--json"])
    assert (result.exit_code, json.loads(result.output)["code"]) == (1, "HTML_INTAKE_SOURCE")
