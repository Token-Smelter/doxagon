/* Stage kit: plain helpers that return ordinary Three objects. Use any one without the others.
 * const K = DoxStageKit(DoxMotionLib); K.surface('satin', { color: '#ebe7dc' }) -> MeshPhysicalMaterial
 */
(() => {
  'use strict';

  // ---------- Shaders for the drawn surfaces; the material surfaces use Three's own materials ----------
  const LIGHT = 'const vec3 L = normalize(vec3(-0.45, 0.8, 0.5));';
  const SURFACE_VS = `
    varying vec3 vN; varying vec3 vP;
    void main() {
      vec4 mv = modelViewMatrix * vec4(position, 1.0);
      vP = mv.xyz; vN = normalize(normalMatrix * normal);
      gl_Position = projectionMatrix * mv;
    }`;
  // Gooch: cool where the surface turns from the light, warm where it faces it, so form reads without dark shadows.
  const WARMCOOL_FS = `
    uniform vec3 uBase; uniform vec3 uCool; uniform vec3 uWarm; uniform float uCoolMix; uniform float uWarmMix; uniform float uHighlight;
    varying vec3 vN; varying vec3 vP; ${LIGHT}
    void main() {
      vec3 n = normalize(vN), v = normalize(-vP);
      float k = 0.5 + 0.5 * dot(n, L);
      vec3 cool = uCool + uCoolMix * uBase, warm = uWarm + uWarmMix * uBase;
      float s = pow(max(dot(n, normalize(L + v)), 0.0), 48.0);
      gl_FragColor = vec4(mix(cool, warm, k) + uHighlight * s, 1.0);
      #include <colorspace_fragment>
    }`;
  // Hatching: darker tone adds a second and third direction of lines, as in an engraving.
  const HATCH_FS = `
    uniform vec3 uBase; uniform vec3 uPaper; uniform vec3 uInk; uniform float uSpacing; uniform float uTint;
    varying vec3 vN; varying vec3 vP; ${LIGHT}
    float line(float u, float w) {
      if (w <= 0.0) return 0.0;
      float f = fract(u), d = min(f, 1.0 - f), fw = fwidth(u);
      return 1.0 - smoothstep(w - fw, w + fw, d);
    }
    void main() {
      float diffuse = max(dot(normalize(vN), L), 0.0);
      float lum = dot(uBase, vec3(0.2126, 0.7152, 0.0722));
      float tone = (0.3 + 0.7 * diffuse) * mix(0.3, 1.0, sqrt(lum));
      vec2 p = gl_FragCoord.xy / uSpacing;
      float ink = line((p.x + p.y) * 0.7071, clamp((0.92 - tone) * 0.5, 0.0, 0.32));
      ink = max(ink, line((p.x - p.y) * 0.7071, clamp((0.62 - tone) * 0.5, 0.0, 0.3)));
      ink = max(ink, line(p.y, clamp((0.36 - tone) * 0.6, 0.0, 0.3)));
      gl_FragColor = vec4(mix(mix(uPaper, uBase, uTint), uInk, 0.9 * ink), 1.0);
      #include <colorspace_fragment>
    }`;
  // X-ray: density rises toward silhouettes (Fresnel) and accumulates, so inner parts show through.
  const XRAY_FS = `
    uniform vec3 uRim; uniform float uFill; uniform float uFalloff; uniform float uStrength; uniform float uGlow;
    varying vec3 vN; varying vec3 vP;
    void main() {
      float f = pow(1.0 - abs(dot(normalize(vN), normalize(-vP))), uFalloff);
      float a = clamp(uFill + uStrength * f, 0.0, 1.0);
      gl_FragColor = uGlow > 0.5 ? vec4(uRim * a, 1.0) : vec4(uRim, a);
      #include <colorspace_fragment>
    }`;
  // Inverted hull: back faces pushed out along the screen-space normal by a fixed pixel width.
  const HULL_VS = `
    uniform vec2 uRes; uniform float uWidth;
    void main() {
      vec4 c = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
      vec2 d = (normalMatrix * normal).xy;
      float l = length(d);
      c.xy += (l > 1e-4 ? d / l : vec2(0.0)) * uWidth / (uRes * 0.5) * c.w;
      gl_Position = c;
    }`;
  const FLAT_FS = `
    uniform vec3 uColor; uniform float uOpacity;
    void main() {
      gl_FragColor = vec4(uColor, uOpacity);
      #include <colorspace_fragment>
    }`;

  // Defaults double as the parameter reference: every surface accepts exactly these keys, plus `three`
  // for raw material properties.
  const SURFACE_DEFAULTS = {
    flat: { color: '#ebe7dc', glow: 0.62, roughness: 0.82 },
    satin: { color: '#ebe7dc', roughness: 0.48, clearcoat: 0.35, clearcoatRoughness: 0.3, grain: 'powder', bump: 0.2 },
    clay: { color: '#e8e1d5', roughness: 1 },
    gloss: { color: '#2b4a70', roughness: 0.16, clearcoat: 1, clearcoatRoughness: 0.04 },
    metal: { color: '#c4c9d1', roughness: 0.3, brushed: true, anisotropy: 0.5 },
    cel: { color: '#ebe7dc', steps: 3 },
    warmcool: { color: '#ebe7dc', cool: '#0038a8', warm: '#aea000', coolMix: 0.25, warmMix: 0.6, highlight: 0.55 },
    hatch: { color: '#ebe7dc', paper: '#f6f4ee', ink: '#1d2430', spacing: 5, tint: 0.22 },
    xray: { color: '#7fd4ff', background: '#0e1a2b', fill: 0.02, falloff: 2, strength: 0.55 },
  };
  const custom = {};

  const LOOKS = {
    ink: {
      surface: 'flat', edges: 'sharp', light: 'flat', background: 'paper', toneMapping: 'none',
      lines: { width: 1.4, opacity: 0.85 }, outline: { width: 1.3, curvedOnly: true },
    },
    satin: { surface: 'satin', edges: 'rounded', light: 'studio', environment: 0.4, shadow: 0.22, toneMapping: 'neutral', exposure: 0.9, background: 'paper' },
    clay: {
      surface: 'clay', edges: 'rounded', light: 'soft', environment: 0.15, shadow: 0.32, toneMapping: 'neutral', exposure: 0.9,
      background: '#dbd5c9', monochrome: { color: '#e8e1d5', mix: 0.35 },
    },
    gloss: { surface: 'gloss', edges: 'rounded', light: 'studio', lightIntensity: 1.3, environment: 0.6, shadow: 0.2, toneMapping: 'neutral', exposure: 0.95, background: 'paper' },
    metal: {
      surface: 'metal', accentSurface: 'gloss', edges: 'rounded', light: 'studio', lightIntensity: 1.2, environment: 0.9, shadow: 0.22,
      toneMapping: 'neutral', exposure: 0.95, background: '#e3e4e6',
    },
    cel: { surface: 'cel', edges: 'rounded', light: 'cel', toneMapping: 'none', background: '#fbf7ec', outline: { width: 2 } },
    technical: {
      surface: 'warmcool', edges: 'sharp', light: 'none', toneMapping: 'none', background: '#ffffff',
      lines: { width: 1.2 }, outline: { width: 1.4, curvedOnly: true },
    },
    engraving: {
      surface: 'hatch', edges: 'sharp', light: 'none', toneMapping: 'none', background: 'paper',
      lines: { width: 1.3 }, outline: { width: 1.3, curvedOnly: true },
    },
    xray: {
      surface: ['xray', { color: '#7fd4ff' }], edges: 'sharp', light: 'none', toneMapping: 'none', background: '#0e1a2b',
      lines: { color: '#7fd4ff', width: 1.1, opacity: 0.6 },
    },
  };
  const CURVED = new Set(['cylinder', 'sphere', 'cone', 'torus', 'capsule']);

  function merge(base, extra) {
    const out = { ...base };
    for (const [key, value] of Object.entries(extra || {})) {
      const nested = value && typeof value === 'object' && !Array.isArray(value) && base[key] && typeof base[key] === 'object' && !Array.isArray(base[key]);
      out[key] = nested ? { ...base[key], ...value } : value;
    }
    return out;
  }
  const known = (kind, table, label) => {
    if (!(kind in table)) throw new Error(`Unknown ${label} "${kind}". Known: ${Object.keys(table).join(', ')}`);
  };

  function DoxStageKit(T = globalThis.DoxMotionLib) {
    if (!T || !T.Mesh) throw new Error('DoxStageKit needs the Three namespace, for example DoxStageKit(DoxMotionLib)');
    const owned = new Set();
    const own = item => { owned.add(item); return item; };
    const color = value => (value && value.isColor ? value.clone() : new T.Color(value));

    // ---------- Shapes ----------
    const shapes = new Map();
    function lathe(rt, rb, h, segments, fillet) {
      const points = [new T.Vector2(1e-4, -h / 2)];
      const arc = (cx, cy, a0, a1) => {
        for (let i = 0; i <= 6; i += 1) {
          const a = a0 + (a1 - a0) * i / 6;
          points.push(new T.Vector2(cx + fillet * Math.cos(a), cy + fillet * Math.sin(a)));
        }
      };
      arc(rb - fillet, -h / 2 + fillet, -Math.PI / 2, 0);
      arc(rt - fillet, h / 2 - fillet, 0, Math.PI / 2);
      points.push(new T.Vector2(1e-4, h / 2));
      return new T.LatheGeometry(points, segments);
    }
    /** Geometry by name, cached. Rounded shapes get small fillets that catch highlights. */
    function shape(kind, size = [], { rounded = false, radius } = {}) {
      const key = `${kind}:${size.join(',')}:${rounded ? 1 : 0}:${radius ?? ''}`;
      if (shapes.has(key)) return shapes.get(key);
      let g;
      if (kind === 'box') {
        const [w = 1, h = 1, d = 1] = size, small = Math.min(w, h, d);
        const r = radius ?? Math.min(small * 0.45, Math.max(w, h, d) * 0.025);
        g = rounded && r > 1e-5 ? new T.RoundedBoxGeometry(w, h, d, 3, r) : new T.BoxGeometry(w, h, d);
      } else if (kind === 'cylinder') {
        const [rt = 0.5, rb = rt, h = 1, segments = 40] = size;
        const f = radius ?? Math.min(rt * 0.4, rb * 0.4, h * 0.3, Math.max(rt, rb, h) * 0.04);
        g = rounded && f > 1e-5 ? lathe(rt, rb, h, segments, f) : new T.CylinderGeometry(rt, rb, h, segments);
      } else if (kind === 'sphere') g = new T.SphereGeometry(size[0] ?? 0.5, size[1] ?? 32, size[2] ?? 20);
      else if (kind === 'cone') g = new T.ConeGeometry(size[0] ?? 0.5, size[1] ?? 1, size[2] ?? 32);
      else if (kind === 'torus') g = new T.TorusGeometry(size[0] ?? 0.5, size[1] ?? 0.1, size[2] ?? 12, size[3] ?? 64);
      else if (kind === 'capsule') g = new T.CapsuleGeometry(size[0] ?? 0.25, size[1] ?? 0.5, 8, 24);
      else if (kind === 'plane') g = new T.PlaneGeometry(size[0] ?? 1, size[1] ?? 1);
      else if (kind === 'disc') g = new T.CircleGeometry(size[0] ?? 0.5, size[1] ?? 48);
      else throw new Error(`Unknown shape "${kind}". Known: box, cylinder, sphere, cone, torus, capsule, plane, disc`);
      shapes.set(key, own(g));
      return g;
    }

    // ---------- Textures, computed as data so they look the same everywhere ----------
    const textures = new Map();
    function dataTexture(width, height, fill, repeat) {
      const data = new Uint8Array(width * height * 4);
      let seed = 7;
      const rand = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
      fill(data, width, height, rand);
      const texture = new T.DataTexture(data, width, height, T.RGBAFormat);
      texture.wrapS = texture.wrapT = T.RepeatWrapping;
      texture.repeat.set(repeat, repeat);
      texture.magFilter = T.LinearFilter;
      texture.minFilter = T.LinearMipmapLinearFilter;
      texture.generateMipmaps = true;
      texture.anisotropy = 4;
      texture.needsUpdate = true;
      return own(texture);
    }
    /** 'powder': soft mottling for satin finishes. 'brushed': streaks along one axis for metal. */
    function grain(kind = 'powder') {
      if (textures.has(kind)) return textures.get(kind);
      let texture;
      if (kind === 'powder') {
        texture = dataTexture(256, 256, (data, w, h, rand) => {
          const cells = 24, grid = Array.from({ length: cells * cells }, () => rand());
          const at = (x, y) => grid[((y + cells) % cells) * cells + ((x + cells) % cells)];
          for (let y = 0; y < h; y += 1) for (let x = 0; x < w; x += 1) {
            const gx = x / w * cells, gy = y / h * cells, ix = Math.floor(gx), iy = Math.floor(gy), fx = gx - ix, fy = gy - iy;
            const soft = (at(ix, iy) * (1 - fx) + at(ix + 1, iy) * fx) * (1 - fy) + (at(ix, iy + 1) * (1 - fx) + at(ix + 1, iy + 1) * fx) * fy;
            const v = 205 + soft * 50 * 0.65 + rand() * 50 * 0.35, i = (y * w + x) * 4;
            data[i] = data[i + 1] = data[i + 2] = v; data[i + 3] = 255;
          }
        }, 2);
      } else if (kind === 'brushed') {
        texture = dataTexture(512, 512, (data, w, h, rand) => {
          for (let y = 0; y < h; y += 1) {
            const row = 222 + rand() * 33;
            for (let x = 0; x < w; x += 1) {
              const i = (y * w + x) * 4;
              data[i] = data[i + 1] = data[i + 2] = Math.min(255, row + rand() * 4); data[i + 3] = 255;
            }
          }
        }, 1);
      } else throw new Error(`Unknown grain "${kind}". Known: powder, brushed`);
      textures.set(kind, texture);
      return texture;
    }
    function ramp(steps = 3) {
      const key = `ramp:${steps}`;
      if (textures.has(key)) return textures.get(key);
      const data = new Uint8Array(steps).map((_, i) => Math.round(70 + (255 - 70) * (i / Math.max(1, steps - 1))));
      const texture = own(new T.DataTexture(data, steps, 1, T.RedFormat));
      texture.minFilter = texture.magFilter = T.NearestFilter;
      texture.needsUpdate = true;
      textures.set(key, texture);
      return texture;
    }

    // ---------- Surfaces ----------
    const shader = (fragmentShader, uniforms, extra = {}) => new T.ShaderMaterial({ vertexShader: SURFACE_VS, fragmentShader, uniforms, ...extra });
    const BUILT_IN = {
      flat: o => new T.MeshStandardMaterial({ color: color(o.color), emissive: color(o.color).multiplyScalar(o.glow), roughness: o.roughness, metalness: 0 }),
      satin: o => new T.MeshPhysicalMaterial({
        color: color(o.color), roughness: o.roughness, clearcoat: o.clearcoat, clearcoatRoughness: o.clearcoatRoughness,
        roughnessMap: o.grain ? grain(o.grain) : null, bumpMap: o.grain && o.bump ? grain(o.grain) : null, bumpScale: o.bump,
      }),
      clay: o => new T.MeshStandardMaterial({ color: color(o.color), roughness: o.roughness, metalness: 0 }),
      gloss: o => new T.MeshPhysicalMaterial({ color: color(o.color), roughness: o.roughness, clearcoat: o.clearcoat, clearcoatRoughness: o.clearcoatRoughness }),
      metal: o => new T.MeshPhysicalMaterial({
        color: color(o.color), metalness: 1, roughness: o.roughness,
        roughnessMap: o.brushed ? grain('brushed') : null, anisotropy: o.brushed ? o.anisotropy : 0,
      }),
      cel: o => new T.MeshToonMaterial({ color: color(o.color), gradientMap: ramp(o.steps) }),
      warmcool: o => shader(WARMCOOL_FS, {
        uBase: { value: color(o.color) }, uCool: { value: color(o.cool) }, uWarm: { value: color(o.warm) },
        uCoolMix: { value: o.coolMix }, uWarmMix: { value: o.warmMix }, uHighlight: { value: o.highlight },
      }),
      hatch: o => {
        const material = shader(HATCH_FS, {
          uBase: { value: color(o.color) }, uPaper: { value: color(o.paper) }, uInk: { value: color(o.ink) },
          uSpacing: { value: o.spacing }, uTint: { value: o.tint },
        });
        material.userData.doxSpacing = o.spacing;
        return material;
      },
      // Added light vanishes on a light background, so light backgrounds switch to ink that darkens with overlap.
      xray: o => {
        const glow = color(o.background).getHSL({}).l < 0.5;
        return shader(XRAY_FS, {
          uRim: { value: color(o.color) }, uFill: { value: o.fill }, uFalloff: { value: o.falloff },
          uStrength: { value: o.strength }, uGlow: { value: glow ? 1 : 0 },
        }, { transparent: true, blending: glow ? T.AdditiveBlending : T.NormalBlending, depthWrite: false, side: T.DoubleSide });
      },
    };
    /** A material by surface name. Unknown option keys are refused so typos fail loudly. */
    function surface(kind, options = {}) {
      if (custom[kind]) return own(custom[kind](T, options, kit));
      known(kind, BUILT_IN, 'surface');
      const defaults = SURFACE_DEFAULTS[kind];
      const { three, ...rest } = options;
      const unknown = Object.keys(rest).filter(key => !(key in defaults) && !['background', 'paper', 'ink'].includes(key));
      if (unknown.length) throw new Error(`Surface "${kind}" has no option ${unknown.join(', ')}. Options: ${Object.keys(defaults).join(', ')}`);
      const resolved = { ...defaults, ...rest };
      const material = BUILT_IN[kind](resolved);
      if (three) material.setValues(three);
      if (material.emissive) {
        material.userData.doxSolid = {
          color: material.color.clone(), emissive: material.emissive.clone(),
          env: material.envMapIntensity ?? 1, clearcoat: material.clearcoat ?? 0,
        };
      }
      return own(material);
    }
    /**
     * Blend a lit surface between a flat paper drawing (s = 0) and its finished self (s = 1).
     * Drawn surfaces (warm-cool, hatch, x-ray) have no paper state and are left unchanged.
     */
    function setSolid(material, s, paper = '#f6f4ee') {
      const base = material.userData.doxSolid;
      if (!base) return;
      material.color.setRGB(0, 0, 0).lerp(base.color, s);
      material.emissive.copy(color(paper)).lerp(base.emissive, s);
      if ('envMapIntensity' in material) material.envMapIntensity = base.env * s;
      // Keep clearcoat above zero: crossing zero recompiles the shader mid-transition.
      if (base.clearcoat > 0) material.clearcoat = Math.max(1e-3, base.clearcoat * s);
    }

    // ---------- Lines ----------
    const edges = new Map(), lineMaterials = new Map();
    function lineMaterial({ color: c = '#1d2430', width = 1.2, opacity = 1, key = '' } = {}) {
      const id = `${new T.Color(c).getHexString()}:${width}:${opacity}:${key}`;
      if (!lineMaterials.has(id)) {
        const material = own(new T.LineMaterial({ color: color(c), linewidth: width, transparent: true, opacity, worldUnits: false }));
        material.userData.doxOpacity = opacity;
        lineMaterials.set(id, material);
      }
      return lineMaterials.get(id);
    }
    /** Ink along crease and boundary edges. Rounded shapes have no creases; use outline() for their silhouettes. */
    function creases(geometry, { angle = 28, ...style } = {}) {
      const id = `${geometry.uuid}:${angle}`;
      if (!edges.has(id)) edges.set(id, own(new T.LineSegmentsGeometry().fromEdgesGeometry(own(new T.EdgesGeometry(geometry, angle)))));
      return new T.LineSegments2(edges.get(id), lineMaterial(style));
    }
    const hulls = new Map();
    /** A constant-width silhouette, drawn as pushed-out back faces. */
    function outline(geometry, { color: c = '#1d2430', width = 1.4, opacity = 1, key = '' } = {}) {
      const id = `${new T.Color(c).getHexString()}:${width}:${opacity}:${key}`;
      if (!hulls.has(id)) {
        const material = own(new T.ShaderMaterial({
          vertexShader: HULL_VS, fragmentShader: FLAT_FS, side: T.BackSide, transparent: true,
          uniforms: { uRes: { value: new T.Vector2(1, 1) }, uWidth: { value: width }, uColor: { value: color(c) }, uOpacity: { value: opacity } },
        }));
        material.userData.doxOpacity = opacity;
        hulls.set(id, material);
      }
      return new T.Mesh(geometry, hulls.get(id));
    }
    /** A polyline in model space, optionally dashed (dash and gap in model units). */
    function line(points, { dash = 0, gap = 0, ...style } = {}) {
      const segments = [];
      for (let k = 0; k < points.length - 1; k += 1) {
        const a = points[k], b = points[k + 1], length = Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2]);
        if (!dash) { segments.push(...a, ...b); continue; }
        for (let s = 0; s < length; s += dash + gap) {
          const e = Math.min(length, s + dash), at = x => a.map((v, i) => v + (b[i] - v) * (x / length));
          segments.push(...at(s), ...at(e));
        }
      }
      const geometry = own(new T.LineSegmentsGeometry());
      geometry.setPositions(segments);
      return new T.LineSegments2(geometry, lineMaterial(style));
    }

    // ---------- Light, environment, shadow ----------
    /** Named light setups. Returns the lights it added. */
    function light(scene, rig = 'studio', { intensity, shadow = true, direction = [-3, 3.6, 2.6], extent = 2.4, target = [0, 0, 0] } = {}) {
      const added = [];
      const add = item => { scene.add(item); added.push(item); return item; };
      const key = strength => {
        const sun = add(new T.DirectionalLight(0xffffff, strength));
        sun.target.position.set(...target);
        add(sun.target);
        sun.position.set(...direction).setLength(extent * 3).add(sun.target.position);
        if (shadow) {
          sun.castShadow = true;
          sun.shadow.mapSize.set(1024, 1024);
          Object.assign(sun.shadow.camera, { left: -extent, right: extent, top: extent, bottom: -extent, near: 0.1, far: extent * 8 });
          sun.shadow.bias = -0.0004;
          sun.shadow.normalBias = 0.015;
        }
        return sun;
      };
      if (rig === 'studio') key(intensity ?? 1.6);
      else if (rig === 'soft') { add(new T.HemisphereLight(0xffffff, 0xb9b0a2, 0.5)); key(intensity ?? 1.9); }
      else if (rig === 'flat') {
        add(new T.HemisphereLight(0xffffff, 0xd8d2c3, 0.75));
        add(new T.DirectionalLight(0xffffff, intensity ?? 0.9)).position.set(-0.55, 0.9, 0.75);
      } else if (rig === 'cel') {
        add(new T.AmbientLight(0xffffff, 0.75));
        add(new T.DirectionalLight(0xffffff, intensity ?? 1.7)).position.set(...direction);
      } else if (rig !== 'none') throw new Error(`Unknown light "${rig}". Known: studio, soft, flat, cel, none`);
      return added;
    }
    const environments = new WeakMap();
    /** Soft studio reflections from Three's official room environment, computed once per renderer. */
    function environment(renderer, scene, intensity = 1) {
      if (!environments.has(renderer)) {
        const pmrem = new T.PMREMGenerator(renderer);
        environments.set(renderer, own(pmrem.fromScene(new T.RoomEnvironment(), 0.04).texture));
        pmrem.dispose();
      }
      scene.environment = environments.get(renderer);
      scene.environmentIntensity = intensity;
      return scene.environment;
    }
    /** An invisible floor that only shows shadows. Needs a shadow-casting light. */
    function ground(scene, { y = 0, opacity = 0.2, size = 40 } = {}) {
      const mesh = new T.Mesh(own(new T.PlaneGeometry(size, size)), own(new T.ShadowMaterial({ opacity })));
      mesh.rotation.x = -Math.PI / 2;
      mesh.position.y = y;
      mesh.receiveShadow = true;
      scene.add(mesh);
      return mesh;
    }

    // ---------- Skins: an image laid onto a shape, as a repeating tile or one continuous wrap ----------
    /**
     * A texture from a document image (an <img> or its id; embed it like any image slot). With `tint`, the image's
     * marks become ink of one colour over a base colour: `key: 'alpha'` uses its transparency, `key: 'luminance'`
     * turns light-on-black art into coverage, so one generated image serves any palette. `ready` resolves once drawn.
     */
    function skinTexture(source, { tint } = {}) {
      const image = typeof source === 'string' ? document.getElementById(source) : source;
      if (!image || !image.decode) throw new Error(`Skin image "${source}" is not an <img> in the document`);
      const canvas = document.createElement('canvas');
      canvas.width = canvas.height = 2;
      const texture = own(new T.CanvasTexture(canvas));
      texture.colorSpace = T.SRGBColorSpace;
      texture.wrapS = texture.wrapT = T.RepeatWrapping;
      texture.anisotropy = 8;
      texture.userData.ready = image.decode().then(() => {
        const w = image.naturalWidth, h = image.naturalHeight, g = canvas.getContext('2d', { willReadFrequently: true });
        canvas.width = w; canvas.height = h;
        if (!tint) g.drawImage(image, 0, 0);
        else {
          const ink = document.createElement('canvas');
          ink.width = w; ink.height = h;
          const i = ink.getContext('2d', { willReadFrequently: true });
          i.drawImage(image, 0, 0);
          if (tint.key === 'luminance') {
            const pixels = i.getImageData(0, 0, w, h), d = pixels.data, [lo, hi] = tint.range ?? [48, 210];
            for (let k = 0; k < d.length; k += 4) {
              const light = 0.2126 * d[k] + 0.7152 * d[k + 1] + 0.0722 * d[k + 2];
              d[k + 3] = Math.round(255 * Math.min(1, Math.max(0, (light - lo) / (hi - lo))) * (d[k + 3] / 255));
            }
            i.putImageData(pixels, 0, 0);
          }
          i.globalCompositeOperation = 'source-in';
          i.fillStyle = tint.ink ?? '#ffffff';
          i.fillRect(0, 0, w, h);
          g.fillStyle = tint.base ?? '#1d2430';
          g.fillRect(0, 0, w, h);
          g.globalAlpha = tint.strength ?? 0.8;
          g.drawImage(ink, 0, 0);
        }
        texture.userData.aspect = w / h;
        // The placeholder may already be on the GPU at 2 x 2, and that storage cannot grow: release it first.
        texture.dispose();
        texture.needsUpdate = true;
        return texture;
      });
      return texture;
    }
    /** The average colour of one row of a drawn skin, at height v (0 bottom, 1 top): a flat colour for caps. */
    function sampleRow(texture, v) {
      const canvas = texture.image, row = Math.min(canvas.height - 1, Math.max(0, Math.round(canvas.height * (1 - v))));
      const d = canvas.getContext('2d', { willReadFrequently: true }).getImageData(0, row, canvas.width, 1).data;
      const sum = [0, 0, 0];
      for (let k = 0; k < d.length; k += 4) { sum[0] += d[k]; sum[1] += d[k + 1]; sum[2] += d[k + 2]; }
      const n = d.length / 4;
      return `rgb(${sum.map(x => Math.round(x / n)).join(',')})`;
    }
    const extent = geometry => { geometry.computeBoundingBox(); return geometry.boundingBox.getSize(new T.Vector3()); };
    const vertices = (geometry, group) => {
      const index = geometry.index ? geometry.index.array : null, out = new Set();
      const end = Math.min(group.start + group.count, index ? index.length : geometry.attributes.position.count);
      for (let k = group.start; k < end; k += 1) out.add(index ? index[k] : k);
      return out;
    };
    /** Repeat a skin at `size` world units per tile, the same on every face. Mutates UVs: clone shared geometry first. */
    function mapTile(geometry, kind, size = 0.5) {
      const p = geometry.attributes.position, uv = geometry.attributes.uv, dims = extent(geometry);
      if (kind === 'box') {
        for (const group of geometry.groups) {
          const axis = group.materialIndex >> 1, sign = group.materialIndex % 2 ? -1 : 1;
          for (const i of vertices(geometry, group)) {
            const x = p.getX(i), y = p.getY(i), z = p.getZ(i);
            const [u, v] = axis === 0 ? [-sign * z, y] : axis === 1 ? [x, -sign * z] : [sign * x, y];
            uv.setXY(i, u / size, v / size);
          }
        }
      } else {
        // Turned and round shapes: their UVs already run around and along; scale them to world size.
        const around = Math.PI * Math.max(dims.x, dims.z), along = kind === 'sphere' ? around / 2 : dims.y;
        for (let i = 0; i < uv.count; i += 1) uv.setXY(i, uv.getX(i) * around / size, uv.getY(i) * along / size);
      }
      uv.needsUpdate = true;
      return geometry;
    }
    /**
     * Lay one image continuously around a shape, never stretched: it fits the wrapped span and crops the excess.
     * Box: across the front and right side (what a three-quarter camera sees), mirrored over the back and left so
     * both rear corners meet; top and bottom are caps for a flat colour. Turned shapes: once around, joined at the back.
     * Returns `fill`, the share of image height used, for sampling a cap colour at the crop line.
     */
    function mapWrap(geometry, kind, aspect) {
      const p = geometry.attributes.position, uv = geometry.attributes.uv, dims = extent(geometry);
      const box = kind === 'box', W = dims.x, H = dims.y, D = dims.z;
      const span = box ? W + D : Math.PI * Math.max(W, D), ratio = span / H;
      const fill = Math.min(1, aspect / ratio), width = Math.min(1, ratio / aspect), left = (1 - width) / 2;
      const place = (u, y) => [left + width * Math.min(1, Math.max(0, u)), fill * Math.min(1, Math.max(0, (y + H / 2) / H))];
      if (box) {
        for (const group of geometry.groups) {
          const face = group.materialIndex;
          if (face === 2 || face === 3) continue;
          for (const i of vertices(geometry, group)) {
            const x = p.getX(i), y = p.getY(i), z = p.getZ(i);
            const s = face === 4 ? x + W / 2 : face === 0 ? W + (D / 2 - z) : face === 5 ? W + D + (W / 2 - x) : 2 * W + D + (z + D / 2);
            uv.setXY(i, ...place(s <= span ? s / span : 2 - s / span, y));
          }
        }
      } else {
        // Only the side wraps; a cylinder's end caps (groups 1 and 2) keep their radial UVs.
        const side = geometry.groups.length ? vertices(geometry, geometry.groups[0]) : null;
        for (let i = 0; i < uv.count; i += 1) if (!side || side.has(i)) uv.setXY(i, left + width * (uv.getX(i) + 0.5), fill * uv.getY(i));
      }
      uv.needsUpdate = true;
      return { fill, span: ratio };
    }

    // ---------- Camera ----------
    /** Place a camera so every point (or every corner of a Box3) is inside the frame from the given direction. */
    function fit(camera, shape, { elevation = 0.42, azimuth = 0, margin = 1.08, target, aspect = camera.aspect || 1 } = {}) {
      const box = shape.isBox3 ? shape : new T.Box3().setFromPoints(shape);
      const points = shape.isBox3 ? [] : shape;
      if (shape.isBox3) for (const x of [box.min.x, box.max.x]) for (const y of [box.min.y, box.max.y]) for (const z of [box.min.z, box.max.z]) points.push(new T.Vector3(x, y, z));
      const center = target ? new T.Vector3(...target) : box.getCenter(new T.Vector3());
      const toward = new T.Vector3(Math.sin(azimuth) * Math.cos(elevation), Math.sin(elevation), Math.cos(azimuth) * Math.cos(elevation));
      const forward = toward.clone().negate();
      const right = new T.Vector3().crossVectors(forward, new T.Vector3(0, 1, 0)).normalize();
      const up = new T.Vector3().crossVectors(right, forward);
      const rel = new T.Vector3();
      const corners = points.map(point => { rel.copy(point).sub(center); return [rel.dot(right), rel.dot(up), rel.dot(toward)]; });
      const radius = box.getSize(new T.Vector3()).length() / 2 || 1;
      let distance;
      if (camera.isOrthographicCamera) {
        let halfW = 0, halfH = 0;
        for (const [x, y] of corners) { halfW = Math.max(halfW, Math.abs(x) * margin); halfH = Math.max(halfH, Math.abs(y) * margin); }
        if (halfW / halfH > aspect) halfH = halfW / aspect; else halfW = halfH * aspect;
        Object.assign(camera, { left: -halfW, right: halfW, top: halfH, bottom: -halfH });
        distance = radius * 4;
      } else {
        camera.aspect = aspect;
        const tanV = Math.tan(T.MathUtils.degToRad(camera.fov) / 2), tanH = tanV * aspect;
        distance = 0;
        for (const [x, y, z] of corners) distance = Math.max(distance, z + Math.max(Math.abs(x) * margin / tanH, Math.abs(y) * margin / tanV));
      }
      camera.position.copy(center).addScaledVector(toward, distance);
      camera.near = Math.max(0.01, distance - radius * 2);
      camera.far = distance + radius * 4;
      camera.lookAt(center);
      camera.updateProjectionMatrix();
      return { distance, center };
    }

    /** Per-frame sizes that screen-space materials need: line resolution, outline width, hatch spacing. */
    function sync(scene, { width, height, pixelRatio = 1 }) {
      scene.traverse(object => {
        const list = Array.isArray(object.material) ? object.material : object.material ? [object.material] : [];
        for (const material of list) {
          if (material.isLineMaterial) material.resolution.set(width, height);
          if (material.uniforms?.uRes) material.uniforms.uRes.value.set(width, height);
          if (material.uniforms?.uSpacing && material.userData.doxSpacing) material.uniforms.uSpacing.value = material.userData.doxSpacing * pixelRatio;
        }
      });
    }

    function toneMapping(name = 'none') {
      const table = { none: T.NoToneMapping, neutral: T.NeutralToneMapping, aces: T.ACESFilmicToneMapping, agx: T.AgXToneMapping };
      known(name, table, 'tone mapping');
      return table[name];
    }

    function dispose() {
      owned.forEach(item => item.dispose?.());
      owned.clear(); shapes.clear(); textures.clear(); edges.clear(); lineMaterials.clear(); hulls.clear();
    }

    const kit = {
      T, shape, grain, ramp, surface, setSolid, lineMaterial, creases, outline, line, light, environment, ground, fit, sync,
      skinTexture, sampleRow, mapTile, mapWrap,
      toneMapping, look: DoxStageKit.look, looks: DoxStageKit.looks, surfaces: DoxStageKit.surfaces, defineSurface: DoxStageKit.defineSurface,
      curved: kind => CURVED.has(kind), dispose,
    };
    return kit;
  }

  /** A look by name, with overrides; nested lines, outline and monochrome settings merge one level deep. */
  DoxStageKit.look = (value = 'satin', overrides) => {
    if (Array.isArray(value)) return merge(DoxStageKit.look(value[0], value[1]), overrides);
    let base = value;
    if (typeof value === 'string') { known(value, LOOKS, 'look'); base = { name: value, ...LOOKS[value] }; }
    else if (value.base) base = merge(DoxStageKit.look(value.base), value);
    return merge(base, overrides);
  };
  DoxStageKit.looks = () => Object.keys(LOOKS);
  DoxStageKit.surfaces = () => ({ ...JSON.parse(JSON.stringify(SURFACE_DEFAULTS)), ...Object.fromEntries(Object.keys(custom).map(k => [k, 'custom'])) });
  /** Register a surface: make(T, options, K) returns a material. It is then usable by name in any look. */
  DoxStageKit.defineSurface = (name, make) => {
    if (SURFACE_DEFAULTS[name]) throw new Error(`Surface "${name}" is built in; choose another name`);
    custom[name] = make;
  };
  globalThis.DoxStageKit = DoxStageKit;
})();
