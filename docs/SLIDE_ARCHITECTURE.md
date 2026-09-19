# Slide Architecture

Examples are fictional. This describes the legacy slide format; see
[document authoring](document-authoring.md) for selected single-page documents.

Image generation goes through the adapter `DOXAGON_IMAGE_GENERATOR` names,
under [image-providers.md](./image-providers.md). The `factory/` scripts shown
below predate that contract and are examples to adapt, not a supported route.

## Overview

This document describes the slide structure that separates:
- **Slide content** (text, speaker notes, metadata) in `slide.md`
- **Image definitions** (visual prompts, styles, generation config) in `images/{id}/definition.md`

## Directory Structure

Slides live within the presentation output:

```
theses/{name}/
├── config.yaml                       # Shared metadata (name, audience, description)
├── thesis/
│   └── core.md                       # The canonical argument
├── ideation/
│   ├── research/                     # Source material
│   └── notes/                        # Working thoughts
└── outputs/
    └── presentation/
        ├── config.yaml               # Presentation rules (timing, constraints, metaphors)
        ├── styles/                   # Visual style definitions
        │   └── html/
        │       └── global.css        # Shared CSS injected into all HTML slides
        ├── build/                    # Compiled outputs
        └── slides/
            └── {number}-{slug}/
                ├── slide.md          # Content + image relationships
                └── images/
                    └── {image-id}/
                        ├── definition.md     # Visual description, styles, config
                        ├── sources/          # Reference images for THIS image
                        └── outputs/          # Generated images
```

### Single Image Slides (Common Case)

Most slides have one image. Use `main` as the default image ID:

```
outputs/presentation/slides/07-star-map/
├── slide.md
└── images/
    └── main/
        ├── definition.md
        ├── sources/
        └── outputs/
```

### Multi-Image Slides

Slides can have multiple images with distinct IDs:

```
outputs/presentation/slides/07-star-map/
├── slide.md
└── images/
    ├── main/
    │   ├── definition.md
    │   └── outputs/
    └── comparison/
        ├── definition.md
        ├── sources/
        │   └── comparison-chart.png
        └── outputs/
```

## File Schemas

### slide.md

Contains all slide content and image relationships.

```yaml
---
layout: image              # image | html
animation: auto            # auto | manual (HTML)
text:
  title: "A Night at the Observatory"
  body: |
    Compare the star chart with the observation log.
speaker_notes: |
  Point out the telescope and describe the fictional observation.
doxai:
  - d-observe-stars
  - d-compare-charts
images:
  - id: main
    is_primary: true
    selected: outputs/selected.png
    placement: full-bleed
    purpose: Show the telescope and its field of view
  - id: comparison
    selected: outputs/selected.png
    placement: inset-right
    purpose: Compare a star chart with the main image
---
```

#### Layout Types

| Layout | Description | Build Output |
|--------|-------------|--------------|
| `image` | Static image slide (default) | Display bundle's selected image |
| `html` | Interactive/animated HTML slide | Headless Playwright screenshot; falls back to display bundle |

#### Display Bundle (`is_primary`)

For image slides with multiple bundles, one bundle is the **display bundle** — its selected image appears in the audience display, presenter thumbnail, and PPTX output. Set `is_primary: true` on that bundle. If none marked, falls back to `images[0]`.

HTML slides don't need a display bundle — all bundles are peers, referenced by ID in the HTML via `data-image-id`.

### images/{id}/definition.md

Self-contained visual bundle. Does NOT contain slide-specific info.

```yaml
---
styles:
  - ink
config:
  versions: 3
  resolution: 2k
  aspect_ratio: '16:9'
sources:
  - reference-chart.png
custom_constraints: |
  Keep the telescope and horizon visible.
---

<illustration style="INK">
A telescope beneath a clear sky. Use the selected style's palette.
<rendered_text>Observatory</rendered_text>
</illustration>
```

### Semantic XML Tag Convention

Style tags like `<terminal_style>` or `<code_block>` are **semantic XML tags** that:
1. Wrap content with styling context
2. Link to style definitions via `style="NAME"` attribute
3. Nest naturally to show containment relationships

**Why**: The assembly process appends style definitions at the end. Semantic tags create explicit links between content and its style definition, with readable closing tags.

**Pattern**:
```xml
<semantic_tag style="STYLE_NAME">
Content that this style applies to...
</semantic_tag>
```

Each tag's `style="NAME"` corresponds to `name="NAME"` in the appended style definition.

