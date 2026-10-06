"""Probe the built sample in an opaque iframe under the document's CSP."""

import argparse
from html import escape
from io import BytesIO
import json
from pathlib import Path

from PIL import Image, ImageChops
from playwright.sync_api import sync_playwright

CSP = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:; connect-src 'none'; frame-src 'none'"
SEEK_TIMES = [12.35, 21.7, 33.1]

# Pattern contracts evaluated on pure samples of the choreography; no pixels involved.
CONTRACTS = """() => {
  const s = t => motion.stateAt(t), near = (a, b) => Math.abs(a - b) < 1e-6;
  const rate = t => (s(t + 0.1).scanner.cycles - s(t).scanner.cycles) / 0.1;
  const a = s(14.2).scanner, b = s(15.2).scanner;
  const attached = [24, 30.5, 38, 40].every(t => {
    const x = s(t), cap = x.candidate.layers[2];
    return x.scanner.docked && x.scanner.x === x.candidate.x + cap.dx && x.scanner.y === x.candidate.y + cap.dy;
  });
  const last = s(40).scanner;
  const crossing = 12 + (3 + 1 / 12 - 2.4);
  return {
    'loop-periodic-at-cruise': near(a.angle, b.angle) && near(a.ringAlpha, b.ringAlpha) && near(a.blink, b.blink),
    'loop-spins-up-to-cruise': rate(8.6) < rate(10) && rate(10) < rate(11.7) && Math.abs(rate(14) - 1) < 1e-6,
    'loop-travels-then-rides-object': s(18).scanner.travel === 0 && !s(18).scanner.docked && attached,
    'loop-locks-at-rest': last.locked && near(last.angle % 360, 0) && last.ringAlpha === 0,
    'sweep-crossing-drives-reading': s(crossing - 0.02).checks[0].readings === 0 && s(crossing + 0.02).checks[0].readings === 1,
    'nested-idle-repeats': near(s(5).breathe, s(9).breathe) && !near(s(5).breathe, s(6).breathe),
    'particle-pools-bounded': s(30).packets.length === 36 && s(35).confetti.length === 24,
    'revision-not-approval': s(29).status === 'Revised \\u00b7 awaiting recheck' && s(29).checks[1].verdict === 'Change' && !s(29).accepted,
    'stagger-within-one-beat': s(8.65).probes[0].opacity > 0 && s(8.65).probes[2].opacity === 0 && s(9.4).probes[2].opacity > 0,
    'layers-reassemble': s(29).candidate.layers.every(l => Math.abs(l.dx) < 1 && Math.abs(l.lift) < 0.05),
  };
}"""


