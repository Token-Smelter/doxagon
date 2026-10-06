/* Three ways to draw the same choreography state, plus the DOM layer they share. */
window.DoxMotionRenderers = (() => {
  'use strict';
  const LIFT = 42;
  const LAYERS = ['base', 'core', 'cap'];
  const DEG = Math.PI / 180;
  const clamp = (value, lo = 0, hi = 1) => Math.max(lo, Math.min(hi, value));
  const cross = 'M0,0 C6,6 14,14 20,20 M20,0 C14,6 6,14 0,20';
  const tick = 'M0,10 C3,13 6,16 8,18 M8,18 C12,12 16,6 20,0';
  const draftOutline = 'M-64,-100 L-22,-108 L6,-94 L60,-104 L68,-60 L54,-44 L64,-28 L-60,-28 L-68,-62 Z';
  const revisedOutline = 'M-58,-102 H58 Q68,-102 68,-92 V-38 Q68,-28 58,-28 H-58 Q-68,-28 -68,-38 V-92 Q-68,-102 -58,-102 Z';
  const tone = (profile, check) => check.verdict === 'Change' ? profile.reject : check.verdict === 'Pass' ? profile.accept : profile.ink;
  function seeded(seed) {
    return () => { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed / 4294967296; };
  }
  function relativeBox(stage, rect) {
    const outer = stage.getBoundingClientRect();
    if (!outer.width || !rect.width) return null;
    return { x0: (rect.left - outer.left) / outer.width, y0: (rect.top - outer.top) / outer.height,
      x1: (rect.right - outer.left) / outer.width, y1: (rect.bottom - outer.top) / outer.height };
  }

  /* Status, readings and a tracking bracket recomputed from state every frame. */
  class Overlay {
    constructor(root, config) {
      this.root = root; this.stage = root.querySelector('.motion-stage'); this.text = new Map();
      this.track = root.querySelector('.motion-track');
      this.track.innerHTML = '<i data-corner="0"></i><i data-corner="1"></i><i data-corner="2"></i><i data-corner="3"></i><span class="motion-track-label"></span>';
      this.ledger = root.querySelector('.motion-ledger');
      this.ledger.innerHTML = '<div class="motion-ledger-sheet"></div><ol class="motion-ledger-checks">' +
        config.checks.map(() => '<li><span class="motion-check-name"></span><span class="motion-check-reading"></span><b class="motion-check-verdict"></b></li>').join('') +
        '</ol><p class="motion-counter"><span class="motion-counter-label"></span> <output class="motion-counter-value"></output></p>' +
        '<p class="motion-ledger-extra">Released after recheck</p>';
      this.rows = [...this.ledger.querySelectorAll('li')];
    }
    // Readouts write only when their text changes, so scrubbing does not churn the DOM.
    write(node, value) {
      if (this.text.get(node) !== value) { node.textContent = value; this.text.set(node, value); }
    }
    render(state, box) {
      state.checks.forEach((check, i) => {
        const row = this.rows[i];
        this.write(row.querySelector('.motion-check-name'), check.name);
        this.write(row.querySelector('.motion-check-reading'), `${check.readings}/${check.of}`);
        this.write(row.querySelector('.motion-check-verdict'), check.verdict);
        row.dataset.result = check.verdict;
      });
      const counter = state.ledger;
      this.write(this.ledger.querySelector('.motion-counter-label'), counter.mode);
      this.write(this.ledger.querySelector('.motion-counter-value'), `${counter.counter}/${counter.of}`);
      this.ledger.querySelector('.motion-counter-value').style.transform = `scale(${1 + 0.22 * counter.counter / counter.of})`;
      this.ledger.querySelector('.motion-ledger-sheet').style.transform = `scaleY(${0.8 + 0.2 * counter.expand})`;
      const extra = this.ledger.querySelector('.motion-ledger-extra');
      extra.style.opacity = counter.expand; extra.style.transform = `translateY(${(counter.expand - 1) * 10}px)`;
      this.track.hidden = !box;
      if (!box) return;
      const w = this.stage.clientWidth, h = this.stage.clientHeight;
      const points = [[box.x0, box.y0], [box.x1, box.y0], [box.x0, box.y1], [box.x1, box.y1]];
      this.track.querySelectorAll('i').forEach((corner, i) => {
        corner.style.transform = `translate(${(points[i][0] * w).toFixed(1)}px,${(points[i][1] * h).toFixed(1)}px)`;
      });
      const label = this.track.querySelector('.motion-track-label');
      this.write(label, state.status);
      label.dataset.accepted = String(state.accepted);
      label.style.transform = `translate(${(box.x0 * w).toFixed(1)}px,${(Math.max(0, box.y0 * h - 30)).toFixed(1)}px)`;
    }
  }

  class Engraving {
    constructor(root, plan) {
      this.root = root; this.plan = plan; this.stage = root.querySelector('.motion-stage');
      this.svg = root.querySelector('svg');
      this.svg.setAttribute('role', 'img');
      const image = (component, x, y, size) => `<image data-component="${component}" x="${x}" y="${y}" width="${size}" height="${size}"/>`;
      const random = seeded(0x51ed27);
      const scraps = Array.from({ length: 6 }, (_, i) => {
        const x = 120 + (i % 3) * 64, y = 110 + Math.floor(i / 3) * 60, points = [];
        for (let k = 0; k <= 6; k++) points.push(`${x + k * 11},${y + random() * 5}`);
        for (let k = 0; k <= 6; k++) points.push(`${x + 66 - random() * 5},${y + k * 10.5}`);
        for (let k = 6; k >= 0; k--) points.push(`${x + k * 11},${y + 62 - random() * 5}`);
        for (let k = 6; k >= 0; k--) points.push(`${x + random() * 5},${y + k * 10.5}`);
        return `<polygon class="mp-scrap" data-scrap="${i}" points="${points.join(' ')}"/>`;
      }).join('');
      this.flights = Array.from({ length: 6 }, (_, i) => ({ start: 20.6 + i * 0.15, dx: (i % 3 - 1) * 90 + 20, dy: -150 - random() * 80, angle: (random() - 0.5) * 70 }));
      this.svg.innerHTML = `<defs>
        <pattern id="mp-hatch" width="16" height="16" patternUnits="userSpaceOnUse" patternTransform="rotate(35)"><path d="M0 0V16" class="mp-mark"/></pattern>
        <pattern id="mp-grid" width="28" height="28" patternUnits="userSpaceOnUse"><path d="M28 0H0V28" fill="none" class="mp-mark"/></pattern>
        <pattern id="mp-solid" width="36" height="36" patternUnits="userSpaceOnUse"><circle cx="18" cy="18" r="2" class="mp-dot"/></pattern>
        <pattern id="mp-arcs" width="64" height="64" patternUnits="userSpaceOnUse"><path d="M8 32 Q32 8 56 32 M8 48 Q32 24 56 48" fill="none" class="mp-mark"/></pattern>
        <pattern id="mp-perforation" width="40" height="40" patternUnits="userSpaceOnUse"><path d="M10 20H26" class="mp-mark" stroke-linecap="square"/></pattern>
        <pattern id="mp-weave" width="32" height="32" patternUnits="userSpaceOnUse"><path d="M0 8H14 M18 24H32 M8 18V32 M24 0V14" class="mp-mark"/></pattern>
        <filter id="mp-dof" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="0"/></filter>
        <radialGradient id="mp-bloom"><stop offset="0" class="mp-bloom-in"/><stop offset="1" class="mp-bloom-out"/></radialGradient>
      </defs>
      <rect class="mp-ground" x="-3000" y="-3000" width="7000" height="7000"/>
      <g class="mp-world">
        <g class="mp-far">
          <ellipse class="mp-platform" cx="470" cy="392" rx="190" ry="62"/>
          <ellipse class="mp-platform" cx="800" cy="512" rx="78" ry="22"/>
          <path class="mp-route mp-intake" d="${plan.paths.intake}"/><path class="mp-route mp-exit" d="${plan.paths.exit}"/>
          <path class="mp-post" d="M985 260V${260 - 3.6 * LIFT}"/><circle class="mp-post-cap" cx="985" cy="${260 - 3.6 * LIFT}" r="9"/>
          ${plan.paths.probes.map((d, i) => `<path class="mp-probe-route" data-route="${i}" d="${d}"/>`).join('')}
          ${[0, 1, 2].map(i => `<g class="mp-probe" data-probe="${i}"><ellipse class="mp-contact" rx="30" ry="8" cy="62"/><g class="mp-probe-body">${image('probe', -42, -42, 84)}</g></g>`).join('')}
        </g>
        <g class="mp-echoes">${[0, 1, 2, 3].map(() => `<g class="mp-echo">${image('core', -100, -170, 200)}</g>`).join('')}</g>
        <g class="mp-candidate">
          <ellipse class="mp-contact" rx="92" ry="20" cy="26"/>
          ${LAYERS.map((name, i) => `<g class="mp-layer" data-layer="${i}">${image(name, -100, -170, 200)}${i === 1 ? `<path class="mp-outline" d="${draftOutline}"/>` : ''}</g>`).join('')}
          <path class="mp-verdict-mark" d="${cross}"/>
        </g>
        <g class="mp-revision"><rect class="mp-sheet" x="120" y="110" width="192" height="122" rx="3"/>
          <text class="mp-sheet-title" x="138" y="142">Core revised</text>
          <path class="mp-sheet-lines" d="M138 168h150 M138 188h118 M138 208h138"/>${scraps}</g>
        <g class="mp-scanner"><ellipse class="mp-pedestal" rx="62" ry="17" cy="16"/><circle class="mp-ring" r="60"/>
          <g class="mp-spin"><path class="mp-wedge" d="M0 0 L150 -26 A152 152 0 0 1 150 26 Z"/>${image('scanner', -56, -56, 112)}</g>
          ${[0, 1, 2].map(i => `<path class="mp-tick" data-tick="${i}" d="M58 0H78"/>`).join('')}<circle class="mp-blink" r="7"/></g>
        <g class="mp-packets">${Array.from({ length: 36 }, () => '<circle r="5"/>').join('')}</g>
        <g class="mp-confetti">${Array.from({ length: 24 }, () => '<rect x="-5" y="-2.5" width="10" height="5"/>').join('')}</g>
        <g class="mp-seal"><circle class="mp-bloom" r="130" fill="url(#mp-bloom)"/>${image('seal', -58, -58, 116)}</g>
      </g>`;
      const q = selector => this.svg.querySelector(selector), all = selector => [...this.svg.querySelectorAll(selector)];
      Object.assign(this, {
        world: q('.mp-world'), ground: q('.mp-ground'), far: q('.mp-far'), blur: q('#mp-dof feGaussianBlur'),
        probes: all('.mp-probe'), probeRoutes: all('.mp-probe-route'), echoes: all('.mp-echo'), candidate: q('.mp-candidate'),
        layers: all('.mp-layer'), outline: q('.mp-outline'), mark: q('.mp-verdict-mark'), revision: q('.mp-revision'),
        scraps: all('.mp-scrap'), scanner: q('.mp-scanner'), spin: q('.mp-spin'), ring: q('.mp-ring'), ticks: all('.mp-tick'),
        blink: q('.mp-blink'), pedestal: q('.mp-pedestal'), wedge: q('.mp-wedge'), packets: all('.mp-packets circle'),
        confetti: all('.mp-confetti rect'), seal: q('.mp-seal'), bloom: q('.mp-bloom'), core: q('.mp-layer[data-layer="1"]')
      });
      this.ticks.forEach((node, i) => node.setAttribute('transform', `rotate(${plan.bearings[i] * 360})`));
      const timeline = gsap.timeline({ paused: true });
      timeline.fromTo(q('.mp-intake'), { drawSVG: '0%' }, { drawSVG: '100%', duration: 6.8, ease: 'power2.inOut' }, 0.6);
      timeline.fromTo(q('.mp-exit'), { drawSVG: '0%' }, { drawSVG: '100%', duration: 4.1, ease: 'power2.inOut' }, 35.5);
      this.probeRoutes.forEach((path, i) => timeline.fromTo(path, { drawSVG: '0%' }, { drawSVG: '100%', duration: 3.2, ease: 'power3.out' }, 8.6 + i * 0.18));
      timeline.fromTo(this.outline, { morphSVG: draftOutline }, { morphSVG: revisedOutline, duration: 4.5, ease: 'power2.inOut' }, 21);
      timeline.fromTo(this.mark, { morphSVG: cross }, { morphSVG: tick, duration: 0.8, ease: 'power3.inOut' }, 33.8);
      timeline.to({}, { duration: 0.001 }, plan.end - 0.001);
      timeline.totalTime(plan.end, true).totalTime(0, true);
      this.timeline = timeline;
    }
    render(state, profile, images) {
      if (this.style !== state.style) {
        this.svg.querySelectorAll('image').forEach(node => node.setAttribute('href', images[node.dataset.component].src));
        this.style = state.style;
      }
      const w = this.stage.clientWidth, h = this.stage.clientHeight, aspect = w / h;
      const W = aspect >= 1080 / 650 ? 650 * aspect : 1080, H = W / aspect;
      this.svg.setAttribute('viewBox', `0 0 ${W.toFixed(2)} ${H.toFixed(2)}`);
      this.svg.setAttribute('aria-label', `${state.label}. ${state.status}.`);
      const view = state.camera, zoom = view.zoom * (H > 700 ? 1.08 : 1);
      // Viewport change: a single world transform carries the camera in the flat recipe.
      this.world.setAttribute('transform', `translate(${W / 2} ${H / 2}) scale(${zoom}) translate(${-view.fx} ${-view.fy})`);
      this.ground.setAttribute('fill', `url(#mp-${profile.pattern})`);
      this.svg.style.setProperty('--mp-stroke', profile.stroke);
      this.svg.style.setProperty('--mp-cap', profile.linecap);
      this.timeline.totalTime(state.time, true).pause();
      // MorphSVG converts paths lazily; holds own exact endpoints so reverse seeks match.
      if (state.time < 21) this.outline.setAttribute('d', draftOutline);
      else if (state.time >= 25.5) this.outline.setAttribute('d', revisedOutline);
      if (state.time < 33.8) this.mark.setAttribute('d', cross);
      else if (state.time >= 34.6) this.mark.setAttribute('d', tick);
      this.blur.setAttribute('stdDeviation', (state.focus * 3.5).toFixed(3));
      this.far.style.opacity = 1 - 0.3 * state.focus;
      this.probes.forEach((node, i) => {
        const probe = state.probes[i];
        node.setAttribute('transform', `translate(${probe.x} ${probe.y - (probe.lift - 1.5) * LIFT - 30})`);
        node.style.opacity = probe.opacity;
        node.querySelector('.mp-probe-body').setAttribute('transform', `scale(${probe.scale})`);
        this.probeRoutes[i].style.opacity = probe.drawn >= 1 ? 0.25 : 0.7;
      });
      const c = state.candidate;
      this.candidate.setAttribute('transform', `translate(${c.x} ${c.y})`);
      c.layers.forEach((layer, i) => this.layers[i].setAttribute('transform',
        `translate(${layer.dx} ${layer.dy - layer.lift * LIFT}) rotate(${layer.rz})`));
      this.outline.style.stroke = c.rejected ? profile.reject : profile.accent;
      this.mark.setAttribute('transform', `translate(${72 + c.layers[2].dx} ${-176 + c.layers[2].dy - c.layers[2].lift * LIFT}) scale(1.6)`);
      this.mark.style.opacity = c.rejected || state.time >= 33.8 ? 1 : 0;
      this.mark.style.stroke = state.time >= 33.8 ? profile.accept : profile.reject;
      c.echoes.forEach((echo, i) => {
        this.echoes[i].setAttribute('transform', `translate(${echo.x} ${echo.y})`);
        this.echoes[i].style.opacity = echo.alpha;
      });
      this.revision.style.opacity = clamp((state.time - 20.2) / 0.4) * (1 - clamp((state.time - 29.6) / 0.8));
      this.scraps.forEach((scrap, i) => {
        const flight = this.flights[i], p = clamp((state.time - flight.start) / 1.3), f = p * p;
        scrap.setAttribute('transform', `translate(${flight.dx * f} ${flight.dy * f}) rotate(${flight.angle * f} ${120 + (i % 3) * 64 + 33} ${140 + Math.floor(i / 3) * 60})`);
        scrap.style.opacity = 1 - p;
        scrap.style.fill = i % 2 ? profile.surface : profile.background;
      });
      const s = state.scanner;
      this.scanner.setAttribute('transform', `translate(${s.x} ${s.y - (s.lift - 0.35) * LIFT}) scale(${s.scale})`);
      this.spin.setAttribute('transform', `rotate(${s.angle.toFixed(4)})`);
      this.wedge.style.opacity = s.sweep;
      this.pedestal.style.opacity = 1 - s.travel;
      this.ring.setAttribute('r', (60 + s.ring * 110).toFixed(3));
      this.ring.style.opacity = s.ringAlpha;
      this.blink.style.opacity = s.blink;
      this.ticks.forEach((node, i) => { node.style.stroke = tone(profile, state.checks[i]); });
      state.packets.forEach((packet, i) => {
        const node = this.packets[i];
        node.setAttribute('cx', packet.x.toFixed(3)); node.setAttribute('cy', (packet.y - (packet.lift - 1.5) * LIFT).toFixed(3));
        node.style.opacity = packet.alpha;
      });
      state.confetti.forEach((piece, i) => {
        const node = this.confetti[i];
        node.setAttribute('transform', `translate(${piece.x.toFixed(3)} ${(piece.y - piece.lift * LIFT).toFixed(3)}) rotate(${piece.spin.toFixed(3)})`);
        node.style.opacity = piece.alpha;
        node.style.fill = [profile.accent, profile.accept, profile.ink][piece.tone];
      });
      const cap = c.layers[2];
      this.seal.setAttribute('transform', `translate(${c.x + cap.dx} ${c.y + cap.dy - (c.capLift + 1.9) * LIFT}) scale(${state.seal.scale})`);
      this.bloom.style.opacity = state.seal.bloom;
      this.seal.style.color = profile.accept;
      return relativeBox(this.stage, this.core.getBoundingClientRect());
    }
    destroy() { this.timeline.kill(); this.svg.replaceChildren(); }
  }

  class Spatial {
    constructor(root, plan) {
      const T = window.DoxMotionLib;
      Object.assign(this, { T, root, plan, canvas: root.querySelector('canvas'), stage: root.querySelector('.motion-stage') });
      const context = this.canvas.getContext('webgl2', { antialias: true, alpha: false, preserveDrawingBuffer: true });
      if (!context) throw new Error('WebGL2 is unavailable');
      this.renderer = new T.WebGLRenderer({ canvas: this.canvas, context, antialias: true, alpha: false });
      this.renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 1));
      this.renderer.outputColorSpace = T.SRGBColorSpace;
      this.renderer.toneMapping = T.ACESFilmicToneMapping;
      this.renderer.shadowMap.enabled = true; this.renderer.shadowMap.type = T.PCFSoftShadowMap;
      this.camera = new T.PerspectiveCamera(40, 1, 0.1, 200);
      this.lost = event => { event.preventDefault(); root.dispatchEvent(new Event('motion:gpu-lost')); };
      this.canvas.addEventListener('webglcontextlost', this.lost);
    }
    invalidateTextures() { this.key = null; }
    world(point) { return { x: (point.x - 540) / 55, z: (point.y - 360) / 55 }; }
    canvasTexture(width, height, paint) {
      const canvas = document.createElement('canvas'); canvas.width = width; canvas.height = height;
      paint(canvas.getContext('2d'));
      const texture = new this.T.CanvasTexture(canvas); texture.colorSpace = this.T.SRGBColorSpace;
      this.owned.push(texture); return texture;
    }
    imageTexture(image) {
      const texture = new this.T.Texture(image); texture.colorSpace = this.T.SRGBColorSpace; texture.needsUpdate = true;
      this.owned.push(texture); return texture;
    }
    patternTexture(profile) {
      return this.canvasTexture(512, 512, ctx => {
        ctx.fillStyle = profile.background; ctx.fillRect(0, 0, 512, 512);
        ctx.strokeStyle = profile.ink; ctx.fillStyle = profile.ink; ctx.globalAlpha = 0.13; ctx.lineWidth = 1.2;
        if (['arcs', 'perforation', 'weave'].includes(profile.pattern)) {
          const step = profile.pattern === 'arcs' ? 64 : profile.pattern === 'perforation' ? 40 : 32;
          for (let x = 0; x < 512; x += step) for (let y = 0; y < 512; y += step) {
            ctx.beginPath();
            if (profile.pattern === 'arcs') {
              ctx.moveTo(x + 8, y + 32); ctx.quadraticCurveTo(x + 32, y + 8, x + 56, y + 32);
              ctx.moveTo(x + 8, y + 48); ctx.quadraticCurveTo(x + 32, y + 24, x + 56, y + 48);
            } else if (profile.pattern === 'perforation') {
              ctx.lineWidth = 2.5; ctx.moveTo(x + 10, y + 20); ctx.lineTo(x + 26, y + 20);
            } else {
              ctx.moveTo(x, y + 8); ctx.lineTo(x + 14, y + 8); ctx.moveTo(x + 18, y + 24); ctx.lineTo(x + 32, y + 24);
              ctx.moveTo(x + 8, y + 18); ctx.lineTo(x + 8, y + 32); ctx.moveTo(x + 24, y); ctx.lineTo(x + 24, y + 14);
            }
            ctx.stroke();
          }
        }
        for (let i = -512; i < 1024; i += profile.pattern === 'grid' ? 24 : 12) {
          ctx.beginPath();
          if (profile.pattern === 'hatch') { ctx.moveTo(i, 0); ctx.lineTo(i + 300, 512); ctx.stroke(); }
          else if (profile.pattern === 'grid' && i >= 0 && i <= 512) { ctx.moveTo(i, 0); ctx.lineTo(i, 512); ctx.moveTo(0, i); ctx.lineTo(512, i); ctx.stroke(); }
          else if (profile.pattern === 'solid' && i >= 0 && i <= 512) for (let y = 6; y < 512; y += 24) ctx.fillRect(i, y, 2.4, 2.4);
        }
      });
    }
    shader(name, from, to, profile, water) {
      const T = this.T;
      const edge = water ? 'vec2 edge=min(v_uv,1.-v_uv);gl_FragColor.rgb=mix(u_background,gl_FragColor.rgb,smoothstep(0.,.12,min(edge.x,edge.y)));' : '';
      const fragment = (water ? 'uniform vec3 u_background;\n' : '') +
        T.getFragSource(name).replace(/}\s*$/, '\n#include <tonemapping_fragment>\n#include <colorspace_fragment>\n' + edge + '}');
      const material = new T.ShaderMaterial({
        uniforms: { u_from: { value: from }, u_to: { value: to }, u_progress: { value: 0 }, u_resolution: { value: new T.Vector2(512, 512) },
          u_background: { value: new T.Color(profile.background).convertLinearToSRGB() }, u_accent: { value: new T.Color(profile.accent) },
          u_accent_dark: { value: new T.Color(profile.ink) }, u_accent_bright: { value: new T.Color(profile.surface) } },
        vertexShader: 'varying vec2 v_uv; void main(){v_uv=uv;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);}',
        fragmentShader: fragment, side: T.DoubleSide, transparent: !water, depthWrite: water
      });
      return material;
    }
    // Rack focus on camera-facing image layers: a texel-offset blur driven by one uniform.
    focusMaterial(texture) {
      const material = new this.T.SpriteMaterial({ map: texture, transparent: true, depthWrite: false });
      material.userData.focus = { value: 0 };
      material.onBeforeCompile = shader => {
        shader.uniforms.motionFocus = material.userData.focus;
        shader.fragmentShader = 'uniform float motionFocus;\n' + shader.fragmentShader.replace('#include <map_fragment>', `
          #ifdef USE_MAP
            vec2 d=vec2(motionFocus/256.);
            vec4 color=texture2D(map,vMapUv)*0.36;
            color+=(texture2D(map,vMapUv+vec2(d.x,0.))+texture2D(map,vMapUv-vec2(d.x,0.))+texture2D(map,vMapUv+vec2(0.,d.y))+texture2D(map,vMapUv-vec2(0.,d.y)))*0.16;
            diffuseColor*=color;
          #endif`);
      };
      return material;
    }
    mesh(geometry, material, cast = true) {
      const mesh = new this.T.Mesh(geometry, material); mesh.castShadow = cast; mesh.receiveShadow = true; return mesh;
    }
    line(points, color, opacity) {
      const T = this.T, geometry = new T.BufferGeometry();
      geometry.setAttribute('position', new T.Float32BufferAttribute(points.flatMap(p => { const w = this.world(p); return [w.x, 0.06, w.z]; }), 3));
      return new T.Line(geometry, new T.LineBasicMaterial({ color, transparent: true, opacity }));
    }
    build(recipe, profile, images) {
      const T = this.T, cinematic = recipe === 'cinematic';
      this.dispose(); this.owned = [];
      const scene = new T.Scene(); scene.background = new T.Color(profile.background);
      scene.fog = new T.FogExp2(profile.background, 0.012);
      scene.add(new T.HemisphereLight(0xffffff, profile.ink, 1.3));
      const sun = new T.DirectionalLight(0xffffff, 2.1); sun.position.set(-8, 16, 7); sun.castShadow = true;
      sun.shadow.mapSize.set(512, 512); Object.assign(sun.shadow.camera, { left: -14, right: 14, top: 11, bottom: -11, near: 1, far: 50 });
      sun.shadow.bias = -0.0005; scene.add(sun);
      const material = (color, extra = {}) => new T.MeshStandardMaterial({ color, roughness: profile.roughness, metalness: profile.metalness, ...extra });
      const surface = material(profile.surface), accent = material(profile.accent), ink = material(profile.ink, { metalness: 0 });
      const textures = Object.fromEntries(Object.entries(images).map(([name, image]) => [name, this.imageTexture(image)]));
      const ground = this.patternTexture(profile);
      const parts = { scene, cinematic };
      if (cinematic) {
        parts.water = this.shader('ripple-waves', ground, ground, profile, true);
        const plane = new T.Mesh(new T.PlaneGeometry(44, 30), parts.water); plane.rotation.x = -Math.PI / 2; scene.add(plane);
        const shadow = new T.Mesh(new T.PlaneGeometry(44, 30), new T.ShadowMaterial({ color: profile.ink, opacity: 0.18 }));
        shadow.rotation.x = -Math.PI / 2; shadow.position.y = 0.02; shadow.receiveShadow = true; scene.add(shadow);
      } else {
        ground.wrapS = ground.wrapT = T.RepeatWrapping; ground.repeat.set(3, 2);
        const plinth = this.mesh(new T.BoxGeometry(27, 1, 17), material(profile.background, { map: ground }), false);
        plinth.position.y = -0.5; scene.add(plinth);
      }
      const station = this.world(this.plan.station), home = this.world(this.plan.scannerHome), post = this.world(this.plan.ledgerPost);
      const k = cinematic ? 1.3 : 1;
      parts.k = k;
      const platform = this.mesh(new T.CylinderGeometry(3.2, 3.4, 0.12, 48), surface, false);
      platform.position.set(station.x, 0.06, station.z); scene.add(platform);
      const pillar = this.mesh(new T.CylinderGeometry(0.09, 0.12, this.plan.ledgerPost.lift * k, 12), ink);
      pillar.position.set(post.x, this.plan.ledgerPost.lift * k / 2, post.z); scene.add(pillar);
      const pillarCap = this.mesh(new T.SphereGeometry(0.22, 16, 12), accent); pillarCap.position.set(post.x, this.plan.ledgerPost.lift * k, post.z); scene.add(pillarCap);
      parts.routes = { intake: this.line(this.plan.samples.intake, profile.accent, 0.55), exit: this.line(this.plan.samples.exit, profile.accent, 0.55),
        probes: this.plan.samples.probes.map(points => this.line(points, profile.ink, 0.35)) };
      [parts.routes.intake, parts.routes.exit, ...parts.routes.probes].forEach(item => scene.add(item));
      // Candidate: registered image layers in the cinematic recipe, solids with an image decal in the miniature.
      const draft = this.canvasTexture(256, 256, ctx => {
        // The unrevised state: the same generated layer, desaturated. Rejection is shown elsewhere and only after a reading.
        ctx.filter = 'grayscale(0.9) contrast(0.8) brightness(1.08)'; ctx.drawImage(images.core, 0, 0, 256, 256); ctx.filter = 'none';
      });
      parts.proof = this.shader('cross-warp-morph', draft, textures.core, profile, false);
      parts.candidate = new T.Group(); scene.add(parts.candidate);
      parts.layers = LAYERS.map((name, i) => {
        const holder = new T.Group(); parts.candidate.add(holder);
        if (cinematic) {
          const plane = new T.Mesh(new T.PlaneGeometry(2.8, 2.8), i === 1 ? parts.proof :
            new T.MeshBasicMaterial({ map: textures[name], transparent: true, alphaTest: 0.04, side: T.DoubleSide, depthWrite: false }));
          plane.position.set(0, 1.4, i * 0.03); plane.renderOrder = 2 + i; holder.add(plane);
        } else {
          const capsule = this.plan.motif === 'capsule';
          const size = [[2.5, 0.55, 1.6], [2.05, 0.55, 1.35], [2.25, 0.32, 1.5]][i];
          const geometry = capsule ? new T.CylinderGeometry(size[0] / 2.1, size[0] / 2.1, size[1], 40) : new T.BoxGeometry(...size);
          const solid = this.mesh(geometry, [surface, accent, surface][i]); solid.position.y = [0.28, 0.83, 1.27][i]; holder.add(solid);
          if (i === 1) {
            const decal = new T.Mesh(capsule ? new T.CircleGeometry(0.85, 40) : new T.PlaneGeometry(1.75, 1.15), parts.proof);
            decal.rotation.x = -Math.PI / 2; decal.position.y = 1.115; holder.add(decal);
          }
        }
        return holder;
      });
      parts.echoes = [0, 1, 2, 3].map(() => {
        const sprite = new T.Sprite(new T.SpriteMaterial({ map: textures.core, transparent: true, depthWrite: false }));
        sprite.center.set(0.5, 0); sprite.scale.set(2.8, 2.8, 1); scene.add(sprite); return sprite;
      });
      const trailGeometry = new T.BufferGeometry(); trailGeometry.setAttribute('position', new T.Float32BufferAttribute(new Float32Array(4 * 3), 3));
      parts.trail = new T.Line(trailGeometry, new T.LineBasicMaterial({ color: profile.ink, transparent: true, opacity: 0.5 })); scene.add(parts.trail);
      parts.probes = [0, 1, 2].map(() => {
        const group = new T.Group(); scene.add(group);
        const badge = new T.Sprite(this.focusMaterial(textures.probe)); badge.center.set(0.5, 0.5);
        group.add(badge); group.userData.badge = badge;
        if (!cinematic) {
          const body = this.mesh(new T.SphereGeometry(0.34, 24, 16), material(profile.accent, { transparent: true }));
          const halo = this.mesh(new T.TorusGeometry(0.52, 0.05, 8, 40), material(profile.ink, { transparent: true }));
          halo.rotation.x = Math.PI / 2; group.add(body, halo); group.userData.solids = [body, halo];
          badge.position.y = 0.95;
        }
        const contact = new T.Mesh(new T.CircleGeometry(0.55, 24), new T.MeshBasicMaterial({ color: profile.ink, transparent: true, opacity: 0.12, depthWrite: false }));
        contact.rotation.x = -Math.PI / 2; scene.add(contact); group.userData.contact = contact;
        return group;
      });
      // The looping sub-component: a fixed rig whose spinner child turns with the loop's angle.
      parts.scanner = new T.Group(); scene.add(parts.scanner);
      parts.pedestal = this.mesh(new T.CylinderGeometry(1.15, 1.3, 0.3, 32), ink);
      parts.pedestal.position.set(home.x, 0.15, home.z); scene.add(parts.pedestal);
      parts.spinner = new T.Group(); parts.scanner.add(parts.spinner);
      if (!cinematic) { const disc = this.mesh(new T.CylinderGeometry(1.02, 1.02, 0.12, 40), surface); disc.position.y = -0.07; parts.spinner.add(disc); }
      const face = new T.Mesh(new T.CircleGeometry(1, 48), new T.MeshBasicMaterial({ map: textures.scanner, transparent: true, alphaTest: 0.04, side: T.DoubleSide }));
      face.rotation.x = -Math.PI / 2; face.position.y = 0.002; parts.spinner.add(face);
      const beam = this.canvasTexture(64, 256, ctx => {
        const fade = ctx.createLinearGradient(0, 0, 0, 256);
        fade.addColorStop(0, 'rgba(255,255,255,.9)'); fade.addColorStop(1, 'rgba(255,255,255,0)'); ctx.fillStyle = fade; ctx.fillRect(0, 0, 64, 256);
      });
      const wedgeGeometry = new T.BufferGeometry();
      wedgeGeometry.setAttribute('position', new T.Float32BufferAttribute([0, 0.01, 0, 2.9 * Math.cos(0.17), 0.01, -2.9 * Math.sin(0.17), 2.9 * Math.cos(0.17), 0.01, 2.9 * Math.sin(0.17)], 3));
      wedgeGeometry.setAttribute('uv', new T.Float32BufferAttribute([0.5, 1, 0, 0, 1, 0], 2));
      parts.wedge = new T.Mesh(wedgeGeometry, new T.MeshBasicMaterial({ map: beam, color: profile.accent, transparent: true, side: T.DoubleSide, depthWrite: false }));
      parts.spinner.add(parts.wedge);
      parts.ring = new T.Mesh(new T.TorusGeometry(1, 0.035, 6, 72), new T.MeshBasicMaterial({ color: profile.accent, transparent: true, depthWrite: false }));
      parts.ring.rotation.x = -Math.PI / 2; parts.ring.position.y = 0.02; parts.scanner.add(parts.ring);
      parts.blink = new T.Mesh(new T.SphereGeometry(0.11, 12, 8), new T.MeshBasicMaterial({ color: profile.accent, transparent: true }));
      parts.blink.position.set(0, 0.16, 0); parts.scanner.add(parts.blink);
      parts.ticks = this.plan.bearings.map(fraction => {
        const tickMesh = new T.Mesh(new T.BoxGeometry(0.34, 0.08, 0.1), new T.MeshBasicMaterial({ color: profile.ink }));
        const angle = fraction * 2 * Math.PI; tickMesh.position.set(1.18 * Math.cos(angle), 0.03, 1.18 * Math.sin(angle)); tickMesh.rotation.y = -angle;
        parts.scanner.add(tickMesh); return tickMesh;
      });
      const points = (count, size, colors) => {
        const geometry = new T.BufferGeometry();
        geometry.setAttribute('position', new T.Float32BufferAttribute(new Float32Array(count * 3), 3));
        if (colors) geometry.setAttribute('color', new T.Float32BufferAttribute(colors, 3));
        const item = new T.Points(geometry, new T.PointsMaterial({ color: colors ? 0xffffff : profile.accent, vertexColors: !!colors, size, transparent: true }));
        scene.add(item); return item;
      };
      parts.packets = points(36, 0.22);
      const palette = [profile.accent, profile.accept, profile.ink].map(color => new T.Color(color));
      parts.confetti = points(24, 0.2, Array.from({ length: 24 }, (_, j) => palette[j % 3].toArray()).flat());
      parts.bloom = new T.Sprite(new T.SpriteMaterial({ map: this.canvasTexture(128, 128, ctx => {
        const glow = ctx.createRadialGradient(64, 64, 0, 64, 64, 64);
        glow.addColorStop(0, 'rgba(255,255,255,1)'); glow.addColorStop(1, 'rgba(255,255,255,0)'); ctx.fillStyle = glow; ctx.fillRect(0, 0, 128, 128);
      }), color: profile.accept, transparent: true, depthWrite: false }));
      parts.bloom.scale.set(5, 5, 1); scene.add(parts.bloom);
      parts.seal = new T.Sprite(new T.SpriteMaterial({ map: textures.seal, transparent: true, depthWrite: false })); scene.add(parts.seal);
      parts.halo = new T.Mesh(new T.TorusGeometry(1.75, 0.06, 8, 64), new T.MeshBasicMaterial({ color: profile.accept }));
      parts.halo.rotation.x = -Math.PI / 2; scene.add(parts.halo);
      this.parts = parts;
    }
    position(object, point, y = 0) { const w = this.world(point); object.position.set(w.x, y, w.z); }
    render(state, profile, images) {
      const T = this.T, key = `${state.recipe}:${state.style}`;
      if (this.key !== key) { this.build(state.recipe, profile, images); this.key = key; }
      const p = this.parts, k = p.k, w = this.stage.clientWidth, h = this.stage.clientHeight;
      if (w !== this.width || h !== this.height) { this.renderer.setSize(w, h, false); this.width = w; this.height = h; }
      const view = state.camera, distance = Math.max(1, 1.55 / (w / h));
      this.camera.aspect = w / h; this.camera.fov = view.fov;
      this.camera.position.set(view.tx + (view.x - view.tx) * distance, view.y * distance, view.tz + (view.z - view.tz) * distance);
      this.camera.lookAt(view.tx, 1.3, view.tz); this.camera.updateProjectionMatrix(); this.camera.updateMatrixWorld();
      if (p.water) p.water.uniforms.u_progress.value = 0.42 + 0.18 * Math.sin(state.time * 0.32);
      p.proof.uniforms.u_progress.value = state.candidate.revision;
      p.routes.intake.geometry.setDrawRange(0, Math.round(48 * state.routes.intake));
      p.routes.exit.geometry.setDrawRange(0, Math.round(48 * state.routes.exit));
      state.probes.forEach((probe, i) => {
        p.routes.probes[i].geometry.setDrawRange(0, Math.round(48 * probe.drawn));
        p.routes.probes[i].material.opacity = probe.drawn >= 1 ? 0.15 : 0.4;
        const group = p.probes[i], badge = group.userData.badge, dim = 1 - (p.cinematic ? 0.35 : 0.55) * state.focus;
        this.position(group, probe, probe.lift * k);
        group.visible = probe.opacity > 0.01; group.scale.setScalar(Math.max(0.001, probe.scale));
        group.rotation.y = -probe.heading * DEG;
        badge.scale.set(p.cinematic ? 1.7 : 0.9, p.cinematic ? 1.7 : 0.9, 1);
        badge.material.opacity = probe.opacity * dim;
        badge.material.userData.focus.value = 7 * state.focus;
        (group.userData.solids || []).forEach(solid => { solid.material.opacity = probe.opacity * dim; });
        this.position(group.userData.contact, probe, 0.04); group.userData.contact.visible = group.visible;
      });
      const c = state.candidate;
      this.position(p.candidate, c);
      p.candidate.rotation.y = p.cinematic ? Math.atan2(this.camera.position.x - p.candidate.position.x, this.camera.position.z - p.candidate.position.z) : -c.heading * DEG;
      c.layers.forEach((layer, i) => {
        const holder = p.layers[i];
        holder.position.set(layer.dx / 55, layer.lift * (p.cinematic ? 0.9 : 0.8), -layer.dy / 55 * 0.6);
        holder.rotation.set(layer.rx * DEG, layer.ry * DEG, layer.rz * DEG);
      });
      c.echoes.forEach((echo, i) => {
        this.position(p.echoes[i], echo); p.echoes[i].visible = p.cinematic && echo.alpha > 0.01;
        p.echoes[i].material.opacity = echo.alpha;
      });
      const trail = p.trail.geometry.attributes.position;
      c.echoes.forEach((echo, i) => { const e = this.world(echo); trail.setXYZ(i, e.x, 0.08, e.z); });
      trail.needsUpdate = true; p.trail.geometry.computeBoundingSphere(); p.trail.visible = !p.cinematic && c.speed > 20;
      const s = state.scanner, lift = p.cinematic ? s.lift * 1.45 : s.lift;
      this.position(p.scanner, s, lift); p.scanner.scale.setScalar(s.scale);
      p.spinner.rotation.y = -s.angle * DEG;
      p.wedge.material.opacity = s.sweep * 0.8;
      p.ring.scale.setScalar(1 + s.ring * 1.8); p.ring.material.opacity = s.ringAlpha;
      p.blink.material.opacity = s.blink;
      p.pedestal.visible = s.travel < 0.98;
      p.ticks.forEach((tickMesh, i) => tickMesh.material.color.set(tone(profile, state.checks[i])));
      const packets = p.packets.geometry.attributes.position;
      state.packets.forEach((packet, i) => {
        const point = this.world(packet);
        packets.setXYZ(i, point.x, packet.alpha > 0.02 ? packet.lift * k : -50, point.z);
      });
      packets.needsUpdate = true; p.packets.geometry.computeBoundingSphere();
      const confetti = p.confetti.geometry.attributes.position;
      state.confetti.forEach((piece, i) => {
        const point = this.world(piece);
        confetti.setXYZ(i, point.x, piece.alpha > 0.02 ? piece.lift * k : -50, point.z);
      });
      confetti.needsUpdate = true; p.confetti.geometry.computeBoundingSphere();
      const cap = c.layers[2], top = { x: c.x + cap.dx, y: c.y + cap.dy };
      const sealY = (c.capLift + 1.9) * (p.cinematic ? 1.45 : 1);
      this.position(p.seal, top, sealY); p.seal.scale.setScalar(Math.max(0.001, state.seal.scale * (p.cinematic ? 1.3 : 1.1)));
      p.seal.visible = state.seal.scale > 0.001;
      this.position(p.bloom, top, sealY); p.bloom.material.opacity = state.seal.bloom; p.bloom.visible = state.seal.bloom > 0.001;
      this.position(p.halo, c, 0.12); p.halo.visible = !p.cinematic && state.accepted; p.halo.scale.setScalar(Math.max(0.001, state.seal.scale));
      p.scene.fog.density = 0.012 + (p.cinematic ? 0 : 0.02 * state.focus);
      this.renderer.render(p.scene, this.camera);
      // Project the candidate's bounds for the DOM tracking bracket.
      const base = this.world(c), height = p.cinematic ? 2.9 : 1.6;
      let x0 = 1, y0 = 1, x1 = 0, y1 = 0;
      for (const [dx, dy, dz] of [[-1.3, 0, -0.8], [1.3, 0, -0.8], [-1.3, 0, 0.8], [1.3, 0, 0.8], [-1.3, height, -0.8], [1.3, height, -0.8], [-1.3, height, 0.8], [1.3, height, 0.8]]) {
        const v = new T.Vector3(base.x + dx, dy, base.z + dz).project(this.camera);
        const x = (v.x + 1) / 2, y = (1 - v.y) / 2;
        x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y);
      }
      return { x0, y0, x1, y1 };
    }
    dispose() {
      if (!this.parts) return;
      const materials = new Set();
      this.parts.scene.traverse(object => { object.geometry?.dispose(); [].concat(object.material || []).forEach(m => materials.add(m)); });
      materials.forEach(material => material.dispose());
      (this.owned || []).forEach(texture => texture.dispose());
      this.parts = null;
    }
    destroy() { this.canvas.removeEventListener('webglcontextlost', this.lost); this.dispose(); this.renderer.dispose(); }
  }
  return Object.freeze({ Engraving, Spatial, Overlay });
})();
