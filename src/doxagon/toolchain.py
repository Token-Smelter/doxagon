"""Provisioning commands for the platform-owned vault toolchain."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from importlib.resources import files
import json
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
from typing import Mapping, NamedTuple

from doxagon.presentation_backends import (
    GENERATED_MEDIA_TYPES,
    provider_command,
    resolve_image_generator_path,
)

AGENT_RESOURCES_MANIFEST_SCHEMA = "doxagon.agent-resources-manifest/1"
SKILLS_MANIFEST_SCHEMA = "doxagon.skills-manifest/1"
RESOURCE_ROOT = files("doxagon").joinpath("resources")
SKILL_ROOT = RESOURCE_ROOT.joinpath("skills")
AGENTS_RESOURCE = "AGENTS.md"
SKILLS_DIRECTORY = ".pi/skills"
# The manifest keeps the path skills already wrote, so a vault that only holds
# the skills-only schema upgrades in place instead of being re-flagged.
MANIFEST_PATH = f"{SKILLS_DIRECTORY}/.platform-manifest.json"


def platform_root() -> Path:
    """Return the checkout when available; installed packages have no checkout."""
    return Path(__file__).resolve().parents[2]


def _git(args: list[str], cwd: Path) -> str | None:
    try:
        result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=5, check=False)
    except OSError:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def platform_sha() -> str | None:
    return _git(["rev-parse", "HEAD"], platform_root())


def packaged_skills() -> dict[str, bytes]:
    return {
        item.name: item.joinpath("SKILL.md").read_bytes()
        for item in SKILL_ROOT.iterdir()
        if item.is_dir() and item.joinpath("SKILL.md").is_file()
    }


def packaged_agents_md() -> bytes:
    """Return the platform-owned vault orientation a fresh vault starts from."""
    return RESOURCE_ROOT.joinpath(AGENTS_RESOURCE).read_bytes()


class AgentResource(NamedTuple):
    destination: str
    content: bytes


def _skill_files(directory, prefix=""):
    for item in sorted(directory.iterdir(), key=lambda entry: entry.name):
        if item.name.startswith('.') or item.name == '__pycache__' or item.name.endswith(('.pyc', '.pyo')):
            continue
        if getattr(item, 'is_symlink', lambda: False)():
            raise ValueError(f"Packaged skills cannot contain symlinks: {item}")
        relative = f"{prefix}{item.name}"
        if item.is_dir():
            yield from _skill_files(item, f"{relative}/")
        elif item.is_file():
            yield relative, item.read_bytes()


def packaged_resources() -> dict[str, AgentResource]:
    """Name every platform-owned file; retain legacy keys for SKILL.md."""
    resources = {}
    for name in sorted(packaged_skills()):
        for relative, content in _skill_files(SKILL_ROOT.joinpath(name)):
            key = name if relative == 'SKILL.md' else f"{name}/{relative}"
            resources[key] = AgentResource(f"{SKILLS_DIRECTORY}/{name}/{relative}", content)
    resources[AGENTS_RESOURCE] = AgentResource(AGENTS_RESOURCE, packaged_agents_md())
    return resources


def _destination(name: str) -> str | None:
    if name == AGENTS_RESOURCE:
        return name
    parts = name.split('/')
    if any(not part or part.startswith('.') or '\\' in part or ':' in part for part in parts):
        return None
    return f"{SKILLS_DIRECTORY}/{name}" + ('/SKILL.md' if len(parts) == 1 else '')


def _symlinked(vault: Path, target: Path) -> bool:
    return any(path.is_symlink() for path in (target, *target.parents) if path != vault and vault in path.parents)


def _manifest(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _recorded(manifest: dict) -> dict[str, dict]:
    """Read either manifest generation; the skills-only schema is the skills half."""
    schema = manifest.get("schema")
    if schema == AGENT_RESOURCES_MANIFEST_SCHEMA:
        recorded = manifest.get("resources", {})
    elif schema == SKILLS_MANIFEST_SCHEMA:
        recorded = manifest.get("skills", {})
    else:
        recorded = {}
    if not isinstance(recorded, dict):
        return {}
    return {name: value for name, value in recorded.items() if isinstance(value, dict)}


def resource_status(vault: Path) -> dict[str, dict[str, str]]:
    vault = vault.expanduser().resolve()
    manifest = {} if _symlinked(vault, vault / MANIFEST_PATH) else _manifest(vault / MANIFEST_PATH)
    recorded = _recorded(manifest)
    current_platform = manifest.get("platform_sha") == platform_sha()
    result: dict[str, dict[str, str]] = {}
    resources = packaged_resources()
    active = set(resources)
    for name, record in recorded.items():
        destination = _destination(name)
        if name not in resources and destination and (vault / destination).exists():
            resources[name] = AgentResource(destination, b'')
    for name, resource in resources.items():
        target = vault / resource.destination
        expected = sha256(resource.content).hexdigest()
        prior = recorded.get(name, {}).get("sha256")
        unsafe = _symlinked(vault, target) or (target.exists() and not target.is_file())
        disk = sha256(target.read_bytes()).hexdigest() if not unsafe and target.is_file() else None
        if unsafe:
            state = "foreign"
        elif name not in active:
            state = 'stale' if disk == prior else 'foreign'
        elif disk is None:
            state = "missing"
        elif disk != (prior or expected):
            state = "foreign"
        elif disk == expected and prior == expected and current_platform:
            state = "current"
        else:
            state = "stale"
        result[name] = {"status": state, "sha256": expected}
    return result


def skill_status(vault: Path) -> dict[str, dict]:
    result = {}
    priority = {'current': 0, 'stale': 1, 'missing': 2, 'foreign': 3}
    for key, record in resource_status(vault).items():
        if key == AGENTS_RESOURCE:
            continue
        name = key.split('/')[0]
        group = result.setdefault(name, {'status': 'current', 'files': {}})
        group['files'][key] = record
        if key == name:
            group['sha256'] = record['sha256']
        if priority[record['status']] > priority[group['status']]:
            group['status'] = record['status']
    return result


def sync_agent_resources(vault: Path, force: bool = False) -> dict:
    vault = vault.expanduser().resolve()
    manifest_path = vault / MANIFEST_PATH
    if _symlinked(vault, manifest_path):
        raise ValueError('Refusing to sync agent resources through a symlinked manifest path')
    manifest = _manifest(manifest_path)
    prior = _recorded(manifest)
    manifest_stale = (manifest.get("platform_sha") != platform_sha()
                      or manifest.get("schema") != AGENT_RESOURCES_MANIFEST_SCHEMA)
    created: list[str] = []
    updated: list[str] = []
    current: list[str] = []
    foreign: list[str] = []
    resources = packaged_resources()
    managed = {}
    removed = []
    for name, resource in resources.items():
        destination = vault / resource.destination
        if _symlinked(vault, destination) or (destination.exists() and not destination.is_file()):
            foreign.append(name)
            if name in prior:
                managed[name] = prior[name]
            continue
        old = prior.get(name, {}).get("sha256")
        existed = destination.exists()
        disk_digest = sha256(destination.read_bytes()).hexdigest() if destination.is_file() else None
        content_digest = sha256(resource.content).hexdigest()
        local_edit = existed and disk_digest != (old or content_digest)
        if local_edit and not force:
            foreign.append(name)
            if name in prior:
                managed[name] = prior[name]
            continue
        managed[name] = {'sha256': content_digest}
        if disk_digest == content_digest:
            current.append(name)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(resource.content)
        (updated if existed else created).append(name)
    for name, record in prior.items():
        if name in resources:
            continue
        relative = _destination(name)
        if relative is None or relative in {resource.destination for resource in resources.values()}:
            continue
        destination = vault / relative
        if _symlinked(vault, destination) or (destination.exists() and not destination.is_file()):
            foreign.append(name)
            managed[name] = record
        elif destination.is_file():
            if sha256(destination.read_bytes()).hexdigest() == record.get('sha256'):
                destination.unlink()
                removed.append(name)
            else:
                foreign.append(name)
                managed[name] = record
    changed = bool(created or updated or removed or managed != prior or not manifest_path.exists() or manifest_stale or force)
    if changed:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps({"schema": AGENT_RESOURCES_MANIFEST_SCHEMA, "platform_sha": platform_sha(),
            "synced_at": datetime.now(timezone.utc).isoformat(), "resources": managed}, indent=2) + "\n", encoding="utf-8")
    skills_root = vault / SKILLS_DIRECTORY
    vault_only = sorted(path.name for path in skills_root.iterdir() if path.is_dir() and path.name not in packaged_skills()) if skills_root.exists() else []
    return {"vault": str(vault), "created": created, "updated": updated, "current": current,
            "removed": removed, "foreign": foreign, "vault_only": vault_only, "changed": changed}


def _capability_result(executable: Path) -> tuple[dict | None, str | None]:
    try:
        result = subprocess.run([str(executable), "--capabilities"], capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        return None, str(error)
    if result.returncode:
        return None, f"exited {result.returncode}: {result.stderr.strip()[-400:]}"
    try:
        return json.loads(result.stdout), None
    except ValueError:
        return None, "stdout was not JSON"


def provider_check(executable: str | None, live: bool) -> dict:
    command = executable or provider_command()
    path = resolve_image_generator_path(command)
    report = {"command": command, "resolved_path": str(path) if path else None, "ok": False}
    if path is None:
        report["error"] = "provider executable is not configured or cannot be resolved"
        return report
    if not path.is_file() or not os.access(path, os.X_OK):
        report["error"] = "provider executable lacks the executable bit"
        return report
    try:
        report["executable_sha256"] = sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        report["error"] = f"provider executable cannot be hashed: {error}"
        return report
    capabilities, error = _capability_result(path)
    from doxagon.renderings.document_generation import validate_provider_capabilities
    if error:
        report["error"] = f"--capabilities {error}"
        return report
    try:
        report["capabilities"] = validate_provider_capabilities(capabilities)
    except ValueError as failure:
        report["error"] = f"invalid capabilities: {failure}"
        return report
    if live:
        with TemporaryDirectory(prefix="doxagon-provider-check-") as scratch:
            root = Path(scratch)
            output = root / "output"
            output.mkdir()
            prompt = root / "prompt.txt"
            prompt.write_text("Synthetic conformance prompt.", encoding="utf-8")
            from PIL import Image
            refs = []
            for index in range(2):
                ref = root / f"reference-{index}.png"
                Image.new("RGB", (16, 16), (index, index, index)).save(ref, format="PNG")
                refs.append(ref)
            argv = [str(path), "--prompt-file", str(prompt), "--output", str(output), "--image-size", "1K", "--aspect-ratio", "1:1"]
            for ref in refs:
                argv.extend(["--source", str(ref)])
            result = subprocess.run(argv, capture_output=True, text=True, timeout=600, check=False)
            produced = sorted(item for item in output.iterdir() if item.is_file() and item.suffix.lower() in GENERATED_MEDIA_TYPES)
            if result.returncode or not produced:
                report["error"] = f"live invocation exited {result.returncode}; supported output: {bool(produced)}"
                return report
            report["live"] = {"output": produced[0].name, "cleaned": True}
    report["ok"] = True
    return report


def context(project_name: str) -> dict:
    """Give one stable orientation envelope for authored and legacy projects."""
    from doxagon.renderings.document_context import inspect_project
    from doxagon.renderings.project import resolve_document_project
    project = resolve_document_project(project_name)
    view = inspect_project(project)
    summary = view.summary
    model = summary['model']
    document_model = model == 'authored'
    links = summary.get('links', {})
    argument = summary.get('argument', {})
    argument_sources = {
        'thesis': argument.get('source'),
        'diegesis': argument.get('diegesis') or links.get('diegesis'),
        'walk': links.get('walk'),
    }
    note_ids = (summary.get('notes_metadata') or {}).get('cues')
    cue_ids = [cue.get('id') for cue in summary.get('cues', [])]
    cue_notes = ('agree' if note_ids == cue_ids else 'disagree') if document_model and note_ids is not None else (
        'not-applicable' if not document_model else 'notes-absent'
    )
    return {
        'schema': 'doxagon.presentation-context/1',
        'identity': {'project': project.slug, 'title': summary['title'], 'vault': str(project.vault)},
        'argument_sources': argument_sources,
        'model': {'name': 'document-model' if document_model else 'legacy-slides',
                  'authoritative': summary.get('document', {}).get('path') if document_model else 'outputs/presentation/slides/'},
        'cue_notes_agreement': cue_notes,
        'skill': 'presentation-document' if document_model else 'presentation-context',
        'inspection': {'snapshot': summary['snapshot'], 'cues': len(summary.get('cues', [])),
                       'slides': summary.get('slides', []), 'checks': summary.get('checks', [])},
    }


def doctor(environ: Mapping[str, str] | None = None) -> dict:
    env = os.environ if environ is None else environ
    root = platform_root()
    command = shutil.which("dox", path=env.get("PATH"))
    vault_value = env.get("DOXAGON_ROOT")
    vault = Path(vault_value).expanduser().resolve() if vault_value else None
    status = _git(["status", "--porcelain=v1"], root)
    entry = {"platform_command": command, "resolved_target": str(Path(command).resolve()) if command else None,
             "platform_sha": platform_sha(), "working_tree": "clean" if status == "" else "dirty",
             "ok": bool(command and platform_sha())}
    vault_check = {"DOXAGON_ROOT": vault_value, "resolved_vault": str(vault) if vault else None,
                   "knowledge": bool(vault and (vault / "knowledge").is_dir()), "projects": bool(vault and (vault / "projects").is_dir())}
    vault_check["ok"] = bool(vault_check["knowledge"] and vault_check["projects"])
    resources = resource_status(vault) if vault_check["ok"] else {}
    skills = skill_status(vault) if vault_check["ok"] else {}
    agents_md = dict(resources.get(AGENTS_RESOURCE, {"status": "unavailable"}))
    agents_md["ok"] = agents_md["status"] == "current"
    provider = __import__("doxagon.renderings.document_generation", fromlist=["provider_capabilities"]).provider_capabilities(env)
    provider["ok"] = bool(provider["configured"] and provider["executable_sha256"] and provider["resolved_path"]
                          and os.access(provider["resolved_path"], os.X_OK))
    candidates = sorted({str((Path(part) / "dox").resolve()) for part in env.get("PATH", "").split(os.pathsep)
                         if (Path(part) / "dox").exists()})
    selected = str(Path(command).resolve()) if command else None
    others = [candidate for candidate in candidates if candidate != selected]
    shims = {"matches": candidates, "other": others, "ok": not others}
    frontend = {"status": "built" if (root / "apps/web/frontend/build").is_dir() else "absent"}
    frontend["ok"] = frontend["status"] == "built"
    checks = {"entry_point": entry, "vault_binding": vault_check, "skills": skills, "agents_md": agents_md,
              "provider": provider, "frontend": frontend, "path_shims": shims}
    skills_ok = bool(skills) and all(record["status"] == "current" for record in skills.values())
    checks["ok"] = all(item["ok"] for key, item in checks.items() if key != "skills") and skills_ok
    return checks
