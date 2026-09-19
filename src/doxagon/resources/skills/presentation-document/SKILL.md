---
name: presentation-document
description: Create and modify single-page HTML presentations selected by outputs/document/presentation.json.
---

# Single-page presentation documents

## Prerequisites

1. Run `dox doctor` and fix every failing check.
2. Run `dox context <project>` and confirm `document-model` is authoritative.

One HTML file owns layout, animation, and cues. `presentation.json` selects that HTML and private `notes.json`; sibling legacy slides do not affect playback. Cue IDs are stable and notes must retain the same IDs and order. Change the edition whenever cues change.

Use `dox document context --project <project> --json` to inspect bounded context, then use the document plan/apply flow for changes. Validate delivered HTML in a browser before delivery. Do not embed private notes in HTML, regenerate imagery merely for an edit, or change player code to fix a document problem.
