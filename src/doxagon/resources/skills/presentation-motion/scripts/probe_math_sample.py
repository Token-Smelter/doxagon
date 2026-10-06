"""Check numerical/SVG agreement and navigation in the actual document CSP."""

import argparse
from html import escape
from io import BytesIO
import json
from pathlib import Path

from PIL import Image, ImageChops
from playwright.sync_api import sync_playwright

CSP = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:; connect-src 'none'; frame-src 'none'"


def probe(html: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    report = {"checks": [], "errors": [], "requests": [], "captures": []}
    content = html.read_text().replace(
        '<meta charset="utf-8">', f'<meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="{CSP}">'
    )

    def check(name, passed, detail=None):
        report["checks"].append({"name": name, "pass": bool(passed), "detail": detail})

    def open_frame(browser, width, reduce=False):
        page = browser.new_page(
            viewport={"width": width, "height": 1040}, reduced_motion="reduce" if reduce else "no-preference"
        )
        page.on("pageerror", lambda error: report["errors"].append(str(error)))
        page.on(
            "request",
            lambda request: report["requests"].append(request.url)
            if not request.url.startswith(("data:", "about:"))
            else None,
        )
        page.set_content(
            '<iframe sandbox="allow-scripts" style="position:absolute;inset:0;border:0;width:100%;height:100%" srcdoc="'
            + escape(content, quote=True)
            + '"></iframe>'
        )
        frame = page.frames[1]
        frame.wait_for_function("() => window.mathLesson?.state().rendered")
        frame.evaluate("() => document.fonts.ready")
        return page, frame

    def pose(frame):
        return frame.evaluate("""() => ({state:mathLesson.state(), paths:[...document.querySelectorAll('.math-plane path')].map(n=>n.getAttribute('d')),
          formula:document.querySelector('.math-relation').textContent, matrix:document.querySelector('.math-live-matrix').textContent})""")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for width in [1280, 390]:
            page, frame = open_frame(browser, width)
            states = []
            for style in ["night", "paper"]:
                frame.locator("#math-style").select_option(style)
                for i, time in enumerate([0, 6, 14, 23, 32, 40]):
                    frame.evaluate("i => mathLesson.go(i)", i)
                    state = frame.evaluate("() => mathLesson.state()")
                    check(f"{width}-{style}-hold-{i}", state["time"] == time and state["cue"] is not None)
                    if time in [6, 14, 23, 40]:
                        file = f"{width}-{style}-{time}.png"
                        frame.locator("[data-math-lesson]").screenshot(path=str(output / file))
                        report["captures"].append(file)
                frame.evaluate("() => mathLesson.seek(20.7)")
                states.append(frame.evaluate("() => mathLesson.state()"))
                for time in [9.3, 19.4, 27.5, 38.2]:
                    poses, images = [], []
                    for history in [[0, 6, time], [40, 23, 14, time]]:
                        for t in history:
                            frame.evaluate("t => mathLesson.seek(t)", t)
                        poses.append(pose(frame))
                        images.append(Image.open(BytesIO(frame.locator(".math-plane").screenshot())).convert("RGB"))
                    difference = ImageChops.difference(*images)
                    maximum = max(high for _, high in difference.getextrema())
                    check(
                        f"{width}-{style}-seek-{time}",
                        poses[0] == poses[1] and maximum == 0,
                        {"max_channel_error": maximum},
                    )
                agreement = frame.evaluate(r"""() => {
                  let error=0;
                  for(const t of [0,6,9.3,14,19.4,23,27.5,32,40]){
                    mathLesson.seek(t); const s=mathLesson.state();
                    const d=document.querySelector('[data-vector="target"] path').getAttribute('d').match(/[-+]?\d*\.?\d+/g).map(Number);
                    error=Math.max(error,Math.abs((d[2]-340)/53-s.target[0]),Math.abs((374-d[3])/53-s.target[1]));
                  }
                  return error;
                }""")
                check(f"{width}-{style}-svg-matches-math", agreement < 1e-5, agreement)
            check(f"{width}-style-does-not-change-mathematics", states[0] == states[1])
            frame.evaluate("() => mathLesson.go(3)")
            frame.locator("[data-math-angle]").fill("90")
            check(f"{width}-angle-counterexample", not frame.evaluate("() => mathLesson.state().aligned"))
            for degrees, eigenvalue in [(45, 3), (135, 1)]:
                frame.locator(f'[data-math-direction="{degrees}"]').click()
                state = frame.evaluate("() => mathLesson.state()")
                check(
                    f"{width}-angle-eigenpair-{degrees}",
                    state["aligned"] and abs(state["eigenvalue"] - eigenvalue) < 1e-12,
                )
            frame.evaluate("() => {mathLesson.go(5,true);mathLesson.go(1)}")
            frame.wait_for_timeout(150)
            check(f"{width}-new-cue-cancels-travel", frame.evaluate("() => mathLesson.state().time") == 6)
            check(f"{width}-no-overflow", frame.evaluate("() => document.documentElement.scrollWidth <= innerWidth"))
            check(
                f"{width}-typeset-matrix",
                frame.evaluate(
                    '() => document.querySelector(".math-live-matrix mtable").getBoundingClientRect().height > 30'
                ),
            )
            page.close()
        page, frame = open_frame(browser, 1280)
        frame.evaluate("() => {mathLesson.go(2);mathLesson.play()}")
        frame.wait_for_timeout(350)
        check("play-advances", frame.evaluate("() => mathLesson.state().time > 14 && mathLesson.state().playing"))
        frame.evaluate('() => {document.querySelector("[data-math-lesson]").style.display="none"}')
        frame.wait_for_timeout(150)
        before = frame.evaluate("() => mathLesson.state().time")
        frame.wait_for_timeout(150)
        check(
            "offscreen-pauses",
            not frame.evaluate("() => mathLesson.state().playing")
            and frame.evaluate("() => mathLesson.state().time") == before,
        )
        frame.evaluate("() => mathLesson.destroy()")
        check("destroy-not-rendered", not frame.evaluate("() => mathLesson.state().rendered"))
        page.close()
        page, frame = open_frame(browser, 1280, reduce=True)
        frame.evaluate("() => mathLesson.go(4,true)")
        check(
            "reduced-motion-holds",
            frame.evaluate("() => mathLesson.state().time") == 32 and not frame.evaluate("() => mathLesson.play()"),
        )
        page.close()
        browser.close()
        no_gpu = p.chromium.launch(headless=True, args=["--disable-webgl"])
        page, frame = open_frame(no_gpu, 1280)
        check("no-gpu-required", frame.evaluate("() => {mathLesson.go(5);return mathLesson.state().rendered}"))
        page.close()
        no_gpu.close()
    check("no-script-errors", not report["errors"], report["errors"])
    check("no-network", not report["requests"], report["requests"])
    report["ok"] = all(row["pass"] for row in report["checks"])
    (output / "validation.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--html", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = probe(args.html, args.output)
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "checks": len(report["checks"]),
                "failures": [row for row in report["checks"] if not row["pass"]],
            }
        )
    )
    raise SystemExit(0 if report["ok"] else 1)
