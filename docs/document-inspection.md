# Document inspection workspace

Authored single-page presentations open in the existing presentation workspace.
The canvas contains the selected HTML renderer. Overview, Source, Sections,
Media/styles and private Notes remain available beside it. On desktop the canvas
and inspector share the available width; the preview retains a 16:9 proportion.
Narrow layouts stack the panels.

Inspection is read-only. Thumbnails load as the gallery approaches them during
scrolling; full-resolution images and prompt text load when selected. Image
details expose the image-specific prompt, saved assembled prompts, current
assembly and inherited components, tags and references. See
[generation details](image-generation-details.md) for the provenance rules.

Present expands the same frame. Exit returns to inspection with the current cue
preserved. External file edits require an explicit refresh.

## Agent entry point

`dox document context --project NAME --json` resolves an explicitly selected vault
and returns the rendering model, a bounded source inventory, opaque inspection
item IDs and a snapshot. It excludes image bytes, note bodies and prompt bodies.
Inspect an item with the same snapshot to obtain its paged contents. Changed inputs
invalidate the snapshot; refresh context before planning another change.

Projects without an authored document retain their existing Step or legacy
workflow. Reading context never migrates them or generates thumbnails.

## Editing and generation

[Document authoring](document-authoring.md) describes checked text changes, asset
adoption, generation candidates, image selection and recovery. Plans bind exact
inputs and expected hashes. Generation requires an explicit bounded request;
inspection never invokes a provider. Multi-file promotion uses the vault write
ahead log so coordinated HTML and notes changes are recoverable together.

Saved prompts establish historical provenance only when matching receipts verify
the prompt and image hashes. Current definitions and ambiguous legacy bundle
associations remain distinct from verified historical inputs.

## Verification

The synthetic Observatory and Alpha fixtures exercise these contracts in
`tests/test_document_*.py` and the frontend inspection, player and workspace
Playwright suites. Keep real project HTML, prompts, notes, screenshots and
operator acceptance records in the private vault.
