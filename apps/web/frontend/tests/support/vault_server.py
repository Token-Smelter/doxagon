"""Serve the production app over a synthetic vault so a browser proof is real.

Nothing here stubs a producer. The vault is written from public bytes in a
directory this process owns, `DOXAGON_ROOT` points at it, and then
`apps.web.backend.main.app` — the same application object uvicorn serves — is
imported and run. The thesis list the project rail reads and the Step workspace
the editor opens therefore both come from the real routers, and the first open
runs the real migrator against the real legacy tree.

The port is bound here and printed, so a caller never races a fixed port.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shlex
import shutil
import socket
import sys

REPO_ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

PORT_LINE = "PRESENTATION_VAULT_PORT="

#: The two backends this deployment configures. They are separate executables
#: the server runs through its own seams, exactly as a hosted deployment names
#: them, so the whole server-side path is the production one.
IMAGE_GENERATOR = Path(__file__).resolve().parent / "image_generator.py"
AGENT_AUTHOR = Path(__file__).resolve().parent / "agent_author.py"


def python_executable(script: Path, root: Path) -> Path:
    """Wrap a backend script in the interpreter that runs this clean archive."""

    executable = root / ".doxagon-image-generator"
    executable.write_text(
        f"#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(script))} \"$@\"\n",
        encoding="utf-8",
    )
    executable.chmod(0o700)
    return executable


#: Two beliefs a telling's cue can rest on. The first carries the hand-written
#: `short:` label a chip prefers; the second carries none, so a reader of it has
#: to shorten the belief itself. Both are ordinary vault files read by the real
#: graph loader and the real doxa router.
CLAIM_DOXAI = {
    "d-partisan-validators": (
        "---\n"
        "short: Validators serve their master\n"
        "belief: \"Validators are partisan: they read every ambiguity in favour of whoever appointed them\"\n"
        "tags: []\n"
        "evidence: []\n"
        "---\n\nA validator argues for the side that pays it.\n"
    ),
    "d-household-verification-airlock": (
        "---\n"
        "belief: \"Households verify high-risk actions in an airlock before they reach the world\"\n"
        "tags: []\n"
        "evidence: []\n"
        "---\n\nNothing leaves the household unparsed.\n"
    ),
}


def write_claim_doxai(root: Path) -> None:
    """Write the doxai a telling's claim chips resolve their labels from."""

    doxai = root / "library" / "doxai"
    doxai.mkdir(parents=True, exist_ok=True)
    for slug, body in CLAIM_DOXAI.items():
        (doxai / f"{slug}.md").write_text(body, encoding="utf-8")


#: The diegesis the `outline` project declares instead of `synthetic`.
#:
#: The `n-` prefix is the library's own convention and the only shape
#: `list_diegeses` enumerates, so this is the scope whose *title* a caller can
#: resolve. `synthetic` stays off-convention on purpose: together the two prove
#: a rail groups by the declared slug either way, naming the scope when the
#: library lists it and falling back to the slug when it does not.
SECOND_DIEGESIS = "n-cartography"


def write_synthetic_diegesis(root: Path) -> None:
    """The diegeses the synthetic projects declare in their `config.yaml`.

    With them, the real diegeses and theses routers answer the graph's diegesis
    panel, so a proof of its Linked Theses cards reads both rendering models
    from the producers rather than from a fixture the test invented.
    """

    diegeses = root / "library" / "diegeses"
    diegeses.mkdir(parents=True, exist_ok=True)
    (diegeses / "synthetic.md").write_text(
        "---\n"
        "title: Synthetic diegesis\n"
        "sections:\n"
        "  opening:\n"
        "    title: Opening\n"
        "    doxai:\n"
        + "".join(f"      - {slug}\n" for slug in CLAIM_DOXAI)
        + "walks:\n  canonical:\n    - opening\n---\n\nThe scope these synthetic projects argue within.\n",
        encoding="utf-8",
    )
    (diegeses / f"{SECOND_DIEGESIS}.md").write_text(
        "---\ntitle: Cartography\nsections: {}\nwalks:\n  canonical: []\n---\n\nA second scope, so a vault holds more than one.\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="an empty directory this server owns")
    parser.add_argument("--host", default="127.0.0.1")
    arguments = parser.parse_args()

    root = Path(arguments.root)
    (root / "library").mkdir(parents=True, exist_ok=True)

    # `doxagon.config` resolves its roots at import time, so the vault has to be
    # declared before anything imports the application. The generator and author
    # are read at import time too, by `main.install_vault_presentations`.
    os.environ["DOXAGON_ROOT"] = str(root)
    os.environ["DOXAGON_IMAGE_GENERATOR"] = str(python_executable(IMAGE_GENERATOR, root))
    os.environ["DOXAGON_AGENT_AUTHOR"] = str(AGENT_AUTHOR)

    from tests.synthetic_vault import (  # noqa: E402
        write_blocked_presentation,
        write_empty_presentation,
        write_numbered_presentation,
        write_legacy_presentation,
        write_stock_presentation,
        write_vault,
    )

    write_claim_doxai(root)
    write_synthetic_diegesis(root)
    (root / 'projects').mkdir(exist_ok=True)
    (root / 'theses').symlink_to('projects')
    vault = write_vault(root)
    from tests.authored_vault import write_authored_project, write_image_generation_inputs
    write_image_generation_inputs(write_authored_project(root))
    # Two more real legacy shapes the migrator answers differently: a tree with
    # blocking mapping ambiguities, and a project with no presentation authored
    # yet. Both are served by the same production routers as `alpha`.
    write_blocked_presentation(vault)
    write_empty_presentation(vault)
    write_stock_presentation(vault)
    write_numbered_presentation(vault)
    # A second copy of the same legacy shape, reserved for the one test that
    # reorders a deck. Reordering the shared `stock` tree would decide what a
    # later test in the same worker reads. It declares the second diegesis, so
    # the vault this server serves spans more than one scope.
    write_stock_presentation(vault, "outline", SECOND_DIEGESIS)

    from doxagon.presentations.vault import open_or_migrate

    for slug, fixture in (("scene", "scene-deck"), ("document", "document-deck")):
        write_legacy_presentation(vault, slug)
        workspace = open_or_migrate(vault, slug)
        with workspace.store.exclusive(), workspace.store.candidate() as candidate:
            for stale in candidate.iterdir():
                if stale.name not in {"assets", "receipts"}:
                    shutil.rmtree(stale, ignore_errors=True) if stale.is_dir() else stale.unlink()
            shutil.copytree(REPO_ROOT / f"tests/fixtures/presentations/{fixture}", candidate, dirs_exist_ok=True)
            workspace.store.promote(candidate)

    import uvicorn  # noqa: E402

    from apps.web.backend.main import app  # noqa: E402

    bound = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    bound.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    bound.bind((arguments.host, 0))
    bound.listen(64)
    print(f"{PORT_LINE}{bound.getsockname()[1]}", flush=True)

    uvicorn.Server(uvicorn.Config(app, log_level="warning")).run(sockets=[bound])


if __name__ == "__main__":
    main()
