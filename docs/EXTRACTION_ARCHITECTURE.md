# Extraction Skill Architecture

## Data Flow Diagram

```
[Phantasia Source]
        |
        v
[1. Load & Format]
  - Inject 65+ existing doxai (6.5k tokens)
  - Inject phantasia content (5-20k tokens)
  - Set extraction rules
        |
        v
[2. Call Gemini API]
  gemini-3-pro-high (1M context)
        |
        v
[3. Parse JSON Response]
  Extract: doxai[], evidence[], edges[]
        |
        v
[4. Validate Batch]
  ├─ Schema & type checks (FAIL FAST)
  ├─ Semantic completeness
  ├─ Internal consistency (IDs, edges)
  └─ Write safety (collisions)
        |
        v
[5. Dedup Loop]
  For each new_doxa:
    ├─ Run: dox dedup "{belief_text}" --json
    ├─ Parse: UNIQUE | DUPLICATE:slug | RELATED:slug
    │
    ├─ UNIQUE
    │   └─ Continue to step 6
    │
    ├─ DUPLICATE
    │   ├─ Load existing doxa file
    │   ├─ Append evidence
    │   ├─ Rewrite existing file
    │   └─ Skip file creation
    │
    └─ RELATED
        ├─ Continue to step 6
        └─ Auto-create elaborates edge
        |
        v
[6. Write Files & Graph]
  ├─ Create library/doxai/d-{slug}.md
  ├─ Create library/evidence/e-{slug}.md
  ├─ Update library/logos.yaml with edges
  └─ Invalidate cache
        |
        v
[7. Report Results]
  - X new doxai created
  - Y evidence merged
  - Z edges added
  - W duplicates resolved
```

## Component Responsibilities

### Prompt System
- Location: `src/doxagon/prompts/extract.md`
- Input: 65+ doxai list, phantasia content
- Output: JSON schema definition, rules, examples
- Responsibility: Guide LLM to structured output

### Extraction Module (NEW)
- Location: `src/doxagon/extraction.py`
- Pydantic models: DoxaExtraction, EvidenceExtraction, EdgeExtraction, ExtractionBatch
- Responsibility: Validate JSON structure and consistency

### Dedup Integration
- Location: `scripts/dox.py` (existing `dedup` command)
- Called from: Extraction module post-validation
- Responsibility: Check semantic duplicates, decide actions

### File Writer
- Location: `src/doxagon/storage.py` (or inline in dox extract)
- Responsibility: Safe file creation with collision detection

### Graph Manager
- Location: `src/doxagon/graph.py` (existing)
- Responsibility: Update logos.yaml, invalidate cache

## State Transitions

Each extracted doxa goes through states:

```
        [Extracted]
            |
            +-- DUPLICATE → [Merge Evidence]
            |                      |
            |                      v
            |              [Update Existing]
            |
            +-- RELATED ----+
            |               |
            v               v
        [UNIQUE]      [Create New]
            |               |
            +-------+-------+
                    |
                    v
            [Write File]
                    |
                    v
            [Update Graph]
                    |
                    v
            [Success]
```

## Error Handling

### Validation Failures
- Schema error → Stop, report malformed JSON
- ID collision within batch → Stop, ask user to fix LLM output
- Edge points to non-existent node → Drop edge, warn user
- File collision → Stop, refuse overwrite, suggest rename

### Dedup Failures
- Gemini timeout → Treat as UNIQUE, warn user
- Parse error → Log raw response, treat as UNIQUE
- Network error → Fail extraction, user can retry

### Write Failures
- Permission error → Stop with clear error
- Disk full → Stop with clear error
- Invalid markdown → Log warning, proceed (frontmatter valid = success)

## Performance Considerations

### Token Usage
- Pre-existing doxai: ~6.5k tokens (fixed)
- Phantasia content: 5-20k tokens (variable)
- Prompt overhead: ~2k tokens
- Total: 13.5k - 28.5k tokens (well within 1M)

### Execution Time
- Gemini API call: 5-30 seconds
- JSON parsing: <100ms
- Validation: <100ms
- Dedup loop (N doxai): N × 5-10 seconds
- File writing: <500ms
- Total: 5 seconds + (N × 5-10 seconds dedup time)

### Optimization
- Batch dedup calls? (Not yet - dedup runs sequentially)
- Cache dedup results? (Consider for re-runs)
- Parallel file writes? (Not needed - typically < 10 files)

## Testing Strategy

### Unit Tests
- Validate extraction schema parsing
- Validate edge connectivity checks
- Validate dedup integration points

### Integration Tests
- Extract from real phantasia documents
- Verify files created correctly
- Verify logos.yaml updated
- Verify no duplicates created

### Edge Cases
- Empty phantasia
- Phantasia with all existing claims
- All extracted doxai are duplicates
- Invalid belief text (too short, empty)
- Self-referential edges
- Circular dependencies

## Future Enhancements

### Phase 2 (Optional)
- Batch dedup calls for faster processing
- Caching layer for repeated phantasia extractions
- Human-in-the-loop approval flow
- Confidence scoring on extractions
- Evidence quality scoring

### Phase 3 (Optional)
- Interactive refinement of edges post-extraction
- Suggestion of edge types based on content
- Merging suggestions for highly similar beliefs
- Visualization of new extraction in context of existing graph

