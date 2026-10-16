# Audit: judgment and answer format

Goal: for every edge, confirm its type or correct it, and give it a
rationale, an alias and a confidence.

`dox audit --context` prints edges with both endpoint beliefs and their
current type, alias, rationale and confidence. Page through large graphs with
`--offset N --limit M`; each page is an independent unit of work.

## Judging an edge

1. Read both beliefs, then ask whether the current type is the *most*
   accurate name in `edge_types`.
2. Check the confusions first:
   - `contradicts` that is really `resolves`, where one belief solves a
     problem the other states
   - `supports` that is really `grounds`, a theoretical foundation rather
     than evidence
   - `supports` that is really `elaborates`, detail rather than justification
3. Write a rationale that explains the mechanism, so someone who has not read
   the beliefs understands it:
   - good: "Cost collapse enables consumption growth because lower barriers
     reduce friction to adoption"
   - bad: "Both are about AI"; "Related to governance"
4. Give an **alias**, a free-form 2–5 word label for this specific
   relationship. The type stays rigid while the alias carries nuance:
   `contradicts` → "is in tension with", `grounds` → "makes urgent",
   `causes` → "unlocks", `requires` → "presupposes".
5. Calibrate confidence: `high` when the texts make it unambiguous, `medium`
   when it takes some inference, `low` when it is plausible but uncertain.

Review edges with vague or missing rationales, and cross-domain edges, most
carefully. Audit every edge on the page; do not skip any. A symmetric type
such as `contradicts` is stored in both directions, so each direction is its
own edge and needs its own verdict.

## Answer format

One block per edge. `source`, `target` and `current_type` must match the
context exactly.

```
===AUDIT===
source: d-source-slug
target: d-target-slug
current_type: contradicts
verdict: CORRECT
correct_type: resolves
alias: offers a way out of
confidence: high
rationale: |
  Why the source resolves the target.
===END_AUDIT===
```

`verdict` is CONFIRM or CORRECT; CORRECT requires `correct_type`. A block
naming an edge that does not exist, or any invalid block, refuses the whole
answer. Show the user the corrections before applying them.
