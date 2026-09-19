"""Proof that generation and AI authoring are producer-backed, not decorative.

Both surfaces are one seam between the workspace and an executable this
deployment names: `SubprocessImageGenerator` renders a variant, and
`SubprocessAgentAuthor` writes one scoped source. Every test here runs a real
executable across that seam, because the failure these replace is a control the
product exposes and nothing behind it — a Retry that could only ever be refused,
and an "Edit with AI" whose bytes the client wrote for itself.

The scripts are written into the test's own temporary directory from public
bytes; nothing here reads a real vault, a model, or a network.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
import pytest

from doxagon.html_editions.contracts import sha256
from doxagon.presentation_backends import (
    SubprocessAgentAuthor,
    SubprocessImageGenerator,
    resolve_agent_author,
    resolve_image_generator,
)
from doxagon.presentations import PresentationWorkspace, WorkspaceError
from doxagon.presentations.api import create_presentation_workspace_app
from doxagon.presentations.authoring import AGENT_PROPOSAL_SCHEMA
from doxagon.presentations.jobs import FAILED, SUCCEEDED
from tests.test_presentations_agent import _deck

_PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

#: A backend that renders 16:9 and refuses anything else, exactly as a hosted
#: one may. The refusal has to travel as the backend's own diagnostic.
_GENERATOR = f"""#!/usr/bin/env python3
import argparse, base64, pathlib, sys

parser = argparse.ArgumentParser()
parser.add_argument("--prompt-file", required=True)
parser.add_argument("--output", required=True)
parser.add_argument("--image-size", required=True)
parser.add_argument("--aspect-ratio", required=True)
parser.add_argument("--source", action="append", default=[])
arguments = parser.parse_args()
if arguments.aspect_ratio != "16:9":
    print("this backend renders 16:9 only", file=sys.stderr)
    raise SystemExit(2)
target = pathlib.Path(arguments.output) / "generated.png"
target.write_bytes(base64.b64decode("{_PNG}"))
"""

#: An author that answers from the task context it was handed, so a proposal
#: can be shown to have come from the backend rather than from the caller.
_AUTHOR = """#!/usr/bin/env python3
import json, sys

request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
task = request["task"]
sys.stdout.write(
    "<section class=\\"checkpoint\\" data-checkpoint=\\"%s\\"><h1>%s</h1></section>\\n"
    % (task["checkpoint"]["id"], request["instruction"])
)
"""

_REFUSING_AUTHOR = """#!/usr/bin/env python3
import sys

