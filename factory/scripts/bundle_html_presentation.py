#!/usr/bin/env python3
"""
Bundle an HTML-slide presentation into a single self-contained, shareable HTML file.

Each slide's slide.html is embedded in its own sandboxed <iframe srcdoc>, exactly
like the web app does, so per-slide JS/CSS stays isolated. Into every iframe we
inject:
  - styles/html/global.css   (the CSS variables the slides depend on)
  - a minimal `dox.slide` shim implementing steps()/onStep()/onEnter()/onExit()
    plus a postMessage bridge for step advance + ready signalling.

The outer document is a deck shell: keyboard nav (Left/Right/Space advance steps
within a slide, then cross to the next/prev slide), a slide counter, a progress
bar, and an optional speaker-notes panel (toggle with 'N').

Mirrors the web app's slide-mount contract (apps/web/frontend/src/lib/utils/
htmlSlideMount.ts + slideController.ts): same global.css injection, same
steps()/onStep()/onEnter()/onExit() runtime surface, same DOX_* postMessage
protocol. Keep this shim in sync if that contract changes.

Scope: HTML-layout slides only. Slides that resolve images via data-image-id /
dox.imageUrl() are flagged with a warning (the share file has no asset server);
for decks with image-layout slides, use compile.py to produce PNG/PPTX instead.

Reuses the shared helpers in utils.py (get_slide_order, find_slide_dir,
parse_frontmatter, load_config) so slide ordering matches compile.py exactly.

Usage:
    # CDN build (D3 + fonts from web; smallest file)
    python3 factory/scripts/bundle_html_presentation.py -p observatory --notes

    # Offline build (inlines D3 so chart slides render with no network)
    python3 factory/scripts/bundle_html_presentation.py -p observatory --notes --vendor

Flags:
    -p/--presentation  Presentation slug (required)
    -o/--output        Output path (default: outputs/presentation/{name}-bundle.html)
    --notes            Embed speaker notes (toggle in-deck with 'N')
    --vendor           Inline D3 for offline chart rendering (larger file)

In-deck navigation: ←/→/space step then cross slides · F fill · N notes · Home/End.
"""

import argparse
import html
import json
import re
import sys
import urllib.request
from pathlib import Path

D3_URL = "https://d3js.org/d3.v7.min.js"
_d3_cache = {"js": None}


def get_d3() -> str:
    if _d3_cache["js"] is None:
        print("Vendoring D3 (one-time download)...", file=sys.stderr)
        req = urllib.request.Request(D3_URL, headers={"User-Agent": "Mozilla/5.0"})
        _d3_cache["js"] = urllib.request.urlopen(req, timeout=30).read().decode("utf-8")
    return _d3_cache["js"]


def inline_d3(slide_html: str) -> str:
    """Replace the D3 <script src=...> tag with the inlined library."""
    if "d3js.org" not in slide_html and "d3.v7" not in slide_html:
        return slide_html
    js = get_d3()
    return re.sub(
        r'<script[^>]*src=["\']https?://[^"\']*d3[^"\']*["\'][^>]*>\s*</script>',
        lambda _: "<script>\n" + js + "\n</script>",
        slide_html,
        flags=re.I,
    )

from utils import (
    get_presentation_path,
    get_slide_order,
    find_slide_dir,
    parse_frontmatter,
    load_config,
)


BRIDGE = """
<script>
(function () {
  var _total = 0, _current = 0, _stepCbs = {}, _enterCbs = [], _exitCbs = [];
  window.dox = window.dox || {};
  window.dox.slide = {
    steps: function (n) { _total = (n > 0) ? n : 0; parent.postMessage({type:'DOX_STEPS', total:_total}, '*'); },
    onStep: function (i, cb) { if (i >= 1) _stepCbs[i] = cb; },
    onEnter: function (cb) { _enterCbs.push(cb); },
    onExit: function (cb) { _exitCbs.push(cb); },
    imageUrl: function () { return ''; },
    get currentStep() { return _current; },
    get totalSteps() { return _total; }
  };
  function fire(i) { var cb = _stepCbs[i]; if (cb) { try { cb(); } catch (e) { console.error(e); } } }
  window.__doxEnter = function () { _current = 0; _enterCbs.forEach(function (c){ try{c();}catch(e){console.error(e);} }); };
  window.__doxAdvance = function () { if (_total > 0 && _current < _total) { _current++; fire(_current); return true; } return false; };
  window.__doxFill = function () { while (_total > 0 && _current < _total) { _current++; fire(_current); } };
  window.addEventListener('message', function (e) {
    var d = e.data || {};
    if (d.type === 'DOX_ENTER') window.__doxEnter();
    else if (d.type === 'DOX_ADVANCE') window.__doxAdvance();
    else if (d.type === 'DOX_FILL') window.__doxFill();
  });
  // Signal ready so the shell can drive enter/advance.
  parent.postMessage({type:'DOX_READY'}, '*');
})();
</script>
"""


