/* Projected SVG view of a 3D linear map. Geometry, labels and readouts all come from DoxSpaceModel. */
window.DoxSpaceLesson = (() => {
  'use strict';
  const NS = 'http://www.w3.org/2000/svg';
  const model = window.DoxSpaceModel;
  const W = 760, H = 620;
  const titles = [
    'Three basis vectors span space.', 'Each column is a destination.', 'A twists and stretches space.',
    'Look straight down the diagonal.', 'One line keeps its direction.'
  ];
  const notes = [
    'Every point is a combination x e\u2081 + y e\u2082 + z e\u2083. The unit cube is built from these three arrows.',
    'A sends e\u2081 to (1, 2, 1), e\u2082 to (1, 1, 2) and e\u2083 to (2, 1, 1). Read the destinations as the columns of A.',
    'Every lattice line follows the same rule. The cube becomes a slanted box, and its volume grows to det A = 4.',
    'Along the diagonal d = (1, 1, 1), the twist is a one-third turn. d itself only gets longer.',
    'A d = 4d. Every other direction turns. A real 3 \u00d7 3 matrix always keeps at least one line, because its characteristic polynomial is cubic.'
  ];
  const fmt = n => Math.abs(n) < 0.0005 ? '0' : String(Number(n.toFixed(3))).replace('-', '\u2212');
  const coords = v => `(${v.map(fmt).join(', ')})`;
  const short = n => Math.abs(n) < 0.005 ? '0' : String(Number(n.toFixed(2))).replace('-', '\u2212');
  const matrixHTML = M => '<mrow><mo>[</mo><mtable>' + M.map(row => '<mtr>' + row.map(n => `<mtd><mn>${short(n)}</mn></mtd>`).join('') + '</mtr>').join('') + '</mtable><mo>]</mo></mrow>';
  function el(tag, attributes = {}, text = '') {
    const node = document.createElementNS(NS, tag);
    for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
    if (text) node.textContent = text;
    return node;
  }
  // Faces of the unit cube by corner index (x*4 + y*2 + z), tinted by the basis direction they face.
  const faces = [[0, 1, 3, 2, 'e1'], [4, 5, 7, 6, 'e1'], [0, 1, 5, 4, 'e2'], [2, 3, 7, 6, 'e2'], [0, 2, 6, 4, 'e3'], [1, 3, 7, 5, 'e3']];
  const edges = [[0, 1], [2, 3], [4, 5], [6, 7], [0, 2], [1, 3], [4, 6], [5, 7], [0, 4], [1, 5], [2, 6], [3, 7]];

  function mount(root) {
    const svg = root.querySelector('svg');
    const viewport = root.querySelector('.math-plane');
    const abort = new AbortController(), options = { signal: abort.signal };
    const reduced = matchMedia('(prefers-reduced-motion: reduce)');
    const clock = { time: 0 };
    const master = gsap.timeline({ paused: true }).fromTo(clock, { time: 0 }, { time: 40, duration: 40, ease: 'none' });
    let time = 0, orbit = 0, tween = null, playing = false, visible = true, dead = false;
    const cache = new Map();
    const setText = (node, text) => { if (cache.get(node) !== text) { node.textContent = text; cache.set(node, text); } };
    const setHTML = (node, html) => { if (cache.get(node) !== html) { node.innerHTML = html; cache.set(node, html); } };
    svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
    svg.setAttribute('role', 'img');
    const layer = name => { const g = el('g', { class: name }); svg.append(g); return g; };
    const floor = layer('space-floor'), lattice = layer('space-lattice'), axisLayer = layer('space-axis');
    const solid = layer('space-solid'), trailLayer = layer('space-trail'), arrows = layer('space-arrows'), labels = layer('space-labels');
    const floorLines = [], latticeLines = [];
    for (let k = -1; k <= 4; k++) {
      floorLines.push([[k, -1, 0], [k, 4, 0]], [[-1, k, 0], [4, k, 0]]);
      if (k <= 2) latticeLines.push([[k, -1, 0], [k, 2, 0]], [[-1, k, 0], [2, k, 0]]);
    }
    const floorPaths = floorLines.map(() => floor.appendChild(el('path')));
    const latticePaths = latticeLines.map(() => lattice.appendChild(el('path')));
    const axisPath = axisLayer.appendChild(el('path', { class: 'space-axis-line' }));
    const facePaths = faces.map(([, , , , tint]) => el('path', { class: `space-face space-${tint}` }));
    const edgePaths = edges.map(() => el('path', { class: 'space-edge' }));
    const trail = trailLayer.appendChild(el('path', { class: 'space-trail-path' }));
    function arrow(name, tint, ghost = false) {
      const group = arrows.appendChild(el('g', { class: `space-arrow space-${tint}${ghost ? ' space-ghost' : ''}`, 'data-vector': name }));
      const shaft = group.appendChild(el('path', { fill: 'none' })), head = group.appendChild(el('path'));
      const label = labels.appendChild(el('text', { class: `space-label space-${tint}` }));
      return { group, shaft, head, label };
    }
    const vectors = ['e1', 'e2', 'e3'].map(tint => arrow(tint, tint));
    const columns = ['e1', 'e2', 'e3'].map((tint, i) => arrow(`column${i + 1}`, tint, true));
    const diagonal = arrow('diagonal', 'd');

    function render() {
      if (dead) return;
      const s = model.at(time, orbit);
      const aspect = W / H;
      const screen = point => {
        const p = model.project(point, s.view, aspect);
        return { x: W / 2 + p.x * W / 2, y: H / 2 - p.y * H / 2, depth: p.depth };
      };
      const d = points => points.map((p, i) => { const q = screen(p); return `${i ? 'L' : 'M'}${q.x.toFixed(3)},${q.y.toFixed(3)}`; }).join(' ');
      floorLines.forEach((line, i) => floorPaths[i].setAttribute('d', d(line)));
      floor.style.opacity = s.amount > 0 ? 0.45 : 0.9;
      latticeLines.forEach((line, i) => latticePaths[i].setAttribute('d', d(line.map(p => model.apply(s.matrix, p)))));
      lattice.style.opacity = s.amount > 0 ? 0.8 * s.reveal.lattice : 0;
      axisPath.setAttribute('d', d([[-1, -1, -1], [5, 5, 5]]));
      axisLayer.style.opacity = Math.max(s.reveal.axis, s.phase >= 3 ? 1 : 0) * 0.85;
      // Painter's order: farthest faces first; translucent fills keep hidden edges legible.
      const projected = s.corners.map(screen);
      faces.map((face, i) => ({ i, depth: face.slice(0, 4).reduce((sum, c) => sum + projected[c].depth, 0) / 4 }))
        .sort((a, b) => b.depth - a.depth)
        .forEach(({ i }) => { facePaths[i].setAttribute('d', faces[i].slice(0, 4).map((c, k) => `${k ? 'L' : 'M'}${projected[c].x.toFixed(3)},${projected[c].y.toFixed(3)}`).join(' ') + 'Z'); solid.append(facePaths[i]); });
      edges.forEach(([a, b], i) => { edgePaths[i].setAttribute('d', `M${projected[a].x.toFixed(3)},${projected[a].y.toFixed(3)} L${projected[b].x.toFixed(3)},${projected[b].y.toFixed(3)}`); solid.append(edgePaths[i]); });
      const drawArrow = (art, vector, text, opacity) => {
        const tip = screen(vector), base = screen([0, 0, 0]);
        const back = screen(vector.map(x => x * (1 - 0.14 / Math.max(Math.hypot(...vector), 0.14))));
        const dx = tip.x - back.x, dy = tip.y - back.y, n = Math.hypot(dx, dy) || 1, ux = dx / n, uy = dy / n;
        art.shaft.setAttribute('d', `M${base.x.toFixed(3)},${base.y.toFixed(3)} L${tip.x.toFixed(3)},${tip.y.toFixed(3)}`);
        art.head.setAttribute('d', `M${tip.x.toFixed(3)},${tip.y.toFixed(3)} L${(tip.x - 13 * ux + 5.5 * uy).toFixed(3)},${(tip.y - 13 * uy - 5.5 * ux).toFixed(3)} L${(tip.x - 13 * ux - 5.5 * uy).toFixed(3)},${(tip.y - 13 * uy + 5.5 * ux).toFixed(3)}Z`);
        art.group.style.opacity = opacity; art.label.style.opacity = opacity;
        art.group.dataset.x = vector[0]; art.group.dataset.y = vector[1]; art.group.dataset.z = vector[2];
        art.label.setAttribute('x', (tip.x + 10 * ux + 6).toFixed(3)); art.label.setAttribute('y', (tip.y + 10 * uy - 6).toFixed(3));
        setText(art.label, text);
      };
      const named = s.amount === 1 ? 'A' : s.amount === 0 ? '' : 'T';
      vectors.forEach((art, i) => drawArrow(art, s.images[i], named ? `${named} e${'\u2081\u2082\u2083'[i]}` : `e${'\u2081\u2082\u2083'[i]}`, s.phase === 4 ? 0.35 : 1));
      columns.forEach((art, i) => drawArrow(art, model.A.map(row => row[i]), `A e${'\u2081\u2082\u2083'[i]}`, s.reveal.columns));
      const showDiagonal = Math.max(s.reveal.axis, s.phase >= 3 ? 1 : 0);
      drawArrow(diagonal, s.diagonal, s.amount === 1 ? 'A d = 4d' : s.amount === 0 ? 'd' : `T d = ${fmt(s.diagonalFactor)}d`, showDiagonal);
      trail.setAttribute('d', d(s.trail));
      trail.style.opacity = s.phase >= 2 && s.amount > 0 ? 0.9 : 0;
      const intermediate = s.amount > 0 && s.amount < 1;
      setText(root.querySelector('.math-heading'), titles[s.phase]);
      setText(root.querySelector('.math-explanation'), notes[s.phase]);
      setText(root.querySelector('.math-phase'), `Idea ${s.phase + 1} of 5`);
      setHTML(root.querySelector('.math-live-matrix'), `<mrow><mi>${intermediate ? 'T' : 'A'}</mi>${intermediate ? '<mo>(</mo><mi>s</mi><mo>)</mo>' : ''}<mo>=</mo>${matrixHTML(intermediate ? s.matrix : model.A)}</mrow>`);
      const relation = root.querySelector('.math-relation');
      if (s.phase === 0) setText(relation, 'v = x e\u2081 + y e\u2082 + z e\u2083');
      else if (s.phase === 1) setText(relation, 'A e\u2081 = (1, 2, 1)\nA e\u2082 = (1, 1, 2)\nA e\u2083 = (2, 1, 1)');
      else if (s.phase === 2) setText(relation, `det T(s) = 1 + 3s = ${fmt(s.volume)}`);
      else if (s.phase === 3) setText(relation, `Seen along d, the outline has turned ${fmt(s.amount * 120)}\u00b0`);
      else setText(relation, 'A d = 4d,  d = (1, 1, 1)');
      setText(root.querySelector('.space-volume'), fmt(s.volume));
      setText(root.querySelector('.space-turned'), `${fmt(s.turned)}\u00b0`);
      setText(root.querySelector('.space-factor'), `\u00d7 ${fmt(s.diagonalFactor)}`);
      setText(root.querySelector('.math-transformation'), s.replaying ? 'Replaying from above the diagonal' :
        s.phase < 2 && s.amount === 0 ? 'Reference floor \u00b7 one unit per square' :
        s.alongDiagonal < 0.01 && orbit === 0 ? 'Viewing along d = (1, 1, 1)' : `T(s): \u2153 turn \u00d7 s about d, stretch 1 + 3s \u00b7 s = ${fmt(s.amount)}`);
      const conclusion = root.querySelector('.math-conclusion');
      conclusion.hidden = s.reveal.invariant === 0;
      conclusion.style.opacity = s.reveal.invariant;
      root.querySelector('[data-space-orbit]').value = orbit;
      setText(root.querySelector('.space-orbit-value'), `${fmt(orbit)}\u00b0`);
      root.dataset.phase = s.phase;
      root.dataset.ready = 'true';
      svg.setAttribute('aria-label', `${titles[s.phase]} Image of e\u2081 ${coords(s.images[0])}; volume ${fmt(s.volume)}.`);
      root.dispatchEvent(new CustomEvent('space:state', { detail: state() }));
    }
    function state() { return { ...model.at(time, orbit), playing, rendered: !dead && root.dataset.ready === 'true' }; }
    function stop() { tween?.kill(); tween = null; master.pause(); playing = false; }
    function seek(value) {
      model.at(value);
      stop(); time = Math.max(0, Math.min(40, value)); master.totalTime(time, true); render(); return state();
    }
    function go(cue, animate = false) {
      const index = typeof cue === 'number' ? cue : model.cues.indexOf(cue);
      if (!Number.isInteger(index) || index < 0 || index >= model.holds.length) throw new RangeError('Unknown spatial cue');
      stop(); orbit = 0;
      if (!animate || reduced.matches || document.hidden) return seek(model.holds[index]);
      master.totalTime(time, true);
      tween = master.tweenTo(model.holds[index], { duration: Math.min(5, Math.max(0.25, Math.abs(model.holds[index] - time) / 2)), ease: 'none',
        onUpdate: () => { time = clock.time; render(); }, onComplete: () => { tween = null; time = model.holds[index]; render(); } });
    }
    // View-only: turning the camera never changes the mathematical state.
    function setOrbit(degrees) {
      model.at(time, degrees);
      orbit = Math.max(-180, Math.min(180, degrees)); render();
    }
    const api = {
      state, stateAt: model.at, seek, go, setOrbit, cues: [...model.cues], holds: [...model.holds], duration: 40,
      setStyle(value) {
        if (!['night', 'paper'].includes(value)) throw new RangeError('Unknown mathematical visual style');
        root.dataset.style = value; render();
      },
      pause() { stop(); render(); },
      play() {
        if (reduced.matches || document.hidden || !visible || dead) return false;
        stop(); if (time === 40) time = 0;
        playing = true; master.totalTime(time, true);
        tween = master.tweenTo(40, { duration: 40 - time, ease: 'none',
          onUpdate: () => { time = clock.time; render(); }, onComplete: () => { time = 40; playing = false; tween = null; render(); } });
        render(); return true;
      },
      destroy() { stop(); master.kill(); dead = true; abort.abort(); observer.disconnect(); resize.disconnect(); root.dataset.ready = 'false'; }
    };
    const resize = new ResizeObserver(() => { if (viewport.clientWidth) svg.style.setProperty('--math-font-scale', Math.max(1, W / viewport.clientWidth * 0.8)); });
    resize.observe(viewport);
    const observer = new IntersectionObserver(entries => { visible = entries[0].isIntersecting; if (!visible) { stop(); render(); } });
    observer.observe(viewport);
    document.addEventListener('visibilitychange', () => { if (document.hidden) { stop(); render(); } }, options);
    reduced.addEventListener('change', () => { stop(); go(model.holds.slice(1).filter(t => time >= t).length); }, options);
    root.querySelector('[data-space-orbit]').addEventListener('input', e => setOrbit(Number(e.target.value)), options);
    root.querySelector('[data-space-reset]').addEventListener('click', () => setOrbit(0), options);
    let drag = null;
    svg.addEventListener('pointerdown', e => { drag = { x: e.clientX, orbit }; svg.setPointerCapture(e.pointerId); }, options);
    svg.addEventListener('pointermove', e => { if (drag) setOrbit(drag.orbit - (e.clientX - drag.x) * 0.4); }, options);
    svg.addEventListener('pointerup', () => { drag = null; }, options);
    svg.addEventListener('pointercancel', () => { drag = null; }, options);
    document.fonts.ready.then(() => { if (!dead) render(); });
    render();
    return Object.freeze(api);
  }
  return Object.freeze({ mount });
})();
