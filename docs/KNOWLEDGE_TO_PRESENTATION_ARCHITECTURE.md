# Knowledge-to-Presentation Architecture

This document describes the complete data flow from epistemic primitives (doxai) through argument structures (diegeses) to rendered presentations (slides with generated visuals).

All examples below are fictional. Paths describe the legacy vault aliases;
`knowledge/` and `projects/` are the canonical content directories. Authored
documents use the [document authoring workflow](document-authoring.md).

## Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         KNOWLEDGE LAYER                                  │
│  library/                                                                │
│  ├── doxai/d-*.md          Atomic beliefs with evidence                 │
│  ├── evidence/e-*.md       Sources backing beliefs                      │
│  ├── diegeses/n-*.md       Narrative walks through beliefs              │
│  ├── logos.yaml            Typed edges between beliefs                  │
│  └── schema.yaml           Canonical schema definitions                 │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          THESIS LAYER                                    │
│  theses/{name}/                                                          │
│  ├── config.yaml           Thesis metadata + diegesis reference         │
│  └── thesis/core.md        Argument structure derived from diegesis     │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                       PRESENTATION LAYER                                 │
│  theses/{name}/outputs/presentation/                                     │
│  ├── config.yaml           Presentation settings                        │
│  ├── slides/{n}-{slug}/    Individual slides                            │
│  │   ├── slide.md          Content + image references                   │
│  │   └── images/{id}/      Visual bundles                               │
│  │       ├── definition.md Style refs + visual description              │
│  │       ├── sources/      Reference images                             │
│  │       └── outputs/      Generated images                             │
│  └── styles/               Reusable style bundles                       │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 1. Doxa Schema (Atomic Beliefs)

**Location**: `library/doxai/d-*.md`
**Prefix**: `d-`

Doxai are the epistemic primitives—single atomic claims that can be true or false.

### Frontmatter

```yaml
---
id: d-belief-slug                    # Unique identifier (optional, derived from filename)
belief: "Single atomic claim"        # Required, immutable once set
status: draft                        # draft | canonical | archived
confidence: 0.95                     # Optional, 0.0-1.0
tags:                                # Domain classification
  - domain:astronomy
  - domain:verification
evidence:                            # Links to evidence files
  - source: e-example-observation
    quote: "Supporting quote..."
diegeses:                            # Which diegeses include this doxa
  - n-observatory
provenance:                          # How belief was created
  path: reactive                     # reactive | proactive | direct
  via_katalepsis: k-claim-name       # For reactive path
  from_phantasia: p-source-name      # For reactive path
created: 2025-12-26
updated: 2025-12-26
---
```

### Body

```markdown
# [Belief restated as title]

Expanded explanation of the belief.

## Implications

What follows from this belief.
```

### Example

```yaml
---
belief: "The example star is visible from the observation site"
tags: [domain:astronomy]
evidence:
  - source: e-example-observation
    quote: "The sample log records a visible star."
diegeses:
  - n-observatory
---

# A visible star

This fictional observation illustrates a belief linked to evidence.
```

---

## 2. Evidence Schema

**Location**: `library/evidence/e-*.md`
**Prefix**: `e-`

Evidence provides backing for beliefs with traceable sources.

### Frontmatter

```yaml
---
title: "Full Title of Source"
source_type: article                 # article | paper | report | book | thread | video
date: 2025-01-01
url: "https://example.com/source"
authors:
  - Author Name
tags:
  - domain:astronomy
credibility: high                    # high | medium | low
created: 2025-01-01
---
```

### Body

```markdown
# Source Title

Brief description of source.

## Key Findings

### Finding 1

> "Exact quote from source" (p. 42)
```

---

## 3. Logos Schema (Relationships)

**Location**: `library/logos.yaml`

Logos defines typed, directional relationships between doxai.

### Edge Structure

