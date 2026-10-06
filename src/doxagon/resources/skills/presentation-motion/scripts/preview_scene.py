"""Preview and check any seekable scene inside the document sandbox, then write one contact sheet.

A scene is any element marked data-dox-scene whose `doxScene` property exposes holds, stateAt(t) and
seek(t). DoxHost and DoxStage do this; a from-scratch scene calls DoxHost.expose or sets it itself.

  python preview_scene.py page.html --output NEW_DIR
  python preview_scene.py --scene my-scene.js --output NEW_DIR   # wraps the script with the stage libraries
"""

from __future__ import annotations

import argparse
from collections import Counter
from html import escape
from io import BytesIO
import json
from pathlib import Path
import runpy
import statistics

from PIL import Image, ImageChops, ImageDraw, ImageStat
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
CSP = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:; connect-src 'none'; frame-src 'none'"
FRAMES = "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(() => requestAnimationFrame(r))))"
SCENES = "() => [...document.querySelectorAll('[data-dox-scene]')].filter(el => el.doxScene).length"
READY = "() => [...document.querySelectorAll('[data-dox-scene]')].every(el => el.doxScene && el.dataset.doxReady === 'true')"


def wrap(scene: Path, aspect: str = "16 / 9") -> str:
    """A minimal page for a scene script: the GPU bundle, the stage layers, and a [data-stage] root."""
    stage = runpy.run_path(str(ROOT / "scripts/build_stage_sample.py"))
    inline = stage["inline_script"]
    return (
        '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{escape(scene.name)}</title><style>html,body{{margin:0;background:#e9e6df}}"
        f"[data-stage]{{position:relative;margin:0;width:100%;aspect-ratio:{aspect}}}</style>"
        '<figure data-stage aria-label="Scene preview"></figure>'
        # The sample skins ride along as document images (ids skin-engraved-lines, skin-harbour-wrap).
        + stage["skin_images"]()
        + inline((ROOT / "vendor/motion-deps.min.js").read_text())
        + stage["stage_scripts"]()
        + inline(scene.read_text())
        + "</html>"
    )


