/* Starter: skins — a document image laid onto parts, as a continuous wrap or a repeating tinted tile.
 * Images are ordinary <img> elements in the document (an image slot, or the sample skins the preview embeds).
 * Preview: preview_scene.py --scene skin-scene.js
 */
(() => {
  window.scene = DoxStage.mount(document.querySelector('[data-stage]'), {
    name: 'starter-skin',
    look: 'satin',                       // skins need a lit look: ink, satin, clay, gloss, metal or cel
    palette: { crate: '#ebe7dc', drum: '#1d3766', band: '#c9971c' },
    parts: [
      // Wrap: one image around the box, never stretched; the join sits at the back, the top takes a sampled colour.
      { id: 'crate', shape: 'box', size: [1.3, 0.62, 0.56], role: 'crate', at: [-0.55, 0, 0],
        skin: { image: 'skin-harbour-wrap', mode: 'wrap' } },
      // Tile: repeats at 0.35 world units; light-on-black art keyed and tinted to the palette.
      { id: 'drum', shape: 'cylinder', size: [0.34, 0.34, 0.9, 64], role: 'drum', at: [0.75, 0.14, 0],
        skin: { image: 'skin-engraved-lines', mode: 'tile', size: 0.35, tint: { base: '#1d3766', ink: '#dfe7f6', strength: 0.8 } } },
      { id: 'band', shape: 'torus', size: [0.345, 0.025, 12, 96], role: 'band', parent: 'drum', rotate: [Math.PI / 2, 0, 0], at: [0, 0.28, 0] },
    ],
    holds: [0, 3],
    cues: ['front', 'turned'],
    pose: t => ({ model: { rotate: [0, -0.45 - 0.5 * Math.min(1, t / 3), 0] } }),
  });
})();
