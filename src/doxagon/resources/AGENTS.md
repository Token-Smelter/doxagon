# Agent orientation

**Run `dox doctor` before you read or change anything in this vault.** This
vault is data; the `dox` CLI is the only supported way to inspect and change it.

This file is platform-owned. `dox init` installs it, `dox skills sync` keeps it
current, and a local edit is reported as `foreign` and never silently
overwritten. Conventions this vault owns belong in `AGENTS.local.md` — see the
last section.

## 0. `dox doctor` is step zero

```bash
dox doctor          # --json for a parseable report
```

It is read-only and exits 0 only when every check passes.

| Check | Reports | A failure means |
|---|---|---|
| `entry_point` | which `dox` ran, its resolved target, the platform commit, and whether the platform tree is clean | the command you invoke is not the platform you think it is |
| `vault_binding` | `DOXAGON_ROOT`, the resolved vault, and whether `knowledge/` and `projects/` exist | no vault is bound, or the bound path is not a vault |
| `skills` | per-skill freshness: `missing`, `current`, `stale`, `foreign` | the skills you are about to follow are absent or not the platform's |
| `agents_md` | this file's freshness in the same four-word vocabulary | your orientation text is absent or not the platform's |
| `provider` | the configured image provider's name, resolved path and `executable_sha256` | image generation cannot run, or runs an unidentified binary |
| `path_shims` | every other `dox` found on `PATH` | a stale shim can shadow the platform entry point |
| `frontend` | whether the platform's built web frontend is present | the hosted workspace cannot serve |

Fix a failing check before doing anything else. Do not route around it, and do
not carry a failed check forward into a task.

`missing` and `stale` are resolved by `dox skills sync`. `foreign` means the
file on disk is not the bytes the platform wrote: read it, decide whether the
local change still matters, and only then re-run with `--force`, which replaces
it. Sync never touches `AGENTS.local.md`, and never removes skills this vault
authored itself.

## 1. Orient on a project before touching it

```bash
dox context <project>            # --json for a parseable report
```

Read-only. It reports the project's identity, its argument sources (thesis,
diegesis, walk), which rendering model is authoritative, whether cues and notes
agree, and which skill to invoke next. Run it for every project you work on;
never infer a project's shape from another project.

## 2. Two rendering models

A project uses exactly one. `dox context` names it; do not guess.

| Model | Authoritative source | How you change it |
|---|---|---|
| Document model | the selected single-file HTML document under `projects/<project>/outputs/document/` | `dox document` — inspect, plan, apply, validate |
| Legacy slides | per-slide sources under `projects/<project>/outputs/presentation/slides/` | edit only the slide sources `dox context` reports |

## 3. The knowledge graph

Canonical vault layout — these names, no others:

| Path | Holds |
|---|---|
| `knowledge/doxai/` | beliefs, one markdown file each, `d-<slug>.md`, frontmatter carries `belief`, `status`, `tags`, `evidence`, `created`, `updated` |
| `knowledge/evidence/` | evidence records, `e-<slug>.md` |
| `knowledge/diegeses/` | narrative walks over the graph |
| `knowledge/logos.yaml` | every typed edge; the only place edges live |
| `knowledge/schema.yaml` | the registered edge-type and domain vocabulary |
| `projects/<project>/` | one presentation or document project, including its outputs |
| `media/` | vault-owned media |

Rules the platform enforces, so work with them rather than against them:

- An edge is identified by `(source, target, type)` and must be unique. Two
  different types may intentionally share an ordered pair.
- Every edge type must already be registered in `knowledge/schema.yaml`. Nuance
  that is not a registered type belongs in the edge's alias or rationale, not in
  a new type invented on the spot.
- Both endpoints of an edge must be existing `d-*` beliefs. Placeholders and
  evidence ids are rejected.
- Write edges with `dox link` and remove them with `dox unlink`; both validate
  the whole candidate edge set before replacing `knowledge/logos.yaml` atomically.

Commands you will use:

```bash
dox list [--tag T] [--status draft|canonical|archived] [-v]
dox show <belief>                 # one belief and its edges
dox related <belief> [--in|--out]
dox search <query>
dox path <source> <target>        # directed by default
dox tree <belief> [--depth N]
dox capture "<belief statement>"  # new draft belief
dox link <source> <target> <edge_type> [--alias LABEL]
dox unlink <source> <target> <edge_type>
dox validate                      # integrity codes; run before you finish
```

## 4. Style bundles

```bash
dox styles lint [<project>]       # exits 1 on errors
```

Reports stale markers, broken bundle dependencies, missing sources and closures
too large for the configured provider. `--fix-requires` mirrors body
`**Requires:**` markers into frontmatter `requires:` and prints the diff.

## 5. Authoring a document

```bash
dox document context   --project <project>
dox document inspect   --project <project> --snapshot <snapshot>
dox document plan      --project <project> --snapshot <snapshot> --change C.json --output P.json
dox document apply     --project <project> P.json
dox document validate  --project <project>
```

Plans are reviewed artifacts: `plan` writes a patch against a named snapshot and
changes nothing, `apply` promotes it only if the recorded inputs still match.
`asset-plan`, `generation-plan`, `generation-run` and `generation-job` cover
images; a generation run is a bounded, potentially paid external effect, so the
prompt is read before it is spent. Invoke the `presentation-document` skill for
this path, and `visual-definition` or `visual-concept-brainstorm` for imagery.

## 6. Standing rules

- The platform owns code, contracts and skills; this vault owns data. Nothing is
  copied between them, and the platform checkout is never a fallback vault.
- Fail rather than substitute: never drop a reference, downgrade a setting, or
  admit a placeholder to make a command succeed.
- Derived outputs are derived. Change the authoritative source `dox context`
  names, then regenerate.

## This vault's local conventions

Read ./AGENTS.local.md if present — conventions this vault owns. The platform
never overwrites it.
