#!/usr/bin/env python3
"""
Render an HTML slide to a PNG screenshot using headless Playwright.

Resolves data-image-id references to local file paths, injects a stub
dox.slide API, and captures the initial visual state at the target resolution.

Usage:
    python factory/scripts/render_html_slide.py \
        --slide-dir theses/{name}/outputs/presentation/slides/{slug} \
        --output rendered.png \
        --width 1920 --height 1080
"""

import argparse
import re
import sys
import tempfile
from pathlib import Path

# Add parent for utils import
sys.path.insert(0, str(Path(__file__).parent))
from utils import parse_frontmatter


DOX_STUB = """\
<script>
window.dox = {
  slide: {
    steps: function() {},
    onStep: function() {},
    onEnter: function() {},
    onExit: function() {},
    imageUrl: function(id) { return ''; },
    currentStep: 0,
    totalSteps: 0,
  }
};
</script>
"""


def resolve_image_refs_local(html: str, slide_dir: Path, images: list[dict]) -> str:
    """Replace data-image-id references with local file:// paths."""
    for img_config in images:
        if not isinstance(img_config, dict):
            continue
        image_id = img_config.get('id')
        selected = img_config.get('selected')
        if not image_id or not selected:
            continue

        local_path = slide_dir / 'images' / image_id / selected
        if not local_path.exists():
            continue

        file_uri = local_path.as_uri()

        # Replace <img data-image-id="X" ...> with src set to the local path
        # Handle both self-closing and regular img tags
        pattern = rf'(<[^>]*\bdata-image-id\s*=\s*["\']?{re.escape(image_id)}["\']?[^>]*?)(/?>)'

        def replacer(m):
            tag = m.group(1)
            close = m.group(2)
            # Remove existing src if present
            tag = re.sub(r'\bsrc\s*=\s*["\'][^"\']*["\']', '', tag)
            # Remove data-image-id attribute
            tag = re.sub(rf'\bdata-image-id\s*=\s*["\']?{re.escape(image_id)}["\']?', '', tag)
            return f'{tag} src="{file_uri}"{close}'

        html = re.sub(pattern, replacer, html, flags=re.IGNORECASE)

    return html


def wrap_html(fragment: str, width: int, height: int, global_css: str = "") -> str:
    """Wrap an HTML fragment in a full document with fixed viewport."""
    global_style_block = f"\n  <style id=\"dox-global-styles\">\n{global_css}\n  </style>" if global_css.strip() else ""
    return f"""\
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    html, body {{ width: {width}px; height: {height}px; overflow: hidden; background: #000; }}
  </style>{global_style_block}
</head>
<body>
{DOX_STUB}
{fragment}
</body>
</html>"""


def render_slide(slide_dir: Path, output_path: Path, width: int = 1920, height: int = 1080) -> bool:
    """Render an HTML slide to PNG. Returns True on success."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("WARNING: playwright not installed. Run: uv pip install playwright && playwright install chromium", file=sys.stderr)
        return False

    slide_html_path = slide_dir / "slide.html"
    if not slide_html_path.exists():
        print(f"WARNING: No slide.html found in {slide_dir}", file=sys.stderr)
        return False

    # Read HTML content
    html_content = slide_html_path.read_text()

    # Read slide.md frontmatter for image config
    slide_md = slide_dir / "slide.md"
    images = []
    if slide_md.exists():
        frontmatter, _ = parse_frontmatter(slide_md.read_text())
        images = frontmatter.get('images', [])

    # Read global CSS (styles/html/global.css relative to presentation root)
    presentation_dir = slide_dir.parent.parent  # slides/{slug} -> outputs/presentation
    global_css_path = presentation_dir / "styles" / "html" / "global.css"
    global_css = global_css_path.read_text() if global_css_path.exists() else ""

    # Resolve image references to local file paths
    resolved_html = resolve_image_refs_local(html_content, slide_dir, images)

    # Full documents render as-is (with dox stub injected); fragments get wrapped
    trimmed = resolved_html.lstrip()[:200].lower()
    is_full_doc = trimmed.startswith('<!doctype') or trimmed.startswith('<html')

    if is_full_doc:
        # Inject dox stub and global styles into existing document
        global_style_block = f'<style id="dox-global-styles">\n{global_css}\n</style>\n' if global_css.strip() else ''
        injection = global_style_block + DOX_STUB
        if '</head>' in resolved_html.lower():
            full_html = re.sub(r'</head>', injection + '\n</head>', resolved_html, count=1, flags=re.IGNORECASE)
        else:
            full_html = injection + '\n' + resolved_html
    else:
        full_html = wrap_html(resolved_html, width, height, global_css)

    # Write to temp file and render
    with tempfile.NamedTemporaryFile(suffix='.html', delete=False, mode='w') as tmp:
        tmp.write(full_html)
        tmp_path = Path(tmp.name)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={'width': width, 'height': height})
            page.goto(tmp_path.as_uri())
            page.wait_for_load_state('networkidle')
            # Full documents may have animations; capture initial state
            page.wait_for_timeout(1000 if is_full_doc else 500)

            output_path.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(output_path))
            browser.close()

        return True
    except Exception as e:
        print(f"WARNING: Playwright render failed: {e}", file=sys.stderr)
        return False
    finally:
        tmp_path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description="Render an HTML slide to PNG")
    parser.add_argument("--slide-dir", type=Path, required=True, help="Path to slide directory")
    parser.add_argument("--output", type=Path, required=True, help="Output PNG path")
    parser.add_argument("--width", type=int, default=1920, help="Viewport width (default: 1920)")
    parser.add_argument("--height", type=int, default=1080, help="Viewport height (default: 1080)")
    args = parser.parse_args()

    if not args.slide_dir.is_dir():
        print(f"Error: Slide directory not found: {args.slide_dir}", file=sys.stderr)
        return 1

    success = render_slide(args.slide_dir, args.output, args.width, args.height)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