print("the model refused this request", file=sys.stderr)
raise SystemExit(3)
"""


def _executable(directory: Path, name: str, body: str) -> str:
    path = directory / name
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)
    return str(path)


@pytest.fixture
def workspace(tmp_path: Path) -> PresentationWorkspace:
    return PresentationWorkspace.create(tmp_path / "workspace", _deck(tmp_path))


def _target(checkpoint_id: str = "intro", **overrides: Any) -> dict[str, Any]:
    return {
        "checkpoint_id": checkpoint_id,
        "label": "Map",
        "alt": "A rendered map",
        "description": "A wide map of the region.",
        "aspect_ratio": "16:9",
        "variants": 1,
        **overrides,
    }


# --- the generator seam ----------------------------------------------------


def test_no_configured_generator_is_reported_rather_than_stubbed() -> None:
    """A deployment with no backend has no backend; it does not get a stand-in."""

    assert resolve_image_generator(None) is None
    assert resolve_image_generator("   ") is None
    assert isinstance(resolve_image_generator("/usr/bin/true"), SubprocessImageGenerator)


def test_a_generation_admits_exactly_what_the_backend_produced(
    workspace: PresentationWorkspace, tmp_path: Path
) -> None:
    generator = SubprocessImageGenerator(_executable(tmp_path, "generator.py", _GENERATOR))
    job = workspace.start_generation(idempotency_key="one", targets=[_target()])

    finished = workspace.run_generation(job.job_id, generator)

    assert finished.status == SUCCEEDED
    admitted = {str(item["id"]): item for item in workspace.read().as_dict()["assets"]}
    produced = [admitted[asset_id] for asset_id in finished.asset_ids]
    assert produced, "a succeeded generation admits the variants it produced"
    assert all(item["provenance"]["kind"] == "generated" for item in produced)
    assert all(item["provenance"]["generator"] == "image-generation/1" for item in produced)
    # Admitted, not selected: no step references a variant until someone says so.
    assert all(item["referenced_by"] == [] for item in produced)


def test_a_refusing_backend_fails_the_job_in_its_own_vocabulary(
    workspace: PresentationWorkspace, tmp_path: Path
) -> None:
    """A backend refusal is data on a durable record, not a crash or a placeholder."""

    generator = SubprocessImageGenerator(_executable(tmp_path, "generator.py", _GENERATOR))
    before = workspace.revision
    job = workspace.start_generation(idempotency_key="portrait", targets=[_target(aspect_ratio="9:16")])

    finished = workspace.run_generation(job.job_id, generator)

    assert finished.status == FAILED
    assert finished.error["code"] == "PRES_GENERATION_FAILED"
    assert "16:9" in finished.failures[0]["message"], "the backend's own diagnostic survives"
    assert workspace.revision == before, "a failed generation promotes nothing"


def test_only_a_failed_job_is_retryable_and_a_retry_is_a_new_attempt(
    workspace: PresentationWorkspace, tmp_path: Path
) -> None:
    """The control the editor may offer is exactly the one the store accepts."""

    generator = SubprocessImageGenerator(_executable(tmp_path, "generator.py", _GENERATOR))
    succeeded = workspace.run_generation(
        workspace.start_generation(idempotency_key="wide", targets=[_target()]).job_id, generator
    )
    failed = workspace.run_generation(
        workspace.start_generation(idempotency_key="tall", targets=[_target(aspect_ratio="9:16")]).job_id,
        generator,
    )

    with pytest.raises(WorkspaceError) as refused:
        workspace.retry_job(succeeded.job_id)
    assert refused.value.code == "PRES_JOB_NOT_RETRYABLE"

    retry = workspace.retry_job(failed.job_id)

    assert retry.attempt == 2
    assert retry.retry_of == failed.job_id
    assert retry.lineage_id == failed.lineage_id
    # The retry is pending: it is work that still has to be executed.
    assert workspace.run_generation(retry.job_id, generator).status == FAILED


def test_the_jobs_route_lists_the_failed_job_a_retry_exists_for(
    workspace: PresentationWorkspace, tmp_path: Path
) -> None:
    """A failed job admitted no asset, so it is only reachable through this list."""

    generator = SubprocessImageGenerator(_executable(tmp_path, "generator.py", _GENERATOR))
    workspace.run_generation(
        workspace.start_generation(idempotency_key="tall", targets=[_target(aspect_ratio="9:16")]).job_id,
        generator,
    )
    client = TestClient(create_presentation_workspace_app(workspace.store.root))

    response = client.get("/presentation/jobs")

    assert response.status_code == 200
    listed = response.json()["jobs"]
    assert [record["status"] for record in listed] == [FAILED]
    assert client.get("/presentation/jobs?kind=nonsense").status_code == 422


def test_the_run_route_executes_the_configured_backend(
    workspace: PresentationWorkspace, tmp_path: Path
) -> None:
    """The hosted route is the one the editor calls; unconfigured says so."""

    job = workspace.start_generation(idempotency_key="wide", targets=[_target()])
    unconfigured = TestClient(create_presentation_workspace_app(workspace.store.root))

    refused = unconfigured.post(f"/presentation/jobs/{job.job_id}/run")

    assert refused.status_code == 503
    assert refused.json()["code"] == "PRES_GENERATOR_UNAVAILABLE"

    configured = TestClient(
        create_presentation_workspace_app(
            workspace.store.root,
            generator=SubprocessImageGenerator(_executable(tmp_path, "generator.py", _GENERATOR)),
        )
    )

    ran = configured.post(f"/presentation/jobs/{job.job_id}/run")

    assert ran.status_code == 200
    assert ran.json()["status"] == SUCCEEDED


# --- the authoring seam ----------------------------------------------------


def test_no_configured_author_is_reported_rather_than_faked(workspace: PresentationWorkspace) -> None:
    task = workspace.open_agent_task("intro")

    with pytest.raises(WorkspaceError) as refused:
        workspace.propose_agent_edit(task["task_id"], role="document", instruction="Tighten it", author=None)

    assert refused.value.code == "PRES_AGENT_AUTHOR_UNAVAILABLE"
    assert refused.value.status == 503


def test_the_author_writes_the_bytes_the_editor_will_show(
    workspace: PresentationWorkspace, tmp_path: Path
) -> None:
    """The proposal is the backend's answer, digested over the exact bytes."""

    author = SubprocessAgentAuthor(_executable(tmp_path, "author.py", _AUTHOR))
    task = workspace.open_agent_task("intro")
    before = workspace.revision

    proposal = workspace.propose_agent_edit(
        task["task_id"], role="document", instruction="Say it for investors", author=author
    )

    assert proposal["schema"] == AGENT_PROPOSAL_SCHEMA
    assert proposal["task_id"] == task["task_id"]
    assert proposal["checkpoint_id"] == "intro"
    assert proposal["base_revision"] == task["base_revision"]
    assert proposal["author"] == "subprocess:author.py"
    assert "Say it for investors" in proposal["proposal"]
    assert 'data-checkpoint="intro"' in proposal["proposal"]
    assert proposal["proposal_sha256"] == sha256(proposal["proposal"].encode("utf-8"))
    # A proposal is not a mutation: approving it is a separate, checked patch.
    assert workspace.revision == before


