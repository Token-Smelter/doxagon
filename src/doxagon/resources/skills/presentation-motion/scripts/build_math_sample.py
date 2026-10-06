"""Build an offline mathematical explanation from coordinates, not generated images."""

from __future__ import annotations

import argparse
import base64
from hashlib import sha256
from html import escape
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FONTS = {
    "MotionSerif": "newsreader-latin.woff2",
    "MotionSans": "space-grotesk-latin.woff2",
    "MotionMono": "jetbrains-mono-latin.woff2",
}


def inline_script(text: str) -> str:
    return "<script>" + text.replace("</script", "<\\/script") + "</script>"


PLANE_FIGURE = """<figure data-math-lesson id="math-lesson" data-style="night">
<div class="math-stage">
<div class="math-plane"><svg></svg><p class="math-transformation"></p></div>
<div class="math-narration">
<p class="math-phase"></p><h2 class="math-heading">Start with two basis vectors.</h2>
<p class="math-explanation"></p>
<math class="math-live-matrix" aria-label="Current transformation matrix"></math>
<p class="math-relation"></p>
<dl class="math-readouts"><dt>Input x,y</dt><dd class="math-readout-input"></dd><dt>Image x,y</dt><dd class="math-readout-output"></dd><dt>Direction</dt><dd class="math-direction-test"></dd></dl>
<div class="math-explorer" hidden>
<label for="math-angle">Explore a direction <output class="math-angle-value"></output></label>
<input data-math-angle id="math-angle" type="range" min="0" max="180" step="0.1" aria-label="Vector angle in degrees">
<div class="math-directions"><button data-math-direction="45">45° · factor 3</button><button data-math-direction="135">135° · factor 1</button></div>
</div>
<div class="math-conclusion" aria-hidden="true">
<math aria-label="In the eigenvector basis, inverse P times A times P equals diagonal three and one"><mrow><msup><mi>P</mi><mn>−1</mn></msup><mi>A</mi><mi>P</mi><mo>=</mo><mo>[</mo><mtable><mtr><mtd><mn>3</mn></mtd><mtd><mn>0</mn></mtd></mtr><mtr><mtd><mn>0</mn></mtd><mtd><mn>1</mn></mtd></mtr></mtable><mo>]</mo></mrow></math>
<p>P has columns v₊ and v₋. Both eigenvalues here are positive; in general an eigenvalue may reverse a vector or send it to zero.</p>
</div>
</div></div></figure>"""
SPACE_FIGURE = """<figure data-space-lesson id="space-lesson" data-style="night">
<div class="math-stage">
<div class="math-plane"><svg></svg><p class="math-transformation"></p></div>
<div class="math-narration">
<p class="math-phase"></p><h2 class="math-heading">Three basis vectors span space.</h2>
<p class="math-explanation"></p>
<math class="math-live-matrix" aria-label="Current transformation matrix"></math>
<p class="math-relation"></p>
<dl class="math-readouts"><dt>Volume, det</dt><dd class="space-volume"></dd><dt>e₁ turned</dt><dd class="space-turned"></dd><dt>Along d</dt><dd class="space-factor"></dd></dl>
<div class="space-orbit">
<label for="space-orbit">Turn the view <output class="space-orbit-value"></output></label>
<input data-space-orbit id="space-orbit" type="range" min="-180" max="180" step="0.5" value="0">
<button data-space-reset>Reset view</button>
</div>
<div class="math-conclusion" hidden>
<math aria-label="p of lambda equals lambda cubed minus three lambda squared minus three lambda minus four"><mrow><mi>p</mi><mo>(</mo><mi>λ</mi><mo>)</mo><mo>=</mo><msup><mi>λ</mi><mn>3</mn></msup><mo>−</mo><mn>3</mn><msup><mi>λ</mi><mn>2</mn></msup><mo>−</mo><mn>3</mn><mi>λ</mi><mo>−</mo><mn>4</mn></mrow></math>
<math aria-label="which equals lambda minus four times lambda squared plus lambda plus one"><mrow><mo>=</mo><mo>(</mo><mi>λ</mi><mo>−</mo><mn>4</mn><mo>)</mo><mo>(</mo><msup><mi>λ</mi><mn>2</mn></msup><mo>+</mo><mi>λ</mi><mo>+</mo><mn>1</mn><mo>)</mo></mrow></math>
<p>λ² + λ + 1 has no real roots, so the plane perpendicular to d turns instead of keeping a line. A turns that plane a third of a revolution; det A = 4 is the product of the stretch and the rotation.</p>
</div>
</div></div></figure>"""

