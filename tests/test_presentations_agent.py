"""Proof for the single-checkpoint agent task, patch, and before/after result.

The legacy annotation flow posted free text against a slide slug: no revision,
no source digest, no edge, no asset provenance, no scope, and no independent
validation before the agent's edit reached the tree. Every test here asserts a
property that flow could not have: the task is versioned and scoped to one
checkpoint, arbitrary registered HTML/CSS/JS lands without a reveal/hide/style
ceiling, and every refusal happens before a single byte of the promoted tree
changes.
"""

from __future__ import annotations

import base64
from contextlib import contextmanager
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
from typing import Any, Iterator

from PIL import Image
from fastapi.testclient import TestClient
import pytest

from doxagon.presentations import (
    AGENT_PATCH_SCHEMA,
    AGENT_RESULT_SCHEMA,
    AGENT_TASK_SCHEMA,
    MANIFEST_SCHEMA,
    REGISTRATION_SCHEMA,
    RUNTIME_VERSION,
    PresentationWorkspace,
    WorkspaceError,
    state_digest,
)
from doxagon.presentations.api import create_presentation_workspace_app

_PROGRAM = """export function create(context) {
  const stage = context.root.querySelector('#stage');
  return {
    enter() {
      stage.dataset.state = 'ready';
    },
    exit() {
      delete stage.dataset.state;
    },
    signature() {
      return 'ready@1.0.0';
    },
  };
}
"""

# Arbitrary registered JavaScript: a WebGL context, an animation loop under a
# declared timers grant, and author-owned state. Nothing here is expressible as
# a reveal/hide/style action list, which is exactly the point.
_CANVAS_PROGRAM = """export function create(context) {
  const scene = context.root.querySelector('#scene');
  const gl = scene.getContext('webgl2') || scene.getContext('2d');
  let frame = 0;
  let handle = null;
  const step = () => {
    frame += 1;
    handle = requestAnimationFrame(step);
  };
  return {
    enter() {
      handle = requestAnimationFrame(step);
      scene.dataset.mode = gl === null ? 'none' : 'live';
    },
    exit() {
      if (handle !== null) {
        cancelAnimationFrame(handle);
        handle = null;
      }
      delete scene.dataset.mode;
    },
    signature() {
      return `scene@${frame === 0 ? 'idle' : 'running'}`;
    },
    inspect() {
      return { frame, mode: scene.dataset.mode };
    },
  };
}
"""

_DOCUMENT = """<section class="stage">
  <h2>Stage</h2>
  <div id="stage"></div>
</section>
"""

_CANVAS_DOCUMENT = """<section class="scene">
  <h2>Market</h2>
  <canvas id="scene" width="960" height="540"></canvas>
  <svg viewBox="0 0 10 10"><circle cx="5" cy="5" r="4" /></svg>
</section>
"""

_STYLES = ".stage { display: grid; }\n"

_CANVAS_STYLES = """@keyframes drift { from { transform: translateX(0); } to { transform: translateX(4rem); } }
.scene { display: grid; gap: 1rem; background: radial-gradient(circle, #101820, #000); }
.scene canvas { animation: drift 2s ease-in-out infinite alternate; }
"""


def _png(colour: tuple[int, int, int] = (12, 34, 56)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (8, 8), colour).save(buffer, format="PNG")
    return buffer.getvalue()


def _module(checkpoint_id: str, program: str = _PROGRAM, **registration: Any) -> str:
    block = json.dumps(
        {"schema": REGISTRATION_SCHEMA, "id": checkpoint_id, "version": "1.0.0", **registration},
        indent=2,
        sort_keys=True,
    )
    return f"/* doxagon-checkpoint-registration\n{block}\n*/\n{program}"


def _write(path: Path, data: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))