def wrap_slide(slide_html: str, global_css: str) -> str:
    """Embed one slide's HTML as a full document with global css + bridge injected."""
    style_tag = f'<style id="dox-global-styles">\n{global_css}\n</style>'
    inject = style_tag + "\n" + BRIDGE

    # Full document? inject before </head> (or </body>); else wrap as fragment.
    if re.search(r"<html[\s>]", slide_html, re.I):
        if re.search(r"</head>", slide_html, re.I):
            return re.sub(r"</head>", inject + "\n</head>", slide_html, count=1, flags=re.I)
        if re.search(r"<body[^>]*>", slide_html, re.I):
            return re.sub(r"(<body[^>]*>)", r"\1\n" + inject, slide_html, count=1, flags=re.I)
        return inject + slide_html
    # Fragment
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        + inject
        + "</head><body>"
        + slide_html
        + "</body></html>"
    )


def build(presentation: str, out_path: Path, include_notes: bool, vendor: bool) -> None:
    pres_path = get_presentation_path(presentation)
    slides_dir = pres_path / "outputs" / "presentation" / "slides"
    css_path = pres_path / "outputs" / "presentation" / "styles" / "html" / "global.css"
    global_css = css_path.read_text() if css_path.exists() else ""
    if not global_css:
        print(f"WARN: no global.css at {css_path}", file=sys.stderr)

    config = load_config(pres_path)
    order = get_slide_order(slides_dir, config)
    slides = []
    for slug in order:
        sdir = find_slide_dir(slides_dir, slug)
        if not sdir:
            print(f"WARN: slide dir not found for '{slug}' — skipping", file=sys.stderr)
            continue
        md = sdir / "slide.md"
        html_file = sdir / "slide.html"
        if not html_file.exists():
            print(f"WARN: no slide.html for '{slug}' — skipping (image-only slide)", file=sys.stderr)
            continue
        raw = html_file.read_text()
        if vendor:
            raw = inline_d3(raw)
        if re.search(r"data-image-id|getThesisAssetUrl|\bimageUrl\(", raw):
            print(f"WARN: '{slug}' references external image assets; bundle may render incomplete", file=sys.stderr)
        fm, _ = parse_frontmatter(md.read_text()) if md.exists() else ({}, "")
        text_fm = fm.get("text") if isinstance(fm.get("text"), dict) else {}
        title = (text_fm or {}).get("title", slug)
        notes = (fm.get("speaker_notes", "") or "") if include_notes else ""
        slides.append({
            "slug": slug,
            "title": title,
            "srcdoc": wrap_slide(raw, global_css),
            "notes": notes,
        })

    if not slides:
        print("ERROR: no slides bundled", file=sys.stderr)
        sys.exit(1)

    payload = json.dumps(slides)
    doc = SHELL.replace("__TITLE__", html.escape(presentation)) \
              .replace("__SLIDES__", payload) \
              .replace("__NOTES__", "true" if include_notes else "false")
    out_path.write_text(doc)
    print(f"Bundled {len(slides)} slides → {out_path}  ({out_path.stat().st_size // 1024} KB)")


SHELL = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  :root { --bg:#06060a; }
  * { margin:0; padding:0; box-sizing:border-box; }
  html, body { height:100%; background:var(--bg); overflow:hidden; font-family:system-ui, sans-serif; }
  #stage { position:fixed; inset:0; display:flex; align-items:center; justify-content:center; }
  /* 16:9 letterboxed slide surface */
  #frameWrap { position:relative; width:100vw; height:56.25vw; max-height:100vh; max-width:177.78vh; }
  iframe { position:absolute; inset:0; width:100%; height:100%; border:0; background:var(--bg); }
  iframe.hidden { display:none; }
  #bar { position:fixed; left:0; top:0; height:3px; background:#c8965a; width:0%; transition:width .25s; z-index:10; }
  #hud { position:fixed; bottom:10px; right:14px; font-family:'IBM Plex Mono', monospace; font-size:12px;
         color:#7a7a86; z-index:10; user-select:none; }
  #hint { position:fixed; bottom:10px; left:14px; font-size:11px; color:#3a3a46; z-index:10;
          font-family:system-ui, sans-serif; }
  #notes { position:fixed; left:0; right:0; bottom:0; max-height:38vh; overflow:auto; z-index:20;
           background:rgba(8,8,14,.96); border-top:1px solid #1c1c28; color:#cfcfd6; padding:14px 20px;
           font-family:system-ui, sans-serif; font-size:13px; line-height:1.5; white-space:pre-wrap; display:none; }
  #notes.show { display:block; }
  #notes h4 { color:#c8965a; font-size:11px; letter-spacing:.1em; text-transform:uppercase; margin-bottom:8px; }
