/* Stage sample: an intake machine drawn on paper, then made solid, then producing and checking output.
 * The scene owns only its palette, parts and pose; the look is chosen separately.
 */
(() => {
  'use strict';
  const Z = Math.PI / 2;
  const palette = {
    housing: '#ebe7dc', shell: '#e4dfd2', plate: '#f6f2e8', bolt: '#d8d2c3', pipe: '#f1efe8', tile: '#1d2430',
    ok: '#1b7f4b', card: '#fdf8ea', ref: '#c9971c', p: '#2f6db5', i: '#6b4bb7', x: '#1f8a7a',
  };
  const SLOTS = [0.84, 0.98, 1.12, 1.26];
  const PATH = [[1.06, 0.29, -0.66], [1.06, -0.24, -0.66], [1.06, -0.24, -0.2]];
  const parts = [
    { id: 'rail', shape: 'cylinder', size: [0.026, 0.026, 0.56, 24], role: 'pipe', at: [-1.34, -0.04, 0], rotate: [0, 0, Z] },
    { id: 'hopper', shape: 'cylinder', size: [0.1, 0.3, 0.36, 48], role: 'shell', at: [-0.88, 0, 0], rotate: [0, 0, Z] },
    { id: 'housing', shape: 'box', size: [1.2, 0.72, 0.62], role: 'housing', at: [-0.1, 0, 0] },
    { id: 'screen', shape: 'box', size: [0.5, 0.15, 0.02], role: 'plate', at: [-0.1, 0.03, 0.32] },
    { id: 'lamp', shape: 'sphere', size: [0.034], role: 'ok', accent: true, at: [0.4, 0.27, 0.33] },
    { id: 'outlet', shape: 'box', size: [0.2, 0.16, 0.24], role: 'shell', at: [0.6, -0.12, 0] },
    { id: 'tray', shape: 'box', size: [0.66, 0.04, 0.36], role: 'shell', at: [1.06, -0.33, 0] },
    ...[[-0.64, 0.29], [0.44, 0.29], [-0.64, -0.29], [0.44, -0.29]].map(([x, y], k) =>
      ({ id: `bolt-${k}`, shape: 'cylinder', size: [0.024, 0.024, 0.02, 24], role: 'bolt', at: [x, y, 0.315], rotate: [Z, 0, 0] })),
    ...[0, 1, 2].map(k => ({ id: `vent-${k}`, shape: 'box', size: [0.16, 0.014, 0.016], role: 'tile', at: [0.27, 0.2 - k * 0.045, 0.316] })),
    ...[-0.17, 0.17].map((z, k) => ({ id: `side-${k}`, shape: 'box', size: [0.66, 0.09, 0.024], role: 'shell', at: [1.06, -0.285, z] })),
    ...[0.74, 1.38].map((x, k) => ({ id: `end-${k}`, shape: 'box', size: [0.024, 0.09, 0.36], role: 'shell', at: [x, -0.285, 0] })),
    ...SLOTS.map((x, k) => ({ id: `tile-${k}`, shape: 'box', size: [0.12, 0.17, 0.03], role: 'tile', at: [x, -0.21, 0.02 - k * 0.02], rotate: [-0.12, 0, 0] })),
    // Reference cards float above the tray; their shadow would read as a stray object.
    ...[0, 1, 2].map(k => ({ id: `card-${k}`, shape: 'box', size: [0.34, 0.016, 0.24], role: 'card', shadow: false, at: [1.06 + k * 0.012, 0.3 + k * 0.034, -0.66 + k * 0.01] })),
    { id: 'path', make: (T, { K, resolve }) => K.line(PATH, { color: resolve('ref'), width: 1.6, dash: 0.045, gap: 0.035 }) },
    { id: 'token-p', shape: 'sphere', size: [0.038], role: 'p', accent: true },
    { id: 'token-i', shape: 'box', size: [0.061, 0.061, 0.061], role: 'i', accent: true },
    { id: 'token-x', shape: 'cone', size: [0.044, 0.074, 3], role: 'x', accent: true },
  ];

  const clamp = x => Math.min(1, Math.max(0, x));
  const smooth = (t, a, b) => { const x = clamp((t - a) / (b - a)); return x * x * (3 - 2 * x); };

  /** Timeline t drives the explanation and is seekable; idle only drives the ambient sway and intake. */
  function pose(t, idle) {
    const state = { solid: smooth(t, 0.4, 2.6), model: { rotate: [0, -0.5 + 0.35 * Math.sin(idle * 0.32), 0] } };
    SLOTS.forEach((x, k) => {
      const s = smooth(t, 3.3 + k * 0.55, 4.1 + k * 0.55);
      state[`tile-${k}`] = {
        visible: t > 3.3 + k * 0.55,
        at: [0.6 + (x - 0.6) * s, -0.12 - 0.09 * s + 0.12 * Math.sin(Math.PI * s), (0.02 - k * 0.02) * s],
      };
    });
    [0, 1, 2].forEach(k => {
      const s = smooth(t, 6.3 + k * 0.25, 7.3 + k * 0.25);
      state[`card-${k}`] = { at: [1.06 + k * 0.012, 0.3 + k * 0.034 + 0.22 * (1 - s), -0.66 + k * 0.01], opacity: s };
    });
    state.path = { opacity: smooth(t, 7.6, 8.6) };
    ['token-p', 'token-i', 'token-x'].forEach((id, k) => {
      const s = ((idle * 0.16 + k / 3) % 1 + 1) % 1;
      state[id] = { at: [-1.62 + 0.62 * s, 0.03, 0], scale: Math.min(1, (1 - s) * 6, s * 8), rotate: [0, idle * 0.7 + k, 0] };
    });
    return state;
  }

  globalThis.DoxStageSamples = Object.assign(globalThis.DoxStageSamples || {}, {
    machine: {
      name: 'machine', palette, parts, pose, drawing: true, ambient: true,
      holds: [0, 3, 6, 9], cues: ['machine-drawing', 'machine-solid', 'machine-output', 'machine-check'],
    },
  });
})();
