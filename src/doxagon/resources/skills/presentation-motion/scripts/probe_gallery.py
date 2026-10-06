"""Probe the consolidated sample sheet, including the 3D lesson and the 3D looks tab, inside the document CSP."""

import argparse
from html import escape
from io import BytesIO
import json
from pathlib import Path

from PIL import Image, ImageChops
from playwright.sync_api import sync_playwright

CSP = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:; connect-src 'none'; frame-src 'none'"

# Pure-model contracts for the 3D lesson, evaluated without rendering.
SPACE_CONTRACTS = r"""() => {
  const m = DoxSpaceModel, near = (a, b, e = 1e-9) => Math.abs(a - b) < e;
  const end = m.matrixAt(1), axisLine = [1, 1, 1];
  let invariant = true, volume = true;
  for (let s = 0; s <= 1.0001; s += 0.05) {
    const image = m.apply(m.matrixAt(s), axisLine);
    invariant = invariant && image.every(x => near(x, 1 + 3 * s));
    volume = volume && near(m.det(m.matrixAt(s)), 1 + 3 * s);
  }
  const square = M => M.map(r => [0, 1, 2].map(j => r.reduce((t, x, k) => t + x * M[k][j], 0)));
  const A = m.A, A2 = square(A), A3 = A2.map(r => [0, 1, 2].map(j => r.reduce((t, x, k) => t + x * A[k][j], 0)));
  const cayley = A3.every((r, i) => r.every((x, j) => near(x - 3 * A2[i][j] - 3 * A[i][j] - 4 * (i === j), 0)));
  const axis = m.at(28), aspect = 760 / 620;
  const origin = m.project([0, 0, 0], axis.view, aspect), tip = m.project(axis.diagonal, axis.view, aspect);
  const turned = m.at(28, 60), plain = m.at(28);
  return {
    'space-end-matrix-is-A': end.every((r, i) => r.every((x, j) => near(x, A[i][j], 1e-12))),
    'space-diagonal-stays-on-its-line': invariant,
    'space-volume-is-determinant': volume,
    'space-cayley-hamilton-cubic': cayley,
    'space-axis-view-points-at-viewer': near(origin.x, tip.x, 1e-9) && near(origin.y, tip.y, 1e-9) && axis.alongDiagonal < 1e-6,
    'space-orbit-is-view-only': JSON.stringify([turned.matrix, turned.images, turned.volume]) === JSON.stringify([plain.matrix, plain.images, plain.volume])
      && JSON.stringify(turned.view) !== JSON.stringify(plain.view),
  };
}"""

