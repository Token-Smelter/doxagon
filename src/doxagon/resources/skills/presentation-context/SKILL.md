---
name: presentation-context
description: Load presentation context before reading or changing a project.
---

# Presentation context

## Prerequisites

1. Run `dox doctor` and fix every failing check.
2. Run `dox context <project>` before touching presentation files.

The context command identifies the authoritative model, argument sources (thesis, diegesis, walk), cue and notes agreement, and the skill to use next. It is read-only and never selects an active project.

For a document-model project, invoke `presentation-document`. For legacy slides, read `docs/SLIDE_ARCHITECTURE.md` and edit only the reported authoritative slide sources. Do not infer a model from another project or edit before loading context.
