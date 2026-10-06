# Sample skins

**Two generated images that show how an image becomes a skin on a 3D part: one repeats as a tile, one wraps around the shape.** These are teaching samples, not house art. For a real document, generate skins that suit its subject through the document's own image assets ([image components](./../../../reference/image-components.md)).

| File | Mode | Source | Processing |
|---|---|---|---|
| `engraved-lines.png` | Tile, tinted | Gemini `gemini-3.1-flash-image-preview`, 2K, 1:1, 2026-10-06; prompt below | Brightness keyed to alpha (knee 48–210), white ink, 1024 × 1024 PNG. Edges wrap: seam differences 0.96 left–right and 0.62 top–bottom of the interior average |
| `harbour-wrap.jpg` | Wrap, as-is | Gemini `gemini-3.1-flash-image-preview`, 2K, 21:9, 2026-10-06; prompt below | Resized to 2048 × 869, JPEG quality 86 |

The tile asked for guilloché and came back as looser interwoven wave lines with a few soft patches; it is kept as generated. Gemini returns no real transparency, so the tile was requested light-on-black and keyed. That works with any provider.

## Prompts

`engraved-lines.png`:

> A seamless, tileable square texture of fine guilloché engraving linework: the engine-turned pattern found under the translucent enamel of a watch dial or on a precision instrument panel. Interlaced, evenly spaced wave lines form one continuous woven lattice across the whole square. Thin, crisp, pure white (#FFFFFF) lines of uniform weight on a solid, pure black (#000000) background. Nothing else: no shading, no gradients, no glow, no metal or paper texture, no noise, no vignette, no border, no text. Flat and orthographic, viewed straight on. The pattern must repeat seamlessly in both directions: the left edge continues exactly into the right edge, and the top edge into the bottom edge.

`harbour-wrap.jpg`:

> A wide panoramic illustration designed as a product wrap: a continuous harbour at dawn in a flat screen-print style. Calm water with long horizontal ripples, small cargo ships, dockside cranes and a lighthouse on a low headland, soft layered hills, a pale gradient sky. Limited palette of five flat inks: deep navy, teal, warm sand, coral and off-white. Large, simple shapes that stay readable when small; no fine detail. Spread the composition evenly across the whole width, with no single centred subject. Horizon at about 60% of the height. No text, no logos, no border, no frame, no vignette.
