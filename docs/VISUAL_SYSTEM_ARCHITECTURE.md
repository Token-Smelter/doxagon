# Visual System Architecture

Complete technical specification for the presentation visual generation system.

All project names and examples below are fictional. For the current authored
document generation contract, see [document authoring](document-authoring.md)
and [generation details](image-generation-details.md).

**Image generation is vendor-neutral.** The platform names no provider, passes
no credentials, and invokes only the adapter `DOXAGON_IMAGE_GENERATOR` names,
under [image-providers.md](./image-providers.md). Scripts under `factory/`
predate that seam: they are worked examples to adapt, not a supported route.

## Overview

The visual system enables **prompt assembly** for AI image generation. Each presentation defines a unique visual language in a `styles/` directory, and individual slide images reference those styles via `definition.md` files. A Python script assembles all components into a single prompt that gets passed to Gemini for image generation.

```
┌─────────────────────────────────────────────────────────────────┐
│                        Data Flow                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Image Definition                                               │
│  (slides/{slug}/images/main/definition.md)                      │
│           │                                                     │
│           ▼                                                     │
│  ┌─────────────────────────────────────┐                        │
│  │   generate_visuals.py               │                        │
│  │                                     │                        │
│  │   1. Parse frontmatter (YAML)       │                        │
│  │   2. Load global constraints        │                        │
│  │   3. Load palette (if diagram)      │                        │
│  │   4. Inject custom_constraints      │                        │
│  │   5. Inject visual description      │                        │
│  │   6. Load each style definition     │                        │
│  │   7. Collect reference images       │                        │
│  │   8. Write assembled_prompt.md      │                        │
│  │   9. Write generation_config.json   │                        │
│  └─────────────────────────────────────┘                        │
│           │                                                     │
│           ▼                                                     │
│  ┌─────────────────────────────────────┐                        │
│  │   Gemini API                        │                        │
│  │   (Vertex AI or API Key)            │                        │
│  │                                     │                        │
│  │   - Read assembled prompt           │                        │
│  │   - Load reference images           │                        │
│  │   - Generate image                  │                        │
│  │   - Save generated_YYYYMMDD.png     │                        │
│  └─────────────────────────────────────┘                        │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Directory Structure

### Presentation Layout

```
theses/{presentation}/
├── config.yaml                           # Shared metadata (name, audience)
├── thesis/
│   └── core.md                           # The canonical argument
├── outputs/
│   └── presentation/
│       ├── config.yaml                   # Presentation rules (timing, constraints)
│       ├── styles/                       # Visual style definitions
│       │   ├── README.md                 # Design system entry point
│       │   ├── constraints/
│       │   │   └── layout/
│       │   │       └── definition.md     # Global constraints (loaded first)
│       │   ├── foundations/              # Atomic building blocks
│       │   │   ├── canvas/
│       │   │   │   ├── definition.md
│       │   │   │   └── sources/          # Exemplar images
│       │   │   ├── typography/
│       │   │   └── colors/
│       │   └── {family}/                 # Style families (blueprint, collage, etc.)
│       │       ├── definition.md         # Base style
│       │       ├── sources/              # Reference images
│       │       └── {variant}/            # Sub-styles
│       │           └── definition.md
│       ├── slides/
│       │   └── {slug}/
│       │       ├── slide.md              # Content + image relationships
│       │       └── images/
│       │           └── {id}/             # Usually "main"
│       │               ├── definition.md # Visual description + style refs
│       │               ├── sources/      # Image-specific references
│       │               └── outputs/      # Generated images
│       └── build/                        # Compiled PPTX output
└── templates/
    └── *.pptx                            # PowerPoint templates
```

### Key Paths

| Path | Purpose |
|------|---------|
| `CLAUDE.local.md` | Active presentation (`**CURRENT**: name`) |
| `theses/{name}/outputs/presentation/styles/README.md` | Design system entry point |
| `theses/{name}/outputs/presentation/styles/constraints/layout/definition.md` | Global constraints |
| `theses/{name}/outputs/presentation/slides/{slug}/slide.md` | Slide content |
| `theses/{name}/outputs/presentation/slides/{slug}/images/main/definition.md` | Image definition |

---

## File Schemas

### Style Definition (`styles/{path}/definition.md`)

Style definitions use **semantically meaningful XML tags** that describe what they are:

```xml
<terminal_style_definition>