PAGE_CSS = """html{background:#101b2a;color:#e8eff7}body{margin:0;font:16px/1.5 MotionSans,sans-serif}main{max-width:1190px;margin:auto;padding:28px 24px}header{display:flex;align-items:start;gap:24px;justify-content:space-between}h1{font:500 clamp(32px,4.8vw,52px)/1.08 MotionSerif,serif;max-width:21ch;margin:0 0 14px}header p{max-width:62ch;color:#a9b9cb;margin:0}header label{display:grid;gap:6px;font-size:13px;min-width:145px}figure{margin:12px 0!important}button,select{font:inherit;color:inherit;background:#172638;border:1px solid #6a8099;border-radius:3px;min-height:44px;padding:7px 12px}button:hover{background:#263c53}button[aria-pressed=true]{border-color:#edc36a;color:#edc36a}button:disabled{opacity:.5}nav{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0 20px}.math-controls{display:flex;align-items:center;flex-wrap:wrap;gap:16px}.math-controls input{flex:1;min-width:140px;accent-color:#edc36a}.math-controls output{font-family:MotionMono,monospace;min-width:7ch}button:focus-visible,select:focus-visible,input:focus-visible{outline:3px solid #edc36a;outline-offset:3px}footer{font-size:13px;color:#a9b9cb;margin-top:24px;border-top:1px solid #3a506b;padding-top:16px;max-width:75ch}::selection{background:#edc36a;color:#101b2a}@media(max-width:650px){main{padding:20px 14px}header{display:block}header label{display:flex;align-items:center;margin:16px 0}h1{font-size:36px}nav button{font-size:13px}}"""

LESSONS = {
    "plane": {
        "prefix": "math",
        "global": "mathLesson",
        "event": "math:state",
        "factory": "DoxMathLesson",
        "root": "math-lesson",
        "figure": PLANE_FIGURE,
        "scripts": ("model.js", "lesson.js"),
        "holds": ["Basis", "Columns", "Transform", "Find directions", "Stretch", "Eigenbasis"],
        "title": "What makes a vector an eigenvector?",
        "intro": "Follow the geometry first. The algebra will name what stays unchanged.",
        "footer": "Original mathematical sample: A = [[2, 1], [1, 2]]. SVG geometry and live MathML, driven by one clock. The angle explorer is available at “Find directions”.",
        "report": {"matrix": [[2, 1], [1, 2]], "holds": [0, 6, 14, 23, 32, 40], "renderer": "svg-mathml"},
    },
    "space": {
        "prefix": "space",
        "global": "spaceLesson",
        "event": "space:state",
        "factory": "DoxSpaceLesson",
        "root": "space-lesson",
        "figure": SPACE_FIGURE,
        "scripts": ("space-model.js", "space.js"),
        "holds": ["Basis", "Columns", "Twist", "Down the diagonal", "Invariant line"],
        "title": "What does a 3 × 3 matrix keep?",
        "intro": "Turn a cube about its diagonal while stretching that diagonal. Watch which line survives.",
        "footer": "Original mathematical sample: A = [[1, 1, 2], [2, 1, 1], [1, 2, 1]], a third of a turn about (1, 1, 1) combined with a fourfold stretch along it. Perspective-projected SVG from one 3D model; drag the figure or use “Turn the view”.",
        "report": {
            "matrix": [[1, 1, 2], [2, 1, 1], [1, 2, 1]],
            "holds": [0, 8, 18, 28, 40],
            "renderer": "svg-projected-3d-mathml",
        },
    },
}


def fonts_css() -> str:
    return "\n".join(
        f"@font-face{{font-family:{family};src:url(data:font/woff2;base64,{base64.b64encode((ROOT / 'vendor/fonts' / name).read_bytes()).decode()});font-weight:100 900;}}"
        for family, name in FONTS.items()
    )


