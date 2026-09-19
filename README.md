# Doxagon

**A personal epistemology platform.** Doxagon stores what you believe as plain
Markdown, tracks the evidence for it, types the relationships between beliefs,
and renders the result as an interactive graph, presentations, and essays.

A **Token Smelter** project by Mike Wrather.

## The model

| Concept | What it is | Lives at |
|---|---|---|
| **Phantasia** | an encountered source — a raw impression before judgment | `knowledge/phantasiai/p-*.md` |
| **Katalepsis** | a grasped claim, understood and under evaluation but not yet believed | `knowledge/katalepseis/k-*.md` |
| **Doxa** | one belief, one file | `knowledge/doxai/d-*.md` |
| **Evidence** | a source a belief rests on | `knowledge/evidence/e-*.md` |
| **Logos** | typed edges between beliefs — supports, contradicts, refines | `knowledge/logos.yaml` |
| **Diegesis** | a narrative walk through the graph | `knowledge/diegeses/n-*.md` |

The lifecycle runs from phantasia to katalepsis; assent promotes a katalepsis to doxa.

Beliefs are files, the graph is derived, and everything is inspectable with a
text editor. Validation is strict: dangling endpoints, placeholder nodes, and
noncanonical edge types are errors, not warnings.

## Platform and vault

The platform (this repository) contains **no personal content**. Your
knowledge lives in a **vault** — a separate directory, typically its own
private repository — that you select explicitly at runtime. Nothing is ever
inferred from the checkout, and no vault is ever created implicitly.

```
doxagon-platform        code, packaged CLI, web UI, presentation tooling
your-vault/             knowledge/  projects/  media/  .doxagon/
```

Writes to a vault go through a writer fence (flock) and a roll-forward
write-ahead log, so an interrupted write converges instead of corrupting.

## Quickstart

```bash
git clone https://github.com/Token-Smelter/doxagon-platform.git
cd doxagon-platform

# look around first: packaged synthetic sample vault, read-only
uv run python scripts/dox.py workspace --demo

# create a vault of your own
uv run python scripts/dox.py init ~/doxagon-vault
uv run python scripts/dox.py workspace --vault ~/doxagon-vault

# web UI (the backend still selects its vault by environment variable;
# converting it to --vault is in progress)
DOXAGON_ROOT=~/doxagon-vault uv run uvicorn apps.web.backend.main:app --port 8000
```

For continuous authored HTML, use **Presentations → Open HTML document**.
[Local document playback](./docs/document-playback.md) covers file selection,
private speaker notes, the bridge contract, and an isolated loopback preview.

The full test suite runs with no vault present: `uv run --extra dev pytest`.

## Install and update

Install a checkout with `pipx install -e <checkout>`, or expose
`<checkout>/.venv/bin/dox` on `PATH`. Run `dox doctor` to verify the platform,
vault binding, packaged skills, provider, and frontend build. A non-Docker web
install also needs `npm run build` from `apps/web/frontend/`; Docker builds that
stage itself. After `git pull` (or a package upgrade), run `dox skills sync` to
refresh platform-owned skills in the selected vault.

See [document inspection](docs/document-inspection.md) and
[authoring](docs/document-authoring.md) for the integrated workspace. Before
sharing a repository, follow the [publication boundary](docs/platform-publication.md).

## Status

Actively being extracted from a personal codebase into a standalone platform.
The CLI's workspace commands and the graph engine are converted to explicit
vault selection; the web backend still resolves paths at import time and is
next. Expect interfaces to move.

## License and attribution

Apache-2.0 — see [LICENSE](LICENSE). Redistributions must carry the
[NOTICE](NOTICE) file's attribution. The names "Doxagon" and "Token Smelter"
are trademarks and are **not** licensed — see [TRADEMARKS.md](TRADEMARKS.md);
forks ship under their own name.

If you build something on Doxagon, a "Powered by Doxagon" link is appreciated
and helps the project — but the license, not goodwill, is what governs.
