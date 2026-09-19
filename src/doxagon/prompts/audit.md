You are auditing a personal knowledge graph of beliefs (doxai) and their relationships (edges).

Your task is to evaluate EVERY edge and either CONFIRM it is correct or CORRECT it with the right type.

For EVERY edge, you MUST provide:
1. A **rationale** explaining WHY this relationship exists (not just what it is)
2. An **alias** - a human-readable label that captures the specific nuance of this relationship
3. A **confidence** level (high/medium/low) in your assessment
4. Either CONFIRM the type is correct, or CORRECT it to the right type

## BELIEFS (DOXAI)

Each belief is shown as: `slug: "belief statement"`

{doxai_content}

## CURRENT EDGES

Each edge shows: source → target [type]

{edges_content}

## EDGE TYPES

Choose the MOST ACCURATE type for each relationship:

- `supports` - Source provides reason/evidence to accept target
- `contradicts` - Source and target are genuinely in tension (cannot both be fully true)
- `requires` - Target is a prerequisite for source (source depends on target being true)
- `elaborates` - Source adds detail, nuance, or specificity to target
- `grounds` - Source provides foundational/theoretical basis for target
- `causes` - Source creates, produces, or leads to target
- `resolves` - Source provides solution or answer to a problem stated in target

**CRITICAL DISTINCTIONS:**
- `contradicts` vs `resolves`: If belief A provides a SOLUTION to problem B, use `resolves`, NOT `contradicts`
- `supports` vs `grounds`: Use `grounds` for theoretical foundations, `supports` for evidence/reasons
- `elaborates` vs `supports`: Use `elaborates` when adding detail, `supports` when providing justification

## OUTPUT FORMAT

For EACH edge, output in this exact format:

```
===AUDIT===
source: d-source-slug
target: d-target-slug
current_type: <the current type>
verdict: CONFIRM | CORRECT
correct_type: <type if CORRECT, same as current if CONFIRM>
alias: <human-readable label for this specific relationship>
confidence: high | medium | low
rationale: |
  Why does [source] [type] [target]? Explain the logical connection.
  This should be understandable to someone who hasn't read the beliefs.
flags:
  - Any concerns about this edge (optional)
===END_AUDIT===
```

## ALIAS GUIDELINES

The alias is a human-readable label that captures the specific nuance of the relationship.
While the type is rigid and programmatic, the alias is free-form and descriptive.

**Examples:**
- Type: `contradicts` → Alias: "is in tension with" (when not a hard contradiction)
- Type: `grounds` → Alias: "makes urgent" (when it creates urgency)
- Type: `supports` → Alias: "provides evidence for"
- Type: `causes` → Alias: "enables" or "unlocks"
- Type: `requires` → Alias: "depends on" or "presupposes"

Make aliases concise but descriptive (2-5 words).

## QUALITY GUIDELINES

**Good rationales explain the logical mechanism:**
- "Cost collapse enables consumption increase because lower barriers reduce friction to adoption"
- "JIT synthesis resolves the decomposition trap by replacing static workflows with dynamic path discovery"

**Bad rationales just describe the beliefs:**
- "These are both about AI"
- "Related to governance"
- "Maps content to architecture"

**Confidence calibration:**
- `high` - The relationship is clear and unambiguous from the belief texts
- `medium` - The relationship is likely but requires some inference
- `low` - The relationship is plausible but uncertain

## YOUR TASK

Evaluate ALL {edge_count} edges. Do not skip any.
For each edge, determine if the current type is correct and provide a substantive rationale.

Focus especially on:
1. Any `contradicts` edges that might actually be `resolves`
2. Any edges with vague or missing annotations
3. Cross-domain connections that may be mistyped
