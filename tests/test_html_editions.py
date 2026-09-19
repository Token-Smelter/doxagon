"""Producer-to-artifact coverage for the bounded HTML Edition slice."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
from click.testing import CliRunner

import doxagon.html_editions.cli as html_edition_cli
from doxagon.html_editions import HtmlEditionCompiler, HtmlEditionError, inspect_edition
from doxagon.html_editions.inspector import inspect_edition_bytes
from doxagon.html_editions.public import PublicEdgeV1, PublicEvidenceV1, PublicGraphExcerptV1
from doxagon.html_editions.contracts import MAX_BODY_BYTES, ContentDocument, load_content_document_from_fd
from doxagon.workspace import initialize_empty_vault
from scripts.dox import cli


def _source(mode: str = "article", body: object = "Readable offline content.") -> dict[str, object]:
    source: dict[str, object] = {
        "schema": "doxagon.content-document/1",
        "document_key": "sample",
        "mode": mode,
        "metadata": {"title": "Sample Edition"},
        "theme_id": "default",
        "sections": [{"section_id": "opening", "kind": "prose", "title": "Opening", "level": 2, "body": body}],
        "resources": [],
        "features": {},
    }
    if mode == "graph-brief":
        source["graph_scope"] = {"node_ids": []}
    return source


@pytest.mark.parametrize("mode", ["deck", "article", "interactive-essay", "report", "graph-brief"])
def test_compiler_emits_deterministic_direct_offline_sections_for_each_mode(tmp_path: Path, mode: str) -> None:
    document = ContentDocument.parse(_source(mode))

    first = HtmlEditionCompiler().compile(document, tmp_path)
    second = HtmlEditionCompiler().compile(document, tmp_path)

    assert first.html == second.html
    assert b'<main id="dox-content"><section id="section-opening"' in first.html
    assert b"<iframe" not in first.html
    assert b"https://" not in first.html
    assert inspect_edition_bytes(first.html).edition_id == first.edition_id


@pytest.mark.parametrize(
    ("source_url", "accepted"),
    [
        ("https://example.com/source", True),
        ("file:///private/source", False),
        ("https://user:secret@example.com/source", False),
        ("https://example.com/source#private", False),
    ],
)
def test_public_evidence_accepts_only_safe_https_source_urls(source_url: str, accepted: bool) -> None:
    evidence = {"id": "e-one", "assertion": "a", "source_label": "Example", "source_url": source_url, "type": "source", "strength": "high", "status": "validated", "summary_or_quote": "q"}

    if accepted:
        assert PublicEvidenceV1.parse(evidence).value["source_url"] == source_url
    else:
        with pytest.raises(HtmlEditionError) as rejected:
            PublicEvidenceV1.parse(evidence)
        assert rejected.value.code == "HTML_EDITION_PUBLIC_PROJECTION_REJECTED"


def test_public_projection_rejects_path_leakage_and_receipts_exclude_it(tmp_path: Path) -> None:
    with pytest.raises(HtmlEditionError) as leaked:
        PublicEvidenceV1.parse({"id": "e-one", "assertion": "a", "source_label": "/private", "type": "source", "strength": "high", "status": "validated", "summary_or_quote": "q"})
    assert leaked.value.code == "HTML_EDITION_PUBLIC_PROJECTION_REJECTED"
    graph = PublicGraphExcerptV1.parse({"schema": "doxagon.public-graph/1", "nodes": [], "edges": [], "evidence": [], "scope": {}})
    assert graph.nodes == ()
    receipt = HtmlEditionCompiler().compile(ContentDocument.parse(_source()), tmp_path).receipt.as_dict()
    assert set(receipt) == {"schema", "authoring_revision", "compile_input_hash", "edition_id", "file_sha256", "targets"}


def test_compiler_rejects_executable_body_and_hash_bound_body_changes(tmp_path: Path) -> None:
    with pytest.raises(HtmlEditionError) as rejected:
        HtmlEditionCompiler().compile(ContentDocument.parse(_source(body="<script>alert(1)</script>")), tmp_path)
    assert rejected.value.code == "HTML_EDITION_SANITIZER_REJECTED"

    body = "Trusted body\n".encode()
    body_root = tmp_path / "bodies"
    body_root.mkdir()
    (body_root / "opening.md").write_bytes(body)
    reference = {
        "schema": "doxagon.body-source-ref/1",
        "root": "document-bodies",
        "key": "opening.md",
        "sha256": hashlib.sha256(body).hexdigest(),
        "media_type": "text/markdown",
    }
    compiled = HtmlEditionCompiler().compile(ContentDocument.parse(_source(body=reference)), tmp_path)
    assert b"Trusted body" in compiled.html
    (body_root / "opening.md").write_text("changed", encoding="utf-8")
    with pytest.raises(HtmlEditionError) as changed:
        HtmlEditionCompiler().compile(ContentDocument.parse(_source(body=reference)), tmp_path)
    assert changed.value.code == "HTML_EDITION_BODY_HASH_MISMATCH"


def _document_root(vault: Path, document: str = "sample") -> Path:
    root = vault / "projects" / "thesis" / "outputs" / "content-documents" / document
    root.mkdir(parents=True)
    return root


def test_cli_uses_ready_workspace_and_safe_one_file_output(tmp_path: Path) -> None:
    vault = initialize_empty_vault(tmp_path / "vault")
    document_root = _document_root(vault)
    (document_root / "document.json").write_text(json.dumps(_source()), encoding="utf-8")
    output = tmp_path / "edition.html"
    runner = CliRunner()

    validate = runner.invoke(cli, ["html-edition", "validate", "--vault", str(vault), "--document", str(document_root)])
    build = runner.invoke(cli, ["html-edition", "build", "--vault", str(vault), "--document", str(document_root), "--output", str(output)])
    inspect = runner.invoke(cli, ["html-edition", "inspect", str(output)])

    assert (validate.exit_code, build.exit_code, inspect.exit_code) == (0, 0, 0)
    assert inspect_edition(output).file_sha256 == json.loads(build.output)["file_sha256"]


def test_cli_keeps_selected_document_root_after_replacement(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = initialize_empty_vault(tmp_path / "vault")
    document_root = _document_root(vault)
    trusted_body = b"trusted body"
    escaped_body = b"escaped body"
    for root, body in ((document_root, trusted_body), (tmp_path / "escaped", escaped_body)):
        (root / "bodies").mkdir(parents=True, exist_ok=True)
        (root / "bodies" / "opening.md").write_bytes(body)
        source = _source(
            body={
                "schema": "doxagon.body-source-ref/1",
                "root": "document-bodies",
                "key": "opening.md",
                "sha256": hashlib.sha256(body).hexdigest(),
                "media_type": "text/markdown",
            }
        )
        (root / "document.json").write_text(json.dumps(source), encoding="utf-8")
    escaped = tmp_path / "escaped"
    held = tmp_path / "held"
    original_location = html_edition_cli._document_location

    def replace_after_selection(document: Path, ready: object) -> object:
        location = original_location(document, ready)  # type: ignore[arg-type]
        document_root.rename(held)
        document_root.symlink_to(escaped, target_is_directory=True)
        return location

    monkeypatch.setattr(html_edition_cli, "_document_location", replace_after_selection)
    output = tmp_path / "edition.html"
    result = CliRunner().invoke(cli, ["html-edition", "build", "--vault", str(vault), "--document", str(document_root), "--output", str(output)])

    assert result.exit_code == 0 and b"trusted body" in output.read_bytes() and b"escaped body" not in output.read_bytes()


def test_cli_rejects_yaml_timestamp_with_a_schema_diagnostic(tmp_path: Path) -> None:
    vault = initialize_empty_vault(tmp_path / "vault")
    document_root = _document_root(vault)
    (document_root / "document.yaml").write_text(
        """schema: doxagon.content-document/1
