#!/usr/bin/env python3
"""
Bootstrap a new presentation with the standard factory structure.

Creates:
- config.yaml with metadata
- CLAUDE.md with presentation context
- slides/ directory with title slide
- styles/ directory with basic structure
- templates/ directory

Usage:
    python factory/scripts/new_presentation.py my-presentation --title "My Presentation Title"
    python factory/scripts/new_presentation.py my-presentation --title "Title" --duration 30
"""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent


def create_config(presentation_dir: Path, name: str, title: str, duration: int):
    """Create config.yaml with presentation metadata."""
    config = f'''name: {name}
title: "{title}"
duration: {duration}

description: |
  Add your presentation description here.

timing:
  total: {duration}
  buffer: 3
  acts: []

constraints:
  content: []
  pacing:
    - "Opening should hook, not explain"
    - "Problem section builds tension"
    - "Solution provides relief"

metaphor:
  theme: null
  mappings: {{}}
'''
    (presentation_dir / "config.yaml").write_text(config)


def create_claude_md(presentation_dir: Path, name: str, title: str):
    """Create CLAUDE.md with presentation context."""
    content = f'''# {title}

## Quick Reference

- **Config**: `config.yaml` - All metadata, timing, constraints
- **Slides**: `slides/` - Slide content
- **Styles**: `styles/` - Visual style definitions
- **Template**: `templates/` - PPTX template

## Slide Structure

Each slide has a `slide.md` for content and `images/{{id}}/` bundles for visuals:

```
slides/{{number}}-{{slug}}/
├── slide.md                    # Content + image relationships
└── images/
    └── main/                   # Image bundle
        ├── definition.md       # Visual description, styles
        ├── sources/            # Reference images
        └── outputs/            # Generated images
```

### slide.md Schema

```yaml
---
text:
  title: "Slide Title"
  body: |
    Slide body text...

speaker_notes: |
  What to say when presenting...

images:
  - id: main
    selected: outputs/selected.png
    placement: full-bleed
    purpose: "Why this slide needs this image"
---
```

### images/{{id}}/definition.md Schema

```yaml
---
styles:
  - diagram/base
config:
  resolution: 2k
---

Visual description of what to generate...
```
'''
    (presentation_dir / "CLAUDE.md").write_text(content)


def create_slide_template(templates_dir: Path):
    """Create slide template directory with v2 structure."""
    slide_template = templates_dir / "slide-template"
    slide_template.mkdir(parents=True, exist_ok=True)

    # Create slide.md
    (slide_template / "slide.md").write_text('''---
text:
  title: "Slide Title"
  body: |
    - Bullet point 1
    - Bullet point 2
    - Bullet point 3

speaker_notes: |
  What you'll say when presenting this slide.

  [PAUSE]

  Continue with the next point...

images:
  - id: main
    placement: full-bleed
    purpose: "Visual representation for this slide"
---
''')

    # Create images/main structure
    images_main = slide_template / "images" / "main"
    images_main.mkdir(parents=True, exist_ok=True)
    (images_main / "outputs").mkdir(exist_ok=True)
    (images_main / "sources").mkdir(exist_ok=True)

    (images_main / "definition.md").write_text('''---
styles: []
config:
  resolution: 2k
---

Describe the visual for this slide here.
''')


def create_title_slide(slides_dir: Path, title: str):
    """Create the title slide (00-title-slide) with v2 structure."""
    title_dir = slides_dir / "00-title-slide"
    title_dir.mkdir(parents=True, exist_ok=True)

    # Create slide.md
    (title_dir / "slide.md").write_text(f'''---
text:
  title: "{title}"
  body: |
    **Subtitle:** Your Name

speaker_notes: |
  Welcome everyone. Today we're going to talk about...

images:
  - id: main
    placement: full-bleed
    purpose: "Title slide visual"
---
''')

    # Create images/main structure
    images_main = title_dir / "images" / "main"
    images_main.mkdir(parents=True, exist_ok=True)
    (images_main / "outputs").mkdir(exist_ok=True)
    (images_main / "sources").mkdir(exist_ok=True)

    (images_main / "definition.md").write_text('''---
styles: []
config:
  resolution: 2k
---

Title slide visual - typically uses a template or brand-specific design.
''')


