"""Build a disposable, offline comparison; never overwrite a selected document."""

from __future__ import annotations

import argparse
import base64
from hashlib import sha256
from html import escape
from io import BytesIO
import json
from math import cos, radians, sin
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ["base", "core", "cap", "probe", "scanner", "seal"]
VENDOR = [
    "gsap.min.js",
    "MotionPathPlugin.min.js",
    "MorphSVGPlugin.min.js",
    "DrawSVGPlugin.min.js",
    "motion-deps.min.js",
]
PROGRAM = ["choreography.js", "renderers.js", "motion.js"]
FONTS = {
    "MotionSerif": "newsreader-latin.woff2",
    "MotionSans": "space-grotesk-latin.woff2",
    "MotionMono": "jetbrains-mono-latin.woff2",
}
PATTERNS = [
    "Multi-phase camera with micro-drift; viewport change in SVG",
    "Looping sub-component: one authored revolution driven by an eased cycle counter",
    "Loop handoff: the sub-component travels from its station and rides the object",
    "Control-target sync: sweep crossings produce readings and evidence packets",
    "Depth scatter and reassembly of registered image layers with spring overshoot",
    "Staggered multi-actor MotionPath entrances with spring pop",
    "Sine-wave idle loops: nested finite repeats and phase-offset time reads",
    "Rack focus on off-focus layers",
    "SVG path drawing, shape morphs and torn-paper reveal",
    "HyperFrames ripple and cross-warp shaders on generated textures",
    "Echo trail for fast moves; ballistic particle burst",
    "Tracking bracket, stepped readouts, dynamic-scale counter and anchored ledger expansion",
]

# Registered layers share one canvas: overlaid, they form the whole object.
LAYERS = {
    "module": {
        "base": [
            [(48, 160), (128, 128), (208, 160), (128, 192)],
            [(48, 160), (128, 192), (128, 226), (48, 194)],
            [(208, 160), (128, 192), (128, 226), (208, 194)],
        ],
        "core": [
            [(62, 120), (128, 94), (194, 120), (128, 146)],
            [(62, 120), (128, 146), (128, 180), (62, 154)],
            [(194, 120), (128, 146), (128, 180), (194, 154)],
        ],
        "cap": [
            [(54, 84), (128, 54), (202, 84), (128, 114)],
            [(54, 84), (128, 114), (128, 130), (54, 100)],
            [(202, 84), (128, 114), (128, 130), (202, 100)],
        ],
    }
}


def _marks(image: Image.Image, mask_shape, profile: dict, kind: str = "polygon") -> None:
    """Profile-specific mark-making clipped to one face."""
    mask = Image.new("L", image.size, 0)
    shape = ImageDraw.Draw(mask)
    (shape.polygon if kind == "polygon" else shape.ellipse)(mask_shape, fill=255)
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    if profile["pattern"] == "hatch":
        for x in range(-256, 512, 9):
            draw.line([(x, 0), (x + 256, 256)], fill=profile["ink"], width=1)
    elif profile["pattern"] == "grid":
        for x in range(0, 256, 14):
            draw.line([(x, 0), (x, 256)], fill=profile["ink"], width=2)
    elif profile["pattern"] == "arcs":
        for y in range(0, 256, 28):
            draw.arc((20, y - 40, 236, y + 40), 20, 160, fill=profile["accent"], width=2)
        draw.line([(84, 0), (84, 256)], fill=profile["surface"], width=5)
    elif profile["pattern"] == "perforation":
        for x in range(0, 256, 28):
            for y in range(0, 256, 22):
                draw.rectangle((x, y, x + 12, y + 4), fill=profile["ink"])
    elif profile["pattern"] == "weave":
        for x in range(0, 256, 16):
            for y in range(0, 256, 16):
                draw.line([(x, y + 4), (x + 6, y + 4)], fill=profile["accent"], width=2)
                draw.line([(x + 10, y + 8), (x + 10, y + 14)], fill=profile["ink"], width=1)
    else:
        draw.rectangle((0, 0, 256, 256), fill=profile["accent"])
    image.paste(layer, (0, 0), ImageChops.multiply(mask, layer.getchannel("A")))