<overview>
High-level description of what this style does and when to use it.
</overview>

<components>
Detailed instructions, color tables, rules for applying this style.
</components>

<must_not>
Negative constraints - what to avoid.
</must_not>

</terminal_style_definition>
```

**Tag naming convention:**
- Use descriptive names: `<terminal_style_definition>`, `<code_block_style_definition>`, `<canvas_foundation>`
- The closing tag should read naturally: `</terminal_style_definition>` clearly ends terminal style content
- Foundation styles use `_foundation` suffix: `<canvas_foundation>`, `<colors_foundation>`, `<typography_foundation>`

**Key elements:**
- `<overview>` — High-level purpose and usage
- Component-specific sections (varies by style)
- `<must_not>` — What to avoid

### Image Definition (`slides/{slug}/images/{id}/definition.md`)

```yaml
---
styles:                            # Styles to compose (paths relative to styles/)
  - terminal
  - terminal/code
config:
  resolution: 2k                   # 1k, 2k, 4k (API uses uppercase)
  aspect_ratio: "16:9"             # Standard aspect ratios
sources:                           # Image-specific reference images in ./sources/
  - reference.png
custom_constraints: |              # Per-image rules (override/clarify styles)
  - Keep the illustration within the frame
  - No text except title
---

<terminal_style style="TERMINAL">
Dark terminal background description.

<rendered_text>
TITLE TEXT HERE

Code or content to render...
╭─ ~/example   main   v3.12
╰─❯ █
</rendered_text>

<code_block style="CODE">
Syntax highlighting instructions for code portions.
</code_block>
</terminal_style>
```

**Key fields:**
- `styles:` — List of style paths to include in assembled prompt
- `config.resolution:` — Output resolution (1k, 2k, 4k)
- `config.aspect_ratio:` — Output aspect ratio
- `sources:` — Reference images in the local `sources/` directory
- `custom_constraints:` — Per-image rules that override or clarify styles

**XML Structure:**
- Semantic tags wrap content (e.g., `<terminal_style>`, `<code_block>`)
- `style="NAME"` attribute links to style definitions
- Tags nest naturally: outer style provides context, inner tags style subsections
- `<rendered_text>` marks content that should appear visibly in the image

### Slide Definition (`slides/{slug}/slide.md`)

```yaml
---
layout: image              # "image" (default) | "html"
animation: auto            # "auto" (default) | "manual" (html only)

text:
  title: "Slide Title"
  body: |
    Slide body text here...

speaker_notes: |
  What to say when presenting...

doxai:                             # Links to knowledge graph
  - d-observe-stars
  - d-compare-charts

images:
  - id: main
    is_primary: true               # Display bundle (audience display, presenter, PPTX)
    selected: outputs/selected.png
    placement: full-bleed          # full-bleed|left|right|inset
    purpose: >
      Why this slide needs this image - narrative context
  - id: alt
    selected: outputs/generated_20260314_1.png
    purpose: "Alternative approach"