def probe(html: Path, output: Path, profiles: list[str] | None = None) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    source = html.read_text().replace(
        '<meta charset="utf-8">', f'<meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="{CSP}">'
    )
    report = {"source": str(html), "checks": [], "errors": [], "requests": [], "captures": []}

    def check(name, value, details=None):
        report["checks"].append({"name": name, "pass": bool(value), "details": details})

    def open_frame(browser, width, reduced=False):
        page = browser.new_page(
            viewport={"width": width, "height": 1100}, reduced_motion="reduce" if reduced else "no-preference"
        )
        page.on("pageerror", lambda error: report["errors"].append(str(error)))
        page.on(
            "request",
            lambda request: report["requests"].append(request.url)
            if not request.url.startswith(("data:", "about:"))
            else None,
        )
        page.set_content(
            '<iframe sandbox="allow-scripts" style="border:0;position:absolute;inset:0;width:100%;height:100%" srcdoc="'
            + escape(source, quote=True)
            + '"></iframe>'
        )
        frame = page.frames[1]
        frame.wait_for_function("() => window.motion?.state().rendered")
        return page, frame

    def pose(frame):
        return frame.evaluate(
            "() => ({scene: motion.state().scene,"
            ' paths: [...document.querySelectorAll("svg path")].map(p => p.getAttribute("d")),'
            ' ledger: document.querySelector(".motion-ledger").innerText,'
            ' overlay: [...document.querySelectorAll(".motion-track > *, .motion-ledger [style]")].map(n => n.getAttribute("style"))})'
        )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for width in [1120, 390]:
            page, frame = open_frame(browser, width)
            if width == 1120:
                for name, passed in frame.evaluate(CONTRACTS).items():
                    check(name, passed)
            available = frame.locator("#profile option").evaluate_all("nodes => nodes.map(n => n.value)")
            styles = available if profiles is None else profiles
            if not styles or len(set(styles)) != len(styles) or set(styles) - set(available):
                raise ValueError(f"Choose unique profiles from {available}")
            for recipe in ["engraving", "cinematic", "miniature"]:
                frame.locator("#recipe").select_option(recipe)
                scenes = []
                for style in styles:
                    frame.locator("#profile").select_option(style)
                    for i in range(5):
                        state = frame.evaluate("i => {motion.go(i);return motion.state()}", i)
                        box = state["actorBox"] or {}
                        center = (
                            (box.get("x0", -1) + box.get("x1", -1)) / 2,
                            (box.get("y0", -1) + box.get("y1", -1)) / 2,
                        )
                        check(
                            f"{width}-{recipe}-{style}-hold-{i}",
                            state["cue"] is not None
                            and state["rendered"]
                            and not state["fallback"]
                            and 0.04 < center[0] < 0.96
                            and 0.04 < center[1] < 0.96,
                            center,
                        )
                    frame.evaluate("() => motion.seek(26)")
                    scenes.append(
                        frame.evaluate("times => [...motion.holds, ...times].map(t => motion.stateAt(t))", SEEK_TIMES)
                    )
                    for time in SEEK_TIMES:
                        images, poses = [], []
                        for history in [[0, 8, time], [40, 29, 0, time]]:
                            for t in history:
                                frame.evaluate("t => motion.seek(t)", t)
                            poses.append(pose(frame))
                            # Stage pixels carry the renderers; DOM text outside it is compared as text and transforms.
                            images.append(
                                Image.open(BytesIO(frame.locator(".motion-stage").screenshot())).convert("RGB")
                            )
                        diff = ImageChops.difference(*images)
                        max_error = max(v[1] for v in diff.getextrema())
                        changed = sum(1 for pixel in diff.getdata() if max(pixel)) / (diff.width * diff.height)
                        # SVG edge antialiasing can differ after morph normalization; geometry must still match.
                        tolerance = max_error <= 16 and changed <= 0.0005 if recipe == "engraving" else max_error == 0
                        check(
                            f"{width}-{recipe}-{style}-seek-{time}",
                            poses[0] == poses[1] and tolerance,
                            {"max_error": max_error, "changed_fraction": changed},
                        )
                    name = f"{recipe}-{style}-{width}.png"
                    frame.evaluate("() => motion.seek(21.7)")
                    frame.locator("[data-motion-plate]").screenshot(path=str(output / name))
                    report["captures"].append(name)
                check(f"{width}-{recipe}-style-invariance", all(scene == scenes[0] for scene in scenes))
            check(
                f"{width}-no-horizontal-overflow",
                frame.evaluate("() => document.documentElement.scrollWidth <= innerWidth"),
            )
            frame.evaluate("() => {DoxMotionLib.forceDispatchSeekEvent(12.5)}")
            check(f"{width}-hyperframes-seek", frame.evaluate("() => motion.state().time") == 12.5)
            frame.evaluate("() => {motion.go(0);motion.go(4,true);motion.go(1)}")
            frame.wait_for_timeout(180)
            check(f"{width}-stale-tween-cancelled", frame.evaluate("() => motion.state().time") == 8)
            page.close()
        page, frame = open_frame(browser, 1120, reduced=True)
        frame.evaluate("() => motion.go(3,true)")
        check(
            "reduced-motion-hold",
            frame.evaluate("() => motion.state().time") == 29 and not frame.evaluate("() => motion.play()"),
        )
        page.close()
        page, frame = open_frame(browser, 1120)
        frame.locator("#recipe").select_option("miniature")
        frame.evaluate("() => {motion.seek(8);motion.play()}")
        frame.wait_for_timeout(450)
        check("play-advances", frame.evaluate("() => motion.state().time") > 8)
        frame.evaluate('() => {document.querySelector("[data-motion-plate]").style.display="none"}')
        frame.wait_for_timeout(180)
        before = frame.evaluate("() => motion.state()")
        frame.wait_for_timeout(180)
        after = frame.evaluate("() => motion.state()")
        check(
            "offscreen-pauses",
            not after["playing"] and before["time"] == after["time"] and before["submitted"] == after["submitted"],
        )
        frame.evaluate(
            '() => {document.querySelector("[data-motion-plate]").style.display="";motion.setRecipe("cinematic");motion.go(2)}'
        )
        frame.wait_for_function("() => motion.state().rendered")
        frame.locator("#profile").select_option(styles[0])
        original = frame.locator(".motion-stage").screenshot()
        replacement = next(style for style in available if style != styles[0])
        # Every one of the N component slots gates readiness, not only the first.
        frame.evaluate('style => document.querySelector(`#motion-${style}-scanner`).removeAttribute("src")', styles[0])
        frame.wait_for_function("() => !motion.state().rendered")
        check(
            "missing-component-blocks-playback",
            not frame.evaluate("() => motion.play()") and frame.locator(".motion-fault").is_visible(),
        )
        frame.evaluate(
            '([style, replacement]) => {for (const part of ["scanner", "core"]) '
            "document.querySelector(`#motion-${style}-${part}`).src=document.querySelector(`#motion-${replacement}-${part}`).src}",
            [styles[0], replacement],
        )
        frame.wait_for_function("() => motion.state().rendered")
        check("component-change-refreshes-texture", original != frame.locator(".motion-stage").screenshot())
        frame.evaluate(
            '() => document.querySelector("canvas").dispatchEvent(new Event("webglcontextlost",{cancelable:true}))'
        )
        check(
            "context-loss-fallback",
            frame.evaluate('() => motion.state().fallback && motion.state().renderer === "svg"'),
        )
        before = frame.evaluate("() => {motion.destroy();return motion.state().submitted}")
        frame.evaluate("() => DoxMotionLib.forceDispatchSeekEvent(3)")
        check("destroy-detaches-rendering", frame.evaluate("() => motion.state().submitted") == before)
        page.close()
        browser.close()
        browser = p.chromium.launch(headless=True, args=["--disable-webgl"])
        page, frame = open_frame(browser, 1120)
        frame.locator("#recipe").select_option("miniature")
        for style in styles:
            frame.locator("#profile").select_option(style)
            state = frame.evaluate("() => {motion.go(2);return motion.state()}")
            check(
                f"{style}-explicit-webgl-fallback",
                state["fallback"]
                and state["renderer"] == "svg"
                and state["rendered"]
                and frame.locator(".motion-fault").is_visible(),
            )
        page.close()
        browser.close()
    check("no-page-errors", not report["errors"], report["errors"])
    check("offline-under-csp", not report["requests"], report["requests"])
    report["ok"] = all(item["pass"] for item in report["checks"])
    (output / "validation.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--html", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--profiles", nargs="+", help="Selected profile IDs; defaults to every profile in the built HTML"
    )
    args = parser.parse_args()
    report = probe(args.html, args.output, args.profiles)
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "checks": len(report["checks"]),
                "failures": [c for c in report["checks"] if not c["pass"]],
            }
        )
    )
    raise SystemExit(0 if report["ok"] else 1)