def fixture(profile: dict, component: str, motif: str = "module") -> bytes:
    """Geometric test artwork, not a proxy for image generation or segmentation."""
    im = Image.new("RGBA", (256, 256))
    draw = ImageDraw.Draw(im)
    ink, surface, accent = (profile[k] for k in ("ink", "surface", "accent"))
    width = max(2, round(profile["stroke"] * 1.5))
    if component in {"base", "core", "cap"} and motif == "module":
        top, left, right = LAYERS["module"][component]
        draw.polygon(top, fill=accent if component == "cap" else surface)
        draw.polygon(left, fill=surface)
        _marks(im, left, profile)
        draw.polygon(right, fill=accent)
        for face in (top, left, right):
            draw.polygon(face, outline=ink, width=width)
    elif component in {"base", "core", "cap"}:
        box = {"base": (40, 160, 216, 228), "core": (52, 112, 204, 182), "cap": (52, 40, 204, 150)}[component]
        if component == "cap":
            draw.pieslice(box, 180, 360, fill=surface, outline=ink, width=width)
            _marks(im, (70, 60, 186, 140), profile, "ellipse")
        elif component == "core":
            draw.rounded_rectangle(box, 34, fill=accent, outline=ink, width=width)
            _marks(im, (70, 124, 186, 170), profile, "ellipse")
        else:
            draw.ellipse(box, fill=surface, outline=ink, width=width)
            _marks(im, (64, 172, 192, 214), profile, "ellipse")
    elif component == "probe":
        draw.ellipse((66, 66, 190, 190), outline=ink, width=width)
        for x0, y0, x1, y1 in [(128, 66, 128, 26), (74, 158, 40, 186), (182, 158, 216, 186)]:
            draw.line([(x0, y0), (x1, y1)], fill=ink, width=width + 2)
        draw.ellipse((86, 86, 170, 170), fill=accent, outline=ink, width=width)
        _marks(im, (98, 98, 158, 158), profile, "ellipse")
    elif component == "scanner":
        draw.ellipse((18, 18, 238, 238), fill=surface, outline=ink, width=width)
        for k in range(12):
            angle = radians(k * 30)
            draw.line(
                [(128 + 92 * cos(angle), 128 + 92 * sin(angle)), (128 + 108 * cos(angle), 128 + 108 * sin(angle))],
                fill=ink,
                width=width,
            )
        _marks(im, (52, 52, 204, 204), profile, "ellipse")
        draw.line([(128, 128), (232, 128)], fill=accent, width=width * 3)
        draw.ellipse((108, 108, 148, 148), fill=ink)
    elif component == "seal":
        draw.ellipse((34, 34, 222, 222), fill=profile["accept"], outline=ink, width=width)
        draw.ellipse((62, 62, 194, 194), fill=surface)
        draw.line([(92, 130), (118, 158), (168, 98)], fill=profile["accept"], width=14, joint="curve")
    else:
        raise ValueError(f"Unknown component {component}")
    out = BytesIO()
    im.save(out, format="PNG")
    return out.getvalue()


def data_uri(raw: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(raw).decode()}"


def script(text: str) -> str:
    return "<script>" + text.replace("</script", "<\\/script") + "</script>"


def figure_markup(images: str = "") -> str:
    hidden = f"<div hidden>{images}</div>" if images else ""
    return (
        f'<figure data-motion-plate id="motion-plate">{hidden}'
        '<div class="motion-stage"><canvas aria-label="Spatial candidate"></canvas><svg></svg>'
        '<div class="motion-track" aria-hidden="true"></div></div>'
        '<div class="motion-ledger"></div><figcaption class="motion-caption"></figcaption>'
        '<p class="motion-fault" role="status" hidden></p></figure>'
    )


def fonts_css() -> str:
    return "\n".join(
        f"@font-face{{font-family:{name};src:url({data_uri((ROOT / 'vendor/fonts' / filename).read_bytes(), 'font/woff2')});font-weight:100 900;font-display:swap;}}"
        for name, filename in FONTS.items()
    )