---
```

**Display bundle**: `is_primary: true` marks which bundle shows in the audience display, presenter, and PPTX output. Falls back to `images[0]` if none marked. HTML slides don't use display bundles — all bundles are peers referenced by ID.

**HTML slides**: Set `layout: html` and add `slide.html`. Bundles are referenced via `<img data-image-id="{id}" />`. At build time, rendered to PNG via headless Playwright; falls back to the display bundle if unavailable.

**Key fields:**
- `text.title`, `text.body` — Slide content
- `speaker_notes` — Presenter notes
- `doxai` — Links to beliefs in the knowledge graph
- `images[].id` — Image bundle identifier (usually "main")
- `images[].selected` — Path to chosen generated image
- `images[].purpose` — Why this image serves this slide's narrative

---

## Assembly Algorithm

### Overview

The `generate_visuals.py` script constructs prompts by concatenating content in a specific order. **All sections use XML tags** for clear boundaries:

```
┌─────────────────────────────────────────────────────────────────┐
│ FINAL PROMPT STRUCTURE                                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│ <rendered_text_rule>                                            │
│ CRITICAL: Only render text inside <rendered_text> blocks...    │
│ </rendered_text_rule>                                           │
│                                                                 │
│ ---                                                             │
│                                                                 │
│ <global_constraints>                                            │
│ [contents of constraints/layout/definition.md]                  │
│ </global_constraints>                                           │
│                                                                 │
│ ---                                                             │
│                                                                 │
│ <color_system>                                                  │
│ [contents of global/palette*/definition.md]                     │
│ </color_system>                                                 │
│                                                                 │
│ ---                                                             │
│                                                                 │
│ <image_constraints>                                             │
│ [custom_constraints from image definition.md]                   │
│ </image_constraints>                                            │
│                                                                 │
│ ---                                                             │
│                                                                 │
│ <visual_description>                                            │
│ [body content from image definition.md]                         │
│ </visual_description>                                           │
│                                                                 │
│ ---                                                             │
│                                                                 │
│ <style_definitions>                                             │
│                                                                 │
│ <terminal_style_definition>                                     │
│ [contents of first style definition.md]                         │
│ </terminal_style_definition>                                    │
│                                                                 │
│ <code_block_style_definition>                                   │
│ [contents of second style definition.md]                        │
│ </code_block_style_definition>                                  │
│                                                                 │
│ </style_definitions>                                            │
│                                                                 │
│ ---                                                             │
│                                                                 │
│ <generation_settings>                                           │
│ resolution: 2K                                                  │
│ aspect_ratio: 16:9                                              │
│ </generation_settings>                                          │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Assembly Order

| Order | Source | XML Section | Condition |
|-------|--------|-------------|-----------|
| 0 | Auto-injected | `<rendered_text_rule>` | Always |
| 1 | `styles/constraints/layout/definition.md` | `<global_constraints>` | Always |
| 2 | `styles/global/palette*/definition.md` | `<color_system>` | If any style contains "diagram" |
| 3 | Image's `custom_constraints:` | `<image_constraints>` | If present |
| 4 | Image's body content | `<visual_description>` | Always |
| 5 | Each style from `styles:` list | `<style_definitions>` | Always |
| 6 | Generation settings | `<generation_settings>` | Always |

### Reference Image Collection

Reference images are collected from:
1. Each style's `sources/` directory
2. The image's own `sources/` directory

**Limit:** Maximum 14 images total (Gemini API quota). Excess images are truncated with a warning.

### Output Files

The script writes to `images/{id}/outputs/`:

| File | Contents |
|------|----------|
| `assembled_prompt.md` | Full concatenated prompt text |
| `generation_config.json` | `{image_size, aspect_ratio, source_images[]}` |

---

## Python Utilities

### `factory/scripts/utils.py`

Core utilities used by all factory scripts.

| Function | Signature | Purpose |
|----------|-----------|---------|
| `get_active_presentation` | `() → str \| None` | Parse `CLAUDE.local.md` for `**CURRENT**: name` |
| `get_presentation_path` | `(name: str) → Path` | Return `theses/{name}/` path |
| `get_presentation_output_paths` | `(path: Path) → dict` | Return `{slides_dir, styles_dir, build_dir, templates_dir}` |
| `parse_frontmatter` | `(content: str) → (dict, str)` | Parse YAML frontmatter, return `(metadata, body)` |
| `load_file_content` | `(path: Path) → str` | Read file or return empty string |
| `normalize_slug` | `(dirname: str) → str` | `"05-mcluhan-medium"` → `"mcluhan-medium"` |
| `find_slide_dir` | `(slides_dir: Path, slug: str) → Path \| None` | Find slide by semantic or numbered name |
| `find_slide_image` | `(slide_dir: Path) → Path \| None` | Find display bundle image (checks `is_primary`, falls back to `images[0]`) |
| `natural_sort_key` | `(s: str) → tuple` | Sort key for `00, 00-5, 01, 02` ordering |
| `load_config` | `(path: Path) → dict` | Load `config.yaml` with error handling |
| `load_output_config` | `(path: Path, type: str) → dict` | Load output-specific config merged with root |

