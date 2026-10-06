/* SVG is a view of mathematical state. GSAP supplies the clock, not the mathematics. */
window.DoxMathLesson = (() => {
  'use strict';
  const NS = 'http://www.w3.org/2000/svg';
  const model = window.DoxMathModel;
  const titles = [
    'Start with two basis vectors.', 'Read the columns as destinations.', 'Apply the rule to the whole plane.',
    'Which directions stay on their lines?', 'This direction stretches threefold.', 'In this basis, A only scales.'
  ];
  const notes = [
    'Any vector is a combination of these two arrows. Track their colors as the explanation changes.',
    'The first column is A e₁. The second is A e₂. These destination arrows show the rule before the grid moves.',
    'Every point uses the same map. The dashed path adds one transformed e₁ and two transformed e₂ vectors.',
    'Compare v with A v on the unchanged reference grid. An eigenvector and its image lie on the same line.',
    'For v₊ = (1, 1), applying A changes length but not the line. Its eigenvalue is 3.',
    'Along v₊ the factor is 3; along v₋ = (1, −1) it is 1. The diagonal matrix uses this new basis, not the original axes.'
  ];
  function el(tag, attributes = {}, text = '') {
    const node = document.createElementNS(NS, tag);
    for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
    if (text) node.textContent = text;
    return node;
  }
  const fmt = n => Math.abs(n) < 0.0005 ? '0' : String(Number(n.toFixed(3))).replace('-', '−');
  const coords = v => `(${v.map(fmt).join(', ')})`;
  const matrixHTML = matrix => '<mrow><mo>[</mo><mtable>' + matrix.map(row => '<mtr>' + row.map(n => `<mtd><mn>${fmt(n)}</mn></mtd>`).join('') + '</mtr>').join('') + '</mtable><mo>]</mo></mrow>';

  function mount(root) {
    const svg = root.querySelector('svg');
    const abort = new AbortController();
    const options = { signal: abort.signal };
    const viewport = root.querySelector('.math-plane');
    let time = 0, angle = null, playing = false, tween = null, visible = true, dead = false;
    const clock = { time: 0 };
    const master = gsap.timeline({ paused: true }).fromTo(clock, { time: 0 }, { time: 40, duration: 40, ease: 'none' });
    const reduced = matchMedia('(prefers-reduced-motion: reduce)');
    const cache = new Map();
    const setText = (node, text) => { if (cache.get(node) !== text) { node.textContent = text; cache.set(node, text); } };
    const setHTML = (node, html) => { if (cache.get(node) !== html) { node.innerHTML = html; cache.set(node, html); } };
    // A single conversion defines all marks. Positive mathematical y points up.
    const origin = [340, 374];
    const unit = 53;
    const pixel = v => [origin[0] + unit * v[0], origin[1] - unit * v[1]];
    const path = points => points.map((point, i) => `${i ? 'L' : 'M'}${pixel(point).map(n => n.toFixed(4)).join(',')}`).join(' ');
    const clip = `${root.id}-clip`;
    svg.setAttribute('viewBox', '0 0 730 720');
    svg.setAttribute('role', 'img');
    const defs = el('defs');
    const clipping = el('clipPath', { id: clip });
    clipping.append(el('rect', { x: 0, y: 0, width: 730, height: 720 })); defs.append(clipping); svg.append(defs);
    const geometry = el('g', { 'clip-path': `url(#${clip})` }); svg.append(geometry);
    const reference = el('g', { class: 'math-reference' });
    const transformed = el('g', { class: 'math-transformed' });
    const cell = el('path', { class: 'math-cell' });
    geometry.append(reference, cell, transformed);
    const eigenGrid = el('g', { class: 'math-eigen-grid' });
    geometry.append(eigenGrid);
    const grid = [];
    for (let i = -12; i <= 12; i++) {
      for (const ends of [[[i, -12], [i, 12]], [[-12, i], [12, i]]]) {
        reference.append(el('path', { d: path(ends), class: i === 0 ? 'math-axis' : 'math-grid' }));
        const line = el('path', { class: i === 0 ? 'math-axis' : 'math-grid' });
        transformed.append(line); grid.push({ line, ends });
        eigenGrid.append(el('path', { class: 'math-grid', d: path(ends.map(v => model.apply([[1, 1], [1, -1]], v))) }));
      }
    }
    const invariantPlus = el('path', { class: 'math-invariant math-plus', d: path([[-10, -10], [10, 10]]) });
    const invariantMinus = el('path', { class: 'math-invariant math-minus', d: path([[-10, 10], [10, -10]]) });
    const addition = el('path', { class: 'math-addition' });
    const angleArc = el('path', { class: 'math-angle' });
    const angleLabel = el('text', { class: 'math-angle-label', x: origin[0] + 58, y: origin[1] + 22 });
    geometry.append(invariantPlus, invariantMinus, addition, angleArc, angleLabel);
    const axisLabels = el('g', { class: 'math-axis-labels' });
    for (let i = -5; i <= 6; i++) {
      if (!i) continue;
      const x = pixel([i, 0]), y = pixel([0, i]);
      axisLabels.append(el('text', { x: x[0], y: x[1] + 19, 'text-anchor': 'middle' }, String(i)));
      axisLabels.append(el('text', { x: y[0] - 10, y: y[1] + 4, 'text-anchor': 'end' }, String(i)));
    }
    axisLabels.append(el('text', { x: origin[0] - 14, y: origin[1] + 19 }, '0'));
    axisLabels.append(el('text', { x: 708, y: origin[1] - 10 }, 'x'));
    axisLabels.append(el('text', { x: origin[0] + 12, y: 24 }, 'y'));
    geometry.append(axisLabels);

    function arrow(name, color, ghost = false) {
      const group = el('g', { class: `math-arrow ${color}${ghost ? ' math-ghost' : ''}`, 'data-vector': name });
      const shaft = el('path', { fill: 'none' });
      const head = el('path');
      const label = el('text', { class: 'math-vector-label' });
      group.append(shaft, head, label); geometry.append(group);
      return { group, shaft, head, label };
    }
    const e1 = arrow('e1', 'math-e1'), e2 = arrow('e2', 'math-e2');
    const column1 = arrow('column1', 'math-e1', true), column2 = arrow('column2', 'math-e2', true);
    const source = arrow('source', 'math-plus', true), target = arrow('target', 'math-plus');
    const minus = arrow('minus', 'math-minus');
    function drawArrow(art, vector, text, opacity, dx = 12, dy = -12) {
      const [x, y] = pixel(vector), [ox, oy] = origin;
      const length = Math.hypot(x - ox, y - oy);
      const nx = length ? (x - ox) / length : 1, ny = length ? (y - oy) / length : 0;
      art.shaft.setAttribute('d', `M${ox},${oy} L${x.toFixed(4)},${y.toFixed(4)}`);
      art.head.setAttribute('d', `M${x},${y} L${x - 12 * nx + 5 * ny},${y - 12 * ny - 5 * nx} L${x - 12 * nx - 5 * ny},${y - 12 * ny + 5 * nx} Z`);
      art.head.style.display = length < 0.001 ? 'none' : '';
      art.group.style.opacity = opacity;
      art.group.dataset.x = vector[0]; art.group.dataset.y = vector[1];
      art.label.setAttribute('x', x + dx); art.label.setAttribute('y', y + dy);
      setText(art.label, text);
    }

    function render() {
      if (dead) return;
      const s = model.at(time, angle);
      const phase = s.exploring ? 3 : s.phase;
      const comparing = s.searching;
      grid.forEach(({ line, ends }) => line.setAttribute('d', path(ends.map(v => model.apply(s.matrix, v)))));
      transformed.style.opacity = s.amount > 0 ? 0.65 * (1 - s.reveal.eigenbasis) : 0;
      reference.style.opacity = (s.amount > 0 ? 0.35 : 0.85) * (1 - 0.7 * s.reveal.eigenbasis);
      eigenGrid.style.opacity = 0.65 * s.reveal.eigenbasis;
      axisLabels.style.opacity = 1 - 0.7 * s.reveal.eigenbasis;
      cell.setAttribute('d', path([[0, 0], [1, 0], [1, 1], [0, 1]].map(v => model.apply(s.matrix, v))) + 'Z');
      cell.style.opacity = phase < 3 ? 0.09 : 0;
      const basisOpacity = phase >= 3 ? 0.22 : 1;
      drawArrow(e1, s.basisX, s.amount === 1 ? 'A e₁' : s.amount === 0 ? 'e₁' : 'Tₛ e₁', basisOpacity, 10, 20);
      drawArrow(e2, s.basisY, s.amount === 1 ? 'A e₂' : s.amount === 0 ? 'e₂' : 'Tₛ e₂', basisOpacity, -48, -16);
      const destinations = s.time <= 7 ? s.reveal.columns : Math.max(0, 1 - (s.time - 7) / 2);
      drawArrow(column1, [2, 1], 'A e₁', destinations, 10, 18);
      drawArrow(column2, [1, 2], 'A e₂', destinations, -48, -18);
      const mainOpacity = phase < 2 ? 0 : 1;
      const sourceName = time >= 24 && !comparing ? 'v₊' : 'v';
      const targetName = comparing ? 'A v' : time >= 24 ? (s.amount === 1 ? 'A v₊' : 'Tₛ v₊') : 'Tₛ v';
      drawArrow(source, s.source, sourceName, mainOpacity * 0.55, -54, 18);
      drawArrow(target, s.target, targetName, mainOpacity, 12, -14);
      drawArrow(minus, s.minusImage, 'A v₋ = v₋', s.reveal.minus, 12, 22);
      invariantPlus.style.opacity = s.exploring ? 0.65 : s.reveal.plus * 0.7;
      invariantMinus.style.opacity = s.exploring ? 0.65 : s.reveal.minus * 0.7;
      addition.setAttribute('d', path([[0, 0], s.sumCorner, s.sumEnd]));
      addition.style.opacity = phase === 2 ? 0.65 : 0;
      const fromAngle = Math.atan2(s.source[1], s.source[0]);
      const endAngle = fromAngle + s.angleChange, r = 43;
      const start = [origin[0] + r * Math.cos(fromAngle), origin[1] - r * Math.sin(fromAngle)];
      const finish = [origin[0] + r * Math.cos(endAngle), origin[1] - r * Math.sin(endAngle)];
      angleArc.setAttribute('d', `M${start.join(',')} A${r},${r} 0 0 ${s.angleChange > 0 ? 0 : 1} ${finish.join(',')}`);
      angleArc.style.opacity = comparing && !s.aligned ? 1 : 0;
      angleLabel.style.opacity = comparing ? 1 : 0;
      setText(angleLabel, `${fmt(Math.abs(s.angleChange) * 180 / Math.PI)}°`);
      setText(root.querySelector('.math-heading'), titles[phase]);
      setText(root.querySelector('.math-explanation'), notes[phase]);
      setText(root.querySelector('.math-phase'), `Idea ${phase + 1} of 6`);
      root.dataset.phase = phase;
      root.dataset.ready = 'true';
      setText(root.querySelector('.math-transformation'), phase < 2 ? 'Reference grid · one unit per square' :
        comparing ? 'Reference grid · compare v and A v' : time > 14.5 && time < 16 ? 'Resetting the plane for a comparison' :
        phase === 5 ? 'Same plane · grid follows v₊ and v₋' : `Tₛ = (1 − s)I + sA · s = ${fmt(s.amount)}`);
      const showIntermediate = !comparing && ((time >= 7 && time < 16) || (time >= 24 && time < 32));
      setHTML(root.querySelector('.math-live-matrix'), `<mrow><mi>${showIntermediate ? 'T' : 'A'}</mi>${showIntermediate ? '<mo>(</mo><mi>s</mi><mo>)</mo>' : ''}<mo>=</mo>${matrixHTML(showIntermediate ? s.matrix : model.A)}</mrow>`);
      const formula = root.querySelector('.math-relation');
      if (phase === 0) setText(formula, 'v = x e₁ + y e₂');
      else if (phase === 1) setText(formula, 'A e₁ = (2, 1)\nA e₂ = (1, 2)');
      else if (phase === 2) setText(formula, `Tₛ v = Tₛ e₁ + 2 Tₛ e₂ = ${coords(s.target)}`);
      else if (comparing) setText(formula, s.aligned ? `A v = ${fmt(s.eigenvalue)} v` : 'A v is not a scalar multiple of v');
      else setText(formula, `${s.amount === 1 ? 'A' : 'Tₛ'} v₊ = ${fmt(1 + 2 * s.amount)} v₊`);
      setText(root.querySelector('.math-readout-input'), coords(s.source));
      setText(root.querySelector('.math-readout-output'), coords(s.target));
      setText(root.querySelector('.math-direction-test'), s.aligned ? 'Same line' : 'Different lines');
      root.querySelector('.math-direction-test').dataset.aligned = String(s.aligned);
      root.querySelector('.math-readouts').hidden = phase < 2;
      const conclusion = root.querySelector('.math-conclusion');
      conclusion.hidden = s.reveal.eigenbasis === 0;
      conclusion.style.opacity = s.reveal.eigenbasis;
      conclusion.setAttribute('aria-hidden', String(s.reveal.eigenbasis === 0));
      const explorer = root.querySelector('.math-explorer');
      explorer.hidden = phase !== 3;
      const slider = root.querySelector('[data-math-angle]');
      slider.value = ((s.searchAngle * 180 / Math.PI) % 180 + 180) % 180;
      setText(root.querySelector('.math-angle-value'), `${fmt(Number(slider.value))}°`);
      svg.setAttribute('aria-label', `${titles[phase]} Input ${coords(s.source)}, image ${coords(s.target)}.`);
      root.dispatchEvent(new CustomEvent('math:state', { detail: state() }));
    }
    function state() { return { ...model.at(time, angle), playing, rendered: !dead && root.dataset.ready === 'true' }; }
    function stop() { tween?.kill(); tween = null; master.pause(); playing = false; }
    function seek(value) {
      // Validate before cancelling the last valid state.
      model.at(value);
      stop(); time = Math.max(0, Math.min(40, value)); master.totalTime(time, true); angle = null; render(); return state();
    }
    function go(cue, animate = false) {
      const index = typeof cue === 'number' ? cue : model.cues.indexOf(cue);
      if (!Number.isInteger(index) || index < 0 || index >= model.holds.length) throw new RangeError('Unknown mathematical cue');
      stop(); angle = null;
      if (!animate || reduced.matches || document.hidden) return seek(model.holds[index]);
      master.totalTime(time, true);
      tween = master.tweenTo(model.holds[index], { duration: Math.min(5, Math.max(0.25, Math.abs(model.holds[index] - time) / 2)),
        ease: 'none', onUpdate: () => { time = clock.time; render(); }, onComplete: () => { tween = null; time = model.holds[index]; render(); } });
    }
    function setAngle(radians) {
      model.at(23, radians);
      stop(); time = 23; master.totalTime(time, true); angle = radians; render();
    }
    const api = {
      state, stateAt: model.at, seek, go, setAngle, cues: [...model.cues], holds: [...model.holds], duration: 40,
      setStyle(value) {
        if (!['night', 'paper'].includes(value)) throw new RangeError('Unknown mathematical visual style');
        root.dataset.style = value; render();
      },
      pause() { stop(); render(); },
      play() {
        if (reduced.matches || document.hidden || !visible || dead) return false;
        stop(); angle = null; if (time === 40) time = 0;
        playing = true; master.totalTime(time, true);
        tween = master.tweenTo(40, { duration: 40 - time, ease: 'none',
          onUpdate: () => { time = clock.time; render(); }, onComplete: () => { time = 40; playing = false; tween = null; render(); } });
        render(); return true;
      },
      destroy() { stop(); master.kill(); dead = true; abort.abort(); observer.disconnect(); resize.disconnect(); root.dataset.ready = 'false'; }
    };
    const resize = new ResizeObserver(() => {
      if (viewport.clientWidth) svg.style.setProperty('--math-font-scale', Math.max(1, 730 / viewport.clientWidth * 0.8));
    });
    resize.observe(viewport);
    const observer = new IntersectionObserver(entries => { visible = entries[0].isIntersecting; if (!visible) { stop(); render(); } });
    observer.observe(viewport);
    document.addEventListener('visibilitychange', () => { if (document.hidden) { stop(); render(); } }, options);
    reduced.addEventListener('change', () => { stop(); go(model.holds.slice(1).filter(t => time >= t).length); }, options);
    root.querySelector('[data-math-angle]').addEventListener('input', e => setAngle(Number(e.target.value) * Math.PI / 180), options);
    root.querySelectorAll('[data-math-direction]').forEach(button => button.addEventListener('click', () => setAngle(Number(button.dataset.mathDirection) * Math.PI / 180), options));
    document.fonts.ready.then(() => { if (!dead) render(); });
    render();
    return Object.freeze(api);
  }
  return Object.freeze({ mount });
})();
