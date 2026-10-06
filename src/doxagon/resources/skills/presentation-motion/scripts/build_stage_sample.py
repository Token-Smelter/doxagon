"""Build the 3D looks sample: one machine on the stage, every built-in look, and looks made by changing parameters."""

from __future__ import annotations

import argparse
import base64
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
math = runpy.run_path(str(ROOT / "scripts/build_math_sample.py"))
inline_script = math["inline_script"]

STAGE_FILES = ["kit/stage/kit.js", "kit/stage/host.js", "kit/stage/stage.js"]
HOLDS = ["Drawing", "Solid", "Output", "Check"]
# Each value is the literal an agent would write; the page shows it beside the result.
LOOKS = [
    ("ink", "Ink drawing", "'ink'"),
    ("satin", "Satin", "'satin'"),
    ("clay", "Clay", "'clay'"),
    ("gloss", "Gloss lacquer", "['gloss', { palette: { housing: '#2b4a70' } }]"),
    (
        "metal",
        "Brushed metal",
        "['metal', { palette: { housing: '#c4c9d1', shell: '#b5bcc6', plate: '#d5d9df', bolt: '#8d949e', pipe: '#c9ced6', tile: '#2a3242' } }]",
    ),
    ("cel", "Cel", "'cel'"),
    ("technical", "Technical warm–cool", "'technical'"),
    ("engraving", "Engraving", "'engraving'"),
    ("xray", "X-ray", "'xray'"),
    (
        "xray-mono",
        "X-ray, white on black",
        "['xray', { surface: ['xray', { color: '#ffffff', strength: 0.5 }], lines: { color: '#ffffff' }, background: '#000000' }]",
    ),
    (
        "xray-ink",
        "X-ray, ink on paper",
        "['xray', { surface: ['xray', { color: '#111111', fill: 0.03, strength: 0.6 }], lines: { color: '#111111', opacity: 0.75 }, background: '#ffffff' }]",
    ),
]
FIRST_LOOK = "satin"
# Skins apply to the housing role; each value is the literal an agent would write under `skins`.
SKINS = [
    ("none", "No skin", ""),
    (
        "tile",
        "Engraved tile",
        "{ housing: { image: 'skin-engraved-lines', mode: 'tile', size: 0.62, tint: { base: '#1d3766', ink: '#dfe7f6', strength: 0.8 } } }",
    ),
    ("wrap", "Harbour wrap", "{ housing: { image: 'skin-harbour-wrap', mode: 'wrap' } }"),
]
SKIN_FILES = {
    "skin-engraved-lines": "samples/stage/skins/engraved-lines.png",
    "skin-harbour-wrap": "samples/stage/skins/harbour-wrap.jpg",
}

CSS = """.stage-figure{position:relative;margin:12px 0;aspect-ratio:16/9;border-radius:4px;overflow:hidden;background:#f6f4ee}
.stage-fallback{position:absolute;inset:0;margin:0;display:grid;place-items:center;color:#1d2430;padding:24px;text-align:center}
.stage-fallback[hidden]{display:none}
.stage-controls{display:flex;flex-wrap:wrap;gap:12px;align-items:center;justify-content:space-between}
.stage-controls nav{margin:0}
.stage-looks{border:0;padding:0;margin:14px 0 0;display:flex;flex-wrap:wrap;gap:8px}
.stage-looks legend{font-size:13px;margin:0 0 6px;padding:0}
.stage-call{margin:10px 0 0;font:13px/1.5 MotionMono,monospace;color:#a9b9cb;overflow-wrap:anywhere}
@media(max-width:650px){.stage-figure{aspect-ratio:4/3}}"""

PAGE_CSS = """html{background:#101b2a;color:#e8eff7}body{margin:0;font:16px/1.5 MotionSans,sans-serif}
main{max-width:1190px;margin:auto;padding:28px 24px 40px}header{display:flex;align-items:end;justify-content:space-between;gap:24px}
h1{font:500 clamp(30px,4.4vw,46px)/1.08 MotionSerif,serif;margin:0 0 8px}header p{margin:0;color:#a9b9cb;max-width:64ch}
button{font:inherit;color:inherit;background:#172638;border:1px solid #6a8099;border-radius:3px;min-height:44px;padding:7px 12px;cursor:pointer}
button:hover:not(:disabled){background:#263c53}button[aria-pressed=true]{border-color:#edc36a;color:#edc36a}button:disabled{opacity:.5}
nav{display:flex;flex-wrap:wrap;gap:8px}:is(button):focus-visible{outline:3px solid #edc36a;outline-offset:3px}
footer{font-size:13px;color:#a9b9cb;margin-top:28px;border-top:1px solid #3a506b;padding-top:16px;max-width:78ch}
@media(max-width:650px){main{padding:18px 12px 32px}header{display:block}}"""


def skin_images() -> str:
    """The sample skins as hidden document images, the way a selected image slot would carry them."""
    mime = {".png": "image/png", ".jpg": "image/jpeg"}
    return "".join(
        f'<img id="{key}" hidden alt="" src="data:{mime[Path(path).suffix]};base64,{base64.b64encode((ROOT / path).read_bytes()).decode()}">'
        for key, path in SKIN_FILES.items()
    )


def stage_scripts() -> str:
    """The stage layers, inlined: helpers, host and stage. The page also needs the vendored GPU bundle."""
    return "".join(inline_script((ROOT / name).read_text()) for name in STAGE_FILES)