document_key: sample
mode: article
metadata:
  title: Sample Edition
  published_date: 2026-08-28
theme_id: default
sections:
  - section_id: opening
    kind: prose
    title: Opening
    body: Readable offline content.
resources: []
features: {}
""",
        encoding="utf-8",
    )

    result = CliRunner().invoke(cli, ["html-edition", "validate", "--vault", str(vault), "--document", str(document_root)])

    assert result.exit_code == 1 and "HTML_EDITION_SCHEMA_DIAGNOSTIC" in result.output


def test_compiler_rejects_css_that_can_escape_a_section_wrapper(tmp_path: Path) -> None:
    source = _source()
    source["sections"][0]["css"] = "color:red}body{background:black"

    with pytest.raises(HtmlEditionError) as rejected:
        HtmlEditionCompiler().compile(ContentDocument.parse(source), tmp_path)

    assert rejected.value.code == "HTML_EDITION_CSS_REJECTED"


def test_compiler_emits_only_bounded_section_css_declarations(tmp_path: Path) -> None:
    source = _source()
    source["sections"][0]["css"] = "color: #123; font-weight: 700"

    result = HtmlEditionCompiler().compile(ContentDocument.parse(source), tmp_path)

    assert b"#section-opening{color:#123;font-weight:700}" in result.html


def test_contract_rejects_resource_traversal_before_source_resolution() -> None:
    source = _source(
        body={
            "schema": "doxagon.body-source-ref/1",
            "root": "document-bodies",
            "key": "../outside.md",
            "sha256": "0" * 64,
            "media_type": "text/markdown",
        }
    )

    with pytest.raises(HtmlEditionError) as rejected:
        ContentDocument.parse(source)

    assert rejected.value.code == "HTML_EDITION_SCHEMA_DIAGNOSTIC"


def test_compiler_rejects_resource_declarations_above_type_limit(tmp_path: Path) -> None:
    source = _source()
    source["resources"] = [
        {
            "logical_id": "image",
            "source": {
                "schema": "doxagon.resource-source-ref/1",
                "root": "document-resources",
                "key": "image.png",
                "sha256": "0" * 64,
                "size": 16 * 1024 * 1024 + 1,
                "media_type": "image/png",
            },
            "purpose": "image",
        }
    ]

    with pytest.raises(HtmlEditionError) as rejected:
        HtmlEditionCompiler().compile(ContentDocument.parse(source), tmp_path)

    assert rejected.value.code == "HTML_EDITION_RESOURCE_LIMIT"


def test_compiler_emits_semantic_structure_without_runtime_execution(tmp_path: Path) -> None:
    html = HtmlEditionCompiler().compile(ContentDocument.parse(_source()), tmp_path).html

    assert b'<header><h1>Sample Edition</h1></header><main id="dox-content"><section id="section-opening" data-section-id="opening" aria-label="Opening"><h2>Opening</h2>' in html


@pytest.mark.parametrize(
    ("hash_value", "target"),
    [("#section-alpha-more", None), ("#target-alpha-more-focus", "alpha-more")],
)
def test_deck_runtime_preserves_exact_section_and_target_hashes(hash_value: str, target: str | None) -> None:
    if shutil.which("node") is None:
        pytest.skip("Node.js is required to execute the embedded trusted runtime")
    runtime = (Path(__file__).parents[1] / "src" / "doxagon" / "html_editions" / "resources" / "runtime.js").read_text(encoding="utf-8")
    target_expression = "null" if target is None else f"{{id:'target-alpha-more-focus',dataset:{{targetSection:'{target}'}}}}"
    harness = f"""const vm=require('vm');const runtime=process.argv[1];const sections=[{{tagName:'SECTION',dataset:{{sectionId:'alpha'}}}},{{tagName:'SECTION',dataset:{{sectionId:'alpha-more'}}}}];const main={{children:sections}};const target={target_expression};const context={{document:{{body:{{dataset:{{mode:'deck'}}}},documentElement:{{dataset:{{}}}},getElementById:id=>id==='dox-content'?main:(target&&id===target.id?target:null)}},location:{{hash:'{hash_value}'}},addEventListener:()=>{{}}}};vm.runInNewContext(runtime,context);if(sections[0].hidden!==true||sections[1].hidden!==false||context.location.hash!=='{hash_value}')process.exit(1);"""

    result = subprocess.run(["node", "-e", harness, runtime], capture_output=True, text=True, check=False)

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("suffix", [".whl", ".tar.gz"])
def test_distribution_installs_non_editably_and_runs_html_edition_cli(tmp_path: Path, suffix: str) -> None:
    project_root = Path(__file__).parents[1]
    dist = tmp_path / "dist"
    build = subprocess.run(["uv", "build", "--out-dir", str(dist)], cwd=project_root, capture_output=True, text=True, check=False)
    artifact = next(dist.glob(f"*{suffix}"), None) if build.returncode == 0 else None
    if artifact is None:
        pytest.fail(build.stderr or build.stdout)
    environment = tmp_path / suffix.replace(".", "")
    created = subprocess.run(["uv", "venv", str(environment)], cwd=tmp_path, capture_output=True, text=True, check=False)
    python = environment / "bin" / "python"
    install = subprocess.run(["uv", "pip", "install", "--python", str(python), str(artifact)], cwd=tmp_path, capture_output=True, text=True, check=False)
    if created.returncode != 0 or install.returncode != 0:
        pytest.fail(created.stderr + "\n" + install.stderr)
    vault = initialize_empty_vault(tmp_path / "vault")
    document_root = _document_root(vault)
    (document_root / "document.json").write_text(json.dumps(_source()), encoding="utf-8")
    output = tmp_path / "edition.html"
    environment_variables = os.environ.copy()
    environment_variables.pop("PYTHONPATH", None)
    environment_variables["PATH"] = f"{environment / 'bin'}:{environment_variables['PATH']}"
    commands = [
        [str(environment / "bin" / "dox"), "html-edition", "validate", "--vault", str(vault), "--document", str(document_root)],
        [str(environment / "bin" / "dox"), "html-edition", "build", "--vault", str(vault), "--document", str(document_root), "--output", str(output)],
        [str(environment / "bin" / "dox"), "html-edition", "inspect", str(output)],
    ]
    executions = [subprocess.run(command, cwd=tmp_path, env=environment_variables, capture_output=True, text=True, check=False) for command in commands]

    assert all(run.returncode == 0 for run in executions), "\n".join(run.stderr for run in executions)


def test_compiler_is_deterministic_across_isolated_installed_distributions(tmp_path: Path) -> None:
    project_root = Path(__file__).parents[1]
    dist = tmp_path / "dist"
    build = subprocess.run(["uv", "build", "--out-dir", str(dist)], cwd=project_root, capture_output=True, text=True, check=False)
    artifacts = [next(dist.glob("*.whl"), None), next(dist.glob("*.tar.gz"), None)] if build.returncode == 0 else []
    if len(artifacts) != 2 or any(artifact is None for artifact in artifacts):
        pytest.fail(build.stderr or build.stdout)
    fixture = tmp_path / "document.json"
    fixture.write_text(json.dumps(_source()), encoding="utf-8")
    program = """import base64, json, sys
