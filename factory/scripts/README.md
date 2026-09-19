# Factory Scripts

Build and generation scripts for the presentation factory.

## Visual Generation

### generate_visuals.py

Assembles image generation prompts by concatenating style definitions.

```bash
# Assemble prompt for a single slide (by slug or number)
python3 factory/scripts/generate_visuals.py --slide title --output
python3 factory/scripts/generate_visuals.py --slide 14 --output

# Trace mode (print without writing)
python3 factory/scripts/generate_visuals.py --slide title --trace

# Specify presentation
python3 factory/scripts/generate_visuals.py --presentation observatory --slide 14 --output
```

Output: `slides/{slug}/images/main/outputs/assembled_prompt.md`

### generate_image_vertex.py

Generates images using Vertex AI Gemini 3 Pro Image Preview.

```bash
uv run factory/scripts/generate_image_vertex.py \
    --prompt-file path/to/assembled_prompt.md \
    --output path/to/outputs/
```

Requires: GCP auth via `gcloud auth login`

### batch_generate.py

Batch generates images for multiple slides in parallel.

```bash
# Generate all slides in a presentation
python3 factory/scripts/batch_generate.py --presentation observatory

# Generate slides 10-20 with 5 parallel workers
python3 factory/scripts/batch_generate.py --presentation observatory --start 10 --end 20 --parallel 5
```

Options:
- `--presentation` (required): Presentation name
- `--parallel`: Concurrent workers (default: 3, recommended max: 5)
- `--start`: Start slide number (1-indexed)
- `--end`: End slide number

### generate_thumbnails.py

Generates thumbnail images for compiled presentations.

## Compilation

### compile.py

Compiles a presentation from slides into final output format. For HTML slides (`layout: html`),
automatically renders to PNG via headless Playwright; falls back to the display bundle image
if Playwright is unavailable.

```bash
python3 factory/scripts/compile.py --presentation observatory
```

### render_html_slide.py

Renders a single HTML slide to PNG using headless Playwright. Called automatically by `compile.py`
for slides with `layout: html`, but can also be used standalone.

Resolves `data-image-id` references to local file paths, injects a stub `dox.slide` API to
capture initial state (step 0), and screenshots at the target viewport size.

```bash
python3 factory/scripts/render_html_slide.py \
    --slide-dir theses/{name}/outputs/presentation/slides/{slug} \
    --output rendered.png \
    --width 1920 --height 1080
```

Requires: `playwright` (dev dependency) + Chromium browser (`playwright install chromium`)

### compile_essay.py

Compiles an essay from the thesis structure.

```bash
python3 factory/scripts/compile_essay.py --thesis observatory
```

### scaffold_essay.py

Scaffolds essay structure from a diegesis.

```bash
python3 factory/scripts/scaffold_essay.py --thesis observatory
```

## Sharing & Export

### bundle_html_presentation.py

Bundles an HTML-slide presentation into a **single self-contained HTML file** you
can email or host anywhere — no build server, no asset directory. Each slide is
embedded in its own sandboxed `<iframe srcdoc>` (preserving per-slide JS/CSS
isolation), with `styles/html/global.css` and a minimal `dox.slide` runtime shim
injected into each. The outer shell provides keyboard navigation, a slide counter,
a progress bar, and an optional speaker-notes panel.

```bash
# CDN build (D3 + Google Fonts load from the web; smallest file)
python3 factory/scripts/bundle_html_presentation.py -p observatory --notes

# Offline build (inlines D3 so chart slides render with no network)
python3 factory/scripts/bundle_html_presentation.py -p observatory --notes --vendor
```

Options:
- `-p/--presentation`: Presentation slug (required)
- `-o/--output`: Output path (default: `outputs/presentation/{name}-bundle.html`)
- `--notes`: Embed speaker notes; toggle in-deck with **N**
- `--vendor`: Inline D3 (~280 KB × chart slides) for fully offline charts

In-deck navigation: **← / → / space** step through reveals then cross slides ·
**F** fill all steps on the current slide · **N** notes · **Home / End** jump.

**Scope:** HTML-layout slides only (`layout: html`). Slides that resolve images
via `data-image-id` / `dox.imageUrl()` are flagged with a warning — the share
file has no asset server. For decks with image-layout slides, use `compile.py`
(PNG/PPTX) instead.

**Runtime parity:** the injected `dox.slide` shim mirrors the web app's contract
in `apps/web/frontend/src/lib/utils/htmlSlideMount.ts` + `slideController.ts`
(`steps`/`onStep`/`onEnter`/`onExit`, `DOX_*` postMessage protocol). If that
contract changes, update the `BRIDGE` constant in this script to match.

## Setup & Migration

### new_presentation.py

Creates a new presentation with directory structure and templates.

```bash
python3 factory/scripts/new_presentation.py my-presentation --title "My Presentation"
```

### migrate_slides.py

Migrates slides from legacy structure to current format.

### migrate_to_semantic_slugs.py

Converts numbered slide directories to semantic slugs.

## Utilities

### utils.py

Shared utilities for all scripts:
- `vault_root()`: Resolve the vault from `DOXAGON_ROOT`
- `get_presentation_path()`: Resolve presentation directory
- `parse_frontmatter()`: Parse YAML frontmatter from markdown
- `load_file_content()`: Read file with encoding handling
- `find_slide_image()`: Find display bundle image (`is_primary` → `images[0]` fallback)
- `find_slide_dir()`: Find slide by semantic or numbered name
- `natural_sort_key()`: Sort key for slide directory ordering

### export_graph.py

Exports the Doxagon knowledge graph for external use.

### validate_presentation.py

Validates presentation structure and content.

### populate_pptx.py

Populates PowerPoint templates with slide content.

## Requirements

All scripts require the project virtual environment:

```bash
source .venv/bin/activate
```

For image generation, GCP authentication is required:

```bash
gcloud auth login
```