def test_a_proposal_cannot_reach_a_source_the_task_does_not_own(
    workspace: PresentationWorkspace, tmp_path: Path
) -> None:
    """The scope check happens before the backend is asked to write anything."""

    author = SubprocessAgentAuthor(_executable(tmp_path, "author.py", _AUTHOR))
    task = workspace.open_agent_task("intro")

    with pytest.raises(WorkspaceError) as refused:
        workspace.propose_agent_edit(task["task_id"], role="notes", instruction="Add notes", author=author)

    assert refused.value.code == "PRES_AGENT_SCOPE_VIOLATION"
    assert refused.value.status == 403


def test_a_stale_task_is_refused_before_the_backend_spends_work(
    workspace: PresentationWorkspace, tmp_path: Path
) -> None:
    author = SubprocessAgentAuthor(_executable(tmp_path, "author.py", _AUTHOR))
    task = workspace.open_agent_task("intro")
    workspace.set_checkpoint_label(workspace.etag, "detail", "Detail, renamed")

    with pytest.raises(WorkspaceError) as refused:
        workspace.propose_agent_edit(task["task_id"], role="document", instruction="Tighten", author=author)

    assert refused.value.code == "PRES_AGENT_TASK_STALE"


def test_an_instruction_is_required(workspace: PresentationWorkspace, tmp_path: Path) -> None:
    author = SubprocessAgentAuthor(_executable(tmp_path, "author.py", _AUTHOR))
    task = workspace.open_agent_task("intro")

    with pytest.raises(WorkspaceError) as refused:
        workspace.propose_agent_edit(task["task_id"], role="document", instruction="   ", author=author)

    assert refused.value.code == "PRES_AGENT_INSTRUCTION_REQUIRED"


def test_a_refusing_author_never_becomes_a_proposal(
    workspace: PresentationWorkspace, tmp_path: Path
) -> None:
    author = SubprocessAgentAuthor(_executable(tmp_path, "author.py", _REFUSING_AUTHOR))
    task = workspace.open_agent_task("intro")

    with pytest.raises(WorkspaceError) as refused:
        workspace.propose_agent_edit(task["task_id"], role="document", instruction="Tighten", author=author)

    assert refused.value.code == "PRES_AGENT_AUTHOR_FAILED"
    assert "the model refused this request" in refused.value.message


def test_the_proposal_route_answers_the_editor_and_the_patch_then_lands(
    workspace: PresentationWorkspace, tmp_path: Path
) -> None:
    """End to end: the backend writes, the human approves, the server promotes."""

    client = TestClient(
        create_presentation_workspace_app(
            workspace.store.root, author=resolve_agent_author(_executable(tmp_path, "author.py", _AUTHOR))
        )
    )
    task = client.post("/presentation/checkpoints/intro/agent-tasks", json={"grants": []}).json()

    proposed = client.post(
        f"/presentation/agent-tasks/{task['task_id']}/proposal",
        json={"role": "document", "instruction": "Say it for investors"},
    )

    assert proposed.status_code == 201
    proposal = proposed.json()
    assert proposal["author"].startswith("subprocess:")

    landed = client.post(
        f"/presentation/agent-tasks/{task['task_id']}/patch",
        headers={"If-Match": f'"{task["base_revision"]}"'},
        json={
            "schema": "doxagon.presentation-agent-patch/2",
            "task_id": task["task_id"],
            "base_revision": task["base_revision"],
            "checkpoint_id": task["scope"]["checkpoint_id"],
            "before_digest": task["before_digest"],
            # Exactly the bytes the backend proposed; nothing is re-authored here.
            "sources": {"document": proposal["proposal"]},
            "summary": "Approved AI edit",
        },
    )

    assert landed.status_code == 200
    outcome = landed.json()
    assert outcome["revision"] != task["base_revision"]
    assert outcome["diff"]["preview"]["changed"] is True


def test_an_undeclared_proposal_field_is_refused(
    workspace: PresentationWorkspace, tmp_path: Path
) -> None:
    """The request body is closed, like every other body on this surface."""

    client = TestClient(
        create_presentation_workspace_app(
            workspace.store.root, author=resolve_agent_author(_executable(tmp_path, "author.py", _AUTHOR))
        )
    )
    task = client.post("/presentation/checkpoints/intro/agent-tasks", json={"grants": []}).json()

    response = client.post(
        f"/presentation/agent-tasks/{task['task_id']}/proposal",
        json={"role": "document", "instruction": "Tighten", "checkpoint_id": "detail"},
    )

    assert response.status_code == 422
    assert "checkpoint_id" in json.dumps(response.json())