from pathlib import Path
from doxagon.html_editions import HtmlEditionCompiler
from doxagon.html_editions.contracts import ContentDocument
result = HtmlEditionCompiler().compile(ContentDocument.parse(json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))), Path(sys.argv[2]))
print(json.dumps({'html': base64.b64encode(result.html).decode('ascii'), 'authoring_revision': result.authoring_revision, 'compile_input_hash': result.compile_input_hash, 'edition_id': result.edition_id, 'file_sha256': result.file_sha256}, sort_keys=True))"""
    outputs: list[dict[str, str]] = []
    variations = [("C", "UTC", "1"), ("C.UTF-8", "America/Los_Angeles", "98765")]
    for index, (artifact, (locale, timezone, hash_seed)) in enumerate(zip(artifacts, variations, strict=True)):
        environment = tmp_path / f"environment-{index}"
        created = subprocess.run(["uv", "venv", str(environment)], cwd=tmp_path, capture_output=True, text=True, check=False)
        installed = subprocess.run(["uv", "pip", "install", "--python", str(environment / "bin" / "python"), str(artifact)], cwd=tmp_path, capture_output=True, text=True, check=False)
        if created.returncode != 0 or installed.returncode != 0:
            pytest.fail(created.stderr + installed.stderr)
        cwd = tmp_path / f"cwd-{index}"
        cwd.mkdir()
        process_environment = os.environ.copy()
        process_environment.pop("PYTHONPATH", None)
        process_environment.update({"LC_ALL": locale, "TZ": timezone, "PYTHONHASHSEED": hash_seed})
        run = subprocess.run([str(environment / "bin" / "python"), "-c", program, str(fixture), str(cwd)], cwd=cwd, env=process_environment, capture_output=True, text=True, check=False)
        if run.returncode != 0:
            pytest.fail(run.stderr)
        outputs.append(json.loads(run.stdout))

    assert outputs[0] == outputs[1]


def _resource_source(logical_id: str, key: str, data: bytes) -> dict[str, object]:
    return {
        "logical_id": logical_id,
        "source": {
            "schema": "doxagon.resource-source-ref/1",
            "root": "document-resources",
            "key": key,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
            "media_type": "image/png",
        },
        "purpose": "image",
    }


@pytest.mark.parametrize(
    ("payload", "accepted"),
    [
        pytest.param(b".card { color: #123; }\n", True, id="stylesheet"),
        pytest.param(b"arbitrary bytes carrying no CSS syntax", False, id="arbitrary-bytes"),
        pytest.param(b'{"theme": "dark"}', False, id="json-payload"),
        pytest.param(b"function theme(){return 1}", False, id="javascript-payload"),
    ],
)
def test_compiler_admits_only_a_parsable_stylesheet_for_an_extensionless_css_resource(
    tmp_path: Path, payload: bytes, accepted: bool
) -> None:
    resources = tmp_path / "resources"
    resources.mkdir()
    (resources / "theme").write_bytes(payload)
    source = _source()
    source["resources"] = [
        {
            "logical_id": "theme",
            "source": {
                "schema": "doxagon.resource-source-ref/1",
                "root": "document-resources",
                "key": "theme",
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size": len(payload),
                "media_type": "text/css",
            },
            "purpose": "style",
        }
    ]

    if accepted:
        assert HtmlEditionCompiler().compile(ContentDocument.parse(source), tmp_path).html
    else:
        with pytest.raises(HtmlEditionError) as rejected:
            HtmlEditionCompiler().compile(ContentDocument.parse(source), tmp_path)
        assert rejected.value.code == "HTML_EDITION_RESOURCE_MIME_MISMATCH"


def test_compiler_rejects_cross_section_resource_reference(tmp_path: Path) -> None:
    image = b"\x89PNG\r\n\x1a\n"
    resources = tmp_path / "resources"
    resources.mkdir()
    (resources / "second.png").write_bytes(image)
    source = _source(body="![secret](resource:second-image)")
    source["sections"] = [
        source["sections"][0],
        {"section_id": "second", "kind": "prose", "title": "Second", "level": 2, "body": "Visible", "resource_ids": ["second-image"]},
    ]
    source["resources"] = [_resource_source("second-image", "second.png", image)]

    with pytest.raises(HtmlEditionError) as rejected:
        HtmlEditionCompiler().compile(ContentDocument.parse(source), tmp_path)

    assert rejected.value.code == "HTML_EDITION_SANITIZER_REJECTED"


def test_compiler_retains_directory_descriptors_during_source_parent_replacement(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    body = b"trusted body"
    bodies = tmp_path / "bodies"
    nested = bodies / "nested"
    nested.mkdir(parents=True)
    (nested / "body.md").write_bytes(body)
    escaped = tmp_path / "escaped"
    escaped.mkdir()
    (escaped / "body.md").write_bytes(b"escaped body")
    source = _source(
        body={
            "schema": "doxagon.body-source-ref/1",
            "root": "document-bodies",
            "key": "nested/body.md",
            "sha256": hashlib.sha256(body).hexdigest(),
            "media_type": "text/markdown",
        }
    )
    original_open = os.open
    replaced = False

    def replace_parent(path: str | bytes | os.PathLike[str] | os.PathLike[bytes], flags: int, mode: int = 0o777, *, dir_fd: int | None = None) -> int:
        nonlocal replaced
        if not replaced and os.fspath(path) == "body.md" and dir_fd is not None:
            replaced = True
            nested.rename(bodies / "held")
            nested.symlink_to(escaped, target_is_directory=True)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", replace_parent)
    result = HtmlEditionCompiler().compile(ContentDocument.parse(source), tmp_path)

    assert replaced and b"trusted body" in result.html and b"escaped body" not in result.html


def test_compiler_rejects_external_bodies_above_document_limit(tmp_path: Path) -> None:
    body = b"x" * MAX_BODY_BYTES
    bodies = tmp_path / "bodies"
    bodies.mkdir()
    sections: list[dict[str, object]] = []
    for number in range(5):
        key = f"body-{number}.md"
        (bodies / key).write_bytes(body)
        sections.append(
            {
                "section_id": f"section-{number}",
                "kind": "prose",
                "title": f"Section {number}",
                "level": 2,
                "body": {
                    "schema": "doxagon.body-source-ref/1",
                    "root": "document-bodies",
                    "key": key,
                    "sha256": hashlib.sha256(body).hexdigest(),
                    "media_type": "text/markdown",
                },
            }
        )
    source = _source()
    source["sections"] = sections

    with pytest.raises(HtmlEditionError) as rejected:
        HtmlEditionCompiler().compile(ContentDocument.parse(source), tmp_path)

    assert rejected.value.code == "HTML_EDITION_BODY_LIMIT"


def test_public_projection_rejects_non_json_values() -> None:
    with pytest.raises(HtmlEditionError) as rejected:
        PublicEdgeV1.parse({"source_id": "source", "target_id": "target", "type": "supports", "provenance": object()})

    assert rejected.value.code == "HTML_EDITION_PUBLIC_PROJECTION_REJECTED"


def test_inspector_reports_all_direct_sections_after_a_void_image(tmp_path: Path) -> None:
    image = b"\x89PNG\r\n\x1a\n"
    resources = tmp_path / "resources"
    resources.mkdir()
    (resources / "first.png").write_bytes(image)
    source = _source(body="![first](resource:first-image)")
    source["sections"][0]["resource_ids"] = ["first-image"]
    source["sections"].append({"section_id": "second", "kind": "prose", "title": "Second", "level": 2, "body": "Visible"})
    source["resources"] = [_resource_source("first-image", "first.png", image)]

    report = inspect_edition_bytes(HtmlEditionCompiler().compile(ContentDocument.parse(source), tmp_path).html)

    assert report.section_ids == ("opening", "second")


def test_compiler_maps_generated_targets_to_their_owning_section(tmp_path: Path) -> None:
    source = _source("deck")
    source["sections"][0]["targets"] = ["focus"]

    html = HtmlEditionCompiler().compile(ContentDocument.parse(source), tmp_path).html

    assert b'id="target-opening-focus" data-target-section="opening"' in html


def test_cli_rejects_forced_output_through_a_symlink(tmp_path: Path) -> None:
    vault = initialize_empty_vault(tmp_path / "vault")
    document_root = _document_root(vault)
    (document_root / "document.json").write_text(json.dumps(_source()), encoding="utf-8")
    target = tmp_path / "target.html"
    target.write_text("preserve", encoding="utf-8")
    output = tmp_path / "edition.html"
    output.symlink_to(target)

    result = CliRunner().invoke(
        cli,
        ["html-edition", "build", "--vault", str(vault), "--document", str(document_root), "--output", str(output), "--force"],
    )

    assert result.exit_code == 1 and target.read_text(encoding="utf-8") == "preserve"


def test_content_document_fd_rejects_same_inode_same_size_mutation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original = _source()
    replacement = _source()
    replacement["metadata"] = {"title": "Mutate Edition"}
    original_bytes = json.dumps(original).encode()
    replacement_bytes = json.dumps(replacement).encode()
    assert len(original_bytes) == len(replacement_bytes)
    document = tmp_path / "document.json"
    document.write_bytes(original_bytes)
    reader = os.open(document, os.O_RDONLY | os.O_NOFOLLOW)
    writer = os.open(document, os.O_WRONLY | os.O_NOFOLLOW)
    original_read = os.read
    mutated = False

    def mutate_after_read(fd: int, count: int) -> bytes:
        nonlocal mutated
        chunk = original_read(fd, count)
        if fd == reader and chunk and not mutated:
            mutated = True
            os.pwrite(writer, replacement_bytes, 0)
        return chunk

    monkeypatch.setattr(os, "read", mutate_after_read)
    try:
        with pytest.raises(HtmlEditionError) as rejected:
            load_content_document_from_fd(reader, ".json")
    finally:
        os.close(writer)
        os.close(reader)

    assert rejected.value.code == "HTML_EDITION_SCHEMA_DIAGNOSTIC"


def test_compiler_rejects_same_inode_same_size_source_mutation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    trusted = b"trusted body"
    replacement = b"altered body"
    assert len(trusted) == len(replacement)
    bodies = tmp_path / "bodies"
    bodies.mkdir()
    body_path = bodies / "opening.md"
    body_path.write_bytes(trusted)
    source = _source(
        body={
            "schema": "doxagon.body-source-ref/1",
            "root": "document-bodies",
            "key": "opening.md",
            "sha256": hashlib.sha256(trusted).hexdigest(),
            "media_type": "text/markdown",
        }
    )
    writer = os.open(body_path, os.O_WRONLY | os.O_NOFOLLOW)
    original_read = os.read
    mutated = False

    def mutate_after_read(fd: int, count: int) -> bytes:
        nonlocal mutated
        chunk = original_read(fd, count)
        if chunk == trusted and not mutated:
            mutated = True
            os.pwrite(writer, replacement, 0)
        return chunk

    monkeypatch.setattr(os, "read", mutate_after_read)
    try:
        with pytest.raises(HtmlEditionError) as rejected:
            HtmlEditionCompiler().compile(ContentDocument.parse(source), tmp_path)
    finally:
        os.close(writer)

    assert rejected.value.code == "HTML_EDITION_SOURCE_RACE"