```yaml
edges:
  - source: d-source-belief          # Source doxa slug
    target: d-target-belief          # Target doxa slug
    type: supports                   # Edge type from schema
    alias: "provides evidence for"   # Human-readable label (optional)
    rationale: "Why this edge..."    # Full explanation (required)
    confidence: high                 # high | medium | low (optional)
    strength: moderate               # strong | moderate | weak (optional)
```

### Edge Types

| Type | Description | Inverse |
|------|-------------|---------|
| `supports` | Source provides reason to accept target | is supported by |
| `contradicts` | Source and target are in tension | (symmetric) |
| `requires` | Target is prerequisite for source | enables |
| `elaborates` | Source adds detail to target | is elaborated by |
| `grounds` | Source provides foundational basis | is grounded by |
| `causes` | Source creates/leads to target | is caused by |
| `resolves` | Source provides solution to target | is resolved by |

---

## 4. Diegesis Schema (Argument Structures)

**Location**: `library/diegeses/n-*.md`
**Prefix**: `n-`

A diegesis organizes doxai into sections and defines walks (ordered paths) through them.

### Frontmatter

```yaml
---
id: n-diegesis-slug                  # Unique identifier
title: "Diegesis Title"              # Display title
subtitle: "Optional subtitle"
status: draft                        # draft | active | archived
thesis: thesis-name                  # Primary thesis using this diegesis (optional)
core_claim: |                        # Summary of argument (optional)
  Prepare the observation site before recording measurements.
sections:                            # Map of section_key → section content
  orientation:
    title: "Prepare the site"
    description: "Choose equipment and a viewing position"
    doxai:                           # Doxai in this section
      - d-prepare-telescope
      - d-compare-observations
  level1:
    title: "Observe the sky"
    description: "Focus the telescope and follow a star"
    doxai:
      - d-adjust-focus
      - d-track-stars
walks:                               # Named paths through sections
  canonical:                         # Full argument
    - orientation
    - level1
  essentials:                        # Abbreviated version
    - orientation
    - level1
created: 2026-01-24
updated: 2026-01-25
---
```

### Body

The body contains narrative prose connecting the beliefs:

```markdown
# Diegesis: Title

## Narrative Arc

Description of the argument flow.

---

## Module 1: Section Name

**Anchor:** [[d-doxa-slug]]

> "Key quote from the doxa"

Narrative text connecting beliefs...

**Implication:** What this means for the audience.
```

### Key Relationships

- `sections[key].doxai[]` → references `library/doxai/d-*.md`
- `walks[name][]` → ordered list of section keys
- `thesis` → optional link to primary thesis using this diegesis

---

## 5. Thesis Schema

**Location**: `theses/{name}/`

A thesis selects a diegesis and walk to render as a specific output format.

### Config File

**File**: `theses/{name}/config.yaml`

```yaml
name: thesis-name                    # Thesis slug
title: "Presentation Title"          # Display title
subtitle: "Optional subtitle"
audience: "Target audience"
description: |
  Multi-line description...
diegesis: n-diegesis-slug           # Which diegesis to use
walk: canonical                      # Which walk from diegesis
duration: 180                        # Duration in minutes (optional)
key_themes:
  - "Theme 1"
  - "Theme 2"
```

### Core File

**File**: `theses/{name}/thesis/core.md`

```yaml
---
id: thesis-slug
title: "Thesis Title"
diegesis: n-diegesis-slug           # References diegesis
status: draft
created: 2026-01-24
---

# Thesis: Title

## Core Claim

Single sentence summarizing the thesis.

## The Argument

### 1. First claim
Exposition...

### 2. Second claim
Exposition...

## Evidence Map

| Claim | Key Evidence | Source |
|-------|--------------|--------|
| The star is visible | Observation log | Sample observatory |

## Narrative Arc

### Act I: Setup
**Emotional state:** Curiosity → Understanding
**Purpose:** Introduce the observation

## Key Metaphors

| Metaphor | Maps To | Purpose |
|----------|---------|---------|
| A window | Field of view | Explain observation |

## Audience Assumptions

**Who they are:** Visitors learning to use a telescope.
**What they believe coming in:** The sky contains unfamiliar objects.
**What they believe leaving:** Observations can be recorded and compared.
```

