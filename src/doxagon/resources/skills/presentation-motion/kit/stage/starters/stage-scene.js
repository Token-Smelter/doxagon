/* Starter 1 of 3 — the stage: describe parts, pick a look, write a pure pose(t).
 * Copy, rename the parts, and change the pose and look. Preview: preview_scene.py --scene stage-scene.js
 */
(() => {
  const smooth = (t, a, b) => { const x = Math.min(1, Math.max(0, (t - a) / (b - a))); return x * x * (3 - 2 * x); };
  window.scene = DoxStage.mount(document.querySelector('[data-stage]'), {
    name: 'starter-stage',
    look: 'satin',                       // or 'clay', ['xray', { background: '#000' }], { base: 'cel', outline: { width: 3 } }
    palette: { body: '#ebe7dc', lid: '#2f6db5', token: '#c9971c' },
    parts: [
      { id: 'body', shape: 'box', size: [1.4, 0.7, 0.9], role: 'body' },
      { id: 'lid', shape: 'box', size: [1.44, 0.08, 0.94], role: 'lid', at: [0, 0.39, 0] },
      { id: 'token', shape: 'cylinder', size: [0.16, 0.16, 0.05, 40], role: 'token', accent: true, at: [0, 0.48, 0] },
    ],
    holds: [0, 2, 4],
    cues: ['closed', 'open', 'out'],
    drawing: true,                       // start as an ink drawing; pose.solid fades it to the look
    pose: t => ({
      solid: smooth(t, 0, 1.6),
      lid: { at: [-0.3 * smooth(t, 2, 3.4), 0.39 + 0.35 * smooth(t, 2, 3.4), 0], rotate: [0, 0, 0.5 * smooth(t, 2, 3.4)] },
      token: { at: [0, 0.48 + 0.55 * smooth(t, 3, 4), 0], rotate: [0, 2 * Math.PI * smooth(t, 3, 4), 0] },
      camera: { azimuth: -0.35 + 0.25 * smooth(t, 0, 4) },
    }),
  });
})();
