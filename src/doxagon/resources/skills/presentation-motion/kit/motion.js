/* One clock for all renderers; the document remains the navigation owner. */
window.DoxMotion = (() => {
  'use strict';
  const recipes = ['cinematic', 'engraving', 'miniature'];
  const clamp = (value, lo, hi) => Math.max(lo, Math.min(hi, value));

  function mount(root, config) {
    if (root.motion) throw new Error('This motion plate is already mounted');
    const { gsap, MotionPathPlugin, MorphSVGPlugin, DrawSVGPlugin, DoxMotionLib: lib } = window;
    gsap.registerPlugin(MotionPathPlugin, MorphSVGPlugin, DrawSVGPlugin);
    if (config.cues.length !== 5 || config.holds.length !== 5 || new Set(config.cues).size !== 5 ||
        config.holds[0] !== 0 || config.holds.some((n, i) => !Number.isFinite(n) || (i && n <= config.holds[i - 1]))) {
      throw new Error('The sample needs five unique cues and increasing holds starting at zero');
    }
    const plan = window.DoxMotionChoreography.create(config);
    const end = plan.end;
    const stage = root.querySelector('.motion-stage');
    // N image components per visual profile; production documents usually map one profile to stable slots.
    const slots = Object.fromEntries(Object.keys(config.profiles).map(style => [style, Object.fromEntries(plan.components.map(component => [
      component, config.assets ? document.getElementById(config.assets[style]?.[component]) :
        root.querySelector(`img[data-motion-asset="${component}"][data-style="${style}"]`)
    ]))]));
    const imageNodes = Object.values(slots).flatMap(map => Object.values(map));
    if (imageNodes.some(image => image?.tagName !== 'IMG')) throw new Error('Every profile needs an image slot for each component');
    const reduced = matchMedia('(prefers-reduced-motion: reduce)');
    const abort = new AbortController();
    const options = { signal: abort.signal };
    let time = 0, recipe = 'engraving', style = Object.keys(config.profiles)[0];
    let tween = null, playing = false, visible = true, dead = false, assetsReady = false;
    let rendered = false, submitted = 0, fallback = false, gpu = null, box = null, lastScene = null;
    const clock = { time: 0 };
    const overlay = new window.DoxMotionRenderers.Overlay(root, config);
    const svg = new window.DoxMotionRenderers.Engraving(root, plan);
    // HyperFrames discovers Three.js only while the namespace is present.
    const priorThree = window.THREE;
    window.THREE = lib;
    const adapter = lib.createThreeAdapter();
    adapter.discover();
    window.THREE = priorThree;
    window.__timelines = window.__timelines || {};
    window.__timelines[root.id || 'motion'] = plan.timeline;

    const renderer = () => recipe === 'engraving' || fallback ? 'svg' : 'webgl2';
    function state() {
      const scene = dead ? lastScene : plan.compute(time);
      lastScene = scene;
      return { time, recipe, style, renderer: renderer(), fallback, playing, rendered, submitted,
        cue: scene.cue, phase: scene.phase, status: scene.status, actorBox: box,
        components: plan.components.length, scene };
    }
    function announce() { root.dispatchEvent(new CustomEvent('motion:state', { detail: state() })); }
    function draw() {
      if (dead || !assetsReady || !stage.clientWidth || !stage.clientHeight) { rendered = false; return; }
      if (recipe !== 'engraving' && !gpu && !fallback) {
        try { gpu = new window.DoxMotionRenderers.Spatial(root, plan); }
        catch (_) { fallback = true; }
      }
      const profile = config.profiles[style];
      for (const key of ['background', 'surface', 'ink', 'accent', 'reject', 'accept']) root.style.setProperty(`--motion-${key}`, profile[key]);
      root.style.setProperty('--motion-font', profile.font);
      root.dataset.recipe = recipe;
      root.dataset.pattern = profile.pattern;
      const useSvg = renderer() === 'svg';
      root.querySelector('svg').toggleAttribute('hidden', !useSvg);
      root.querySelector('canvas').toggleAttribute('hidden', useSvg);
      const fault = root.querySelector('.motion-fault');
      fault.hidden = !fallback;
      fault.textContent = fallback ? 'WebGL2 unavailable. The SVG recipe is showing the same state.' : '';
      const scene = { ...plan.compute(time), recipe, style };
      box = (useSvg ? svg : gpu).render(scene, profile, slots[style]);
      overlay.render(scene, box);
      const caption = root.querySelector('.motion-caption');
      if (caption.textContent !== scene.label) caption.textContent = scene.label;
      rendered = true; submitted++;
    }
    function seek(value) {
      if (!Number.isFinite(value)) throw new TypeError('Seek requires finite seconds');
      const previous = time;
      time = clamp(value, 0, end);
      // Force covers repeated times and profile changes; the adapter handles advancing time.
      if (previous === time) lib.forceDispatchSeekEvent(time);
      else adapter.seek({ time, frame: Math.round(time * 30), fps: 30, width: stage.clientWidth, height: stage.clientHeight });
      announce();
      return state();
    }
    function pause() { tween?.kill(); tween = null; playing = false; announce(); }
    function go(cue, animate = false) {
      const i = typeof cue === 'number' ? cue : config.cues.indexOf(cue);
      if (!Number.isInteger(i) || i < 0 || i >= config.cues.length) throw new RangeError('Unknown cue');
      pause();
      const target = config.holds[i];
      if (!animate || reduced.matches || document.hidden) return seek(target);
      clock.time = time;
      tween = gsap.to(clock, { time: target, duration: Math.min(4, Math.max(0.2, Math.abs(target - time) / 3)),
        ease: 'none', onUpdate: () => seek(clock.time), onComplete: () => { tween = null; seek(target); } });
    }
    function refreshAssets() {
      assetsReady = imageNodes.every(img => img.getAttribute('src') && img.complete && img.naturalWidth);
      root.setAttribute('aria-busy', String(!assetsReady));
      stage.hidden = !assetsReady;
      if (assetsReady) { gpu?.invalidateTextures(); svg.style = null; draw(); announce(); return; }
      pause(); rendered = false;
      root.querySelector('.motion-caption').textContent = 'Waiting for selected images';
      const fault = root.querySelector('.motion-fault');
      fault.hidden = false; fault.textContent = 'A selected component is unavailable. Load or select every image before playback.';
      announce();
    }
    window.addEventListener('hf-seek', event => {
      if (Number.isFinite(event.detail?.time)) { time = clamp(event.detail.time, 0, end); draw(); }
    }, options);
    document.addEventListener('visibilitychange', () => { if (document.hidden) pause(); }, options);
    reduced.addEventListener('change', () => { pause(); go(config.holds.slice(1).filter(n => time >= n).length); }, options);
    root.addEventListener('motion:gpu-lost', () => { pause(); fallback = true; draw(); announce(); }, options);
    const resize = new ResizeObserver(() => { draw(); announce(); }); resize.observe(stage);
    const intersection = new IntersectionObserver(entries => { visible = entries[0].isIntersecting; if (!visible) pause(); });
    intersection.observe(stage);
    const mutations = new MutationObserver(refreshAssets);
    imageNodes.forEach(img => {
      img.addEventListener('load', refreshAssets, options);
      img.addEventListener('error', refreshAssets, options);
      mutations.observe(img, { attributes: true, attributeFilter: ['src'] });
    });
    const api = Object.freeze({
      state, cues: [...config.cues], holds: [...config.holds], duration: end, components: [...plan.components],
      // Pure sampling for review and tests: no render, no change to the visible time.
      stateAt(value) { const sample = plan.compute(value); plan.compute(time); return sample; },
      seek: value => { pause(); return seek(value); }, go, pause,
      setRecipe(value) { if (!recipes.includes(value)) throw new RangeError('Unknown recipe'); recipe = value; seek(time); },
      setStyle(value) { if (!config.profiles[value]) throw new RangeError('Unknown style'); style = value; seek(time); },
      play() {
        if (reduced.matches || document.hidden || !visible || !assetsReady) return false;
        pause(); if (time >= end) seek(0); playing = true; clock.time = time;
        tween = gsap.to(clock, { time: end, duration: end - time, ease: 'none',
          onUpdate: () => seek(clock.time), onComplete: () => { playing = false; tween = null; seek(end); } });
        announce(); return true;
      },
      destroy() {
        pause(); dead = true; abort.abort(); resize.disconnect(); intersection.disconnect(); mutations.disconnect();
        plan.destroy(); svg.destroy(); gpu?.destroy(); delete window.__timelines[root.id || 'motion']; delete root.motion;
      }
    });
    root.motion = api;
    document.fonts.ready.then(() => { if (!dead) refreshAssets(); });
    refreshAssets();
    return api;
  }
  return Object.freeze({ mount });
})();
