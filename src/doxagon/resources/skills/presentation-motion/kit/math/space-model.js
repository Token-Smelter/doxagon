/* A 3D linear map and its camera path in math coordinates (z up). No DOM, clock or pixels. */
globalThis.DoxSpaceModel = (() => {
  'use strict';
  // A third of a turn about the cube diagonal composed with a 4x stretch along it: A = P + J.
  const A = [[1, 1, 2], [2, 1, 1], [1, 2, 1]];
  const holds = [0, 8, 18, 28, 40];
  const cues = ['space-basis', 'space-columns', 'space-twist', 'space-axis', 'space-invariant'];
  const root3 = Math.sqrt(3);
  const axis = [1 / root3, 1 / root3, 1 / root3];
  const center = [0.5, 0.5, 0.5];
  const clamp = (n, lo = 0, hi = 1) => Math.max(lo, Math.min(hi, n));
  const ramp = (time, start, duration) => { const p = clamp((time - start) / duration); return p * p * (3 - 2 * p); };
  const dot = (u, v) => u[0] * v[0] + u[1] * v[1] + u[2] * v[2];
  const add = (u, v) => u.map((x, i) => x + v[i]);
  const sub = (u, v) => u.map((x, i) => x - v[i]);
  const scale = (v, k) => v.map(x => x * k);
  const cross = (u, v) => [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]];
  const length = v => Math.hypot(...v);
  const normalize = v => scale(v, 1 / length(v));
  const apply = (M, v) => M.map(row => dot(row, v));
  const basis = [[1, 0, 0], [0, 1, 0], [0, 0, 1]];

  // Stretch by 1 + 3s along the diagonal, then turn by s thirds of a revolution about it (Rodrigues).
  function screw(s, v) {
    const w = add(v, scale(axis, 3 * s * dot(axis, v)));
    const theta = s * 2 * Math.PI / 3, c = Math.cos(theta), n = Math.sin(theta);
    return add(add(scale(w, c), scale(cross(axis, w), n)), scale(axis, dot(axis, w) * (1 - c)));
  }
  const matrixAt = s => { const columns = basis.map(e => screw(s, e)); return [0, 1, 2].map(i => columns.map(c => c[i])); };
  const det = M => dot(M[0], cross(M[1], M[2]));
  const sphere = (azimuth, elevation) => {
    const a = azimuth * Math.PI / 180, e = elevation * Math.PI / 180;
    return [Math.cos(e) * Math.cos(a), Math.cos(e) * Math.sin(a), Math.sin(e)];
  };
  // Camera legs: [start, duration, direction, distance]. Directions blend on the unit sphere.
  const legs = [
    [0.5, 7, sphere(-30, 24), 6.8],
    [8.5, 8.5, sphere(20, 26), 11],
    [19, 2.5, axis, 9],
    [28.5, 4.5, sphere(38, 18), 12.5],
    [33, 7, sphere(62, 22), 12.5]
  ];
  function camera(time, s, orbit) {
    let direction = sphere(-62, 20), distance = 6.8;
    for (const [start, duration, next, far] of legs) {
      const p = ramp(time, start, duration);
      if (p === 0) break;
      direction = normalize(add(scale(direction, 1 - p), scale(next, p)));
      distance += (far - distance) * p;
    }
    if (orbit) {
      const c = Math.cos(orbit), n = Math.sin(orbit);
      direction = [direction[0] * c - direction[1] * n, direction[0] * n + direction[1] * c, direction[2]];
    }
    const target = screw(s, center);
    return { position: add(target, scale(direction, distance)), target, up: [0, 0, 1], fov: 34 };
  }
  // Perspective projection to normalized device coordinates; same math as a three.js PerspectiveCamera.
  function project(point, view, aspect) {
    const forward = normalize(sub(view.target, view.position));
    const right = normalize(cross(forward, view.up));
    const up = cross(right, forward);
    const d = sub(point, view.position), z = dot(d, forward), f = 1 / Math.tan(view.fov * Math.PI / 360);
    return { x: dot(d, right) / z * f / aspect, y: dot(d, up) / z * f, depth: z };
  }

  function at(value, orbit = 0) {
    if (!Number.isFinite(value)) throw new TypeError('Time must be finite');
    if (!Number.isFinite(orbit)) throw new TypeError('Orbit must be finite radians');
    const time = clamp(value, 0, 40);
    const phase = holds.slice(1).filter(t => time >= t).length;
    const hold = holds.findIndex(t => Math.abs(time - t) < 0.001);
    // Twist once from an oblique view, reset, then twist again while looking down the diagonal.
    const amount = time < 18.5 ? ramp(time, 9, 8) : time < 21 ? 1 - ramp(time, 18.6, 1.6) : ramp(time, 22, 5);
    const matrix = matrixAt(amount);
    const view = camera(time, amount, orbit * Math.PI / 180);
    const viewDirection = normalize(sub(view.position, view.target));
    const turned = Math.acos(clamp(dot(basis[0], normalize(apply(matrix, basis[0]))), -1, 1)) * 180 / Math.PI;
    return {
      time, phase, cue: hold < 0 ? null : cues[hold], amount, matrix, A,
      images: basis.map(e => apply(matrix, e)),
      corners: [0, 1].flatMap(x => [0, 1].flatMap(y => [0, 1].map(z => apply(matrix, [x, y, z])))),
      diagonal: apply(matrix, [1, 1, 1]), diagonalFactor: 1 + 3 * amount,
      trail: Array.from({ length: 33 }, (_, i) => screw(amount * i / 32, basis[0])),
      volume: det(matrix), turned, view, orbit,
      alongDiagonal: Math.acos(clamp(dot(viewDirection, axis), -1, 1)) * 180 / Math.PI,
      replaying: time >= 18.5 && time < 22,
      reveal: { columns: ramp(time, 2, 4) * (1 - ramp(time, 8.5, 1)), lattice: ramp(time, 8.6, 1),
        axis: ramp(time, 20, 1.5), invariant: ramp(time, 30, 3) }
    };
  }
  return Object.freeze({ A, holds, cues, axis, basis, screw, matrixAt, det, apply, project, at });
})();
