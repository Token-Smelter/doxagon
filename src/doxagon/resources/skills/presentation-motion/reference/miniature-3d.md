# Miniature 3D

**Use solid geometry when perspective, occlusion and consistent spatial relationships carry the explanation.** Material realism alone is not a reason to choose this recipe. Build new scenes with [the stage library](./stage.md); this page records what the original sample renderer teaches.

| Ingredient | Sample | Boundary |
|---|---|---|
| Solid layers | Box or cylinder layers that scatter, tumble and restack | Code geometry, not AI-generated 3D assets |
| Image decals | Generated `core`, `scanner` and `probe` components as a top decal, a spinning disc face and badges | Images texture the solids; they do not become meshes |
| Lighting | Directional and hemisphere light with cast and received shadows | A bounded stage, not physically based environment capture |
| Materials | Roughness and metalness from the visual profile | Do not hardwire shiny surfaces to the recipe |
| Camera | The same keyed legs as cinematic layers | Keep the object framed at every hold and on mobile |
| Shader | HyperFrames `cross-warp-morph` on the core decal | A visible revision, not an approval shortcut |
| Rack focus | Dimmed off-focus drones and denser fog | No post-processing depth of field |

## Recipe

1. Model only the geometry the argument needs. A few meaningful solids beat a decorative world.
2. Reuse materials and textures. Set transforms from time; never accumulate rotations or simulation steps per frame.
3. Keep small text out of 3D textures. Names and verdicts stay in the DOM.
4. Cap pixel ratio and shadow-map size. The sample uses pixel ratio at most 1 and a 512-square shadow map ([pixel ratio](./../kit/renderers.js:226), [shadows](./../kit/renderers.js:319)); measure on the target device before claiming performance.
5. Dispose textures, geometries, materials and listeners when replacing the plate. Context loss pauses playback and switches to the SVG rendering of the same state.

## Finish

**Light and edges, not textures, separate a finished object from a modelling-tool screenshot.** Flat self-glow on every face, ink on every edge and razor-sharp boxes read as an unfinished model.

| Ingredient | Why | Stage default |
|---|---|---|
| Fillets | Edges catch highlights and read as manufactured | `edges: 'rounded'` in material looks |
| Room reflections | Soft gradients across faces | `environment` in `satin`, `gloss`, `metal` |
| Neutral tone mapping | Keeps palette colours true while compressing highlights | `toneMapping: 'neutral'` |
| Soft contact shadow | Grounds the object | `shadow` opacity with a shadow-casting rig |
| Faint grain | Breaks up perfect reflections; drawn in code, never generated | `satin` powder grain, `metal` brushed streaks |
| Lines only when drawing | Ink on shaded faces is the strongest modelling-tool tell | Material looks draw none; `drawing: true` fades paper ink out as `solid` rises |

Do not imply that an image provider produced a mesh, lighting rig or animation.
