"""Build the consolidated, offline sample sheet: motion recipes, 2D eigenvectors and a 3D transformation."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
motion = runpy.run_path(str(ROOT / "scripts/build_sample.py"))
math = runpy.run_path(str(ROOT / "scripts/build_math_sample.py"))

PAGE_CSS = """html{background:#101b2a;color:#e8eff7}body{margin:0;font:16px/1.5 MotionSans,sans-serif}
main{max-width:1190px;margin:auto;padding:28px 24px 40px}
.sheet-head{display:flex;align-items:end;justify-content:space-between;gap:24px;margin-bottom:22px}
h1{font:500 clamp(32px,4.6vw,50px)/1.08 MotionSerif,serif;margin:0 0 10px;max-width:22ch}
.sheet-head p{max-width:64ch;color:#a9b9cb;margin:0}
[role=tablist]{display:flex;gap:4px;border-bottom:1px solid #3a506b;margin:0 0 20px;overflow-x:auto}
[role=tab]{font:inherit;color:#a9b9cb;background:none;border:0;border-bottom:3px solid transparent;min-height:48px;padding:8px 16px;cursor:pointer;white-space:nowrap}
[role=tab][aria-selected=true]{color:#e8eff7;border-bottom-color:#edc36a}
[role=tab]:hover{color:#e8eff7}
.panel-head{display:flex;align-items:end;justify-content:space-between;gap:20px;flex-wrap:wrap;margin:0 0 14px}
.panel-head h2{font:500 28px/1.15 MotionSerif,serif;margin:0 0 6px}
.panel-head p{margin:0;color:#a9b9cb;max-width:64ch}
[role=tabpanel] label{display:grid;gap:6px;font-size:13px}
[role=tabpanel] .controls{display:flex;gap:16px;flex-wrap:wrap;align-items:end;margin:0}
button,select{font:inherit;color:inherit;background:#172638;border:1px solid #6a8099;border-radius:3px;min-height:44px;padding:7px 12px}
button:hover:not(:disabled){background:#263c53}button[aria-pressed=true]{border-color:#edc36a;color:#edc36a}button:disabled{opacity:.5}
nav{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0}
.math-controls,[role=tabpanel] nav+.controls{display:flex;align-items:center;flex-wrap:wrap;gap:16px;margin:0 0 10px}
input[type=range]{flex:1;min-width:140px;accent-color:#edc36a}
output{font-family:MotionMono,monospace;min-width:7ch}
figure[data-math-lesson],figure[data-space-lesson]{margin:12px 0}
details{margin:16px 0;max-width:68ch;color:#a9b9cb}summary{cursor:pointer;min-height:44px;display:flex;align-items:center}
:is(button,select,input,summary,[role=tab]):focus-visible{outline:3px solid #edc36a;outline-offset:3px}
footer{font-size:13px;color:#a9b9cb;margin-top:28px;border-top:1px solid #3a506b;padding-top:16px;max-width:78ch}
::selection{background:#edc36a;color:#101b2a}
@media(max-width:650px){main{padding:18px 12px 32px}.sheet-head{display:block}h1{font-size:34px}[role=tab]{padding:8px 10px}nav button{font-size:13px}}"""

TABS = """<script>
(()=>{const tabs=[...document.querySelectorAll('[role=tab]')];
const pause={motion:()=>window.motion?.pause(),plane:()=>window.mathLesson?.pause(),space:()=>window.spaceLesson?.pause()};
function select(tab){tabs.forEach(t=>{const on=t===tab;t.setAttribute('aria-selected',String(on));t.tabIndex=on?0:-1;
document.getElementById(t.getAttribute('aria-controls')).hidden=!on;if(!on)pause[t.dataset.sampleTab]();});}
tabs.forEach((tab,i)=>{tab.addEventListener('click',()=>select(tab));tab.addEventListener('keydown',e=>{
const step={ArrowRight:1,ArrowLeft:-1}[e.key];if(!step)return;e.preventDefault();const next=tabs[(i+step+tabs.length)%tabs.length];select(next);next.focus();});});
window.sampleSheet={select:name=>select(tabs.find(t=>t.dataset.sampleTab===name))};})();
</script>"""


def build(output: Path, case: Path | None = None, assets: Path | None = None) -> dict:
    if "outputs" in output.parts and "document" in output.parts:
        raise ValueError("Build a draft sample sheet, not an authoritative document")
    plate = motion["parts"](case or ROOT / "samples/inspection.json", assets)
    plane, space = math["parts"]("plane"), math["parts"]("space")
    output.mkdir(parents=True, exist_ok=False)
    css = motion["fonts_css"]() + plate["css"] + plane["css"]
    tabs = [
        ("motion", "Motion recipes"),
        ("plane", "2D eigenvectors"),
        ("space", "3D transformation"),
    ]
    tablist = (
        '<div role="tablist" aria-label="Samples">'
        + "".join(
            f'<button role="tab" id="tab-{key}" data-sample-tab="{key}" aria-controls="panel-{key}" '
            f'aria-selected="{str(i == 0).lower()}" tabindex="{0 if i == 0 else -1}">{label}</button>'
            for i, (key, label) in enumerate(tabs)
        )
        + "</div>"
    )

    def panel(key: str, title: str, intro: str, controls: str, body: str, hidden: bool) -> str:
        return (
            f'<section role="tabpanel" id="panel-{key}" aria-labelledby="tab-{key}"{" hidden" if hidden else ""}>'
            f'<div class="panel-head"><div><h2>{title}</h2><p>{intro}</p></div>{controls}</div>{body}</section>'
        )

    config = plate["config"]
    panels = (
        panel(
            "motion",
            config["title"],
            "Three rendering recipes and six visual styles on one seekable clock. Six image components per style.",
            plate["above"],
            plate["figure"] + plate["below"],
            False,
        )
        + panel("plane", plane["title"], plane["intro"], plane["style"], plane["figure"] + plane["below"], True)
        + panel("space", space["title"], space["intro"], space["style"], space["figure"] + space["below"], True)
    )
    scripts = (
        motion["vendor_scripts"]()
        + plate["program"]
        + plate["mount"]
        + plane["program"]
        + plane["mount"]
        + space["program"]
        + space["mount"]
        + plate["controls"]
        + plane["controls"]
        + space["controls"]
        + TABS
    )
    page = (
        '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>Presentation motion samples</title><style>" + PAGE_CSS + css + "</style><main>"
        '<header class="sheet-head"><div><h1>Presentation motion samples</h1>'
        "<p>Seekable animation for Doxagon documents: rendering recipes with generated image components, "
        "and geometry-first mathematical explanations in two and three dimensions.</p></div></header>"
        + tablist
        + panels
        + "<footer>Synthetic fixtures and original mathematical examples. Everything is inlined; no network requests, "
        "video player or generated images run in this sheet. Image generation is a separate, reviewed Doxagon action.</footer>"
        + scripts
        + "</main></html>"
    )
    (output / "index.html").write_text(page)
    report = {
        "schema": "doxagon.motion-sample-sheet/1",
        "samples": [key for key, _ in tabs],
        "motion_case": config["title"],
        "motion_images": plate["receipts"],
        "math_lessons": {"plane": plane["report"], "space": space["report"]},
        "html_sha256": sha256(page.encode()).hexdigest(),
        "bytes": len(page.encode()),
    }
    (output / "receipt.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New disposable directory")
    parser.add_argument("--case", type=Path, help="Motion case JSON; defaults to the inspection sample")
    parser.add_argument("--assets", type=Path, help="Reviewed STYLE/COMPONENT.png files for the motion sample")
    args = parser.parse_args()
    report = build(args.output, args.case, args.assets)
    print(json.dumps({key: report[key] for key in ("samples", "html_sha256", "bytes")}, indent=2))