### Key Relationships

- `diegesis` → references `library/diegeses/n-*.md`
- The selected `walk` determines section order from diegesis

---

## 6. Presentation Config

**Location**: `theses/{name}/outputs/presentation/config.yaml`

```yaml
name: thesis-name
title: "Presentation Title"
subtitle: "Subtitle"
audience: "Target audience"
diegesis: n-diegesis-slug
walk: canonical
duration: 180
```

This typically mirrors or extends `theses/{name}/config.yaml` for the presentation output.

---

## 7. Slide Schema

**Location**: `theses/{name}/outputs/presentation/slides/{number}-{slug}/slide.md`

### Directory Structure

```
slides/
└── 07-agents-are-simple/
    ├── slide.md                     # Content + image refs
    └── images/
        └── main/                    # Image bundle
            ├── definition.md        # Visual description
            ├── sources/             # Reference images
            └── outputs/             # Generated images
```

### Frontmatter

```yaml
---
text:
  title: "Slide Title"               # Required
  body: |                            # Optional, supports markdown
    Body content with **formatting**...

    ```python
    code_blocks_supported()
    ```

speaker_notes: |                     # Optional
  - Point to make
  - Another point

doxai:                               # Which beliefs this slide covers
  - d-track-stars
  - d-log-observations

images:
  - id: main                         # Matches images/{id}/ directory
    placement: full-bleed            # full-bleed | right-half | left-half | background
    purpose: "Why this image..."     # Justification for the visual
    selected: outputs/generated.png  # Path to selected image

credits: "Attribution"               # Optional content credit
---
```

### Example

```yaml
---
credits: "Example author"
doxai:
  - d-track-stars
  - d-log-observations
images:
  - id: main
    placement: right-half
    purpose: Show the telescope's field of view
    selected: outputs/selected.png
speaker_notes: |
  Explain how the fictional observation was recorded.
text:
  title: A Night at the Observatory
  body: |
    Compare the star chart with the observation log.
---
```

### Key Relationships

- `doxai[]` → references `library/doxai/d-*.md`
- `images[].id` → maps to `images/{id}/` subdirectory
- `images[].selected` → path to generated image file

---

## 8. Image Definition Schema

**Location**: `slides/{slide}/images/{id}/definition.md`

Image definitions describe what to render and which style bundles to use.

### Directory Structure

```
images/
└── main/
    ├── definition.md                # Visual description + style refs
    ├── sources/                     # Reference images for this image
    │   └── reference.png
    └── outputs/                     # Generated images
        ├── generated_*.png
        ├── assembled_prompt.md      # Full assembled prompt
        └── generation_config.json   # API parameters
```

### Frontmatter

```yaml
---
styles:                              # Style bundles to include
  - terminal                         # → styles/terminal/definition.md
  - terminal/code                    # → styles/terminal/code/definition.md

config:
  resolution: 2k                     # 1k | 2k | 4k
  aspect_ratio: 16:9                 # 1:1, 16:9, 9:16, etc.
  versions: 3                        # Number of variants

sources:                             # Reference images in ./sources/
  - reference-image.png

custom_constraints: |                # Image-specific RULES
  - ONLY Signal Orange for focal element
  - No text except title
  - Code block must show full loop
---
```

### Body Content

The body contains the visual description with semantic style tags:

```markdown
<terminal_style style="TERMINAL">
Dark terminal background with code visualization.

<rendered_text>
# Title That Appears

Body text rendered literally on the slide.

```python
# Code that appears
def example():
    pass
```
</rendered_text>

<code_block style="CODE">
Python syntax highlighting:
- Keywords in Lavender
- Functions in Blue
- Comments in Subtext0
</code_block>

All text uses JetBrains Mono.
</terminal_style>
```

### Separation of Concerns

| Content | Location | Purpose |
|---------|----------|---------|
| RULES (must/must not) | `custom_constraints` | Restrictions and mandates |
| WHAT to render | Body content | Creative visual description |
| HOW to style | `styles[]` | Reusable style definitions |