def _deck(tmp_path: Path) -> Path:
    """Two checkpoints, one registered reversible edge, one declared asset."""

    deck = tmp_path / "deck"
    png = _png()
    digest = hashlib.sha256(png).hexdigest()
    _write(deck / "assets" / "sha256" / digest, png)
    for checkpoint_id, registration in (
        ("intro", {"assets": ["asset_map"], "forward_to": "detail"}),
        ("detail", {"assets": [], "back_to": "intro"}),
    ):
        _write(deck / "checkpoints" / checkpoint_id / "program.js", _module(checkpoint_id, **registration))
        _write(deck / "checkpoints" / checkpoint_id / "document.html", _DOCUMENT)
        _write(deck / "checkpoints" / checkpoint_id / "styles.css", _STYLES)
    _write(
        deck / "presentation.json",
        json.dumps(
            {
                "schema": MANIFEST_SCHEMA,
                "presentation_id": "pres_agent",
                "checkpoint_order": ["intro", "detail"],
                "checkpoints": [
                    {
                        "id": "intro",
                        "label": "Intro",
                        "source": "checkpoints/intro",
                        "entry": "program.js",
                        "document": "document.html",
                        "styles": "styles.css",
                        "assets": ["asset_map"],
                        "transition": {"edge_id": "reveal", "forward_to": "detail"},
                    },
                    {
                        "id": "detail",
                        "label": "Detail",
                        "source": "checkpoints/detail",
                        "entry": "program.js",
                        "document": "document.html",
                        "styles": "styles.css",
                        "assets": [],
                        "transition": {"edge_id": "reveal", "back_to": "intro"},
                    },
                ],
                "groups": [{"id": "opening", "kind": "slide", "label": "Opening", "checkpoints": ["intro", "detail"]}],
                "assets": [
                    {
                        "id": "asset_map",
                        "label": "Map",
                        "alt": "A map",
                        "media_type": "image/png",
                        "bytes": len(png),
                        "sha256": digest,
                        "storage_key": f"sha256/{digest}",
                        "provenance": {"kind": "authored", "created_at": "2026-08-29T00:00:00Z"},
                    }
                ],
            }
        ),
    )
    return deck


@pytest.fixture
def workspace(tmp_path: Path) -> PresentationWorkspace:
    return PresentationWorkspace.create(tmp_path / "workspace", _deck(tmp_path))


def _tree_digest(root: Path) -> str:
    entries: list[tuple[str, str, str]] = []
    for path in sorted(root.rglob("*")):
        relative = str(path.relative_to(root))
        if path.is_symlink():
            entries.append((relative, "symlink", os.readlink(path)))
        elif path.is_file():
            entries.append((relative, "file", hashlib.sha256(path.read_bytes()).hexdigest()))
        else:
            entries.append((relative, "dir", ""))
    return hashlib.sha256(json.dumps(entries).encode()).hexdigest()