def parts() -> dict:
    """Sample pieces shared by the standalone page and the consolidated sample sheet."""
    figure = (
        '<figure class="stage-figure" id="stage-sample" aria-label="An intake machine rendered with the selected look">'
        '<p class="stage-fallback" hidden>WebGL is unavailable here, so the 3D sample cannot be drawn.</p></figure>'
        + skin_images()
    )
    below = (
        '<div class="stage-controls"><nav aria-label="Machine holds">'
        + "".join(
            f'<button data-stage-hold="{i}" aria-pressed="false">{i + 1}. {label}</button>'
            for i, label in enumerate(HOLDS)
        )
        + '</nav><button data-stage-motion aria-pressed="false">Pause motion</button></div>'
        + '<fieldset class="stage-looks"><legend>Look</legend>'
        + "".join(
            f'<button data-stage-look="{key}" aria-pressed="{str(key == FIRST_LOOK).lower()}">{escape(label)}</button>'
            for key, label, _ in LOOKS
        )
        + "</fieldset>"
        + '<fieldset class="stage-looks"><legend>Skin on the housing (material looks)</legend>'
        + "".join(
            f'<button data-stage-skin="{key}" aria-pressed="{str(key == "none").lower()}">{escape(label)}</button>'
            for key, label, _ in SKINS
        )
        + "</fieldset>"
        + f'<p class="stage-call"><code data-stage-call>look: {escape(dict((k, v) for k, _, v in LOOKS)[FIRST_LOOK])}</code></p>'
    )
    looks = "{" + ",".join(f"{json.dumps(key)}:{value}" for key, _, value in LOOKS) + "}"
    sources = json.dumps({key: value for key, _, value in LOOKS})
    skins = "{" + ",".join(f"{json.dumps(key)}:{value or 'null'}" for key, _, value in SKINS) + "}"
    skin_sources = json.dumps({key: value for key, _, value in SKINS})
    mount = inline_script(
        "window.stageSample=DoxStage.mount(document.querySelector('#stage-sample'),"
        f"{{...DoxStageSamples.machine,look:'{FIRST_LOOK}',fallback:'.stage-fallback'}});"
    )
    controls = inline_script(f"""(()=>{{const stage=window.stageSample;if(!stage)return;
const LOOKS={looks}, SOURCES={sources}, SKINS={skins}, SKIN_SOURCES={skin_sources};
const holds=[...document.querySelectorAll('[data-stage-hold]')], looks=[...document.querySelectorAll('[data-stage-look]')], skins=[...document.querySelectorAll('[data-stage-skin]')];
let look='{FIRST_LOOK}', skin='none';
const apply=()=>{{stage.setLook(DoxStageKit.look(LOOKS[look],SKINS[skin]?{{skins:SKINS[skin]}}:undefined));
call.textContent='look: '+SOURCES[look]+(SKINS[skin]?'  ·  skins: '+SKIN_SOURCES[skin]:'');}};
const motion=document.querySelector('[data-stage-motion]'), call=document.querySelector('[data-stage-call]');
const press=(list,on)=>list.forEach(b=>b.setAttribute('aria-pressed',String(b===on)));
holds.forEach((b,i)=>b.addEventListener('click',()=>{{stage.go(i);press(holds,b);}}));
looks.forEach(b=>b.addEventListener('click',()=>{{look=b.dataset.stageLook;press(looks,b);apply();}}));
skins.forEach(b=>b.addEventListener('click',()=>{{skin=b.dataset.stageSkin;press(skins,b);apply();}}));
let still=false;motion.addEventListener('click',()=>{{still=!still;stage.pinIdle(still?stage.state.idle:null);motion.setAttribute('aria-pressed',String(still));motion.textContent=still?'Resume motion':'Pause motion';}});
const reduced=matchMedia('(prefers-reduced-motion: reduce)');motion.disabled=reduced.matches;reduced.addEventListener('change',e=>{{motion.disabled=e.matches;}});
stage.go(1,true);press(holds,holds[1]);}})();""")
    return {
        "title": "3D looks",
        "intro": "One machine on the stage library. Each look is a name or a few parameters, and a generated image can skin a part as a tile or a wrap; geometry, camera and timing stay the same.",
        "style": "",
        "css": CSS,
        "figure": figure,
        "below": below,
        "program": stage_scripts() + inline_script((ROOT / "samples/stage/machine.js").read_text()),
        "mount": mount,
        "controls": controls,
        "report": {
            "looks": [key for key, _, _ in LOOKS],
            "skins": [key for key, _, _ in SKINS],
            "holds": [0, 3, 6, 9],
            "image_components": 0,
            "sample_skins": sorted(SKIN_FILES),
        },
    }


def build(output: Path) -> dict:
    if "outputs" in output.parts and "document" in output.parts:
        raise ValueError("Build a draft, not an authoritative document; integrate through document plan/apply")
    sample = parts()
    output.mkdir(parents=True, exist_ok=False)
    bundle = inline_script((ROOT / "vendor/motion-deps.min.js").read_text())
    page = (
        '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>3D looks on the stage library</title><style>"
        + math["fonts_css"]()
        + PAGE_CSS
        + sample["css"]
        + f"</style><main><header><div><h1>{escape(sample['title'])}</h1><p>{escape(sample['intro'])}</p></div></header>"
        + sample["figure"]
        + sample["below"]
        + "<footer>Code-drawn geometry with two previously generated sample skins. No generation runs when opening this page; no video player or network requests.</footer>"
        + bundle
        + sample["program"]
        + sample["mount"]
        + sample["controls"]
        + "</main></html>"
    )
    (output / "index.html").write_text(page)
    report = {
        "schema": "doxagon.stage-sample/1",
        **sample["report"],
        "html_sha256": sha256(page.encode()).hexdigest(),
        "bytes": len(page.encode()),
    }
    (output / "receipt.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New disposable directory")
    print(json.dumps(build(parser.parse_args().output), indent=2))