### Key Relationships

- `styles[]` → references `styles/{path}/definition.md`
- `sources[]` → images in `./sources/` directory
- Style tags in body → link to full definitions in assembled prompt

---

## 9. Style Bundle Schema

**Location**: `theses/{name}/outputs/presentation/styles/`

Styles are reusable visual definitions that get assembled into prompts.

### Directory Structure

```
styles/
├── foundations/                     # Atomic building blocks
│   ├── canvas/
│   │   ├── definition.md
│   │   └── sources/
│   │       └── exemplar.png
│   ├── colors/
│   │   └── definition.md
│   └── typography/
│       └── definition.md
├── constraints/
│   └── layout/
│       └── definition.md
├── terminal/                        # Style family
│   ├── definition.md                # Base style
│   ├── code/
│   │   └── definition.md            # Code block treatment
│   ├── prompt/
│   │   └── definition.md            # Command prompt treatment
│   └── output/
│       └── definition.md            # Terminal output treatment
└── README.md                        # Style system documentation
```

### Style Definition Frontmatter

```yaml
---
requires:                            # Prerequisite styles
  - foundations/canvas
  - foundations/colors
  - terminal                         # Base style required
---
```

### Style Definition Body

Styles use semantic XML tags for clear boundaries:

```markdown
<terminal_style_definition>

<overview>
The base terminal style. Every slide looks like a modern terminal
emulator—Warp, Kitty, or Alacritty with a Catppuccin theme.
</overview>

<full_bleed_layout>
Slides are **full screen terminal content** — no window decoration.

- **Background:** Base color, edge-to-edge
- **NO window chrome** (no title bar, no traffic lights)
- **Padding:** 24-48px from edges
</full_bleed_layout>

<glow_effect>
Subtle phosphor glow on accent-colored text:
- **Blur:** 2-4px
- **Color:** Same as text, 20-30% opacity
</glow_effect>

<must_not>
- No window decorations
- No photorealistic elements
- No 3D perspective
</must_not>

</terminal_style_definition>
```

### Foundation Styles

**Colors** (`foundations/colors/definition.md`):

```markdown
<colors_foundation>

<canvas_colors>
| Token | Hex | Usage |
|-------|-----|-------|
| **Base** | #1E1E2E | Deep background |
| **Surface0** | #313244 | Elevated elements |
| **Text** | #CDD6F4 | Primary text |
| **Subtext0** | #A6ADC8 | Comments |
</canvas_colors>

<accent_colors>
| Token | Hex | Syntax Role | Semantic Role |
|-------|-----|-------------|---------------|
| **Lavender** | #B4BEFE | Keywords | L4 Delegation |
| **Blue** | #89B4FA | Functions | L3 Orchestration |
| **Teal** | #94E2D5 | Types | L2 Specialists |
| **Green** | #A6E3A1 | Strings | Success |
| **Red** | #F38BA8 | Errors | Failure |
</accent_colors>

</colors_foundation>
```

### Style Family Rules

Styles are organized into families. **Never mix families** in a single image:

- ❌ `styles: [terminal, blueprint/trust]`
- ✅ `styles: [terminal, terminal/code]`

### Style Prerequisites

Some styles require base styles. Check the `requires:` field:

- ❌ `styles: [terminal/code]` (missing base)
- ✅ `styles: [terminal, terminal/code]`

---

## 10. Prompt Assembly

When generating images, the system assembles prompts in a specific order.

### Assembly Order

1. **Global constraints** (`styles/constraints/layout/definition.md`)
2. **Palette** (`styles/foundations/colors/definition.md`)
3. **Custom constraints** (from image `definition.md` frontmatter)
4. **Visual description** (from image `definition.md` body)
5. **Style definitions** (from each style in `styles:` list)
6. **Reference images** (from all `sources/` directories)

### XML Tag Wrapping

Each section is wrapped in semantic XML tags:

```xml
<global_constraints>
[constraints/layout content]
</global_constraints>

<color_system>
[foundations/colors content]
</color_system>

<image_constraints>
[custom_constraints from definition.md]
</image_constraints>

<visual_description>
[body content from definition.md]
</visual_description>

<style_definitions>
[concatenated style definitions]
</style_definitions>

<generation_settings>
Resolution: 2K (2752x1536)
Aspect Ratio: 16:9
</generation_settings>
```

### Output Files

- `assembled_prompt.md` - Full text prompt
- `generation_config.json` - API parameters:
  ```json
  {
    "image_size": "2K",
    "aspect_ratio": "16:9",
    "source_images": ["path/to/ref1.png", "path/to/ref2.png"]
  }
  ```

### Reference Image Limits

- Maximum 14 reference images total across all bundles
- Images collected from:
  - Style bundle `sources/` directories
  - Image-specific `sources/` directory

---

## 11. Complete Reference Flow

```
library/doxai/d-*.md
       │
       │ evidence:
       │   - source: e-*
       ▼
library/evidence/e-*.md

library/logos.yaml
       │
       │ edges:
       │   - source: d-*
       │     target: d-*
       │     type: supports
       ▼
library/diegeses/n-*.md
       │
       │ sections:
       │   section_key:
       │     doxai: [d-*, d-*]
       │ walks:
       │   canonical: [section1, section2]
       ▼
theses/{name}/config.yaml
       │
       │ diegesis: n-*
       │ walk: canonical
       ▼
theses/{name}/outputs/presentation/slides/{n}-{slug}/slide.md
       │
       │ doxai: [d-*, d-*]
       │ images:
       │   - id: main
       │     selected: outputs/*.png
       ▼
slides/{n}-{slug}/images/main/definition.md
       │
       │ styles: [terminal, terminal/code]
       │ custom_constraints: |
       │   - ONLY use palette colors
       ▼
styles/terminal/definition.md
       │
       │ requires: [foundations/colors]
       ▼
styles/foundations/colors/definition.md
       │
       ▼
[ASSEMBLED PROMPT] → Gemini API → Generated Image
```

---

## 12. Schema Reference

All schemas are canonically defined in `library/schema.yaml`:

| Section | Defines |
|---------|---------|
| `node_types` | Prefixes and locations for doxai, evidence, diegeses |
| `diegesis_schema` | Required/optional fields for diegesis frontmatter |
| `thesis_schema` | Config fields for theses |
| `edge_fields` | Required/optional fields for logos edges |
| `edge_types` | Canonical relationship types with descriptions |
| `tag_prefixes` | Controlled vocabulary for domain tags |

---

## 13. Quick Reference Tables

### Entity Prefixes

| Entity | Prefix | Location |
|--------|--------|----------|
| Doxa | `d-` | `library/doxai/` |
| Evidence | `e-` | `library/evidence/` |
| Diegesis | `n-` | `library/diegeses/` |
| Phantasia | `p-` | `library/phantasiai/` |
| Katalepsis | `k-` | `library/katalepseis/` |
| Exploration | `x-` | `library/explorations/` |

### Cross-References

| From | To | Via Field |
|------|----|-----------|
| Doxa | Evidence | `evidence[].source` |
| Doxa | Diegesis | `diegeses[]` |
| Diegesis | Doxa | `sections[].doxai[]` |
| Thesis | Diegesis | `diegesis` |
| Slide | Doxa | `doxai[]` |
| Slide | Image | `images[].id` |
| Image | Style | `styles[]` |
| Style | Style | `requires[]` |
| Logos Edge | Doxa | `source`, `target` |

### Image Placements

| Value | Description |
|-------|-------------|
| `full-bleed` | Image fills entire slide |
| `right-half` | Image on right, text on left |
| `left-half` | Image on left, text on right |
| `background` | Image behind content |

### Resolution Options

| Value | Dimensions (16:9) |
|-------|-------------------|
| `1k` | 1376 × 768 |
| `2k` | 2752 × 1536 |
| `4k` | 5504 × 3072 |