def create_styles_structure(styles_dir: Path):
    """Create basic styles directory structure."""
    # Global constraints
    constraints_dir = styles_dir / "constraints" / "layout"
    constraints_dir.mkdir(parents=True, exist_ok=True)
    (constraints_dir / "definition.md").write_text('''# Layout Constraints

## Background
- Background must be Pure White (`#FFFFFF`)

## Typography
- Use clean, readable fonts
- Headers should be larger than body text
''')

    # Global palette placeholder
    global_dir = styles_dir / "global" / "palette"
    global_dir.mkdir(parents=True, exist_ok=True)
    (global_dir / "definition.md").write_text('''# Color Palette

Define your brand colors here:

| Color Name | Hex Code | Usage |
|------------|----------|-------|
| Primary | `#000000` | Headers, key labels |
| Secondary | `#666666` | Body text |
| Accent | `#0066CC` | Highlights |
''')

    # Diagram base placeholder
    diagram_dir = styles_dir / "diagram" / "base"
    diagram_dir.mkdir(parents=True, exist_ok=True)
    (diagram_dir / "definition.md").write_text('''# Diagram Base Style

Technical diagram style definition.

## Visual Characteristics
- Clean, flat design
- Minimal shadows
- Clear hierarchy
''')
    (diagram_dir / "sources").mkdir(exist_ok=True)


def main():
    parser = argparse.ArgumentParser(
        description="Bootstrap a new presentation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        "name",
        help="Presentation name (used as directory name)"
    )
    parser.add_argument(
        "--title",
        required=True,
        help="Presentation title"
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=25,
        help="Presentation duration in minutes (default: 25)"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing presentation"
    )

    args = parser.parse_args()

    presentation_dir = PROJECT_ROOT / "theses" / args.name

    if presentation_dir.exists() and not args.force:
        print(f"Error: Presentation '{args.name}' already exists at {presentation_dir}")
        print("Use --force to overwrite")
        sys.exit(1)

    print(f"Creating presentation '{args.name}' at {presentation_dir}")

    # Create directories
    presentation_dir.mkdir(parents=True, exist_ok=True)
    slides_dir = presentation_dir / "slides"
    styles_dir = presentation_dir / "styles"
    templates_dir = presentation_dir / "templates"
    build_dir = presentation_dir / "build"

    slides_dir.mkdir(exist_ok=True)
    styles_dir.mkdir(exist_ok=True)
    templates_dir.mkdir(exist_ok=True)
    build_dir.mkdir(exist_ok=True)

    # Create files
    create_config(presentation_dir, args.name, args.title, args.duration)
    create_claude_md(presentation_dir, args.name, args.title)
    create_slide_template(templates_dir)
    create_title_slide(slides_dir, args.title)
    create_styles_structure(styles_dir)

    # Create .gitkeep for build
    (build_dir / ".gitkeep").write_text("# Generated builds go here\n")

    print(f"""
✓ Created presentation '{args.name}'

Structure:
  {presentation_dir}/
  ├── config.yaml
  ├── CLAUDE.md
  ├── slides/
  │   └── 00-title-slide/
  ├── styles/
  │   ├── constraints/layout/
  │   ├── global/palette/
  │   └── diagram/base/
  ├── templates/
  │   └── slide-template/
  └── build/

Next steps:
  1. Load its context: python .pi/skills/presentation-context/scripts/load_context.py {args.name}
  2. Add a PPTX template to templates/
  3. Define your styles in styles/
  4. Create slides by copying templates/slide-template/
  5. Generate visuals: python3 factory/scripts/generate_visuals.py --slide 0 --output
  6. Compile: python3 factory/scripts/compile.py
""")

    return 0


if __name__ == "__main__":
    sys.exit(main())
