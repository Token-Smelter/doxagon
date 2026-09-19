#!/usr/bin/env python3
"""A real authoring backend for the browser proof, behind the real seam.

`SubprocessAgentAuthor` writes the whole authoring request — the server-issued
task included — to this process's stdin and reads the proposed source back from
its stdout. Everything on the server side of that seam runs for real: the scope
check against the issued task's editable sources, the staleness check, the
proposal digest, and the ordinary patch path the human approval then takes.

The bytes it answers with are composed from the *task context the server sent*
(the checkpoint's id and label, its before-state digest) and the operator's
instruction, so a proof can show the editor displaying source no test ever
typed. It is deliberately not the editor's own text echoed back: an author that
returned its input would prove nothing about who wrote the proposal.
"""

from __future__ import annotations

import json
import sys


def compose(request: dict) -> str:
    task = request["task"]
    checkpoint = task["checkpoint"]
    role = request["role"]
    instruction = request["instruction"].strip()
    digest = task["before_digest"][:12]

    if role == "styles":
        return (
            f"/* authored-by-backend for {checkpoint['id']} against {digest} */\n"
            f".checkpoint {{ padding: 4rem; }}\n"
        )
    if role == "notes":
        return f"authored-by-backend for {checkpoint['id']} against {digest}\n\n{instruction}\n"
    if role == "entry":
        # The registration block is the checkpoint's contract; an author that
        # rewrote the program would have to reproduce it, which is a different
        # proof from this one.
        raise SystemExit("this backend does not rewrite a checkpoint program")
    return (
        f'<section class="checkpoint" data-checkpoint="{checkpoint["id"]}">\n'
        f"  <h1>{checkpoint['label']} \u2014 {instruction}</h1>\n"
        f"  <p>authored-by-backend for {checkpoint['id']} against {digest}</p>\n"
        f"</section>\n"
    )


def main() -> int:
    request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    sys.stdout.write(compose(request))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
