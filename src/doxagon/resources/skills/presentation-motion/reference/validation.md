# Validate the contract, then inspect the picture

**A working standalone animation is not proof of integration with the Doxagon host.** Preserve both automated evidence and one bounded visual review of the actual target.

| Layer | Required evidence |
|---|---|
| Resource installation | A clean vault receives nested files; repeat sync is unchanged; local edits/collisions survive; only unmodified platform-owned retired files are removed |
| Sample | All three recipes × three profiles at desktop/mobile; same semantic state at the same time |
| Pattern contracts | Loop periodicity, spin-up, handoff and attachment, lock at rest; a reading exactly at a sweep crossing; nested repeats; bounded particle pools; stagger; reassembly; revision without approval ([contracts](./../scripts/probe_sample.py:16)) |
| Seeking | Forward, reverse, repeated and external HyperFrames seeks; exact semantic/geometry equality |
| Input | Rapid new cue cancels stale tween; scrolling does not fight keyboard navigation |
| Host | Actual opaque sandbox/CSP, selected document, notes/cue order, image residency, resize and audience mode |
| Accessibility | Labels remain readable; focusable controls work; reduced motion lands on holds; no autoplay |
| Failure | Any one of the N component images missing → not ready and no playback; WebGL unavailable or lost → explicit SVG fallback |
| Lifecycle | Offscreen/hidden playback pauses; textures and listeners are released |
| Image pipeline | Per component: assembled prompt and reference review, real variant IDs, alpha review, separate selection and preserved provenance; for layers, an overlay review of registration |

## Reproduce the packaged check

```bash
python "$SKILL/scripts/build_sample.py" --output /tmp/motion-check
python "$SKILL/scripts/probe_sample.py" --html /tmp/motion-check/index.html --output /tmp/motion-check-proof
python "$SKILL/scripts/build_sample.py" --case "$SKILL/samples/transfer.json" --output /tmp/motion-transfer
python "$SKILL/scripts/probe_sample.py" --html /tmp/motion-transfer/index.html --output /tmp/motion-transfer-proof
python "$SKILL/scripts/build_gallery.py" --output /tmp/motion-sheet
python "$SKILL/scripts/probe_gallery.py" --html /tmp/motion-sheet/index.html --output /tmp/motion-sheet-proof
```

The sample-sheet probe checks tabs, keyboard tab navigation, pausing hidden samples, and the 3D lesson: model identities, projection agreement, seek determinism, view-only orbit and reduced motion.

The [probe](./../scripts/probe_sample.py:41) runs the sample in an opaque `sandbox="allow-scripts"` iframe with inline-only scripts, no connections and no frames. Function-form Playwright waits avoid eval-based polling under that CSP. It checks nine technique/style combinations at 1120 and 390 pixels, captures plates, and records requests/errors. It does not pretend the iframe harness is the full Doxagon presenter.

Pixel equality is exact for GPU captures. SVG allows at most 16/255 channel error over 0.05% of pixels, while state and path geometry must still match exactly. This narrow allowance covers edge antialiasing, not different shapes. Do not widen it to hide unstable animation.

## Host review

After applying the real document plan, run `dox document validate --project PROJECT`, then inspect in the actual local presenter at desktop and mobile sizes. Wait for controller cue, rendered scene and viewport size to agree after opening Present. Exercise every hold, a mid-transition time, Back, jumps, scroll reversal, notes and audience resizing. Do not embed private notes in screenshots or public evidence.

For layout, also assert that the actor is on screen; `canvas.is_visible()` alone says nothing about its contents. Measure frame intervals on the target hardware if performance matters. Headless timing is local evidence, not a device guarantee.

Inspect once across the matrix, batch the fixes, confirm once and stop polishing. Keep remaining limitations explicit. The scripts and recipes are machine-tested examples; agent-level style transfer remains a separate evaluation ([proposed prompts](./../evals/evals.json)).