### `factory/scripts/generate_visuals.py`

Main prompt assembly script.

| Function | Purpose |
|----------|---------|
| `load_style_bundle(style_path, styles_dir)` | Load style definition text + source images |
| `get_image_dirs(slide_dir)` | Get all `(image_id, image_dir)` tuples for a slide |
| `construct_prompt(image_dir, styles_dir)` | **Core function:** Build full prompt + collect images |

**`construct_prompt` returns:**
```python
(prompt_text: str, reference_images: list[Path], generation_config: dict)
```

### `factory/scripts/generate_image_vertex.py`

**Example adapter, not a supported path.** The platform invokes whatever
`DOXAGON_IMAGE_GENERATOR` names, under the contract in
[image-providers.md](./image-providers.md). This script predates that seam and
implements only part of it. Copy it to `~/.doxagon/providers/` and point it at
your own Vertex AI project via `GOOGLE_CLOUD_PROJECT`.

```python
def generate_image(prompt: str, output_dir: Path) -> Path | None:
    client = genai.Client(vertexai=True, project=project_id, location=LOCATION)
    response = client.models.generate_content(
        model="gemini-3-pro-image-preview",
        contents=[types.Part.from_text(text=prompt)],
        config=types.GenerateContentConfig(response_modalities=["IMAGE", "TEXT"])
    )
    # Extract and save image from response
```

---

## Skills

### `generate-slide-visual`

**Purpose:** End-to-end image generation workflow.

**Workflow:**
1. Run `generate_visuals.py --slide N --output` to assemble prompt
2. Read `assembled_prompt.md` and `generation_config.json`
3. Call Vertex AI with prompt + reference images
4. Archive prompt alongside generated image
5. Optionally update `slide.md` to select the image

**Usage:**
```bash
/generate-slide-visual 14
```

### `visual-prompt-editor`

**Purpose:** Edit image definitions with full context.

**Mandatory:** Forces reading architecture docs before making changes:
1. `docs/SLIDE_ARCHITECTURE.md`
2. `theses/{name}/outputs/presentation/styles/README.md`

**Key conventions enforced:**
- Inline tag placement (`**[TAG]**` next to relevant instruction)
- Style family separation
- `<rendered_text>` blocks for text rendering

### `visual-concept-brainstorm`

**Purpose:** Multi-agent ideation before writing prompts.

**Context assembly (`assemble_context.py`):**
1. Read slide metadata (title, body, speaker notes)
2. Resolve doxai content from `library/doxai/`
3. Load design system (palette + constraints)
4. Build presentation outline with current slide marked

**Outputs:**
- `goal.md` — Brainstorming objective
- `context.md` — Full context for ideation

### `gemini-image-api`

**Purpose:** Direct image generation with API key.

**Two modes:**
1. **Direct prompt → image:** `--prompt "description"`
2. **Auto-prompt from content:** `--content "concept" --auto-prompt --style diagram`

**Reference images:**
```bash
--ref style_guide.png="Diagram style guide"
--ref astronomer.png="Fictional astronomer reference"
```

### Skill Cross-References

| Starting Point | Next Step | Use Case |
|----------------|-----------|----------|
| `visual-concept-brainstorm` | `visual-prompt-editor` | After selecting a concept, write the definition |
| `visual-prompt-editor` | `generate-slide-visual` | After editing, generate the image |
| `generate-slide-visual` | (done) | Image generated and archived |

**Workflow:** Brainstorm → Edit → Generate

---

## Text Rendering Convention

### The Rule

**Only render text inside `<rendered_text>` blocks.**

Everything else is instruction metadata:
- Style tags (`<terminal_style>`, `<code_block>`) — Styling guidance
- Prose descriptions — What to draw
- Tag attributes — Metadata for style linking

### Auto-Injected Rule

The assembly script automatically injects this rule into every prompt:

```xml
<rendered_text_rule>
CRITICAL: Only render text that appears inside <rendered_text> blocks.
Everything outside these blocks is instruction metadata - do NOT render it as visible text.
Do NOT add text that "seems appropriate" or render words from style descriptions.
</rendered_text_rule>
```

This prevents instruction leakage where the model renders descriptive text as visible labels.