def vendor_scripts(names: list[str] = VENDOR) -> str:
    return "".join(script((ROOT / "vendor" / name).read_text()) for name in names)


def parts(case: Path, assets: Path | None = None) -> dict:
    """Plate pieces shared by the standalone comparison and the consolidated sample sheet."""
    config = json.loads(case.read_text())
    if [item["key"] for item in config["components"]] != COMPONENTS:
        raise ValueError(f"The sample choreography consumes exactly these components: {', '.join(COMPONENTS)}")
    profiles = json.loads((ROOT / "samples/profiles.json").read_text())
    config["profiles"] = profiles
    images, receipts = [], []
    for style, profile in profiles.items():
        for component in COMPONENTS:
            raw = (
                (assets / style / f"{component}.png").read_bytes()
                if assets
                else fixture(profile, component, config["motif"])
            )
            image = Image.open(BytesIO(raw))
            if image.mode != "RGBA" or image.getchannel("A").getextrema()[0] == 255:
                raise ValueError(f"{style}/{component} must be a reviewed transparent RGBA PNG")
            images.append(
                f'<img id="motion-{style}-{component}" data-motion-asset="{component}" data-style="{style}" '
                f'alt="{escape(component)} component" src="{data_uri(raw, "image/png")}">'
            )
            receipts.append(
                {
                    "style": style,
                    "component": component,
                    "sha256": sha256(raw).hexdigest(),
                    "provenance": "user-supplied" if assets else "synthetic-code-fixture",
                }
            )
    recipe_select = '<label>Motion recipe<select id="recipe"><option value="engraving">Living engraving</option><option value="cinematic">Cinematic layers</option><option value="miniature">Miniature 3D</option></select></label>'
    profile_select = (
        '<label>Visual style<select id="profile">'
        + "".join(f'<option value="{name}">{escape(p["name"])}</option>' for name, p in profiles.items())
        + "</select></label>"
    )
    holds = (
        '<nav aria-label="Animation holds">'
        + "".join(
            f'<button data-hold="{i}">{i + 1}. {escape(label)}</button>' for i, label in enumerate(config["labels"])
        )
        + "</nav>"
    )
    patterns = (
        "<details><summary>Patterns in this sample</summary><ul>"
        + "".join(f"<li>{escape(item)}</li>" for item in PATTERNS)
        + "</ul></details>"
    )
    controls = """
<script>
(()=>{const root=document.querySelector('[data-motion-plate]');
const recipe=document.querySelector('#recipe'), profile=document.querySelector('#profile'), scrub=document.querySelector('#scrub'), play=document.querySelector('#play');
recipe.addEventListener('change',()=>motion.setRecipe(recipe.value));
profile.addEventListener('change',()=>motion.setStyle(profile.value));
scrub.addEventListener('input',()=>motion.seek(Number(scrub.value)));
play.addEventListener('click',()=>motion.state().playing?motion.pause():motion.play());
document.querySelectorAll('[data-hold]').forEach(button=>button.addEventListener('click',()=>motion.go(Number(button.dataset.hold),true)));
root.addEventListener('motion:state',event=>{scrub.value=event.detail.time;document.querySelector('#time').textContent=event.detail.time.toFixed(1)+' s';play.textContent=event.detail.playing?'Pause':'Play';});
play.disabled=matchMedia('(prefers-reduced-motion: reduce)').matches;
matchMedia('(prefers-reduced-motion: reduce)').addEventListener('change',event=>{play.disabled=event.matches;});})();
</script>"""
    return {
        "config": config,
        "profiles": profiles,
        "receipts": receipts,
        "css": (ROOT / "kit/plate.css").read_text(),
        "figure": figure_markup("".join(images)),
        "shell_figure": figure_markup(),
        "program": "".join(script((ROOT / "kit" / name).read_text()) for name in PROGRAM),
        "mount": script(
            'window.motion = DoxMotion.mount(document.querySelector("#motion-plate"), '
            + json.dumps(config).replace("<", "\\u003c")
            + ");"
        ),
        "above": '<div class="controls">' + recipe_select + profile_select + "</div>",
        "below": holds
        + f'<div class="controls"><button id="play">Play</button><label for="scrub">Time</label><input id="scrub" type="range" min="0" max="{config["holds"][-1]}" step="0.05" value="0"><output id="time">0.0 s</output></div>'
        + patterns,
        "controls": controls,
    }


