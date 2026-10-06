# Variation without changing the argument

**Cross the recipe with the style; do not assign one look to each technique.** Otherwise the agent learns accidental pairs such as SVG = old paper or 3D = glossy metal.

| Hold steady: signal | Deliberately vary: nuisance variables |
|---|---|
| Claim, causal order, candidate versus approval | Object metaphor, incidental scenery |
| Cue IDs, hold times, actor trajectories, visible states | Palette, typography, contour treatment, texture |
| Component roles and count; silhouette bounds, pivot, registration, transparent margins | Image material and mark-making |
| Seeking, loop timing, input ownership, reduced motion, fallback | Lighting and roughness, within legibility constraints |
| Accessible labels and contrast | Decorative background pattern |

The [profiles](./../samples/profiles.json:2) independently control color roles, type family, stroke width/caps, background pattern and 3D material properties. Their image directions differ while preserving the component contract. All eighteen combinations are valid. None is the default aesthetic for a new project.

## Six orthogonal demonstrations

| Profile | Material and reading situation | Not just a recolor |
|---|---|---|
| Printed field guide | Warm stock, dry contour, crosshatching, serif narration | Sparse hatching, square ends, matte surfaces |
| Night instrument | Low ambient light, luminous readable marks, machined surfaces | Measurement typography, grid, metallic response, lighter contour on dark ground |
| Color-block workshop | Clear educational model on a bright surface | Broad rounded strokes, sans type, solid silhouettes, matte color blocks |
| Glazed porcelain | White ceramic, cobalt brush arcs, cool gallery light | Fine rounded contour, serif narration, curved marks, smooth reflective material and rounded ledger |
| Punched industrial stencil | Ochre powder-coated steel under workshop light | Squared heavy contour, measurement numerals, punched slots, double-rule ledger and muted metallic edges |
| Woven exhibition model | Plum felt and rose thread in a dim exhibition | Broad pale contour, sans narration, interlocking woven marks, stitched edges and diffuse material |

The fixture generator varies image contour/mark treatment too ([fixture renderer](./../scripts/build_sample.py:99)). All six profiles reuse the three bundled licensed fonts; no extra font or remote texture is required. Background marks are drawn locally in SVG and canvas; component marks are clipped to the original face bounds. Porcelain arcs, punched slots and weave affect every recipe, while roughness and metalness additionally affect the spatial solids. Image-generation directions carry those material distinctions into production assets rather than relying on fixture recoloring.

A live style switch preserves time and semantic state; it does not regenerate images or recolor a previously selected production image and call that a new generation.

## How the agent should transfer this

1. State the explanation in plain language, without a material, font or metaphor.
2. Pick the rendering recipe for the relationship that needs to become visible.
3. Recover the project's actual visual system. Choose references from it rather than adopting one of these sample profiles by habit.
4. For a new visual system, compare materially different directions while holding the cue table fixed. Variation is for learning and comparison, not randomizing a delivered presentation on each load.
5. Replace the sample's carrier with a domain-appropriate actor. The [packet transfer case](./../samples/transfer.json:2) exercises changed IDs, language and silhouette; it is not evidence that every domain is an inspection workflow.
6. Check an unseen case against the same contract. Can the result explain a non-logistics idea without retaining crates, boats, paper or a checkmark merely because the sample had them?

## Evaluation boundary

The browser probe discovers profile IDs from the built HTML and checks semantic equality across profiles and seek histories ([probe](./../scripts/probe_sample.py:139)). Use `--profiles porcelain stencil textile` for a bounded new-profile pass, or omit it to cover every profile. This includes mobile and desktop holds, reverse seeks, source replacement, no-WebGL fallback and offline behavior under the document CSP. That proves implementation independence, not that an agent has stopped overfitting. The [transfer prompts](./../evals/evals.json) are proposed qualitative evaluations. Run with/without-skill comparisons through the available orchestration path before claiming improved agent generalization; no model-evaluation score is bundled.