### Example

```xml
<terminal_style style="TERMINAL">
Dark terminal background with code display.

<rendered_text>
# The Agent Loop

messages = [system_prompt]
while not task_complete:
    response = call_llm(messages)

╭─ ~/example   main   v3.12
╰─❯ █
</rendered_text>

<code_block style="CODE">
Python syntax highlighting: keywords in Blue, strings in Green.
</code_block>
</terminal_style>
```

**Result:** Only the content inside `<rendered_text>` appears as visible text. The prose descriptions, style tags, and instructions are metadata for the model, not rendered content.

---

## Tag System

### Purpose

Semantic XML tags provide clear boundaries for natural language parsing by image generation models. These are not meant to be machine-parsed XML—they're semantic markers that help the model understand structure.

### How It Works

1. **In image definition body:**
   ```xml
   <terminal_style style="TERMINAL">
   Dark terminal background.

   <title_treatment style="TITLE">The "300 Lines" Reality</title_treatment>

   <code_block style="CODE">
   def example():
       return "hello"
   </code_block>
   </terminal_style>
   ```

2. **In style definition:** Use a semantically meaningful wrapper tag:
   ```xml
   <terminal_style_definition>
   <overview>Base terminal style...</overview>
   ...
   </terminal_style_definition>
   ```

3. **In assembled prompt:** The model sees semantic tags that self-describe their purpose. The closing tag reads naturally: `</terminal_style_definition>` clearly ends terminal style content.

### Semantic Tag Convention

Tags should describe what they contain:

| Content Type | Definition Tag | Image Definition Tag |
|--------------|----------------|----------------------|
| Terminal base style | `<terminal_style_definition>` | `<terminal_style style="TERMINAL">` |
| Code blocks | `<code_block_style_definition>` | `<code_block style="CODE">` |
| Title treatment | `<title_treatment_style_definition>` | `<title_treatment style="TITLE">` |
| Shell prompt | `<prompt_line_style_definition>` | `<prompt_line style="PROMPT">` |
| ASCII diagrams | `<ascii_diagram_style_definition>` | `<ascii_diagram style="ASCII">` |
| Terminal output | `<terminal_output_style_definition>` | `<terminal_output style="OUTPUT">` |
| Canvas foundation | `<canvas_foundation>` | N/A (foundation only) |
| Color foundation | `<colors_foundation>` | N/A (foundation only) |
| Typography foundation | `<typography_foundation>` | N/A (foundation only) |

### Nesting Structure

In image definitions, tags nest naturally to show containment:

```xml
✅ CORRECT:
<terminal_style style="TERMINAL">
  Base context established here.

  <code_block style="CODE">
    Code-specific instructions here.
  </code_block>

  <terminal_output style="OUTPUT">
    Output styling here.
  </terminal_output>
</terminal_style>

❌ WRONG (flat when nesting makes sense):
<terminal_style style="TERMINAL">
Base context.
</terminal_style>
<code_block style="CODE">
Code instructions (lost containment context).
</code_block>
```

In style definitions, each definition is a self-contained document with its own semantic wrapper:

```xml
<terminal_style_definition>
  <overview>Terminal base style...</overview>
  <full_bleed_layout>...</full_bleed_layout>
  <must_not>...</must_not>
</terminal_style_definition>
```

---

## Style Families and Inheritance

### Family Rules

Styles are organized into **families** that cannot be mixed:

| Family | Purpose | Example Styles |
|--------|---------|----------------|
| `diagram/` | Technical diagrams | `diagram/base`, `diagram/vignette/characters/astronomer` |
| `collage/` | Editorial collage | `collage/fiore` |
| `blueprint/` | Architectural drawings | `blueprint/trust`, `blueprint/non-trust` |
| `3d/` | 3D renders | `3d/base`, `3d/characters/owl` |
| `terminal/` | Matrix/terminal aesthetic | `terminal/base` |
| `artifact/` | Archaeological artifacts | `artifact/pottery`, `artifact/mosaic` |
| `global/` | Cross-family utilities | `global/palette`, `global/titled-frame` |

**Rule:** `global/` styles CAN combine with any family; other families cannot mix.

