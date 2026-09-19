You are extracting beliefs (doxai) and evidence from a source document for a personal epistemology system.

## SOURCE DOCUMENT (Phantasia)

**Title:** {phantasia_title}
**Source:** {phantasia_source}
**Date encountered:** {phantasia_date}

### Content:
{phantasia_content}

## EXISTING BELIEFS (Do Not Duplicate)

These beliefs already exist in the knowledge graph. Do NOT create doxai that express the same idea in different words:

{existing_beliefs}

If you find a claim that semantically matches an existing belief, note it as a DUPLICATE rather than creating a new doxa.

## EXTRACTION RULES

### What is a DOXA (belief)?
- A single atomic claim about reality (typically one sentence)
- Something that can be true or false, supported or refuted
- NOT a definition, tautology, or subjective preference
- NOT evidence itself - evidence SUPPORTS beliefs

Examples:
- DOXA: "AI inference costs are declining exponentially"
- NOT A DOXA: "AI is defined as..." (definition)
- NOT A DOXA: "I prefer Python over Java" (preference)

### What is EVIDENCE?
- A citable source that supports or challenges a belief
- Has concrete attribution: author, title, date, URL
- Contains specific quotes or data points
- Quality annotations: type (empirical/theoretical/anecdotal), strength, gaps

### What are EDGES (relationships)?
- `supports` - Source belief provides reason to accept target
- `contradicts` - Source and target are genuinely in tension (cannot both be fully true)
- `requires` - Target is a prerequisite for source (source depends on target)
- `elaborates` - Source adds detail/nuance to target
- `grounds` - Source provides foundational basis for target
- `causes` - Source creates or leads to target
- `resolves` - Source provides solution or answer to target (use this when one belief solves a problem stated in another)

**CRITICAL: `contradicts` vs `resolves`**
- Use `contradicts` ONLY when beliefs genuinely conflict (e.g., "X is true" vs "X is false")
- Use `resolves` when one belief provides a solution to a problem stated in another
- Example: "JIT procedure synthesis" RESOLVES "decomposition trap" (doesn't contradict it)

### Splitting Compound Claims
Split claims until each can be backed by specific evidence, but no further.

BAD: "AI is getting cheaper and will replace most jobs" (two claims)
GOOD: Split into:
1. "AI inference costs are declining rapidly"
2. "Declining AI costs will lead to significant job displacement"

## OUTPUT FORMAT

Output each artifact with clear markers. Use EXACTLY this format:

For beliefs:
```
===DOXA===
---
belief: "The atomic belief statement goes here"
status: draft
tags: [{tags}]
confidence: {confidence}
provenance:
  method: extraction
  phantasia: {phantasia_slug}
  extracted: {today}
evidence: []
created: {today}
updated: {today}
---

## Reasoning

Why this belief matters and how it connects to other ideas...

## Caveats

- Important limitations or conditions...

## Open Questions

- What remains uncertain...
===END_DOXA===
```

For evidence:
```
===EVIDENCE===
---
assertion: "What this evidence claims"
source: "Author/Organization - Title"
source_url: "https://..."
type: {evidence_type}
strength: {evidence_strength}
status: provisional
provenance:
  phantasia: {phantasia_slug}
  extracted: {today}
annotations: []
gaps: []
---

## Key Quote

> "The relevant quote from the source..."

## Context

Why this evidence matters and its limitations...
===END_EVIDENCE===
```

For edges (one per line):
```
===EDGES===
source|target|edge_type|confidence|rationale
NEW:1|d-existing-belief|supports|high|Because X provides the empirical basis that justifies Y
NEW:2|NEW:1|elaborates|medium|X adds the specific mechanism to Y's general claim
d-existing-slug|NEW:3|grounds|high|X is the theoretical foundation that Y builds upon
===END_EDGES===
```

**CRITICAL for edges:**
- Use `NEW:n` to reference new doxai by their output order (NEW:1 = first doxa, NEW:2 = second, etc.)
- Use exact d-* slugs from the EXISTING BELIEFS list above for existing doxai
- Do NOT invent slugs for new beliefs - always use NEW:n notation
- **confidence**: high (certain), medium (likely), low (tentative)
- **rationale**: MUST explain WHY this relationship exists. Answer: "Why does [source] [edge_type] [target]?"
  - BAD rationale: "Maps the content to structural architecture" (doesn't explain relationship)
  - GOOD rationale: "Cost reduction enables consumption because lower barriers increase usage"

For duplicates found:
```
===DUPLICATE===
belief: "The claim you found that duplicates an existing one"
matches: d-existing-slug
reason: Why these are semantically equivalent
===END_DUPLICATE===
```

## YOUR TASK

1. Read the source document carefully
2. Extract ALL distinct atomic beliefs - be thorough, extract every substantive claim
3. For each potential belief, check against existing beliefs - mark as DUPLICATE if semantically equivalent
4. Identify evidence sources cited in the document
5. Propose edges between new doxai AND to existing beliefs where relationships exist
6. Generate complete artifacts ready for file creation

**CRITICAL EXTRACTION GUIDANCE:**
- Extract AGGRESSIVELY. For a rich 10,000+ word document, expect 20-50+ beliefs.
- Each distinct claim deserves its own doxa, even if related to others
- Don't summarize multiple claims into one - keep them atomic
- Extract from EVERY section of the document, not just conclusions
- Treat each bullet point, each "key insight," each "the reason X is Y" as a potential doxa
- If the document presents a framework with multiple components, each component is a separate belief
- Metaphors and analogies that make substantive claims should be extracted
- "X is like Y because Z" contains multiple extractable claims

Note: For rich sources, extract comprehensively. It's better to have more beliefs that can be merged later than to miss important claims. Err on the side of MORE extraction, not less.

## QUALITY GUIDELINES

- Each belief should be worth defending or attacking
- Evidence should have real citations, not vague "studies show"
- Edges should represent genuine logical relationships
- When uncertain if something is doxa or evidence, ask: "Would I say 'I believe X' or 'X supports my belief that Y'?"

**Edge Quality Checklist:**
1. Is the edge type correct? (especially: is this really a contradiction, or is it a resolution?)
2. Does the rationale explain WHY this specific relationship exists?
3. Could someone unfamiliar with the beliefs understand the connection from the rationale alone?
4. Is confidence appropriately calibrated? (high = certain, medium = likely, low = tentative)
