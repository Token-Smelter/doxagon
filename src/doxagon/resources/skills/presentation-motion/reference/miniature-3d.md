# Miniature 3D

**Use solid geometry when perspective, occlusion and consistent spatial relationships carry the explanation.** Material realism alone is not a reason to choose this recipe.

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

Do not imply that an image provider produced a mesh, lighting rig or animation.
