/* Stage: a scene from a short description. Built only from the public DoxStageKit and DoxHost calls,
 * so anything it does can be done piece by piece, and copying this file is the way out of it.
 * const stage = DoxStage.mount(root, { parts, pose, look: 'satin', holds: [0, 3], cues: ['a', 'b'] });
 */
(() => {
  'use strict';
  const RESERVED = new Set(['model', 'camera', 'solid', 'lines']);
  const COLOR_KEYS = ['color', 'paper', 'ink', 'background', 'cool', 'warm'];

  function mount(root, spec = {}) {
    const T = spec.three || globalThis.DoxMotionLib;
    const K = DoxStageKit(T);
    const palette = { paper: '#f6f4ee', ink: '#1d2430', ...spec.palette };
    const resolve = value => (typeof value === 'string' && Object.prototype.hasOwnProperty.call(palette, value) ? palette[value] : value);
    const hex = value => (value && value.isColor ? `#${value.getHexString()}` : resolve(value));
    const holds = spec.holds || [0];
    const parts = spec.parts || [];
    const pose = spec.pose || (() => ({}));
    const ids = new Set();
    for (const part of parts) {
      if (!part.id) throw new Error('Every part needs an id');
      if (RESERVED.has(part.id)) throw new Error(`Part id "${part.id}" is reserved in poses; rename the part`);
      if (ids.has(part.id)) throw new Error(`Two parts are called "${part.id}"`);
      ids.add(part.id);
    }

    const canvas = document.createElement('canvas');
    canvas.className = 'dox-stage-canvas';
    canvas.setAttribute('aria-hidden', 'true');
    canvas.style.cssText = 'display:block;width:100%;height:100%';
    root.prepend(canvas);
    const fallback = typeof spec.fallback === 'string' ? root.querySelector(spec.fallback) : spec.fallback;
    const fail = reason => {
      canvas.hidden = true;
      if (fallback) fallback.hidden = false;
      root.dataset.doxFailed = reason;
      root.dispatchEvent(new CustomEvent('stage:failed', { detail: reason }));
    };
    let renderer;
    try {
      renderer = new T.WebGLRenderer({ canvas, antialias: true, alpha: true });
    } catch (error) {
      fail('webgl-unavailable');
      return null;
    }
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = T.PCFSoftShadowMap;

    const scene = new T.Scene();
    const model = new T.Group();
    model.name = 'model';
    scene.add(model);
    const view = { kind: 'perspective', fov: 24, elevation: 0.42, azimuth: 0, margin: 1.08, ...spec.camera };
    const camera = view.kind === 'orthographic' ? new T.OrthographicCamera(-1, 1, 1, -1, 0.01, 100) : new T.PerspectiveCamera(view.fov, 1, 0.01, 100);

    let look, groups, rest, surfaces = [], extras = [], drawing = new Set(), faders = new Map(), shadow = null;
    let clones = [], pending = 0, hostRef = null;
    const skinTextures = new Map();

    // A skin needs a lit surface that takes a colour map; drawn looks (warm-cool, hatch, x-ray) keep their own surface.
    const SKINNABLE = new Set(['flat', 'satin', 'clay', 'gloss', 'metal', 'cel']);
    function skinned(part, geometry, skin) {
      const [kind, options] = surfaceFor(part, '#ffffff');
      if (typeof kind !== 'string' || !SKINNABLE.has(kind)) return null;
      const id = `${typeof skin.image === 'string' ? skin.image : skin.image.id}|${JSON.stringify(skin.tint ?? null)}`;
      if (!skinTextures.has(id)) skinTextures.set(id, K.skinTexture(skin.image, { tint: skin.tint && { ...skin.tint, base: hex(skin.tint.base), ink: hex(skin.tint.ink) } }));
      const texture = skinTextures.get(id), own = geometry.clone();
      clones.push(own);
      const side = K.surface(kind, options);
      side.map = texture;
      if (kind === 'flat') side.emissiveMap = texture;
      surfaces.push(side);
      let cap = null;
      const wrap = skin.mode === 'wrap';
      if (wrap && part.shape === 'box') {
        cap = K.surface(kind, { ...options, color: hex(skin.cap && skin.cap !== 'sample' ? skin.cap : partColor(part)) });
        surfaces.push(cap);
      } else if (!wrap) K.mapTile(own, part.shape, skin.size ?? 0.5);
      pending += 1;
      texture.userData.ready.then(() => {
        if (!wrap) return;
        const { fill } = K.mapWrap(own, part.shape, texture.userData.aspect);
        if (cap && (skin.cap ?? 'sample') === 'sample') {
          cap.color.set(K.sampleRow(texture, fill));
          cap.userData.doxSolid.color.copy(cap.color);
          if (cap.emissive) cap.userData.doxSolid.emissive.copy(cap.color).multiplyScalar(kind === 'flat' ? 0.62 : 0);
        }
      }).finally(() => { pending -= 1; hostRef?.invalidate(); });
      return new T.Mesh(own, cap ? [side, side, cap, cap, side, side] : side);
    }
    const frameBox = new T.Box3();
    let framePoints = [];

    function partColor(part) {
      const base = resolve(part.color ?? look.palette?.[part.role] ?? palette[part.role] ?? '#ebe7dc');
      const mono = look.monochrome;
      if (!mono) return base;
      return part.accent ? new T.Color(base).lerp(new T.Color(resolve(mono.color)), mono.mix ?? 0.35) : resolve(mono.color);
    }
    const materials = new Map();
    /** part.surface may be a kind, [kind, options], options for the look's kind, or a function (T, options, K). */
    function surfaceFor(part, color) {
      const [lookKind, lookOptions = {}] = Array.isArray(look.surface) ? look.surface : [look.surface];
      let kind = lookKind, options = { ...lookOptions };
      const own = part.surface ?? (part.accent ? look.accentSurface : undefined);
      if (own) {
        if (typeof own === 'string' || typeof own === 'function') { kind = own; options = {}; }
        else if (Array.isArray(own)) { [kind, options = {}] = own; options = { ...options }; }
        else options = { ...options, ...own };
      }
      options = { background: look.background, paper: 'paper', ink: 'ink', color, ...options };
      for (const key of COLOR_KEYS) if (key in options) options[key] = hex(options[key]);
      if (typeof kind !== 'function') {
        const accepted = K.surfaces()[kind];
        if (accepted && accepted !== 'custom') for (const key of ['background', 'paper', 'ink']) if (!(key in accepted)) delete options[key];
      }
      return [kind, options];
    }
    function material(part, color) {
      const [kind, options] = surfaceFor(part, color);
      const key = JSON.stringify([typeof kind === 'function' ? kind.toString() : kind, options]);
      if (!materials.has(key)) {
        const made = typeof kind === 'function' ? kind(T, options, K) : K.surface(kind, options);
        surfaces.push(made);
        materials.set(key, made);
      }
      return materials.get(key);
    }

    function clear() {
      extras.forEach(item => item.removeFromParent());
      extras = [];
      model.clear();
      surfaces.forEach(item => item.dispose());
      faders.forEach(list => list.forEach(entry => entry.material.dispose()));
      surfaces = []; faders = new Map(); drawing = new Set(); materials.clear(); shadow = null;
      clones.forEach(item => item.dispose());
      clones = [];
      groups = new Map([['model', model]]);
      rest = new Map();
    }

    function build(nextLook) {
      look = K.look(nextLook ?? spec.look ?? 'satin');
      clear();
      for (const part of parts) {
        const group = new T.Group();
        group.name = part.id;
        const parent = groups.get(part.parent || 'model');
        if (!parent) throw new Error(`Part "${part.id}" names parent "${part.parent}", which is not defined before it`);
        const rounded = (part.edges ?? look.edges) === 'rounded';
        if (part.make) {
          const made = part.make(T, {
            K, look, part, resolve,
            material: (color, surface) => material({ surface }, hex(color ?? partColor(part))),
          });
          if (made) group.add(made);
        } else if (part.shape) {
          const geometry = K.shape(part.shape, part.size, { rounded, radius: part.radius });
          const skin = part.skin ?? look.skins?.[part.id] ?? look.skins?.[part.role];
          const mesh = (skin && skinned(part, geometry, skin)) || new T.Mesh(geometry, material(part, partColor(part)));
          mesh.castShadow = look.shadow > 0 && part.shadow !== false;
          mesh.receiveShadow = look.shadow > 0;
          group.add(mesh);
          const curved = K.curved(part.shape);
          const lines = part.lines === false || !look.lines ? null : { ...look.lines, ...(part.lines || {}) };
          if (lines && part.shape !== 'sphere') group.add(K.creases(geometry, { ...lines, color: resolve(lines.color ?? 'ink') }));
          const outline = part.outline === false || !look.outline ? null : { ...look.outline, ...(part.outline || {}) };
          if (outline && (curved || !outline.curvedOnly)) {
            const { curvedOnly, ...style } = outline;
            group.add(K.outline(geometry, { ...style, color: resolve(style.color ?? 'ink') }));
          }
          // The paper drawing's ink, traced from the sharp shape, for looks that draw no lines of their own.
          if (spec.drawing && !look.lines && part.lines !== false && part.shape !== 'sphere') {
            const sharp = K.shape(part.shape, part.size);
            const ink = K.creases(sharp, { color: resolve('ink'), width: 1.4, key: 'drawing' });
            group.add(ink);
            drawing.add(ink.material);
            if (curved) {
              const hull = K.outline(geometry, { color: resolve('ink'), width: 1.3, key: 'drawing' });
              group.add(hull);
              drawing.add(hull.material);
            }
          }
        }
        rest.set(part.id, { at: part.at || [0, 0, 0], rotate: part.rotate || [0, 0, 0], scale: part.scale ?? 1 });
        parent.add(group);
        groups.set(part.id, group);
      }
      frame();
      const center = frameBox.getCenter(new T.Vector3()), radius = frameBox.getSize(new T.Vector3()).length() / 2 || 1;
      extras.push(...K.light(scene, look.light, {
        intensity: look.lightIntensity, shadow: look.shadow > 0, extent: radius * 1.3, target: center.toArray(),
      }));
      if (look.environment) K.environment(renderer, scene, look.environment);
      else scene.environment = null;
      shadow = look.shadow > 0 ? K.ground(scene, { y: frameBox.min.y - 0.002, opacity: look.shadow, size: radius * 12 }) : null;
      if (shadow) extras.push(shadow);
      scene.background = spec.transparent ? null : new T.Color(resolve(look.background));
      renderer.toneMapping = K.toneMapping(look.toneMapping);
      renderer.toneMappingExposure = look.exposure ?? 1;
    }

    /** Frame the union of every pose the timeline can reach, so the object stays in view at every hold. */
    // Corners of each part's bounds, taken in the model's own frame and carried through its pose, keep the
    // fit tight while the whole model turns; one world box would frame empty corners.
    function frame() {
      framePoints = [];
      const first = holds[0], last = holds[holds.length - 1], times = new Set(holds);
      for (let i = 0; i <= 16; i += 1) times.add(first + (last - first) * i / 16);
      const idles = spec.ambient ? Array.from({ length: 17 }, (_, i) => i * 2) : [0];
      const local = new T.Box3(), placed = new T.Matrix4(), seen = new Set();
      for (const t of times) for (const idle of idles) {
        apply(pose(t, idle));
        model.updateMatrix();
        placed.copy(model.matrix);
        model.matrix.identity();
        model.matrixWorld.identity();
        for (const group of model.children) {
          group.updateMatrixWorld(true);
          local.setFromObject(group);
          if (local.isEmpty()) continue;
          for (const x of [local.min.x, local.max.x]) for (const y of [local.min.y, local.max.y]) for (const z of [local.min.z, local.max.z]) {
            const point = new T.Vector3(x, y, z).applyMatrix4(placed);
            const key = `${point.x.toFixed(3)},${point.y.toFixed(3)},${point.z.toFixed(3)}`;
            if (!seen.has(key)) { seen.add(key); framePoints.push(point); }
          }
        }
      }
      if (!framePoints.length) framePoints = [new T.Vector3(-1, -1, -1), new T.Vector3(1, 1, 1)];
      frameBox.setFromPoints(framePoints);
    }

    function fade(id, group, value) {
      if (!faders.has(id)) {
        const list = [];
        const swap = material => {
          if (drawing.has(material)) return material;
          const copy = material.clone();
          copy.transparent = true;
          // clone() round-trips userData through JSON, which turns colours into numbers.
          const solid = material.userData.doxSolid;
          if (solid) copy.userData.doxSolid = { ...solid, color: solid.color.clone(), emissive: solid.emissive.clone() };
          list.push({ material: copy, base: copy.uniforms?.uOpacity ? copy.uniforms.uOpacity.value : copy.opacity });
          return copy;
        };
        // A made part may carry one material per face group.
        group.traverse(object => {
          if (object.material) object.material = Array.isArray(object.material) ? object.material.map(swap) : swap(object.material);
        });
        faders.set(id, list);
      }
      for (const entry of faders.get(id)) {
        if (entry.material.uniforms?.uOpacity) entry.material.uniforms.uOpacity.value = entry.base * value;
        else entry.material.opacity = entry.base * value;
      }
      group.visible = group.visible && value > 0.002;
    }

    /** Pose is absolute: every frame starts from the rest layout, so state depends only on time. */
    function apply(state = {}) {
      model.position.set(0, 0, 0); model.rotation.set(0, 0, 0); model.scale.setScalar(1); model.visible = true;
      for (const [id, r] of rest) {
        const group = groups.get(id);
        group.position.fromArray(r.at);
        group.rotation.set(r.rotate[0] || 0, r.rotate[1] || 0, r.rotate[2] || 0);
        if (typeof r.scale === 'number') group.scale.setScalar(r.scale); else group.scale.fromArray(r.scale);
        group.visible = true;
      }
      const faded = new Set();
      for (const [id, value] of Object.entries(state)) {
        if (id === 'camera' || id === 'solid' || id === 'lines' || value == null) continue;
        const group = groups.get(id);
        if (!group) throw new Error(`pose() moved "${id}", which is not a part id. Parts: ${[...ids].join(', ')}`);
        if (value.at) group.position.fromArray(value.at);
        if (value.rotate) group.rotation.set(value.rotate[0] || 0, value.rotate[1] || 0, value.rotate[2] || 0);
        if (value.scale !== undefined) {
          if (typeof value.scale === 'number') group.scale.setScalar(Math.max(1e-4, value.scale)); else group.scale.fromArray(value.scale);
        }
        if (value.visible !== undefined) group.visible = value.visible;
        if (value.opacity !== undefined) { fade(id, group, value.opacity); faded.add(id); }
      }
      for (const id of faders.keys()) if (!faded.has(id)) fade(id, groups.get(id), 1);
      const solid = state.solid ?? 1, lines = state.lines ?? 1, paper = resolve('paper');
      for (const item of surfaces) K.setSolid(item, solid, paper);
      faders.forEach(list => list.forEach(entry => K.setSolid(entry.material, solid, paper)));
      scene.traverse(object => {
        const list = Array.isArray(object.material) ? object.material : object.material ? [object.material] : [];
        for (const m of list) {
          if (m.userData.doxOpacity === undefined) continue;
          const value = drawing.has(m) ? 1 - solid : lines;
          if (m.uniforms?.uOpacity) m.uniforms.uOpacity.value = m.userData.doxOpacity * value; else m.opacity = m.userData.doxOpacity * value;
          if (drawing.has(m)) object.visible = value > 0.002;
        }
      });
      if (shadow) shadow.material.opacity = look.shadow * solid;
    }

    let size = [0, 0, 0];
    function draw(hostState, frameInfo) {
      const state = spec.ambient ? pose(frameInfo.t, frameInfo.idle) : hostState;
      const { width, height, pixelRatio } = frameInfo;
      if (size[0] !== width || size[1] !== height || size[2] !== pixelRatio) {
        renderer.setPixelRatio(pixelRatio);
        renderer.setSize(width, height, false);
        size = [width, height, pixelRatio];
      }
      apply(state);
      const shot = state.camera || {};
      K.fit(camera, framePoints, {
        elevation: shot.elevation ?? view.elevation, azimuth: shot.azimuth ?? view.azimuth,
        margin: view.margin / (shot.zoom ?? 1), target: shot.target ?? view.target, aspect: width / height,
      });
      K.sync(scene, frameInfo);
      renderer.render(scene, camera);
      spec.onFrame?.(state, three);
    }

    build();
    canvas.addEventListener('webglcontextlost', event => {
      event.preventDefault();
      host.pause();
      fail('gpu-lost');
    });
    const host = DoxHost.attach(root, {
      holds, cues: spec.cues, stateAt: t => pose(t, 0), draw, ambient: !!spec.ambient,
      maxPixelRatio: spec.maxPixelRatio ?? 1.5, travel: spec.travel, name: spec.name, ready: () => pending === 0,
    });
    hostRef = host;
    const three = { T, K, scene, camera, renderer, model, parts: groups };
    const api = {
      root, holds: host.holds, cues: host.cues, stateAt: host.stateAt, three,
      seek: host.seek, go: host.go, play: host.play, pause: host.pause, invalidate: host.invalidate, pinIdle: host.pinIdle, own: host.own,
      get time() { return host.time; },
      get state() { return { ...host.state, look: look.name ?? 'custom' }; },
      get look() { return look; },
      setLook(next) { build(next); host.invalidate(); },
      destroy() {
        host.destroy();
        clear();
        K.dispose();
        renderer.dispose();
        canvas.remove();
        if (root.doxScene === api) { delete root.doxScene; root.removeAttribute('data-dox-scene'); }
      },
    };
    DoxHost.expose(root, api, spec.name || '');
    return api;
  }

  globalThis.DoxStage = { mount };
})();
