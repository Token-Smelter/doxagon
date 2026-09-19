"""Producer-backed authoring for one scoped agent task.

The editor does not write the bytes it asks a human to approve. It asks the
server for a proposal; the server hands the *issued task* — the same scope,
before-state, and source text `build_task` published — to the configured author,
and the author answers with the whole replacement text for exactly one editable
role. That text travels back as a proposal with its own digest so the human
approving it can see what they are promoting, and the patch that actually lands
is still checked by `apply_agent_patch` against the task's context.

A proposal is not a mutation. Nothing here touches a revision, a source file, or
a job; producing one twice produces two proposals and no promotions.

There is no fallback author. A deployment with no author configured is told so
by name (`PRES_AGENT_AUTHOR_UNAVAILABLE`) rather than being handed synthesized
text that no producer wrote — a hollow proposal is exactly the failure this
surface exists to prevent.

The author itself lives outside this package: running an executable is an
execution facility, and this package deliberately holds none
(`doxagon.presentation_backends` implements the seam).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from doxagon.html_editions.contracts import sha256

from .errors import WorkspaceError

AGENT_PROPOSAL_SCHEMA = "doxagon.presentation-agent-proposal/1"
AGENT_AUTHORING_REQUEST_SCHEMA = "doxagon.presentation-agent-authoring-request/1"

MAX_INSTRUCTION_CHARS = 4096
#: A proposal is one source file's whole text. The same ceiling the patch
#: parser enforces applies here, so an author cannot produce bytes that could
#: only ever be refused later.
MAX_PROPOSAL_BYTES = 1 << 20


@dataclass(frozen=True)
class AuthoringRequest:
    """Everything an author is given, and nothing it may decide for itself.

    The scope, the target role, and the before-state all come from the
    server-issued task, so an author cannot widen what it is writing: the role
    was checked against `scope.editable_sources` before this request existed.
    """

    task: Mapping[str, Any]
    role: str
    instruction: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": AGENT_AUTHORING_REQUEST_SCHEMA,
            "role": self.role,
            "instruction": self.instruction,
            "task": dict(self.task),
        }


class AgentAuthor(Protocol):
    """The single seam between a scoped task and whichever backend writes."""

    @property
    def author_id(self) -> str: ...

    def __call__(self, request: AuthoringRequest) -> str: ...


def author_proposal(request: AuthoringRequest, author: AgentAuthor) -> dict[str, Any]:
    """Ask the author for one role's whole text and describe what it produced.

    The digest is computed here, over the exact bytes the editor will show and
    the human will approve, so the proposal a reviewer sees and the patch that
    lands can be compared without trusting either side's summary of itself.
    """

    text = author(request)
    if not isinstance(text, str) or not text.strip():
        raise WorkspaceError(
            "PRES_AGENT_AUTHOR_EMPTY", "the authoring backend proposed no source", status=502
        )
    data = text.encode("utf-8")
    if len(data) > MAX_PROPOSAL_BYTES:
        raise WorkspaceError(
            "PRES_AGENT_PROPOSAL_TOO_LARGE",
            f"the proposed {request.role} source exceeds the source size limit",
            status=422,
        )
    task = request.task
    return {
        "schema": AGENT_PROPOSAL_SCHEMA,
        "task_id": task["task_id"],
        "checkpoint_id": task["scope"]["checkpoint_id"],
        "base_revision": task["base_revision"],
        "role": request.role,
        "instruction": request.instruction,
        "author": author.author_id,
        "proposal": text,
        "proposal_sha256": sha256(data),
    }
