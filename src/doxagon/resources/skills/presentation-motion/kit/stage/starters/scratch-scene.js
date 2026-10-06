/* Starter 3 of 3 — entirely your own: raw Three, your own loop. The only obligation is the contract:
 * expose holds, stateAt(t) and seek(t) on the root so the document and the preview can drive and check it.
 * Preview: preview_scene.py --scene scratch-scene.js
 */
(() => {
  const T = DoxMotionLib, root = document.querySelector('[data-stage]');
  const canvas = root.appendChild(document.createElement('canvas'));
  canvas.style.cssText = 'display:block;width:100%;height:100%';
  const renderer = new T.WebGLRenderer({ canvas, antialias: true });
  const scene = new T.Scene(), camera = new T.PerspectiveCamera(35, 1, 0.1, 50);
  scene.background = new T.Color('#101b2a');
  camera.position.set(0, 1.7, 5.8);
  camera.lookAt(0, 0, 0);
  const knot = new T.Mesh(new T.TorusKnotGeometry(0.8, 0.24, 180, 24), new T.MeshNormalMaterial());
  scene.add(knot);

  const holds = [0, 2, 4];
  const stateAt = t => ({ turn: t * 0.6, squash: 1 - 0.35 * Math.sin(Math.min(t, 4) / 4 * Math.PI) });
  let time = 0;
  function render() {
    const width = root.clientWidth, height = root.clientHeight, ratio = Math.min(devicePixelRatio, 1.5);
    if (!width || !height) return;
    if (canvas.width !== Math.round(width * ratio)) { renderer.setPixelRatio(ratio); renderer.setSize(width, height, false); }
    const s = stateAt(time);
    knot.rotation.set(0.3, s.turn, 0);
    knot.scale.set(1, s.squash, 1);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    renderer.render(scene, camera);
    root.dataset.doxReady = 'true';
  }
  new ResizeObserver(render).observe(root);
  DoxHost.expose(root, {
    root, holds, stateAt,
    seek: t => { time = t; requestAnimationFrame(render); },
    go: index => { time = holds[index]; requestAnimationFrame(render); },
    get time() { return time; },
  }, 'starter-scratch');
})();