**Tag naming convention**: Tags are semantic (describe what they are) rather than generic:
- `<terminal_style>` not `<style ref="TERMINAL">`
- `<code_block>` not `<style ref="CODE">`
- `<ascii_diagram>` not `<style ref="ASCII">`

### Config Resolution Options

| Resolution | 16:9 Size | 1:1 Size | Output Tokens |
|------------|-----------|----------|---------------|
| 1K | 1376x768 | 1024x1024 | 1120 |
| 2K | 2752x1536 | 2048x2048 | 1120 |
| 4K | 5504x3072 | 4096x4096 | 2000 |

## Separation of Concerns

| Concern | Lives in | Why |
|---------|----------|-----|
| Slide title, body text | slide.md `text:` | Narrative content |
| Speaker notes | slide.md `speaker_notes:` | Delivery content |
| Layout type, animation | slide.md `layout:`, `animation:` | Rendering mode |
| Linked doxai | slide.md `doxai:` | Epistemic grounding for slide |
| Display bundle | slide.md `images:` → `is_primary` | Which bundle shows in audience/PPTX |
| Image `purpose` | slide.md `images:` | Why *this slide* needs *this image* |
| Image `placement` | slide.md `images:` | Layout is a slide concern |
| Image `selected` | slide.md `images:` | Slide author chooses output |
| HTML content | slide.html | Interactive/animated rendering |
| Visual description | definition.md body | What to generate |
| Styles, config | definition.md frontmatter | How to generate |
| Reference images | sources/ | Image-specific references |
| Generated outputs | outputs/ | Generation artifacts |

### Key Insight: `purpose` vs Description

- **Image description** (definition.md): "A dramatic cliff edge viewed from above..."
- **Slide purpose** (slide.md): "Visceral representation of the compute gap - audience should feel vertigo"

Same image, different semantic role. The purpose explains why this slide needs this image for its narrative.

## Config Hierarchy

```
theses/{name}/
├── config.yaml                      # Shared: name, audience, description, themes
└── outputs/presentation/
    └── config.yaml                  # Presentation-specific: timing, constraints, metaphors
```

When working on slides:
1. Read `outputs/presentation/config.yaml` for constraints
2. Constraints are **rules for working on this output** - not just build settings
3. Any operation (edit, rewrite, generate) must respect constraints

## Assembly Order for Prompt Generation

When generating `images/{id}/`, the assembly script wraps each section in semantic XML tags:

| Order | Section | XML Tag |
|-------|---------|---------|
| 0 | Rendered text rule (auto-injected) | `<rendered_text_rule>` |
| 1 | Global constraints | `<global_constraints>` |
| 2 | Palette (if diagram family) | `<color_system>` |
| 3 | Custom constraints | `<image_constraints>` |
| 4 | Visual description (body content with semantic tags) | `<visual_description>` |
| 5 | Style definitions | `<style_definitions>` |
| 6 | Generation settings | `<generation_settings>` |

**Output files** (in `images/{id}/outputs/`):
- `assembled_prompt.md` - Full prompt text
- `generation_config.json` - API parameters for image generation:
  ```json
  {
    "image_size": "4K",
    "aspect_ratio": "16:9",
    "source_images": ["/path/to/source1.png", "/path/to/source2.jpg"]
  }
  ```

Max 14 reference images total (style sources + image sources).

## Script Commands

```bash
# Assemble prompt + config for specific image
source .venv/bin/activate
python factory/scripts/generate_visuals.py --slide 07 --image main --output

# Generate image using the configured provider adapter (docs/image-providers.md)
"$DOXAGON_IMAGE_GENERATOR" \
    --prompt-file {outputs_dir}/assembled_prompt.md \
    --output {outputs_dir}/ \
    --image-size 4K --aspect-ratio 16:9 \
    --source {source1.png} --source {source2.jpg}

# Compile presentation (HTML slides auto-rendered via Playwright)
python factory/scripts/compile.py

# Render a single HTML slide to PNG (standalone, also called by compile.py)
python factory/scripts/render_html_slide.py \
    --slide-dir theses/{name}/outputs/presentation/slides/{slug} \
    --output rendered.png --width 1920 --height 1080
```

**Skills** (recommended):
- `visual-definition` - Full assembly + generation workflow
- `visual-concept-brainstorm` - Ideate visual concepts before writing definitions

## Constraints Reference

### Style Family Constraints

Styles are organized into families (e.g., `diagram/`, `3d/`, `terminal/`, `chart/`). Never combine styles from different families in one image:

- ❌ `styles: [diagram/base, 3d/characters/owl]`
- ✅ `styles: [diagram/base, diagram/vignette/characters/astronomer]`

### Style Prerequisites

Some styles require base styles. Check `Requires:` in each style's definition.md:

- ❌ `styles: [diagram/vignette/characters/astronomer]` (missing base)
- ✅ `styles: [diagram/base, diagram/vignette, diagram/vignette/characters/astronomer]`

### Assembly Order Implications

Prompt assembly is sequential - later styles can override earlier ones:

1. **Global constraints** - Applied first, set baseline rules
2. **Palette** - Defines colors; must be loaded before styles that reference colors
3. **Custom constraints** - Can override palette if needed
4. **Visual description** - Assumes all context from above is available
5. **Composed styles** - Detailed style bundles that refine or override
6. **Reference images** - Concrete examples

**Implication**: If you reference a color in step 4 that isn't defined in step 2, generation fails.

### Reference Image Quota

Maximum 14 reference images per image bundle:

```
Count = len(styles/*/sources/) + len(images/{id}/sources/)
```

If this sum exceeds 14, Gemini API quota is exceeded.

### Self-Contained Image Definitions

Image definitions must stand alone - don't reference slide context:

**Bad** (references slide-level context):
```yaml
---
styles: [diagram/base]
---
Shows the waterfall pattern from slide 7, with the observer from the previous slide.
```

**Good** (self-contained):
```yaml
---
styles: [diagram/base, diagram/vignette/characters/astronomer]
---
A waterfall diagram: nodes connected by downward arrows, each stage
labeled. A fictional astronomer points to each labeled stage.
```

The slide.md `purpose:` field explains the connection to the narrative.

### No Custom Colors in Prompts

Colors must come from the palette, not inline hex codes in definition.md:

- ❌ "Use #f4a261 for emphasis"
- ✅ "Use the primary accent color"

All colors are defined in `styles/global/palette/definition.md`.

## HTML Slides

Slides with `layout: html` render interactive/animated content instead of a static image.

### Filesystem

```
slides/search-architecture/
├── slide.md              # layout: html, animation: manual
├── slide.html            # Self-contained HTML fragment
└── images/
    ├── main/             # PPTX fallback (set is_primary if needed)
    ├── flow-diagram/     # Referenced in HTML
    └── query-result/     # Referenced in HTML
```

### HTML Convention

- **Rendering**: All HTML slides render in `<iframe srcdoc>` for complete JS/CSS/event isolation. Both full HTML documents (`<!DOCTYPE html>...`) and fragments are supported — fragments are wrapped automatically.
- **Image references**: `<img data-image-id="{bundle-id}" />` — resolved to asset URLs before iframe injection
- **Controller API**: `dox.slide.steps(N)`, `dox.slide.onStep(n, callback)`, `dox.slide.imageUrl(id)` — bridged into the iframe via `postMessage`
- **Animation modes**: `auto` (steps fire sequentially on entry) or `manual` (presenter advances)
- **Style scoping**: Not required (iframe provides isolation), but `.slide-{slug}` prefix is still a good convention for readability
- **Global styles**: `styles/html/global.css` is injected as `<style id="dox-global-styles">` into every HTML slide (both web UI and Playwright build). Use for CSS custom properties, shared fonts, and base classes. Individual slides override with local `<style>` blocks.

### Build Behavior

During `compile.py`, HTML slides are rendered to PNG via headless Playwright:

1. `slide.html` is read and `data-image-id` refs are resolved to local `file://` paths
2. A stub `dox.slide` API is injected (captures initial visual state, step 0)
3. Playwright screenshots the rendered page at 1920×1080
4. The screenshot is saved to `images/.rendered_slide.png` (regenerated each build)
5. If Playwright is unavailable, falls back to `find_slide_image()` (display bundle)

**Dependency**: `playwright` must be in dev dependencies and Chromium installed:
```bash
uv pip install -e ".[dev]" && playwright install chromium
```

## Design System Location

Each presentation's design system lives in `outputs/presentation/styles/README.md`:

```
theses/{name}/
├── CLAUDE.md                      # Points to outputs/presentation/styles/README.md
└── outputs/
    └── presentation/
        ├── config.yaml            # Constraints, timing, metaphors
        └── styles/
            ├── README.md          # Design system entry point
            ├── constraints/
            ├── global/
            └── {families}/
```

Do not create design documentation in the presentation root.