def border_touch(image: Image.Image) -> float:
    """Share of the outer 3-pixel ring unlike the ring's usual colour: content running off the frame.
    The usual colour, not a corner pixel, so rounded corners showing the page behind do not count."""
    # Element screenshots round outward, so the outermost device pixels can belong to the page.
    rgb = image.convert("RGB").crop((3, 3, image.width - 3, image.height - 3))
    w, h = rgb.size
    ring = [(x, y) for x in range(w) for y in (*range(3), *range(h - 3, h))]
    ring += [(x, y) for y in range(3, h - 3) for x in (*range(3), *range(w - 3, w))]
    colours = [rgb.getpixel(p) for p in ring]
    background = Counter(tuple(c // 8 for c in colour) for colour in colours).most_common(1)[0][0]
    background = tuple(c * 8 + 4 for c in background)
    different = sum(1 for colour in colours if max(abs(a - b) for a, b in zip(colour, background)) > 24)
    return different / len(ring)


def difference(a: Image.Image, b: Image.Image) -> tuple[int, float]:
    diff = ImageChops.difference(a.convert("RGB"), b.convert("RGB"))
    maximum = max(high for _, high in diff.getextrema())
    changed = sum(1 for pixel in diff.getdata() if max(pixel) > 16) / (diff.width * diff.height)
    return maximum, changed


def contact_sheet(rows: list[tuple[str, list[tuple[str, Image.Image]]]], path: Path) -> None:
    cell = 360
    tiles = [
        [(label, image.resize((cell, max(1, round(image.height * cell / image.width))))) for label, image in row]
        for _, row in rows
    ]
    heights = [max(t.height for _, t in row) + 22 for row in tiles]
    width = max(len(row) for row in tiles) * (cell + 8) + 8
    sheet = Image.new("RGB", (width, sum(heights) + 26 * len(rows) + 8), "#f2efe8")
    draw = ImageDraw.Draw(sheet)
    y = 8
    for (title, _), row, height in zip(rows, tiles, heights):
        draw.text((8, y), title, fill="#1d2430")
        y += 22
        for i, (label, tile) in enumerate(row):
            x = 8 + i * (cell + 8)
            sheet.paste(tile, (x, y + 18))
            draw.text((x, y + 2), label, fill="#585f6b")
        y += height + 4
    sheet.save(path)


def preview(page: str, output: Path, widths: tuple[int, ...] = (1280, 390), max_pixel_ratio: float = 1.5) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    content = page.replace(
        '<meta charset="utf-8">',
        f'<meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="{CSP}">',
        1,
    )
    report = {"ok": False, "checks": [], "errors": [], "requests": [], "scenes": [], "contact": "contact.png"}
    rows = []

    def check(name, passed, detail=None):
        report["checks"].append({"name": name, "pass": bool(passed), "detail": detail})

    def open_frame(browser, width, reduce=False):
        page_ = browser.new_page(
            viewport={"width": width, "height": 900},
            device_scale_factor=2,
            reduced_motion="reduce" if reduce else "no-preference",
        )
        page_.on("pageerror", lambda error: report["errors"].append(str(error)))
        page_.on("console", lambda message: report["errors"].append(message.text) if message.type == "error" else None)
        page_.on(
            "request",
            lambda request: None
            if request.url.startswith(("data:", "about:"))
            else report["requests"].append(request.url),
        )
        page_.set_content(
            '<iframe sandbox="allow-scripts" style="position:absolute;inset:0;border:0;width:100%;height:100%" srcdoc="'
            + escape(content, quote=True)
            + '"></iframe>'
        )
        frame = page_.frames[1]
        frame.wait_for_load_state()
        return page_, frame

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        for width in widths:
            page_, frame = open_frame(browser, width)
            try:
                frame.wait_for_function(SCENES, timeout=20000)
                frame.wait_for_function(READY, timeout=30000)
            except Exception:  # noqa: BLE001 - a missing contract is reported, not raised
                check(
                    f"{width}-scene-found",
                    False,
                    "No element exposes doxScene with holds, stateAt and seek, or none finished drawing",
                )
                page_.close()
                continue
            count = frame.evaluate(SCENES)
            # Quiet every scene's ambient motion first; captures need a still page, not just a still subject.
            frame.evaluate(
                "() => document.querySelectorAll('[data-dox-scene]').forEach(el => el.doxScene.pinIdle?.(0))"
            )
            check(
                f"{width}-no-horizontal-overflow",
                frame.evaluate("() => document.documentElement.scrollWidth <= innerWidth + 1"),
            )
            # What a viewer sees on load, before anything seeks: an opening hold can hide what the scene is for.
            openings = {}
            for index in range(count):
                handle = frame.locator("[data-dox-scene]").nth(index)
                handle.scroll_into_view_if_needed()
                frame.evaluate(FRAMES)
                opened_at = frame.evaluate(
                    f"() => document.querySelectorAll('[data-dox-scene]')[{index}].doxScene.time ?? null"
                )
                openings[index] = (opened_at, Image.open(BytesIO(handle.screenshot())).convert("RGB"))
            for index in range(count):
                handle = frame.locator("[data-dox-scene]").nth(index)
                name = handle.get_attribute("data-dox-scene") or f"scene-{index + 1}"
                handle.scroll_into_view_if_needed()
                api = f"document.querySelectorAll('[data-dox-scene]')[{index}].doxScene"
                info = frame.evaluate(
                    f"() => {{ const s = {api}; return {{ holds: s.holds, cues: s.cues || [], pin: typeof s.pinIdle === 'function', play: typeof s.play === 'function' }}; }}"
                )
                holds = info["holds"]
                if info["pin"]:
                    frame.evaluate(f"() => {api}.pinIdle(0)")
                captures, states = {}, {}
                for history in (range(len(holds)), reversed(range(len(holds)))):
                    for i in history:
                        frame.evaluate(f"t => {api}.seek(t)", holds[i])
                        frame.evaluate(FRAMES)
                        image = Image.open(BytesIO(handle.screenshot())).convert("RGB")
                        state = frame.evaluate(f"t => JSON.stringify({api}.stateAt(t))", holds[i])
                        if i in captures:
                            maximum, changed = difference(captures[i], image)
                            check(
                                f"{width}-{name}-hold-{i}-repeats-after-other-seeks",
                                state == states[i] and changed <= 0.002,
                                {"max_channel_error": maximum, "changed_fraction": round(changed, 5)},
                            )
                        else:
                            captures[i], states[i] = image, state
                for i, image in captures.items():
                    file = f"{name}-{width}-hold-{i}.png"
                    image.save(output / file)
                    touch = border_touch(image)
                    check(f"{width}-{name}-hold-{i}-framed", touch <= 0.01, {"edge_share": round(touch, 4)})
                    check(f"{width}-{name}-hold-{i}-not-blank", ImageStat.Stat(image.convert("L")).stddev[0] > 2.5)
                ratio = frame.evaluate(f"""() => Math.max(0, ...[...{api}.root ? {api}.root.querySelectorAll('canvas') : document.querySelectorAll('[data-dox-scene] canvas')]
                    .filter(c => c.clientWidth).map(c => c.width / c.clientWidth))""")
                check(
                    f"{width}-{name}-pixel-ratio-capped",
                    ratio <= max_pixel_ratio + 0.01,
                    {"canvas_pixel_ratio": round(ratio, 3), "cap": max_pixel_ratio},
                )
                timing = None
                if info["play"]:
                    timing = frame.evaluate(f"""async () => {{
                        const s = {api}; s.seek(s.holds[0]); if (s.pinIdle) s.pinIdle(null); s.play();
                        const deltas = []; let last = performance.now();
                        await new Promise(done => {{ const step = now => {{ deltas.push(now - last); last = now;
                          deltas.length < 90 ? requestAnimationFrame(step) : done(); }}; requestAnimationFrame(step); }});
                        s.pause(); if (s.pinIdle) s.pinIdle(0); return deltas.slice(5);
                    }}""")
                report["scenes"].append(
                    {
                        "name": name,
                        "width": width,
                        "holds": holds,
                        "cues": info["cues"],
                        "frame_ms": None
                        if not timing
                        else {
                            "median": round(statistics.median(timing), 1),
                            "p95": round(sorted(timing)[int(len(timing) * 0.95)], 1),
                        },
                    }
                )
                opened_at, opened = openings[index]
                opened.save(output / f"{name}-{width}-opened.png")
                check(f"{width}-{name}-opens-not-blank", ImageStat.Stat(opened.convert("L")).stddev[0] > 2.5)
                rows.append(
                    (
                        f"{name} at {width}px",
                        [("as opened" + (f" · t={opened_at:g}" if opened_at is not None else ""), opened)]
                        + [
                            (
                                f"hold {i} · t={holds[i]:g}"
                                + (f" · {info['cues'][i]}" if i < len(info["cues"]) else ""),
                                captures[i],
                            )
                            for i in sorted(captures)
                        ],
                    )
                )
            page_.close()
        page_, frame = open_frame(browser, widths[0], reduce=True)
        try:
            frame.wait_for_function(READY, timeout=30000)
            for index in range(frame.evaluate(SCENES)):
                api = f"document.querySelectorAll('[data-dox-scene]')[{index}].doxScene"
                handle = frame.locator("[data-dox-scene]").nth(index)
                handle.scroll_into_view_if_needed()
                arrived = frame.evaluate(f"""() => {{ const s = {api}; if (typeof s.go !== 'function') return null;
                    s.go(s.holds.length - 1); return Math.abs((s.time ?? s.holds.at(-1)) - s.holds.at(-1)) < 1e-6; }}""")
                if arrived is not None:
                    check(f"reduced-motion-scene-{index + 1}-arrives-at-once", arrived)
                frame.evaluate(FRAMES)
                first = Image.open(BytesIO(handle.screenshot()))
                frame.wait_for_timeout(600)
                maximum, changed = difference(first, Image.open(BytesIO(handle.screenshot())))
                check(
                    f"reduced-motion-scene-{index + 1}-holds-still",
                    changed <= 0.002,
                    {"changed_fraction": round(changed, 5)},
                )
        except Exception as error:  # noqa: BLE001
            check("reduced-motion-pass", False, str(error)[:300])
        page_.close()
        browser.close()
    check("no-script-errors", not report["errors"], report["errors"][:10])
    check("no-network-requests", not report["requests"], report["requests"][:10])
    if rows:
        contact_sheet(rows, output / "contact.png")
    report["ok"] = bool(rows) and all(row["pass"] for row in report["checks"])
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("page", nargs="?", type=Path, help="An HTML page containing one or more scenes")
    parser.add_argument(
        "--scene", type=Path, help="A scene script that mounts on [data-stage]; wrapped with the stage libraries"
    )
    parser.add_argument("--aspect", default="16 / 9", help="Wrapper aspect ratio for --scene")
    parser.add_argument("--output", type=Path, required=True, help="New directory for the contact sheet and report")
    parser.add_argument("--widths", default="1280,390", help="Viewport widths in CSS pixels")
    parser.add_argument("--max-pixel-ratio", type=float, default=1.5)
    args = parser.parse_args()
    if bool(args.page) == bool(args.scene):
        parser.error("give either a page or --scene")
    html = wrap(args.scene, args.aspect) if args.scene else args.page.read_text()
    result = preview(html, args.output, tuple(int(w) for w in args.widths.split(",")), args.max_pixel_ratio)
    print(
        json.dumps(
            {
                "ok": result["ok"],
                "checks": len(result["checks"]),
                "contact": str(args.output / "contact.png"),
                "scenes": result["scenes"],
                "failures": [row for row in result["checks"] if not row["pass"]],
            },
            indent=2,
        )
    )
    raise SystemExit(0 if result["ok"] else 1)