```yaml
✅ CORRECT:
styles:
  - blueprint
  - blueprint/trust
  - blueprint/non-trust

❌ WRONG:
styles:
  - diagram/base
  - 3d/characters/owl  # Different family!
```

### Dependency Resolution

Styles declare dependencies via `requires:` in frontmatter:

```yaml
# In marble/definition.md
---
requires:
  - foundations/canvas
  - foundations/colors
---
```

**Effect:** When you reference `marble`, the assembly script automatically loads `foundations/canvas` and `foundations/colors` first.

### Override Order

Later content overrides earlier content:

1. Global constraints (baseline)
2. Palette (color definitions)
3. Custom constraints (can override palette)
4. Visual description (uses all above)
5. Style definitions (detailed rules)

---

## Configuration Reference

### Resolution Mapping

| Config Value | API Value | 16:9 Pixels | 1:1 Pixels | Tokens |
|--------------|-----------|-------------|------------|--------|
| `1k` | `1K` | 1376×768 | 1024×1024 | 1120 |
| `2k` | `2K` | 2752×1536 | 2048×2048 | 1120 |
| `4k` | `4K` | 5504×3072 | 4096×4096 | 2000 |

### Aspect Ratio Options

`1:1`, `2:3`, `3:2`, `3:4`, `4:3`, `4:5`, `5:4`, `9:16`, `16:9`, `21:9`

### Reference Image Limits

- **Maximum:** 14 images total
- **Sources:** Style `sources/` + image-specific `sources/`
- **Behavior:** Excess images truncated with warning

---

## Presentation Design Systems

Each presentation defines its own visual language. These are fictional examples:

| Presentation | System Name | Key Concept |
|--------------|-------------|-------------|
| `sample-blueprint` | Modern White Blueprint | Architectural drawings with trust/non-trust zones |
| `sample-editorial` | Editorial Cybernetics | 1960s McLuhan-era corporate modernism |
| `sample-archaeology` | Archaeological Discovery | Greek artifacts (marble, pottery, mosaics) |
| `observatory` | Night Sky | Star charts and telescope illustrations |

### Design System Entry Points

Each presentation's `styles/README.md` contains:
- Style hierarchy diagram
- Color palette with semantic meanings
- Component usage rules
- Example image definitions
- "DO NOT" constraints

---

## Complete Workflow

### Standard Image Generation

```bash
# 1. Select your vault explicitly
export DOXAGON_ROOT=/path/to/vault

# 2. Assemble prompt for slide
source .venv/bin/activate
python3 factory/scripts/generate_visuals.py --presentation observatory --slide 14 --output

# 3. Review assembled prompt (optional)
cat "$DOXAGON_ROOT/projects/observatory/outputs/presentation/slides/14-opening/images/main/outputs/assembled_prompt.md"

# 4. Generate image through the configured adapter (docs/image-providers.md)
"$DOXAGON_IMAGE_GENERATOR" \
    --prompt-file .../outputs/assembled_prompt.md \
    --output .../outputs/ \
    --image-size 2K --aspect-ratio 16:9

# 5. Archive prompt alongside image
cp outputs/assembled_prompt.md outputs/generated_20260125_143052.prompt.md

# 6. Update slide.md to select the image
# images:
#   - id: main
#     selected: outputs/generated_20260125_143052.png
```

### Using Skills

```bash
# Generate visual (full workflow)
/generate-slide-visual 14

# Brainstorm concepts first
/visual-concept-brainstorm 14

# Edit image definition (forces doc reading)
/visual-prompt-editor
```

### Batch Generation

```bash
# Assemble multiple slides
for slide in 14 15 16; do
    python3 factory/scripts/generate_visuals.py --slide $slide --output
done

# Then generate each (read prompts individually)
```

---

## Troubleshooting

### Common Issues

| Symptom | Cause | Solution |
|---------|-------|----------|
| Style not found error | Typo in `styles:` path | Check path exists under `styles/` |
| Wrong colors | Missing palette | Ensure diagram styles are used, or add palette manually |
| Text rendered that shouldn't be | Missing `<rendered_text>` blocks | Wrap intended text in blocks |
| Character looks wrong | Prompt not passed verbatim | Use skills; don't summarize assembled prompt |
| Too many reference images | Combined sources exceed 14 | Reduce style sources or image sources |
| Assembly order wrong | Override not working | Check assembly order; later overrides earlier |

