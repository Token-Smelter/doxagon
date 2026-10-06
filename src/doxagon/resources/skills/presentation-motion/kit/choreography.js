/* Scene meaning as a pure function of time. Renderers only draw what this returns. */
window.DoxMotionChoreography = (() => {
  'use strict';
  const clamp = (value, lo = 0, hi = 1) => Math.max(lo, Math.min(hi, value));
  const lerp = (a, b, p) => a + (b - a) * p;
  const COMPONENTS = ['base', 'core', 'cap', 'probe', 'scanner', 'seal'];
  const STATION = { x: 470, y: 380 };
  const SCANNER_HOME = { x: 800, y: 500 };
  const LEDGER = { x: 985, y: 260, lift: 3.6 };
  const PATHS = {
    intake: 'M150,470 C230,540 380,520 470,380',
    exit: 'M470,380 C560,300 760,250 930,330',
    scanner: 'M800,500 C760,610 540,580 470,380',
    probes: ['M-60,190 C90,160 230,300 329,344', 'M560,-70 C620,40 470,170 521,281', 'M1150,240 C960,170 760,380 611,344']
  };
  // Fractions of one scanner revolution at which each criterion is read.
  const BEARINGS = [1 / 12, 5 / 12, 9 / 12];
  const ACCEPTED_AT = 34.5;
  // The hold at 29 s shows the revision before any recheck reading arrives.
  const RECHECK_AT = 29.2;

  // A damped spring evaluated from elapsed time: overshoot without an integrator.
  function spring(t, omega = 8.8, damping = 0.82) {
    if (t <= 0) return 0;
    const wd = omega * Math.sqrt(1 - damping * damping);
    return 1 - Math.exp(-damping * omega * t) * (Math.cos(wd * t) + damping * omega / wd * Math.sin(wd * t));
  }
  function track(t, keys, omega, damping) {
    let value = keys[0][1];
    for (let i = 1; i < keys.length; i++) value += (keys[i][1] - keys[i - 1][1]) * spring(t - keys[i][0], omega, damping);
    return value;
  }
  // Explicit from-states on every leg keep backward seeks equal to forward playback.
  function legs(timeline, target, initial, segments) {
    Object.assign(target, initial);
    let previous = { ...initial };
    for (const [start, duration, next, ease = 'power2.inOut'] of segments) {
      const from = Object.fromEntries(Object.keys(next).map(key => [key, previous[key]]));
      timeline.fromTo(target, from, { ...next, duration, ease, immediateRender: false }, start);
      previous = { ...previous, ...next };
    }
  }
  function crossings(lower, upper, offset, count) {
    const first = Math.ceil(lower - offset);
    return Array.from({ length: count }, (_, k) => first + k + offset).filter(c => c <= upper);
  }

  function create(config) {
    const { gsap, MotionPathPlugin: paths } = window;
    if (config.checks.length !== BEARINGS.length) throw new Error('The sample scene reads exactly three criteria');
    const end = config.holds[4];
    const ease = gsap.parseEase('power2.inOut');
    const outEase = gsap.parseEase('power3.out');
    const raw = data => paths.getRawPath(data);
    const at = (path, progress) => paths.getPositionOnPath(path, clamp(progress), true);
    const routes = { intake: raw(PATHS.intake), exit: raw(PATHS.exit), scanner: raw(PATHS.scanner), probes: PATHS.probes.map(raw) };
    const sample = path => Array.from({ length: 48 }, (_, i) => at(path, i / 47));
    const samples = { intake: sample(routes.intake), exit: sample(routes.exit), probes: routes.probes.map(sample) };

    const timeline = gsap.timeline({ paused: true });
    const camera = {}, drive = {}, focus = {}, revision = {}, ledger = {}, ambient = { breathe: 0 };
    // Multi-phase camera: establish, follow, inspect, push in, recheck, release.
    legs(timeline, camera, { x: -2, y: 15, z: 24, tx: -2, tz: 1.5, fov: 40, fx: 540, fy: 330, zoom: 1 }, [
      [0.6, 7.0, { x: 2, y: 11, z: 17, tx: -1, tz: 0.5, fov: 38, fx: 470, fy: 360, zoom: 1.16 }],
      [8.4, 3.6, { x: 8, y: 13, z: 15, tx: 0, tz: 0, fov: 40, fx: 540, fy: 330, zoom: 1.04 }],
      [18.4, 2.6, { x: -3, y: 8, z: 11, tx: -1.2, tz: 0.3, fov: 36, fx: 480, fy: 330, zoom: 1.3 }],
      [29.0, 2.0, { x: 6, y: 12, z: 15, tx: 0.5, tz: 0, fov: 40, fx: 560, fy: 320, zoom: 1.06 }],
      [35.0, 5.0, { x: 10, y: 16, z: 22, tx: 3.5, tz: -0.5, fov: 42, fx: 700, fy: 300, zoom: 1.0 }]
    ]);
    // The loop sub-component's master: an eased cycle counter (idle, spin-up, cruise, recheck, lock).
    legs(timeline, drive, { cycles: 0 }, [
      [0, 8.2, { cycles: 0.5 }, 'none'],
      [8.2, 3.8, { cycles: 2.4 }, 'power2.in'],
      [12, 17, { cycles: 19.4 }, 'none'],
      [29, 5, { cycles: 26.9 }, 'none'],
      [34, 4.2, { cycles: 29 }, 'power3.out']
    ]);
    legs(timeline, focus, { value: 0 }, [[18.6, 1.6, { value: 1 }, 'power2.out'], [27.6, 1.2, { value: 0 }]]);
    legs(timeline, revision, { value: 0 }, [[21, 4.5, { value: 1 }]]);
    legs(timeline, ledger, { expand: 0 }, [[34.6, 1.2, { expand: 1 }, 'power3.out']]);
    // Idle breathing as a nested child with finite repeats; GSAP resolves repeats from parent time.
    const idle = gsap.timeline({ repeat: Math.round(end / 4) - 1 });
    idle.fromTo(ambient, { breathe: 0 }, { breathe: 1, duration: 2, ease: 'sine.inOut' })
      .fromTo(ambient, { breathe: 1 }, { breathe: 0, duration: 2, ease: 'sine.inOut', immediateRender: false });
    timeline.add(idle, 0);
    timeline.totalTime(end, true).totalTime(0, true);

    // One authored revolution of the looping scanner. Its playhead is set from drive.cycles.
    const rotor = { angle: 0, ring: 0.15, ringAlpha: 0, blink: 0 };
    const loop = gsap.timeline({ paused: true });
    loop.fromTo(rotor, { angle: 0 }, { angle: 360, duration: 1, ease: 'none' }, 0)
      .fromTo(rotor, { ring: 0.15 }, { ring: 1, duration: 0.7, ease: 'power2.out' }, 0.05)
      .fromTo(rotor, { ringAlpha: 0 }, { ringAlpha: 0.85, duration: 0.08, ease: 'none' }, 0)
      .fromTo(rotor, { ringAlpha: 0.85 }, { ringAlpha: 0, duration: 0.67, ease: 'power1.in', immediateRender: false }, 0.08)
      .fromTo(rotor, { blink: 0 }, { blink: 1, duration: 0.04, ease: 'none' }, 0.5)
      .fromTo(rotor, { blink: 1 }, { blink: 0, duration: 0.04, ease: 'none', immediateRender: false }, 0.58);
    loop.progress(1, true).progress(0, true);

    // Readings happen where the sweep crosses a bearing; their times follow from linear legs.
    const inspection = BEARINGS.map(f => crossings(2.4, 8.4, f, 6));
    const recheck = BEARINGS.map(f => crossings(19.75, 26.9, f, 6));
    const packets = [];
    BEARINGS.forEach((_, i) => {
      inspection[i].forEach(c => packets.push({ probe: i, emit: 12 + (c - 2.4) }));
      recheck[i].forEach(c => packets.push({ probe: i, emit: 29 + (c - 19.4) / 1.5 }));
    });
    const reads = (cycles, list) => list.filter(c => c <= cycles).length;
    const changeAt = 12 + (inspection[1][2] - 2.4);
    const fixedAt = 29 + (recheck[1][5] - 19.4) / 1.5;

    function candidateAt(time) {
      const leaving = time >= 35.5;
      const p = leaving ? ease(clamp((time - 35.5) / 4.1)) : ease(clamp((time - 0.6) / 6.8));
      return at(leaving ? routes.exit : routes.intake, p);
    }
    function layersAt(time) {
      const e = clamp(track(time, [[0, 0], [9, 1], [18.6, 0.45], [25.4, 0], [29.4, 0.55], [33.2, 0]]), -0.1, 1.12);
      // Index-derived offsets: scatter into depth and tumble, then reassemble on registered layers.
      return [0, 1, 2].map(i => ({
        dx: [-110, 10, 120][i] * e, dy: [34, -46, -20][i] * e, lift: [0, 1.4, 2.8][i] * e,
        rx: [18, -24, 30][i] * e, ry: [-30, 20, 40][i] * e, rz: [-12, 6, 15][i] * e
      }));
    }
    function probeAt(i, time) {
      const start = 8.6 + i * 0.18;
      const point = at(routes.probes[i], outEase(clamp((time - start) / 3.2)));
      const retreat = ease(clamp((time - 35.8) / 2));
      const away = { x: point.x - STATION.x, y: point.y - STATION.y };
      return {
        x: point.x + away.x * 0.6 * retreat, y: point.y + away.y * 0.6 * retreat, heading: point.angle,
        // Sine-wave loop read directly from time, phase-offset per actor.
        lift: 1.5 + 0.12 * Math.sin(2 * Math.PI * time / 2.6 + i * 2.1),
        scale: clamp(spring(time - start, 9, 0.55), 0, 1.3),
        opacity: clamp((time - start) / 0.4) * (1 - retreat),
        drawn: clamp((time - start) / 3.2)
      };
    }

    function compute(time) {
      time = clamp(time, 0, end);
      timeline.totalTime(time, true);
      const cycles = drive.cycles;
      loop.progress(((cycles % 1) + 1) % 1, true);
      const phase = config.holds.slice(1).filter(n => time >= n - 0.001).length;
      const hold = config.holds.findIndex(n => Math.abs(time - n) < 0.001);
      const candidate = candidateAt(time);
      const previous = candidateAt(time - 0.05);
      const speed = Math.hypot(candidate.x - previous.x, candidate.y - previous.y) / 0.05;
      const layers = layersAt(time);
      const capLift = 1.1 + layers[2].lift;
      const attach = { x: candidate.x + layers[2].dx, y: candidate.y + layers[2].dy, lift: capLift + 0.45 };
      // Sub-component becomes part of the object: travel from its station, then ride the cap layer.
      const travel = ease(clamp((time - 18.4) / 5));
      const pathPoint = at(routes.scanner, travel);
      const docked = time >= 23.4;
      const scanner = {
        x: docked ? attach.x : pathPoint.x + (attach.x - STATION.x) * travel,
        y: docked ? attach.y : pathPoint.y + (attach.y - STATION.y) * travel,
        lift: docked ? attach.lift : lerp(0.35, attach.lift, travel) + 2 * Math.sin(Math.PI * travel),
        cycles, angle: rotor.angle, ring: rotor.ring, travel, docked, scale: lerp(1, 0.55, travel),
        locked: time >= 38.2,
        ringAlpha: rotor.ringAlpha * (time < 8.2 ? 0.35 : 1), blink: rotor.blink,
        sweep: time < 8.2 || time >= 38.2 ? 0.15 : 0.45
      };
      const probes = [0, 1, 2].map(i => probeAt(i, time));
      const checks = config.checks.map((name, i) => {
        const found = reads(cycles, inspection[i]), again = time >= RECHECK_AT ? reads(cycles, recheck[i]) : 0;
        let verdict = 'Pending';
        if (time >= RECHECK_AT) verdict = again >= 6 ? 'Pass' : 'Rechecking';
        else if (i === 1 && time >= changeAt) verdict = 'Change';
        else if (found >= 6) verdict = 'Pass';
        else if (found > 0) verdict = 'Reading';
        return { name, readings: time >= RECHECK_AT ? again : found, of: 6, verdict, bearing: BEARINGS[i] };
      });
      const packetState = packets.map(packet => {
        const p = (time - packet.emit) / 1.5;
        const source = probeAt(packet.probe, packet.emit);
        const q = clamp(p);
        const mid = { x: (source.x + LEDGER.x) / 2, y: (source.y + LEDGER.y) / 2 - 60 };
        const bez = (a, b, c) => (1 - q) * (1 - q) * a + 2 * (1 - q) * q * b + q * q * c;
        return {
          x: bez(source.x, mid.x, LEDGER.x), y: bez(source.y, mid.y, LEDGER.y),
          lift: bez(source.lift, 4.6, LEDGER.lift), alpha: p >= 0 && p < 1 ? Math.sin(Math.PI * p) * 0.95 : 0
        };
      });
      // Ballistic burst from a fixed pool; every particle is a closed-form function of elapsed time.
      const burstAge = time - ACCEPTED_AT;
      const origin = candidateAt(ACCEPTED_AT);
      const confetti = Array.from({ length: 24 }, (_, j) => {
        const angle = j * 2.399963, speedJ = 70 + (j * 7 % 5) * 18, rise = 3 + (j % 4) * 0.6;
        const age = clamp(burstAge, 0, 2.4);
        return {
          x: origin.x + Math.cos(angle) * speedJ * age, y: origin.y + Math.sin(angle) * speedJ * age * 0.5,
          lift: Math.max(0, 2.2 + rise * age - 3 * age * age), spin: j * 37 + age * 420 * (j % 2 ? 1 : -1),
          alpha: burstAge >= 0 && burstAge < 2.4 ? 1 - clamp((burstAge - 1.6) / 0.8) : 0, tone: j % 3
        };
      });
      const echoes = [1, 2, 3, 4].map(k => {
        const p = candidateAt(time - k * 0.09);
        return { x: p.x, y: p.y, alpha: 0.34 * (1 - k / 5) * clamp(speed / 200) };
      });
      const accepted = time >= ACCEPTED_AT;
      const readTotal = checks.reduce((sum, check) => sum + check.readings, 0);
      return {
        time, phase, cue: hold < 0 ? null : config.cues[hold], label: config.labels[phase],
        // Copy named fields only: GSAP keeps a private cache on tween targets.
        camera: { x: camera.x + 0.18 * Math.sin(0.41 * time), y: camera.y + 0.1 * Math.sin(0.29 * time + 1),
          z: camera.z, tx: camera.tx, tz: camera.tz, fov: camera.fov, fx: camera.fx, fy: camera.fy, zoom: camera.zoom },
        candidate: { x: candidate.x, y: candidate.y, heading: candidate.angle, speed, layers, echoes,
          revision: revision.value, capLift, rejected: time >= changeAt && time < fixedAt },
        scanner, probes, checks, packets: packetState, confetti,
        focus: focus.value, accepted,
        status: accepted ? 'Accepted' : time >= RECHECK_AT ? 'Revised · rechecking' : time >= 25.5 ? 'Revised · awaiting recheck' :
          time >= changeAt ? 'Change requested' : 'Candidate · not approved',
        seal: { scale: accepted ? clamp(spring(time - ACCEPTED_AT, 9, 0.5), 0, 1.4) : 0,
          bloom: 0.42 * clamp((time - ACCEPTED_AT) / 0.8) * (0.78 + 0.22 * ambient.breathe) },
        ledger: { expand: ledger.expand, counter: readTotal, of: 18, mode: time >= RECHECK_AT ? 'Recheck' : 'Readings' },
        station: STATION, scannerHome: SCANNER_HOME, ledgerPost: LEDGER, breathe: ambient.breathe,
        routes: { intake: clamp((time - 0.6) / 6.8), exit: clamp((time - 35.5) / 4.1) }
      };
    }
    return { timeline, compute, end, components: COMPONENTS, paths: PATHS, samples, bearings: BEARINGS,
      station: STATION, scannerHome: SCANNER_HOME, ledgerPost: LEDGER, motif: config.motif,
      destroy() { timeline.kill(); loop.kill(); } };
  }
  return Object.freeze({ create, components: COMPONENTS });
})();
