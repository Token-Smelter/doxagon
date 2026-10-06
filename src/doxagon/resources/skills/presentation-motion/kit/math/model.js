/* Mathematics in world coordinates; presentation and pixel layout are separate. */
globalThis.DoxMathModel = (() => {
  'use strict';
  const A = [[2, 1], [1, 2]];
  const I = [[1, 0], [0, 1]];
  const holds = [0, 6, 14, 23, 32, 40];
  const cues = ['math-basis', 'math-columns', 'math-map', 'math-search', 'math-stretch', 'math-eigenbasis'];
  const plus = [1, 1];
  const minus = [1, -1];
  const ordinary = [1, 2];
  const clamp = (n, lo = 0, hi = 1) => Math.max(lo, Math.min(hi, n));
  const ramp = (time, start, duration) => {
    const p = clamp((time - start) / duration);
    return p * p * (3 - 2 * p);
  };
  const apply = (matrix, v) => matrix.map(row => row[0] * v[0] + row[1] * v[1]);
  const cross = (u, v) => u[0] * v[1] - u[1] * v[0];
  const dot = (u, v) => u[0] * v[0] + u[1] * v[1];
  const scale = (v, amount) => v.map(x => x * amount);
  const mixMatrix = s => I.map((row, i) => row.map((x, j) => x + s * (A[i][j] - x)));

  function at(value, angle = null) {
    if (!Number.isFinite(value)) throw new TypeError('Time must be finite');
    if (angle !== null && !Number.isFinite(angle)) throw new TypeError('Angle must be finite radians');
    const time = clamp(value, 0, 40);
    const phase = holds.slice(1).filter(t => time >= t).length;
    const searching = (time >= 16 && time < 24) || angle !== null;
    // One scalar morphs the linear map, not independently animated coordinates.
    const amount = angle !== null ? 0 :
      time < 16 ? ramp(time, 7, 7) * (1 - ramp(time, 14.5, 1.5)) : ramp(time, 24, 8);
    const matrix = mixMatrix(amount);
    const probeAngle = angle ?? (Math.atan2(2, 1) + (Math.PI * 2 + Math.PI / 4 - Math.atan2(2, 1)) * ramp(time, 16, 7));
    const probe = scale([Math.cos(probeAngle), Math.sin(probeAngle)], Math.SQRT2);
    const source = searching ? probe : time >= 24 ? plus : ordinary;
    const operator = searching ? A : matrix;
    const target = apply(operator, source);
    const determinant = cross(source, target);
    const eigenvalue = dot(source, target) / dot(source, source);
    const residual = Math.hypot(...target.map((x, i) => x - eigenvalue * source[i]));
    const hold = holds.findIndex(t => Math.abs(time - t) < 0.001);
    return {
      time, phase, cue: hold < 0 ? null : cues[hold], matrix, amount, operator,
      source, target, basisX: apply(matrix, [1, 0]), basisY: apply(matrix, [0, 1]),
      // Linear combination for v=(1,2): a tip-to-tail construction, never an eyeballed path.
      sumCorner: apply(matrix, [1, 0]), sumEnd: apply(matrix, ordinary),
      plus: [...plus], minus: [...minus], plusImage: apply(matrix, plus), minusImage: apply(matrix, minus),
      searchAngle: probeAngle, searching, exploring: angle !== null,
      cross: determinant, eigenvalue: residual < 1e-8 ? eigenvalue : null, residual,
      angleChange: Math.atan2(determinant, dot(source, target)),
      aligned: residual < 1e-8,
      reveal: {
        columns: ramp(time, 2, 4), map: ramp(time, 6.5, 0.5),
        search: ramp(time, 16, 1), plus: ramp(time, 20, 3), minus: ramp(time, 33, 3),
        eigenbasis: ramp(time, 35, 5)
      },
      eigenbasisMatrix: [[3, 0], [0, 1]],
      P: [[1, 1], [1, -1]], inverseP: [[0.5, 0.5], [0.5, -0.5]]
    };
  }
  return Object.freeze({ A, I, holds, cues, apply, cross, dot, scale, mixMatrix, at });
})();