### Verification Checklist

When generated images don't match expectations:

1. **Read assembled prompt:** `outputs/assembled_prompt.md`
2. **Check style inclusion:** Are all styles from `styles:` present?
3. **Check tag alignment:** Do inline `**[TAGS]**` match appended definitions?
4. **Check reference images:** Are correct exemplars included?
5. **Check constraints:** Are custom constraints being respected?

---

## Anti-Patterns

### Color Callouts in Image Definitions

**Anti-pattern:** Specifying color names or hex values in individual image `definition.md` files.

```yaml
# ❌ WRONG: Color callouts in custom_constraints
custom_constraints: |
  - Generate node: primary accent
  - Critic nodes: Purple (cognitive diversity)
  - Adjudicate node: Orange (decision point)
  - Approved exit: Green (success)
  - Escalate exit: Red (alert)
```

**Why it's wrong:**
- Breaks coherence: Colors should be determined by the global style system
- Reduces maintainability: Changing a semantic color requires editing every slide
- Creates inconsistency: Different slides might use different colors for the same semantic meaning

**Correct approach:** Define semantic color roles in the global palette, reference semantic names in definitions.

```xml
<!-- In styles/global/palette/definition.md -->
<semantic_assignments>
| Role | Usage |
|------|-------|
| Primary data | Main flow, connections |
| Secondary accent | Emphasis, contrast |
| Success | Approved paths, positive outcomes |
| Warning | Iteration, decision points |
| Alert | Escalation, critical paths |
| Cognitive diversity | Multiple perspectives |
</semantic_assignments>
```

```yaml
# ✅ CORRECT: Semantic references only
custom_constraints: |
  - Generate node uses primary data color
  - Critic nodes show cognitive diversity
  - Decision points use warning semantic
  - Exit paths: success or alert as appropriate
```

**Rule:** Image definitions should describe WHAT elements need emphasis, not WHICH colors to use. The global palette determines color-to-semantic mappings.

### Font Callouts in Image Definitions

**Anti-pattern:** Specifying font families, weights, or sizes in individual definitions.

```yaml
# ❌ WRONG
custom_constraints: |
  - Title in Inter Bold 48pt
  - Labels in Helvetica 14pt
```

```yaml
# ✅ CORRECT
custom_constraints: |
  - Title prominent
  - Labels small, recessive
```

**Rule:** Typography details belong in `global/typography`. Definitions should reference semantic roles (title, label, body) not specific fonts.

### Hardcoded Hex Values

**Anti-pattern:** Using hex codes anywhere in image definitions.

```markdown
# ❌ WRONG
Main nodes in #33B5E5 with #E91E63 accent.
```

```markdown
# ✅ CORRECT
Main nodes in primary accent with secondary accent for emphasis.
```

**Rule:** Hex values appear ONLY in `global/palette/definition.md`. Everywhere else uses semantic names.

---

## Design Decisions

### Why Separation of Content and Style?

- `slide.md` contains **narrative** content (what the audience hears/reads)
- `definition.md` contains **visual** instructions (what the audience sees)
- Allows same narrative to have different visual treatments
- Allows same visual to serve different narratives

### Why Inline Tag Anchoring?

The assembly process appends style definitions at the end. Without inline tags:
1. Model sees instruction about title
2. ...many other instructions...
3. Full title-treatment definition (far away)

With inline tags, `[TITLE_TREATMENT]` in the instruction links to `**Tag:** [TITLE_TREATMENT]` in the appended definition.

### Why Reference Images?

Gemini supports "style transfer" via reference images. Each style's `sources/` directory contains **exemplar images** that demonstrate the style. These maintain visual consistency across slides.

### Why `<rendered_text>` Blocks?

Without explicit boundaries, models tend to render descriptive text as visible labels. The `<rendered_text>` convention creates an unambiguous "render only this" contract.

### Why Maximum 14 Reference Images?

Gemini API quota limit. The assembly script enforces this by truncating excess images with a warning.