def build(output: Path, case: Path, assets: Path | None = None) -> dict:
    if "outputs" in output.parts and "document" in output.parts:
        raise ValueError(
            "Build under an authoring directory, not outputs/document; promote only with dox document plan/apply"
        )
    plate = parts(case, assets)
    config = plate["config"]
    output.mkdir(parents=True, exist_ok=False)
    css = fonts_css() + plate["css"]
    libraries = vendor_scripts()
    fragment = "<style>" + css + "</style>" + plate["figure"] + libraries + plate["program"] + plate["mount"]
    (output / "plate-fragment.html").write_text(fragment)
    # The shell deliberately has no image payloads or mount call. Bind existing slots before mounting.
    (output / "plate-shell.html").write_text(
        "<style>" + css + "</style>" + plate["shell_figure"] + libraries + plate["program"]
    )
    page_style = """body{margin:0;background:#eef3f4;color:#192c44;font:17px/1.5 MotionSans,sans-serif}main{max-width:1080px;margin:auto;padding:24px}h1{font:500 clamp(28px,5vw,48px)/1.15 MotionSans,sans-serif;margin:0 0 12px}p{max-width:68ch;margin:8px 0 20px}.controls{display:flex;gap:20px;flex-wrap:wrap;align-items:end;margin:24px 0}label{display:grid;gap:6px}select,button{font:inherit;color:inherit;background:white;border:1px solid #547084;border-radius:3px;min-height:44px;padding:6px 12px}button:disabled{opacity:.55}button:hover:not(:disabled){background:#dce8ee}button:focus-visible,select:focus-visible,input:focus-visible,summary:focus-visible{outline:3px solid #266094;outline-offset:3px}nav{display:flex;gap:8px;flex-wrap:wrap;margin:20px 0}#scrub{flex:1;min-width:150px;accent-color:#266094}output{font-family:MotionMono,monospace;min-width:7ch}::selection{background:#c6dee9}details{margin:20px 0;max-width:68ch}summary{cursor:pointer;min-height:44px;display:flex;align-items:center}details li{margin:4px 0}footer{border-top:1px solid #9bacb5;padding-top:16px;font-size:14px}@media(max-width:540px){main{padding:16px}.controls{gap:12px}select{max-width:100%}}"""
    page = (
        '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Motion recipe comparison</title><style>'
        + page_style
        + "</style><main><h1>"
        + escape(config["title"])
        + "</h1><p>Keep the explanation steady. Change the rendering technique and visual language independently. "
        + "Six image components per style feed every recipe.</p>"
        + plate["above"]
        + fragment
        + plate["below"]
        + "<footer>"
        + escape(config["caption"])
        + " Not a presentation or an aesthetic default. The comparison runs offline; image generation is a separate, reviewed Doxagon action.</footer>"
        + plate["controls"]
        + "</main></html>"
    )
    (output / "index.html").write_text(page)
    report = {
        "schema": "doxagon.motion-sample/1",
        "case": case.name,
        "components": COMPONENTS,
        "images": plate["receipts"],
        "html_sha256": sha256(page.encode()).hexdigest(),
        "bytes": len(page.encode()),
    }
    (output / "receipt.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New disposable directory")
    parser.add_argument("--case", type=Path, default=ROOT / "samples/inspection.json")
    parser.add_argument(
        "--assets",
        type=Path,
        help="Reviewed transparent PNGs at STYLE/COMPONENT.png for every profile and component; otherwise code fixtures",
    )
    args = parser.parse_args()
    print(json.dumps(build(args.output, args.case, args.assets), indent=2))