</style>
</head>
<body>
<div id="bar"></div>
<div id="stage"><div id="frameWrap"></div></div>
<div id="hud"></div>
<div id="hint">← → / space · F fill · N notes · Home</div>
<div id="notes"></div>
<script>
  const SLIDES = __SLIDES__;
  const HAS_NOTES = __NOTES__;
  const wrap = document.getElementById('frameWrap');
  const hud = document.getElementById('hud');
  const bar = document.getElementById('bar');
  const notesEl = document.getElementById('notes');

  let idx = 0;
  const frames = [];      // iframe per slide
  const ready = [];       // bool per slide
  const totals = [];      // step count per slide
  const cur = [];         // current step per slide

  SLIDES.forEach((s, i) => {
    const f = document.createElement('iframe');
    f.setAttribute('sandbox', 'allow-scripts allow-same-origin');
    f.srcdoc = s.srcdoc;
    f.className = i === 0 ? '' : 'hidden';
    wrap.appendChild(f);
    frames.push(f); ready.push(false); totals.push(0); cur.push(0);
  });

  window.addEventListener('message', (e) => {
    const i = frames.findIndex(f => f.contentWindow === e.source);
    if (i < 0) return;
    const d = e.data || {};
    if (d.type === 'DOX_READY') {
      ready[i] = true;
      if (i === idx) enter(i);
    } else if (d.type === 'DOX_STEPS') {
      totals[i] = d.total || 0;
      updateHud();
    }
  });

  function post(i, type) { try { frames[i].contentWindow.postMessage({type}, '*'); } catch(_){} }
  function enter(i) { cur[i] = 0; post(i, 'DOX_ENTER'); updateHud(); }

  function show(i) {
    frames[idx].classList.add('hidden');
    idx = i;
    frames[idx].classList.remove('hidden');
    if (ready[idx]) enter(idx);
    updateHud(); updateNotes();
  }

  function next() {
    // advance a step inside current slide; if none left, go to next slide
    if (cur[idx] < totals[idx]) { cur[idx]++; post(idx, 'DOX_ADVANCE'); updateHud(); return; }
    if (idx < SLIDES.length - 1) show(idx + 1);
  }
  function prev() {
    // simplest model: go to previous slide (fully revealed), else nothing
    if (idx > 0) { show(idx - 1); cur[idx] = totals[idx]; post(idx, 'DOX_FILL'); updateHud(); }
  }
  function fill() { while (cur[idx] < totals[idx]) { cur[idx]++; } post(idx, 'DOX_FILL'); updateHud(); }

  function updateHud() {
    hud.textContent = (idx + 1) + ' / ' + SLIDES.length +
      (totals[idx] ? '   step ' + cur[idx] + '/' + totals[idx] : '');
    bar.style.width = ((idx) / (SLIDES.length - 1) * 100) + '%';
  }
  function updateNotes() {
    if (!HAS_NOTES) return;
    const n = SLIDES[idx].notes || '(no notes)';
    notesEl.innerHTML = '<h4>' + (SLIDES[idx].title || '') + '</h4>' +
      n.replace(/&/g,'&amp;').replace(/</g,'&lt;');
  }

  document.addEventListener('keydown', (e) => {
    switch (e.key) {
      case 'ArrowRight': case ' ': case 'PageDown': e.preventDefault(); next(); break;
      case 'ArrowLeft': case 'PageUp': e.preventDefault(); prev(); break;
      case 'f': case 'F': fill(); break;
      case 'Home': show(0); break;
      case 'End': show(SLIDES.length - 1); fill(); break;
      case 'n': case 'N': if (HAS_NOTES) notesEl.classList.toggle('show'); break;
    }
  });

  updateHud();
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser(description="Bundle HTML slides into one shareable file")
    ap.add_argument("-p", "--presentation", default=None)
    ap.add_argument("-o", "--output", default=None)
    ap.add_argument("--notes", action="store_true", help="Embed speaker notes (toggle with N)")
    ap.add_argument("--vendor", action="store_true", help="Inline D3 so chart slides work offline (larger file)")
    args = ap.parse_args()

    presentation = args.presentation
    pres_path = get_presentation_path(presentation)
    out = Path(args.output) if args.output else (
        pres_path / "outputs" / "presentation" / f"{presentation}-bundle.html"
    )
    build(presentation, out, args.notes, args.vendor)


if __name__ == "__main__":
    main()