# The rendered arrow tip must sit where the model projects the transformed basis vector.
AGREEMENT = r"""() => {
  let error = 0;
  for (const t of [0, 8, 12.5, 18, 20.4, 24, 28, 34, 40]) {
    spaceLesson.seek(t);
    const s = spaceLesson.state(), aspect = 760 / 620;
    const p = DoxSpaceModel.project(s.images[0], s.view, aspect);
    const d = document.querySelector('#space-lesson [data-vector="e1"] path').getAttribute('d').match(/[-+]?\d*\.?\d+/g).map(Number);
    error = Math.max(error, Math.abs(d[2] - (380 + p.x * 380)), Math.abs(d[3] - (310 - p.y * 310)));
  }
  return error;
}"""


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
            viewport={"width": width, "height": 1000}, reduced_motion="reduce" if reduce else "no-preference"
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
        frame.wait_for_function(
            "() => window.motion?.state().rendered && window.mathLesson?.state().rendered && window.spaceLesson?.state().rendered"
        )
        frame.evaluate("() => document.fonts.ready")
        return page, frame

    def visible_panels(frame):
        return frame.evaluate(
            '() => [...document.querySelectorAll("[role=tabpanel]")].filter(p => !p.hidden).map(p => p.id)'
        )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for width in [1280, 390]:
            page, frame = open_frame(browser, width)
            if width == 1280:
                for name, passed in frame.evaluate(SPACE_CONTRACTS).items():
                    check(name, passed)
            check(f"{width}-starts-on-motion", visible_panels(frame) == ["panel-motion"])
            frame.evaluate("() => {motion.go(1);motion.play()}")
            for key, api in [("plane", "mathLesson"), ("space", "spaceLesson")]:
                frame.locator(f"#tab-{key}").click()
                check(f"{width}-{key}-tab-shows-one-panel", visible_panels(frame) == [f"panel-{key}"])
                check(f"{width}-{key}-renders", frame.evaluate(f"() => {api}.state().rendered"))
            check(f"{width}-switching-pauses-hidden-sample", not frame.evaluate("() => motion.state().playing"))
            frame.locator("#tab-space").focus()
            page.keyboard.press("ArrowLeft")
            check(f"{width}-arrow-key-tabs", visible_panels(frame) == ["panel-plane"])
            frame.locator("#tab-space").click()
            for style in ["night", "paper"]:
                frame.locator("#space-style").select_option(style)
                for i, time in enumerate([0, 8, 18, 28, 40]):
                    frame.evaluate("i => spaceLesson.go(i)", i)
                    state = frame.evaluate("() => spaceLesson.state()")
                    check(f"{width}-{style}-space-hold-{i}", state["time"] == time and state["cue"] is not None)
                    if time in [8, 18, 28, 40]:
                        file = f"space-{width}-{style}-{time}.png"
                        frame.locator("#space-lesson").screenshot(path=str(output / file))
                        report["captures"].append(file)
                for time in [12.5, 20.4, 24.7, 36.1]:
                    poses, images = [], []
                    for history in [[0, 8, time], [40, 28, 18, time]]:
                        for t in history:
                            frame.evaluate("t => spaceLesson.seek(t)", t)
                        poses.append(
                            frame.evaluate(
                                '() => [...document.querySelectorAll("#space-lesson svg path")].map(n => n.getAttribute("d"))'
                            )
                        )
                        images.append(
                            Image.open(BytesIO(frame.locator("#space-lesson .math-plane").screenshot())).convert("RGB")
                        )
                    difference = ImageChops.difference(*images)
                    maximum = max(high for _, high in difference.getextrema())
                    changed = sum(1 for pixel in difference.getdata() if max(pixel)) / (
                        difference.width * difference.height
                    )
                    check(
                        f"{width}-{style}-space-seek-{time}",
                        poses[0] == poses[1] and maximum <= 16 and changed <= 0.0005,
                        {"max_channel_error": maximum, "changed_fraction": changed},
                    )
                agreement = frame.evaluate(AGREEMENT)
                check(f"{width}-{style}-svg-matches-3d-model", agreement < 0.01, agreement)
            frame.evaluate("() => {spaceLesson.go(3);spaceLesson.setOrbit(70)}")
            turned = frame.evaluate("() => spaceLesson.state()")
            check(f"{width}-orbit-turns-view", turned["orbit"] == 70 and turned["alongDiagonal"] > 30)
            frame.evaluate("() => spaceLesson.go(4)")
            check(f"{width}-cue-resets-orbit", frame.evaluate("() => spaceLesson.state().orbit") == 0)
            frame.evaluate("() => {spaceLesson.go(0);spaceLesson.go(4,true);spaceLesson.go(1)}")
            frame.wait_for_timeout(150)
            check(f"{width}-new-cue-cancels-travel", frame.evaluate("() => spaceLesson.state().time") == 8)
            frame.locator("#tab-stage").click()
            check(f"{width}-stage-tab-shows-one-panel", visible_panels(frame) == ["panel-stage"])
            frame.wait_for_function("() => document.querySelector('#stage-sample').dataset.doxReady === 'true'")
            frame.locator('[data-stage-look="xray-ink"]').click()
            check(
                f"{width}-stage-look-changes-by-parameters",
                frame.evaluate("() => stageSample.look.background") == "#ffffff",
            )
            frame.locator('[data-stage-look="gloss"]').click()
            frame.locator('[data-stage-skin="wrap"]').click()
            check(
                f"{width}-stage-skin-by-role",
                frame.evaluate("() => stageSample.look.skins.housing.mode") == "wrap",
            )
            frame.locator('[data-stage-skin="none"]').click()
            frame.locator('[data-stage-look="satin"]').click()
            frame.locator("#tab-space").click()
            check(f"{width}-switching-pauses-stage", not frame.evaluate("() => stageSample.state.playing"))
            check(f"{width}-no-overflow", frame.evaluate("() => document.documentElement.scrollWidth <= innerWidth"))
            for key in ["motion", "plane", "space", "stage"]:
                frame.locator(f"#tab-{key}").click()
                file = f"sheet-{width}-{key}.png"
                page.screenshot(path=str(output / file))
                report["captures"].append(file)
            page.close()
        page, frame = open_frame(browser, 1280, reduce=True)
        frame.locator("#tab-space").click()
        frame.evaluate("() => spaceLesson.go(2,true)")
        check(
            "reduced-motion-holds",
            frame.evaluate("() => spaceLesson.state().time") == 18 and not frame.evaluate("() => spaceLesson.play()"),
        )
        page.close()
        browser.close()
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
