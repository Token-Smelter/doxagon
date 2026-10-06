/* Stage host: time, holds, sizing, visibility, reduced motion and cleanup around any draw function.
 * It never touches the scene. Three, Canvas 2D and SVG renderers all work.
 * const host = DoxHost.attach(root, { holds: [0, 4], stateAt: t => ({ t }), draw: (state, frame) => {...} });
 */
(() => {
  'use strict';
  const ease = x => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);

  /** Mark an element as a checkable scene. Anything exposing holds, stateAt and seek can be previewed. */
  function expose(root, api, name = '') {
    root.doxScene = api;
    root.setAttribute('data-dox-scene', name);
    return api;
  }

  function attach(root, options = {}) {
    const {
      holds = [0], cues = [], stateAt = t => ({ t }), draw, ambient = false, maxPixelRatio = 1.5,
      travel = {}, name = '', onResize, ready = () => true,
    } = options;
    if (!root) throw new Error('DoxHost.attach needs a root element');
    if (typeof draw !== 'function') throw new Error('DoxHost.attach needs draw(state, frame)');
    if (!holds.length || holds.some((t, i) => i && t < holds[i - 1])) throw new Error('holds must be ascending times in seconds');
    const reduceQuery = matchMedia('(prefers-reduced-motion: reduce)');
    const start = holds[0], end = holds[holds.length - 1];
    let reduced = reduceQuery.matches, time = start, idle = 0, pinned = null;
    let playing = false, tween = null, intersecting = true, destroyed = false;
    let raf = 0, last = 0, dirty = true, width = 0, height = 0;
    const disposables = [];

    const visible = () => intersecting && !document.hidden;
    const running = () => visible() && (tween || playing || (ambient && !reduced && pinned === null));
    const clamp = t => Math.min(end, Math.max(start, t));

    function measure() {
      const rect = root.getBoundingClientRect(), w = Math.round(rect.width), h = Math.round(rect.height);
      if (w === width && h === height) return false;
      width = w; height = h;
      onResize?.({ width, height });
      return true;
    }
    function tick(now) {
      raf = 0;
      if (destroyed) return;
      const dt = last ? Math.min(0.1, (now - last) / 1000) : 0;
      last = now;
      if (tween) {
        const k = Math.min(1, (now - tween.began) / (tween.duration * 1000));
        time = tween.from + (tween.to - tween.from) * ease(k);
        if (k >= 1) { time = tween.to; tween = null; }
        dirty = true;
      }
      if (playing) {
        time = Math.min(end, time + dt);
        if (time >= end) playing = false;
        dirty = true;
      }
      if (ambient && !reduced && pinned === null) { idle += dt; dirty = true; }
      if (dirty && width > 0 && height > 0 && visible()) {
        dirty = false;
        draw(stateAt(time), {
          t: time, idle: pinned ?? (reduced ? 0 : idle), width, height,
          pixelRatio: Math.min(window.devicePixelRatio || 1, maxPixelRatio), reduced,
        });
        // Ready means drawn with everything it needs, such as decoded skins, not merely drawn once.
        if (ready()) root.dataset.doxReady = 'true';
      }
      if (running()) schedule(); else last = 0;
    }
    function schedule() { if (!raf && !destroyed) raf = requestAnimationFrame(tick); }
    function invalidate() { dirty = true; schedule(); }

    function seek(t) {
      tween = null; playing = false; time = clamp(t);
      invalidate();
    }
    function holdIndex(target) {
      const index = typeof target === 'string' ? cues.indexOf(target) : target;
      if (index < 0 || index >= holds.length || !Number.isInteger(index)) throw new Error(`No hold "${target}". Holds: ${holds.length}, cues: ${cues.join(', ') || 'none'}`);
      return index;
    }
    /** Travel to a hold; new input replaces travel in progress. Reduced motion arrives at once. */
    function go(target, immediate = false) {
      const to = holds[holdIndex(target)];
      if (immediate || reduced || Math.abs(to - time) < 1e-6) return seek(to);
      const span = Math.abs(to - time);
      const duration = Math.min(travel.max ?? 2.2, Math.max(travel.min ?? 0.6, span * (travel.rate ?? 0.35)));
      playing = false;
      tween = { from: time, to, began: performance.now(), duration };
      schedule();
    }
    function play() {
      if (reduced) return false;
      tween = null;
      if (time >= end) time = start;
      playing = true;
      schedule();
      return true;
    }
    function pause() { playing = false; tween = null; }
    /** Fix the free-running clock, for exact captures; null resumes it. */
    function pinIdle(seconds) { pinned = seconds; invalidate(); }
    function own(item) { disposables.push(item); return item; }

    const resize = new ResizeObserver(() => { if (measure()) invalidate(); });
    resize.observe(root);
    const intersection = new IntersectionObserver(entries => {
      intersecting = entries[entries.length - 1].isIntersecting;
      if (intersecting) invalidate();
    });
    intersection.observe(root);
    const onVisibility = () => { if (visible()) invalidate(); };
    const onReduce = event => {
      reduced = event.matches;
      if (reduced && tween) time = tween.to;
      if (reduced) { tween = null; playing = false; }
      invalidate();
    };
    document.addEventListener('visibilitychange', onVisibility);
    reduceQuery.addEventListener('change', onReduce);

    function destroy() {
      destroyed = true;
      if (raf) cancelAnimationFrame(raf);
      resize.disconnect(); intersection.disconnect();
      document.removeEventListener('visibilitychange', onVisibility);
      reduceQuery.removeEventListener('change', onReduce);
      disposables.splice(0).reverse().forEach(item => (typeof item === 'function' ? item() : item.dispose?.()));
      if (root.doxScene === api) { delete root.doxScene; root.removeAttribute('data-dox-scene'); delete root.dataset.doxReady; }
    }

    const api = {
      root, holds: holds.slice(), cues: cues.slice(), stateAt, seek, go, play, pause, invalidate, pinIdle, own, destroy,
      get time() { return time; },
      get state() { return { time, idle: pinned ?? idle, playing, travelling: !!tween, reduced, hold: holds.reduce((at, t, i) => (t <= time + 1e-6 ? i : at), 0) }; },
    };
    measure();
    expose(root, api, name);
    invalidate();
    return api;
  }

  globalThis.DoxHost = { attach, expose };
})();
