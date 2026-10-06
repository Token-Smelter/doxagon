/* Starter 2 of 3 — your own Three scene, borrowing helpers and the host.
 * Keep whatever you write by hand (here, a custom point cloud); take only the helpers you want.
 * Preview: preview_scene.py --scene helpers-scene.js
 */
(() => {
  const T = DoxMotionLib, K = DoxStageKit(T), root = document.querySelector('[data-stage]');
  const canvas = root.appendChild(document.createElement('canvas'));
  canvas.style.cssText = 'display:block;width:100%;height:100%';
  const renderer = new T.WebGLRenderer({ canvas, antialias: true });
  renderer.shadowMap.enabled = true;
  renderer.toneMapping = K.toneMapping('neutral');
  const scene = new T.Scene(), camera = new T.PerspectiveCamera(26, 1, 0.1, 50);
  scene.background = new T.Color('#f6f4ee');

  // Helpers: a filleted plinth in clay, studio light, reflections and a soft shadow.
  const plinth = new T.Mesh(K.shape('cylinder', [1.1, 1.2, 0.18, 64], { rounded: true }), K.surface('clay', { color: '#ddd6ca' }));
  plinth.castShadow = plinth.receiveShadow = true;
  scene.add(plinth);
  K.light(scene, 'soft', { extent: 2 });
  K.environment(renderer, scene, 0.2);
  K.ground(scene, { y: -0.09, opacity: 0.25 });

  // Hand-written: a cloud of points that gathers into a ring. Nothing here comes from the kit.
  const count = 600, seeds = Array.from({ length: count }, (_, i) => [Math.sin(i * 12.9898) * 43758.5453 % 1, Math.sin(i * 78.233) * 12543.1 % 1]);
  const positions = new Float32Array(count * 3), cloud = new T.BufferGeometry();
  cloud.setAttribute('position', new T.BufferAttribute(positions, 3));
  scene.add(new T.Points(cloud, new T.PointsMaterial({ color: '#2f6db5', size: 0.035 })));
  const box = new T.Box3(new T.Vector3(-1.3, -0.1, -1.3), new T.Vector3(1.3, 1.2, 1.3));

  const stateAt = t => ({ gather: Math.min(1, Math.max(0, (t - 0.5) / 2.5)), spin: t * 0.4 });
  DoxHost.attach(root, {
    name: 'starter-helpers', holds: [0, 3, 5], stateAt,
    draw: (s, frame) => {
      seeds.forEach(([a, b], i) => {
        const angle = (i / count) * Math.PI * 2 + s.spin, loose = 1 - s.gather;
        positions.set([Math.cos(angle) * (0.8 + a * loose), 0.5 + b * loose * 0.6, Math.sin(angle) * (0.8 + a * loose)], i * 3);
      });
      cloud.attributes.position.needsUpdate = true;
      renderer.setPixelRatio(frame.pixelRatio);
      renderer.setSize(frame.width, frame.height, false);
      K.fit(camera, box, { elevation: 0.5, aspect: frame.width / frame.height });
      K.sync(scene, frame);
      renderer.render(scene, camera);
    },
  });
})();
