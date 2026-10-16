# Extraction: judgment and answer format

Input: `dox extract <p-slug> --context`, a JSON document with fields:

| Field | Contents |
|---|---|
| `phantasia` | slug, title, source, channel, encountered, tags |
| `content` | the full source text |
| `existing_beliefs` | every doxa already in the graph |
| `edge_types` | the only edge types you may use, with descriptions |
| `domains` | the only `domain:` tag values you may use |

Output: an answer file of blocks, checked with `--response FILE --dry-run`.

## What counts as what

| Kind | Is | Is not |
|---|---|---|
| **Doxa** | one atomic claim about reality that can be true or false, supported or refuted; usually one sentence | a definition, a tautology, a preference ("I prefer X"), or evidence itself |
| **Evidence** | a citable source the document gives: author or organization, title, date, URL if any, a verbatim quote or data point, and its type, strength and gaps | "studies show"; a citation the source does not give |
| **Edge** | a typed logical relationship between two doxai, with a rationale that says *why* | "both are about X" |

Ask "would I say *I believe X*, or *X supports my belief that Y*?" when unsure
whether something is a doxa or evidence.

**Split compound claims** until each part could be backed by specific evidence,
and no further. "AI is getting cheaper and will replace most jobs" is two
doxai: "AI inference costs are declining rapidly" and "Declining AI costs will
lead to significant job displacement". Metaphors and "X is like Y because Z"
often contain several claims.

**Coverage.** Extract from every section, not just the conclusion. Each
distinct claim, each component of a framework and each "the reason X is Y" is
a candidate. A long report can yield dozens of doxai, a page of notes a
handful. On a user's first import, prefer 3–8 strong beliefs.

## Duplicates

Compare every candidate against `existing_beliefs` before writing it.

| Verdict | Means | Do |
|---|---|---|
| Duplicate | the same claim in different words ("AI will change coding" / "Machine learning will transform software development") | a `===DUPLICATE===` block naming the existing slug; no doxa |
| Related | a different claim that connects ("AI will change coding" / "AI reduces development costs") | a new doxa, plus an edge to the existing slug |
| Unique | nothing similar exists | a new doxa |

When torn between duplicate and related, choose related.

## Choosing edge types

Use only names in `edge_types`, and read their descriptions. The distinctions
that are most often confused:

- `contradicts` only when both cannot be fully true. If one belief *solves* a
  problem another states, that is `resolves`, not `contradicts`.
- `grounds` for a theoretical foundation, `supports` for evidence or reasons.
- `elaborates` adds detail; `supports` adds justification.

A rationale answers "why does *source* *type* *target*?" so that someone who
has not read the beliefs understands the connection. Calibrate confidence:
`high` when the texts make it unambiguous, `medium` when it takes some
inference, `low` when plausible but uncertain.

## Answer format

Blocks may appear in any order. Number new doxai `NEW:1`, `NEW:2`, … in the
order you write them, and use exact `d-*` slugs from `existing_beliefs` for
existing ones. Never invent a slug for a new doxa.

```
===DOXA===
---
belief: "The atomic belief statement"
status: draft
tags: []
confidence: medium
provenance:
  method: extraction
  phantasia: p-source-slug
evidence: []
---

## Reasoning

Why this belief matters and how it connects to other ideas.

## Caveats

- Limits or conditions.
===END_DOXA===

===EVIDENCE===
---
assertion: "What this evidence claims"
source: "Author or organization - Title (year)"
type: empirical
strength: moderate
status: provisional
provenance:
  phantasia: p-source-slug
gaps: []
---

## Key Quote

> "Verbatim from the source"
===END_EVIDENCE===

===EDGES===
source|target|edge_type|confidence|rationale
NEW:2|NEW:1|elaborates|medium|NEW:2 names the mechanism behind NEW:1's general claim
NEW:1|d-existing-slug|supports|high|Why the first supports the second
===END_EDGES===

===DUPLICATE===
belief: "The candidate claim"
matches: d-existing-slug
reason: Why these are the same claim
===END_DUPLICATE===
```

Required fields: a doxa needs `belief` (at least 10 characters), `status` and
`provenance`. Evidence needs `assertion`, `source`, `type`, `strength` and
`status`. Add `source_url` only when the source gives one. `type` is one of
empirical, theoretical, anecdotal, expert-opinion or logical, and `strength`
is strong, moderate or weak.

One invalid block refuses the whole answer. Fix it and dry-run again.
