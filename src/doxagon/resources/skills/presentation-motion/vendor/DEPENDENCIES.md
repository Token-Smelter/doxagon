# Pinned animation dependencies

**The kit uses existing animation libraries; it does not ship another presenter or a custom frame-integrating animation engine.** The browser receives the pinned files inline, with notices intact.

| Dependency | Version / revision | Included use | Terms |
|---|---|---|---|
| GSAP | 3.14.2 | Paused timeline, MotionPath, MorphSVG, DrawSVG | [GSAP Standard License](./GSAP-LICENSE.txt), not MIT or Apache; retain notices and review restrictions on competing visual animation builders |
| Three.js | 0.180.0 | The whole namespace, plus the official room environment, rounded box and wide-line add-ons | [MIT](./THREE-LICENSE.txt) |
| HyperFrames | 65d66cb2c3494e498780897eb4a371ee05e27735 | Three adapter, seek dispatch, shader registry | [Apache-2.0](./hyperframes/LICENSE) |
| Typefaces | Pinned WOFF2 files | Contrastive sample profiles | [Font sources](./fonts/README.md) and adjacent SIL OFL licenses |

[The manifest](./manifest.json) records local hashes and upstream URLs. GSAP products retain their own licensing; their presence does not make them Apache-licensed platform code. This code-authored example is not a legal determination about future no-code editor features.

## Rebuild the GPU bundle

Run from this `vendor` directory, using the project's installed esbuild (recorded build: 0.21.5):

```bash
esbuild deps.ts --bundle --format=iife --global-name=DoxMotionLib --minify \
  --target=es2020 --legal-comments=inline --alias:three=./three.module.js --outfile=motion-deps.min.js
```

[Entry module](./deps.ts) exports the whole Three namespace, five unmodified add-ons from `three/examples/jsm` ([three-addons](./three-addons/environments/RoomEnvironment.js)), HyperFrames' adapter and seek dispatch, plus the shader functions. The alias points the add-ons' `three` imports at the vendored module. Scenes never need a workaround for a missing export. Sources are present for reproducibility; the sample builder inlines only the compiled bundle and four GSAP files. It needs no bundler or download at runtime.

The kit adapts the upstream shader to a Three plane by supplying `v_uv` from geometry UVs and Three's projection/model-view matrices ([renderer](./../kit/renderers.js:274)). It does not copy HyperFrames' player, scheduler or video exporter. Built-in CPU calculations are algebraic poses from timeline time, not a physics integrator.

The sources are unmodified upstream modules apart from the local entry module. Unused shaders are retained by the upstream registry; a future measured size optimization can reduce that closure. No full-player interoperability, exported-video result or physical-device frame rate is asserted by these files.
