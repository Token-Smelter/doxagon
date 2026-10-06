# Cinematic layers

**Use generated image components in a perspective stage when image identity and a changing viewpoint explain more than a static composition.** Ink is an optional image treatment, not part of the technique.

| Ingredient | Sample implementation | Adaptation |
|---|---|---|
| Registered image layers | `base`, `core`, `cap` planes scatter into depth, tumble and reassemble ([offsets](./../kit/choreography.js:118)) | Generate layers against one registration reference; review the overlay |
| Instanced actors | One `probe` image on three rack-focused sprites ([focus material](./../kit/renderers.js:289)) | Reuse one component for repeated actors; vary placement, not art |
| Looping part | `scanner` image on a spinning disc with a sweep, pulse ring and blink ([spinner](./../kit/renderers.js:482)) | Any rotating or cycling part; drive it from the cycle counter, not a free-running clock |
| Camera choreography | Keyed legs with micro-drift ([camera](./../kit/choreography.js:62)) | Establish, follow, inspect, push in, recheck, release; widen for narrow viewports |
| Shader transitions | HyperFrames `ripple-waves` ground and `cross-warp-morph` from a desaturated draft to the revised `core` ([shaders](./../kit/renderers.js:352)) | Blend draft and revision, never unapproved and approved; acceptance stays a separate gate |
| Echo trail and particles | Ghost sprites for fast moves; evidence packets and a burst as point pools | Use for velocity and evidence flow, not decoration |
| Emblem | `seal` sprite with spring pop and a bloom below 0.45 opacity | One acceptance moment |

The [spatial renderer](./../kit/renderers.js:219) owns perspective, texture lifetime, lights and materials. [The choreography](./../kit/choreography.js) owns time. Change them separately.

## Recipe

1. List the moving parts and give each an [image role](./image-components.md). Request components, not a flattened scene.
2. Place planes at meaningful depths. Keep labels and verdicts in DOM text, not textures.
3. Key camera, actors and loops on the same paused clock. Give each cue a legible resting composition.
4. Use masks, depth separation or shaders only where they reveal a change in meaning.
5. Review every hold and two mid-transition times, then run reverse seeks. Small screens need a wider camera, not smaller labels.

The sample uses geometric PNG fixtures, not generated art or photographic mattes. It does not demonstrate semantic segmentation, true depth of field, physically correct refraction or a frame-rate guarantee.
