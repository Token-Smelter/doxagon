You are performing a deep integration pass on a personal knowledge graph of beliefs (doxai).

Your task is to identify relationships that SHOULD exist but DON'T, based on the semantic content of the beliefs.

## EXISTING BELIEFS (DOXAI)

{doxai_content}

## EXISTING RELATIONSHIPS (EDGES)

{edges_content}

## YOUR TASK

Analyze the complete library and identify:

### 1. Missing Edges
Relationships that logically should exist based on belief content:
- **Cross-domain connections** - Beliefs from different domains that relate
- **Implicit dependencies** - Beliefs that assume other beliefs as prerequisites
- **Supporting relationships** - Beliefs that provide evidence for others
- **Elaborations** - Beliefs that add nuance or detail to others

### 2. Tensions
Beliefs that may contradict each other (explicitly or subtly):
- Direct contradictions
- Beliefs with incompatible implications
- Beliefs that cannot both be true in the same context

### 3. Evidence Gaps
Beliefs that lack adequate grounding:
- Claims without supporting evidence
- Claims that assume unestablished prerequisites
- Claims that need more foundation

### 4. Cluster Opportunities
Groups of related beliefs that could form a diegesis (narrative argument):
- Beliefs that together tell a coherent story
- Logical progressions from premises to conclusions

## EDGE TYPES

- `supports` - Source provides reason to accept target
- `contradicts` - Source and target are genuinely in tension (cannot both be fully true)
- `requires` - Target is a prerequisite for source (source depends on target)
- `elaborates` - Source adds detail/nuance to target
- `grounds` - Source provides foundational basis for target
- `causes` - Source creates or leads to target
- `resolves` - Source provides solution or answer to target (use when one belief solves a problem)

**CRITICAL: `contradicts` vs `resolves`**
- Use `contradicts` ONLY when beliefs genuinely conflict (e.g., "X is true" vs "X is false")
- Use `resolves` when one belief provides a solution to a problem stated in another
- Example: "JIT procedure synthesis" RESOLVES "decomposition trap" (doesn't contradict it)

## OUTPUT FORMAT

For each finding, output in this exact format:

### Missing Edges
```
===EDGE===
source: d-source-slug
target: d-target-slug
type: supports|contradicts|requires|elaborates|grounds|causes|resolves
strength: strong|moderate|weak
confidence: high|medium|low
rationale: |
  WHY this relationship exists. Answer: "Why does [source] [type] [target]?"
  Must explain the logical connection, not just describe the beliefs.
  BAD: "These beliefs are related to governance"
  GOOD: "Because the cost reduction mechanism described in source directly enables the consumption pattern described in target"
===END_EDGE===
```

### Tensions
```
===TENSION===
beliefs: [d-first-slug, d-second-slug]
severity: high|medium|low
description: |
  Explanation of the tension and why these beliefs conflict.
resolution_options:
  - One possible resolution
  - Another possible resolution
===END_TENSION===
```

### Evidence Gaps
```
===GAP===
belief: d-slug
gap_type: missing_evidence|missing_prerequisite|needs_foundation
description: |
  What's missing and why it matters.
suggested_research: |
  What would fill this gap.
===END_GAP===
```

### Cluster Opportunities
```
===CLUSTER===
name: "Suggested diegesis name"
beliefs: [d-first, d-second, d-third]
narrative: |
  How these beliefs form a coherent argument.
===END_CLUSTER===
```

## QUALITY GUIDELINES

- Be thorough: propose ALL plausible relationships, not just the most obvious ones
- Include moderate-confidence proposals — the user will review and prune
- Look for cross-domain and non-obvious connections especially
- For tensions, focus on meaningful conflicts, not trivial differences
- Evidence gaps should highlight beliefs that would benefit most from grounding
- Clusters should represent coherent arguments, not just topically related beliefs

**Edge Quality Checklist:**
1. Is the edge type correct? (especially: is this really a contradiction, or is it a resolution?)
2. Does the rationale explain WHY this specific relationship exists?
3. Could someone unfamiliar with the beliefs understand the connection from the rationale alone?
4. Is confidence appropriately calibrated? (high = certain, medium = likely, low = tentative)

**Volume Target:** Aim for at least 20-30 edges per pass. If the graph has sparse regions, propose more. Under-proposing is worse than over-proposing — the user can always reject edges but can't discover ones you didn't surface.

## FOCUS AREAS (if specified)

{focus_instructions}
