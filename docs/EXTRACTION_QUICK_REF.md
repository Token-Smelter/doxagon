# Extraction Skill: Quick Reference

## Three Critical Decisions

### 1. Output Format: JSON

LLM returns structured JSON, not markdown delimiters. Enables:
- Atomic validation before any file writes
- Programmatic safety checks (ID uniqueness, edge connectivity)
- Schema enforcement

```json
{
  "extraction_metadata": {...},
  "doxai": [{id, belief, status, tags, content, evidence_refs}],
  "evidence": [{id, type, title, source, strength, content}],
  "edges": [{source, target, type, quote/annotation}]
}
```

### 2. Dedup: Pre + Post

**Pre-Extraction:** Inject all 65+ existing doxai into system prompt
- LLM "remembers" entire belief landscape
- Can reference existing IDs immediately
- 65 doxai = 6.5k tokens out of 1M available

**Post-Extraction:** Run `dox dedup` on each new doxa
- Catches probabilistic slips and phrasing variations
- Decides: UNIQUE → create | DUPLICATE → merge | RELATED → create & link

### 3. Existing Context: Include All

Don't filter or sample the 65+ doxai. Full context is negligible cost, massive benefit:
- Perfect dedup capability
- LLM makes intelligent linking decisions
- 1M context makes this trivial

## Validation Pipeline

After JSON parsing, run in order:

1. **Schema & Type Safety** - Is it valid JSON? Has required keys?
2. **Semantic Completeness** - Beliefs > 10 chars? Evidence present?
3. **Internal Consistency** - ID uniqueness? Edge connectivity?
4. **Write Safety** - File collisions? Directory issues?

## Post-Dedup Actions

```
UNIQUE     → Create file + add edges
DUPLICATE  → Merge evidence into existing doxa
RELATED    → Create file + auto-create elaborates edge
```

## Edge Type Rules

- Evidence → Doxa: Always `grounds` (hardcoded)
- Doxa ↔ Doxa: LLM chooses from {supports, contradicts, requires, elaborates, grounds}
- Direction: Foundation → Derived

## Prompt Template Location

`src/doxagon/prompts/extract.md` with template sections:
1. Role statement
2. Existing knowledge graph (65+ doxai injected here)
3. Source document (phantasia content)
4. Extraction rules (atomicity, grounding, linking)
5. Output schema (JSON format)