def _patch(task: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    """A well-formed patch bound to the context the task published."""

    return {
        "schema": AGENT_PATCH_SCHEMA,
        "task_id": task["task_id"],
        "base_revision": task["base_revision"],
        "checkpoint_id": task["scope"]["checkpoint_id"],
        "before_digest": task["before_digest"],
        **overrides,
    }


def _canvas_sources(**registration: Any) -> dict[str, str]:
    return {
        "entry": _module("intro", _CANVAS_PROGRAM, **registration),
        "document": _CANVAS_DOCUMENT,
        "styles": _CANVAS_STYLES,
    }


_CANVAS_REGISTRATION = {"assets": ["asset_map"], "capabilities": ["timers"], "forward_to": "detail"}


# --- AC1: versioned, single-checkpoint, fully contextual task ---------------


def test_agent_task_is_versioned_and_names_one_checkpoint(workspace: PresentationWorkspace) -> None:
    task = workspace.open_agent_task("intro")

    assert (task["schema"], task["base_revision"], task["scope"]["checkpoint_id"], task["stale"]) == (
        AGENT_TASK_SCHEMA,
        workspace.revision,
        "intro",
        False,
    )


def test_agent_task_carries_source_edge_before_asset_capability_and_scope_context(
    workspace: PresentationWorkspace,
) -> None:
    task = workspace.open_agent_task("intro")

    assert {
        "source": [(item["role"], item["path"], item["text"] is not None) for item in task["checkpoint"]["sources"]],
        "edge": [edge["id"] for edge in task["edges"]["outgoing"]],
        "neighbour": task["neighbours"]["successor"]["label"],
        "before": task["before_digest"] == state_digest(task["before"]),
        "asset_provenance": [item["provenance"]["kind"] for item in task["assets"]["declared"]],
        "capability": task["capabilities"]["vocabulary"][:2],
        "scope": task["scope"]["denied_operations"],
    } == {
        # Declared order, exactly as the receipt pinned it.
        "source": [
            ("entry", "checkpoints/intro/program.js", True),
            ("document", "checkpoints/intro/document.html", True),
            ("styles", "checkpoints/intro/styles.css", True),
        ],
        "edge": ["reveal"],
        "neighbour": "Detail",
        "before": True,
        "asset_provenance": ["authored"],
        # The vocabulary an agent may request from is exactly what the realm
        # brokers; a capability nothing can honour is not offered.
        "capability": ["media", "timers"],
        "scope": ["add_asset"],
    }


def test_agent_task_scope_reaches_only_the_targeted_checkpoint_sources(workspace: PresentationWorkspace) -> None:
    task = workspace.open_agent_task("intro")

    assert [item["path"] for item in task["scope"]["editable_sources"]] == [
        "checkpoints/intro/document.html",
        "checkpoints/intro/program.js",
        "checkpoints/intro/styles.css",
    ]


def test_agent_task_signature_defers_to_the_sandbox_runtime(workspace: PresentationWorkspace) -> None:
    task = workspace.open_agent_task("intro")

    assert task["before"]["signature"] == {
        "status": "deferred-to-runtime",
        "runtime": RUNTIME_VERSION,
        "value": None,
    }


# --- AC2: arbitrary registered HTML/CSS/JS ---------------------------------


def test_patch_lands_arbitrary_canvas_html_css_and_javascript(workspace: PresentationWorkspace) -> None:
    task = workspace.open_agent_task("intro")

    outcome = workspace.apply_agent_patch(
        workspace.etag,
        task["task_id"],
        _patch(task, sources=_canvas_sources(**_CANVAS_REGISTRATION), capabilities=["timers"]),
    )

    assert (outcome.revision == workspace.revision, outcome.after["capabilities"], outcome.receipt["revision"]) == (
        True,
        ["timers"],
        outcome.revision,
    )


# --- AC4: preservation, evidence, and granted asset/capability requests -----


def test_patch_preserves_every_other_checkpoint_and_the_checkpoint_order(workspace: PresentationWorkspace) -> None:
    start = workspace.read()
    before = {record["id"]: record["sources"] for record in start.checkpoints}
    task = workspace.open_agent_task("intro")

    workspace.apply_agent_patch(
        workspace.etag,
        task["task_id"],
        _patch(task, sources=_canvas_sources(**_CANVAS_REGISTRATION), capabilities=["timers"]),
    )

    view = workspace.read()
    after = {record["id"]: record["sources"] for record in view.checkpoints}
    assert (after["detail"], [record["id"] for record in view.checkpoints], view.groups, view.assets) == (
        before["detail"],
        ["intro", "detail"],
        start.groups,
        start.assets,
    )


def test_outcome_reports_source_preview_asset_capability_and_edge_evidence(
    workspace: PresentationWorkspace,
) -> None:
    task = workspace.open_agent_task("intro")

    outcome = workspace.apply_agent_patch(
        workspace.etag,
        task["task_id"],
        _patch(task, sources=_canvas_sources(**_CANVAS_REGISTRATION), capabilities=["timers"]),
    )

    diff = outcome.diff
    assert {
        "sources": sorted(item["role"] for item in diff["sources"] if item["changed"]),
        "preview_changed": diff["preview"]["changed"],
        "capabilities": diff["capabilities"],
        "assets": diff["assets"]["after"],
        "edges": diff["edges"]["after"]["outgoing"],
        "signatures": [outcome.before["signature"]["status"], outcome.after["signature"]["status"]],
    } == {
        "sources": ["document", "entry", "styles"],
        "preview_changed": True,
        "capabilities": {"before": [], "after": ["timers"], "added": ["timers"], "removed": []},
        "assets": ["asset_map"],
        "edges": ["reveal"],
        "signatures": ["deferred-to-runtime", "deferred-to-runtime"],
    }


def test_granted_patch_admits_a_labelled_asset_with_provenance_and_its_capability(
    workspace: PresentationWorkspace,
) -> None:
    task = workspace.open_agent_task("intro", grants=["add_asset"])
    png = _png((200, 40, 90))

    outcome = workspace.apply_agent_patch(
        workspace.etag,
        task["task_id"],
        _patch(
            task,
            sources=_canvas_sources(assets=["asset_map", "asset_scene"], capabilities=["timers"], forward_to="detail"),
            assets=["asset_map", "asset_scene"],
            capabilities=["timers"],
            asset_requests=[
                {
                    "asset_id": "asset_scene",
                    "label": "Scene plate",
                    "alt": "A generated scene plate",
                    "media_type": "image/png",
                    "data_base64": base64.b64encode(png).decode("ascii"),
                    "provenance": {
                        "kind": "generated",
                        "generator": "image-generation/1",
                        "created_at": "2026-08-30T00:00:00Z",
                    },
                }
            ],
        ),
    )

    admitted = next(item for item in outcome.after["assets"] if item["id"] == "asset_scene")
    assert (outcome.assets_admitted, admitted["label"], admitted["provenance"]["generator"], admitted["sha256"]) == (
        ("asset_scene",),
        "Scene plate",
        "image-generation/1",
        hashlib.sha256(png).hexdigest(),
    )


def test_outcome_describes_its_own_promotion_when_another_writer_lands_immediately_after(
    workspace: PresentationWorkspace,
) -> None:
    """Evidence is bound to this patch's promotion, not to whatever HEAD becomes.

    The interleaving is real, not simulated: a second workspace over the same
    root performs an ordinary labelled mutation in the window between the store
    lock being released and the outcome being described.
    """

    task = workspace.open_agent_task("intro")
    competitor = PresentationWorkspace.open(workspace.store.root)
    landed: list[str] = []
    exclusive = workspace.store.exclusive

    @contextmanager
    def racing_exclusive() -> Iterator[None]:
        with exclusive():
            yield
        if not landed:
            view = competitor.set_checkpoint_label(competitor.etag, "detail", "Detail — competing")
            landed.append(view.revision)

    workspace.store.exclusive = racing_exclusive

    outcome = workspace.apply_agent_patch(
        workspace.etag,
        task["task_id"],
        _patch(task, sources=_canvas_sources(**_CANVAS_REGISTRATION), capabilities=["timers"]),
    )

    competing = landed[0]
    detail = next(item for item in outcome.receipt["checkpoints"] if item["id"] == "detail")
    assert (outcome.revision == competing, outcome.receipt["revision"], detail["label"], competitor.revision) == (
        False,
        outcome.revision,
        "Detail",
        competing,
    )


# --- AC3: every refusal happens before persistence -------------------------


def _stale_task(workspace: PresentationWorkspace, task: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    workspace.set_checkpoint_label(workspace.etag, "detail", "Detail — revised")
    return workspace.etag, _patch(task, label="Intro — revised")


_REFUSALS: tuple[tuple[str, Any, str], ...] = (
    ("stale_task", _stale_task, "PRES_AGENT_TASK_STALE"),
    (
        "revision_conflict",
        lambda workspace, task: ('"sha256:' + "0" * 64 + '"', _patch(task, label="Intro — revised")),
        "PRES_REVISION_CONFLICT",
    ),
    ("if_match_absent", lambda workspace, task: (None, _patch(task, label="Intro — revised")), "PRES_IF_MATCH_REQUIRED"),
    (
        "cross_checkpoint",
        lambda workspace, task: (workspace.etag, _patch(task, checkpoint_id="detail", label="Detail — revised")),
        "PRES_AGENT_SCOPE_VIOLATION",
    ),
    (
        "unscoped_role",
        lambda workspace, task: (workspace.etag, _patch(task, sources={"notes": "Presenter notes"})),
        "PRES_AGENT_SCOPE_VIOLATION",
    ),
    (
        "ungranted_asset",
        lambda workspace, task: (
            workspace.etag,
            _patch(
                task,
                asset_requests=[
                    {
                        "asset_id": "asset_scene",
                        "label": "Scene plate",
                        "alt": "A generated scene plate",
                        "media_type": "image/png",
                        "data_base64": base64.b64encode(_png((9, 9, 9))).decode("ascii"),
                        "provenance": {"kind": "authored", "created_at": "2026-08-30T00:00:00Z"},
                    }
                ],
            ),
        ),
        "PRES_AGENT_UNGRANTED",
    ),
    (
        "context_incomplete",
        lambda workspace, task: (
            workspace.etag,
            {key: value for key, value in _patch(task, label="Intro — revised").items() if key != "before_digest"},
        ),
        "PRES_AGENT_CONTEXT_INCOMPLETE",
    ),
    (
        "context_stale",
        lambda workspace, task: (
            workspace.etag,
            _patch(task, before_digest="0" * 64, label="Intro — revised"),
        ),
        "PRES_AGENT_CONTEXT_STALE",
    ),
    (
        "unvalidated_source",
        lambda workspace, task: (
            workspace.etag,
            _patch(
                task,
                sources={"entry": _module("intro", "export function create(c) { return eval('1'); }\n", assets=["asset_map"], forward_to="detail")},
            ),
        ),
        "PRES_VALIDATION_FAILED",
    ),
    (
        "unknown_patch_field",
        lambda workspace, task: (workspace.etag, _patch(task, label="Intro — revised", checkpoint_order=["detail"])),
        "PRES_AGENT_PATCH_INVALID",
    ),
)


@pytest.mark.parametrize(("name", "build", "code"), _REFUSALS, ids=[row[0] for row in _REFUSALS])
def test_refused_patch_is_rejected_before_any_byte_is_persisted(
    workspace: PresentationWorkspace, name: str, build: Any, code: str
) -> None:
    task = workspace.open_agent_task("intro")
    if_match, patch = build(workspace, task)
    unchanged = _tree_digest(workspace.store.root)

    with pytest.raises(WorkspaceError) as refused:
        workspace.apply_agent_patch(if_match, task["task_id"], patch)

    assert (refused.value.code, _tree_digest(workspace.store.root)) == (code, unchanged)


# --- HTTP surface -----------------------------------------------------------


def test_http_issues_a_task_and_applies_its_patch_against_the_named_revision(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    PresentationWorkspace.create(root, _deck(tmp_path))
    client = TestClient(create_presentation_workspace_app(root))

    issued = client.post("/presentation/checkpoints/intro/agent-tasks", json={"grants": ["add_asset"]})
    task = issued.json()
    applied = client.post(
        f"/presentation/agent-tasks/{task['task_id']}/patch",
        json=_patch(task, sources=_canvas_sources(**_CANVAS_REGISTRATION), capabilities=["timers"]),
        headers={"If-Match": issued.headers["ETag"]},
    )

    assert (issued.status_code, applied.status_code, applied.json()["schema"], applied.headers["ETag"]) == (
        201,
        200,
        AGENT_RESULT_SCHEMA,
        f'"{applied.json()["revision"]}"',
    )


def test_http_refuses_a_patch_whose_task_names_another_checkpoint(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    PresentationWorkspace.create(root, _deck(tmp_path))
    client = TestClient(create_presentation_workspace_app(root))
    issued = client.post("/presentation/checkpoints/intro/agent-tasks", json={})

    refused = client.post(
        f"/presentation/agent-tasks/{issued.json()['task_id']}/patch",
        json=_patch(issued.json(), checkpoint_id="detail", label="Detail — revised"),
        headers={"If-Match": issued.headers["ETag"]},
    )

    assert (refused.status_code, refused.json()["code"]) == (403, "PRES_AGENT_SCOPE_VIOLATION")