def parts(lesson: str) -> dict:
    """Lesson pieces shared by the standalone page and the consolidated sample sheet."""
    spec = LESSONS[lesson]
    p = spec["prefix"]
    nav = (
        f'<nav aria-label="{escape(spec["title"])} holds">'
        + "".join(f'<button data-{p}-hold="{i}">{i + 1}. {label}</button>' for i, label in enumerate(spec["holds"]))
        + "</nav>"
    )
    style = (
        f'<label>Visual style<select id="{p}-style"><option value="night">Night board</option>'
        '<option value="paper">Paper diagram</option></select></label>'
    )
    transport = (
        f'<div class="math-controls"><button id="{p}-play">Play explanation</button><label for="{p}-time">Time</label>'
        f'<input id="{p}-time" type="range" min="0" max="40" step="0.05" value="0"><output id="{p}-clock">0.0 s</output></div>'
    )
    controls = f"""<script>
(()=>{{const lesson=window.{spec["global"]}, plate=document.querySelector('#{spec["root"]}');
const play=document.querySelector('#{p}-play'), scrub=document.querySelector('#{p}-time');
document.querySelector('#{p}-style').addEventListener('change',e=>lesson.setStyle(e.target.value));
document.querySelectorAll('[data-{p}-hold]').forEach(button=>button.addEventListener('click',()=>lesson.go(Number(button.getAttribute('data-{p}-hold')),true)));
play.addEventListener('click',()=>lesson.state().playing?lesson.pause():lesson.play());
scrub.addEventListener('input',()=>lesson.seek(Number(scrub.value)));
plate.addEventListener('{spec["event"]}',event=>{{scrub.value=event.detail.time;document.querySelector('#{p}-clock').textContent=event.detail.time.toFixed(1)+' s';play.textContent=event.detail.playing?'Pause':'Play explanation';document.querySelectorAll('[data-{p}-hold]').forEach((b,i)=>b.setAttribute('aria-pressed',String(event.detail.cue===lesson.cues[i])));}});
const reduced=matchMedia('(prefers-reduced-motion: reduce)');play.disabled=reduced.matches;
reduced.addEventListener('change',e=>{{play.disabled=e.matches;}});
lesson.seek(0);}})();
</script>"""
    return {
        **spec,
        "css": (ROOT / "kit/math/lesson.css").read_text(),
        "program": "".join(inline_script((ROOT / "kit/math" / name).read_text()) for name in spec["scripts"]),
        "mount": inline_script(
            f'window.{spec["global"]}={spec["factory"]}.mount(document.querySelector("#{spec["root"]}"));'
        ),
        "style": style,
        "below": nav + transport,
        "controls": controls,
    }


def build(output: Path, lesson: str = "plane") -> dict:
    if "outputs" in output.parts and "document" in output.parts:
        raise ValueError("Build a draft, not an authoritative document; integrate through document plan/apply")
    sample = parts(lesson)
    output.mkdir(parents=True, exist_ok=False)
    css = fonts_css() + sample["css"]
    gsap = inline_script((ROOT / "vendor/gsap.min.js").read_text())
    shell = "<style>" + css + "</style>" + sample["figure"] + gsap + sample["program"]
    (output / "math-shell.html").write_text(shell)
    page = (
        '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{escape(sample['title'])} — a seekable mathematical explanation</title><style>"
        + PAGE_CSS
        + f"</style><main><header><div><h1>{escape(sample['title'])}</h1><p>{escape(sample['intro'])}</p></div>"
        + sample["style"]
        + "</header>"
        + shell
        + sample["mount"]
        + sample["below"]
        + f"<footer>{escape(sample['footer'])} No generated images, video player or network requests.</footer>"
        + sample["controls"]
        + "</main></html>"
    )
    (output / "index.html").write_text(page)
    report = {
        "schema": "doxagon.mathematical-sample/1",
        "lesson": lesson,
        **sample["report"],
        "image_components": 0,
        "html_sha256": sha256(page.encode()).hexdigest(),
        "bytes": len(page.encode()),
    }
    (output / "receipt.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New disposable directory")
    parser.add_argument(
        "--lesson", choices=sorted(LESSONS), default="plane", help="plane: 2D eigenvectors; space: 3D transformation"
    )
    args = parser.parse_args()
    print(json.dumps(build(args.output, args.lesson), indent=2))
