# Living engraving

**Make internal relationships visible with layers, routes and changing marks.** The recipe is an animated technical diagram; it need not imitate a historical engraving.

| Technique | Source | Meaning |
|---|---|---|
| Layered cutaway | Registered component `<image>` layers in the [SVG renderer](./../kit/renderers.js:69) | Separate the candidate's parts for inspection |
| Viewport change | One world transform carries the camera ([viewport](./../kit/renderers.js:151)) | Push in and pull back without a 3D engine |
| Path drawing | Intake, probe and exit routes on a paused timeline ([drawing](./../kit/renderers.js:132)) | Reveal the path of work or evidence as it happens |
| Shape morph | Draft outline to revised outline; cross to tick, with canonical endpoints at holds ([endpoints](./../kit/renderers.js:157)) | Change shape and verdict only at their authored gates |
| Looping part | The scanner image rotates about its own centre, with a sweep wedge and bearing ticks ([rotation](./../kit/renderers.js:192)) | A sweep crossing produces a reading |
| Torn-paper reveal | Seeded scraps lift off the revision sheet ([scraps](./../kit/renderers.js:82)) | Disclose the revision as a document, not a fade |
| Rack focus | One SVG blur filter on the background group ([blur](./../kit/renderers.js:162)) | Hold attention on the object being revised |

## Recipe

1. Start with a technical relationship that benefits from separation. Author diagram geometry in SVG; generated components supply object identity, not topology.
2. Keep original path strings and explicit morph endpoints. Prewarm the paused timeline and set canonical strings at holds so lazy path conversion cannot leave history-dependent geometry.
3. Move groups from state, not per-layer keyframes per cue. Keep exploded parts identifiable and their relation to the whole clear.
4. Drive DrawSVG, MorphSVG and transforms from the same time. No CSS keyframe loops and no randomness inside `render()`.
5. Test with WebGL disabled: the fallback must still explain all holds.

In [the profiles](./../samples/profiles.json), stroke, caps, pattern, typography and contrast change independently of the mechanics. The night-instrument version is as valid as the paper one.

Repeat-seek tests require exact state and geometry. The probe permits only bounded SVG edge antialiasing differences ([validation](./validation.md)).
