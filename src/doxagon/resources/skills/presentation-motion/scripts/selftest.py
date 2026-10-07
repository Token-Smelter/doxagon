"""Self-test this skill where it is installed. Run it with the Python environment that runs `dox`.

Default checks need Pillow and Node (or Playwright when Node is absent). `--pipeline` drives the real
`dox` CLI through a disposable synthetic vault with the free fixture provider. `--browser` builds the
samples and runs the three browser probes. Nothing touches a real project or calls a paid provider.
"""

from __future__ import annotations

import argparse
import base64
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import re
import runpy
import shlex
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
MODELS = {
    "plane": ["kit/math/model.js"],
    "space": ["kit/math/space-model.js"],
    "stage": ["vendor/motion-deps.min.js", "kit/stage/kit.js"],
}

# Pure-model identities. Each returns a JSON value evaluated in Node or Chromium.
PLANE = {
    "plane-eigenpairs-and-change-of-basis": """(() => { const m=globalThis.DoxMathModel, s=m.at(40);
      const mul=(a,b)=>a.map(r=>b[0].map((_,j)=>r.reduce((t,x,k)=>t+x*b[k][j],0)));
      return JSON.stringify([m.apply(m.A,[1,1]), m.apply(m.A,[1,-1]), mul(mul(s.inverseP,m.A),s.P), mul(mul(s.P,s.eigenbasisMatrix),s.inverseP)])
        === JSON.stringify([[3,3],[1,-1],[[3,0],[0,1]],[[2,1],[1,2]]]); })()""",
    "plane-grid-and-tip-to-tail-use-one-map": """(() => { const m=globalThis.DoxMathModel; let e=0;
      for(let t=0;t<=40;t+=0.125){ const s=m.at(t),p=s.amount;
        for(let x=-3;x<=3;x++) for(let y=-3;y<=3;y++){ const a=m.apply(s.matrix,[x,y]);
          e=Math.max(e,Math.abs(a[0]-((1+p)*x+p*y)),Math.abs(a[1]-(p*x+(1+p)*y))); }
        const sum=s.basisX.map((x,i)=>x+2*s.basisY[i]); e=Math.max(e,...s.sumEnd.map((x,i)=>Math.abs(x-sum[i]))); }
      return e < 1e-12; })()""",
    "plane-search-names-only-true-eigenvalues": """(() => { const m=globalThis.DoxMathModel;
      return JSON.stringify([0,45,90,135,180].map(d=>{const s=m.at(23,d*Math.PI/180);return [s.aligned,s.eigenvalue];}))
        === JSON.stringify([[false,null],[true,3],[false,null],[true,1],[false,null]]); })()""",
    "plane-equations-match-geometry": """(() => { const m=globalThis.DoxMathModel;
      for(let t=0;t<=40;t+=0.1){ const s=m.at(t),c=m.apply(s.operator,s.source);
        if(c.some((x,i)=>Math.abs(x-s.target[i])>1e-12)) return false;
        if(s.aligned && s.target.some((x,i)=>Math.abs(x-s.eigenvalue*s.source[i])>1e-8)) return false; }
      return true; })()""",
}
SPACE = {
    "space-path-ends-at-A-keeps-diagonal-and-volume": """(() => { const m=globalThis.DoxSpaceModel; let e=0;
      for(let s=0;s<=1.0001;s+=0.01){ const M=m.matrixAt(s),d=m.apply(M,[1,1,1]);
        e=Math.max(e,...d.map(x=>Math.abs(x-(1+3*s))),Math.abs(m.det(M)-(1+3*s))); }
      const end=m.matrixAt(1); return e<1e-12 && end.every((r,i)=>r.every((x,j)=>Math.abs(x-m.A[i][j])<1e-12)); })()""",
    "space-cayley-hamilton-cubic": """(() => { const A=globalThis.DoxSpaceModel.A;
      const mul=(X,Y)=>X.map(r=>[0,1,2].map(j=>r.reduce((t,x,k)=>t+x*Y[k][j],0))), A2=mul(A,A), A3=mul(A2,A);
      return A3.every((r,i)=>r.every((x,j)=>x-3*A2[i][j]-3*A[i][j]-4*(i===j)===0)); })()""",
    "space-axis-view-and-view-only-orbit": """(() => { const m=globalThis.DoxSpaceModel, s=m.at(28), t=m.at(28,45);
      const o=m.project([0,0,0],s.view,1.2), d=m.project(s.diagonal,s.view,1.2);
      return Math.hypot(o.x-d.x,o.y-d.y)<1e-12 && s.alongDiagonal<1e-6 && t.alongDiagonal>30
        && JSON.stringify([t.matrix,t.images,t.volume])===JSON.stringify([s.matrix,s.images,s.volume]); })()""",
}


# Stage library contracts that need no GPU: the bundle is complete, every surface and look builds, and the
# helpers keep their promises.
STAGE = {
    "stage-bundle-exports-the-pieces-scenes-needed": """['RoomEnvironment', 'RoundedBoxGeometry', 'LineSegments2', 'LineSegmentsGeometry', 'LineMaterial',
      'EdgesGeometry', 'BackSide', 'MeshPhysicalMaterial', 'MeshToonMaterial', 'PMREMGenerator', 'NeutralToneMapping', 'createThreeAdapter']
      .every(name => name in DoxMotionLib)""",
    "stage-every-surface-and-look-builds": """(() => { const K = DoxStageKit(DoxMotionLib), kinds = Object.keys(K.surfaces());
      const looks = K.looks().every(name => { const look = K.look(name), [kind] = [].concat(look.surface);
        return kinds.includes(kind) && K.toneMapping(look.toneMapping) !== undefined; });
      return kinds.length === 9 && kinds.every(kind => K.surface(kind).isMaterial) && looks; })()""",
    "stage-xray-adapts-to-background": """(() => { const K = DoxStageKit(DoxMotionLib), T = DoxMotionLib;
      return K.surface('xray', { background: '#000000' }).blending === T.AdditiveBlending
        && K.surface('xray', { background: '#ffffff' }).blending === T.NormalBlending; })()""",
    "stage-refuses-unknown-surface-options": """(() => { try { DoxStageKit(DoxMotionLib).surface('satin', { brushed: true }); return false; }
      catch (error) { return /has no option brushed/.test(error.message); } })()""",
    "stage-paper-to-solid-endpoints": """(() => { const K = DoxStageKit(DoxMotionLib), m = K.surface('satin', { color: '#336699' });
      K.setSolid(m, 0, '#f6f4ee'); const paper = m.color.getHex() === 0 && m.emissive.getHexString() === 'f6f4ee' && m.envMapIntensity === 0;
      K.setSolid(m, 1, '#f6f4ee'); return paper && m.color.getHexString() === '336699' && m.emissive.getHex() === 0; })()""",
    "stage-fit-keeps-every-point-in-frame": """(() => { const T = DoxMotionLib, K = DoxStageKit(T), inside = [];
      const box = new T.Box3(new T.Vector3(-1.6, -0.4, -0.8), new T.Vector3(1.4, 0.7, 0.5));
      for (const aspect of [16 / 9, 4 / 3, 0.75]) for (const camera of [new T.PerspectiveCamera(24, aspect), new T.OrthographicCamera()]) {
        K.fit(camera, box, { aspect, elevation: 0.42, azimuth: -0.3 }); camera.updateMatrixWorld();
        for (const x of [box.min.x, box.max.x]) for (const y of [box.min.y, box.max.y]) for (const z of [box.min.z, box.max.z]) {
          const p = new T.Vector3(x, y, z).project(camera); inside.push(Math.abs(p.x) <= 1 + 1e-9 && Math.abs(p.y) <= 1 + 1e-9); } }
      return inside.every(Boolean); })()""",
    "stage-rounded-shapes-keep-their-size": """(() => { const K = DoxStageKit(DoxMotionLib), T = DoxMotionLib, size = new T.Vector3();
      const box = K.shape('box', [1.2, 0.7, 0.6], { rounded: true }); box.computeBoundingBox(); box.boundingBox.getSize(size);
      const okBox = Math.abs(size.x - 1.2) < 1e-6 && Math.abs(size.y - 0.7) < 1e-6 && Math.abs(size.z - 0.6) < 1e-6;
      const turned = K.shape('cylinder', [0.1, 0.3, 0.36, 48], { rounded: true }); turned.computeBoundingBox(); turned.boundingBox.getSize(size);
      return okBox && Math.abs(size.y - 0.36) < 1e-6 && Math.abs(size.x - 0.6) < 1e-3; })()""",
    "stage-look-overrides-merge-one-level": """(() => { const look = DoxStageKit.look(['xray', { lines: { color: '#ffffff' }, background: '#000000' }]);
      return look.lines.color === '#ffffff' && look.lines.width === 1.1 && look.background === '#000000' && look.name === 'xray'; })()""",
    "stage-skin-wrap-is-continuous-and-hides-the-join": """(() => { const K = DoxStageKit(DoxMotionLib), g = K.shape('box', [1.2, 0.72, 0.62]).clone();
      const { fill } = K.mapWrap(g, 'box', 21 / 9), p = g.attributes.position, uv = g.attributes.uv;
      const at = (face, x, z) => { for (const group of g.groups) if (group.materialIndex === face)
        for (let k = group.start; k < group.start + group.count; k++) { const i = g.index ? g.index.array[k] : k;
          if (Math.abs(p.getX(i) - x) < 1e-6 && Math.abs(p.getZ(i) - z) < 1e-6) return uv.getX(i); } return NaN; };
      const near = (a, b) => Math.abs(a - b) < 1e-6, corner = 1.2 / 1.82;  // geometry is float32
      return near(at(4, -0.6, 0.31), 0) && near(at(4, 0.6, 0.31), corner) && near(at(0, 0.6, 0.31), corner)
        && near(at(0, 0.6, -0.31), 1) && near(at(5, 0.6, -0.31), 1) && near(at(1, -0.6, 0.31), 0)
        && near(fill, (21 / 9) / (1.82 / 0.72)); })()""",
    "stage-skin-tile-keeps-world-size": """(() => { const K = DoxStageKit(DoxMotionLib), g = K.shape('box', [1.2, 0.72, 0.62]).clone();
      K.mapTile(g, 'box', 0.3);
      const span = face => { const group = g.groups.find(x => x.materialIndex === face), us = [], vs = [];
        for (let k = group.start; k < group.start + group.count; k++) { const i = g.index.array[k];
          us.push(g.attributes.uv.getX(i)); vs.push(g.attributes.uv.getY(i)); }
        return [Math.max(...us) - Math.min(...us), Math.max(...vs) - Math.min(...vs)]; };
      const near = (a, b) => Math.abs(a - b) < 1e-6, [fu, fv] = span(4), [su, sv] = span(0), [tu, tv] = span(2);
      return near(fu, 4) && near(fv, 2.4) && near(su, 0.62 / 0.3) && near(sv, 2.4) && near(tu, 4) && near(tv, 0.62 / 0.3); })()""",
}


def module(name: str) -> dict:
    return runpy.run_path(str(SCRIPTS / name))


def evaluate(model: str, expressions: dict[str, str]) -> dict:
    """Evaluate identities without rendering: Node first (program on stdin), then a blank Chromium page."""
    sources = [(ROOT / name).read_text() for name in MODELS[model]]
    node = shutil.which("node")
    if node:
        program = (
            "\n;".join(sources)
            + "\nconsole.log(JSON.stringify({"
            + ",".join(f"{json.dumps(k)}:{v}" for k, v in expressions.items())
            + "}));"
        )
        return json.loads(subprocess.run([node, "-"], input=program, check=True, capture_output=True, text=True).stdout)
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        for source in sources:
            page.add_script_tag(content=source)
        result = {name: page.evaluate(f"() => {expression}") for name, expression in expressions.items()}
        browser.close()
    return result


def contracts(work: Path) -> list[tuple[str, bool, object]]:
    rows = []
    build_sample, build_math, build_gallery, build_stage = (
        module("build_sample.py"),
        module("build_math_sample.py"),
        module("build_gallery.py"),
        module("build_stage_sample.py"),
    )
    profiles = json.loads((ROOT / "samples/profiles.json").read_text())
    cases = sorted(p for p in (ROOT / "samples").glob("*.json") if p.name != "profiles.json")
    script = (ROOT / "kit/choreography.js").read_text()
    javascript = re.findall(r"'(\w+)'", re.search(r"COMPONENTS = \[(.*?)\]", script)[1])
    keys = [[c["key"] for c in json.loads(p.read_text())["components"]] for p in cases]
    rows.append(("components-agree", all(k == javascript == build_sample["COMPONENTS"] for k in keys), javascript))
    varied = {f: len({p[f] for p in profiles.values()}) for f in ("pattern", "stroke", "roughness", "image_direction")}
    rows.append(
        (
            "profiles-vary-material-not-only-palette",
            all(n == len(profiles) for n in varied.values()) and len({p["font"] for p in profiles.values()}) > 1,
            varied,
        )
    )
    manifest = json.loads((ROOT / "vendor/manifest.json").read_text())
    stale = [
        r["path"]
        for r in manifest["files"]
        if sha256((ROOT / "vendor" / r["path"]).read_bytes()).hexdigest() != r["sha256"]
    ]
    rows.append(("vendor-bytes-match-manifest", not stale, stale))
    broken = []
    for md in ROOT.rglob("*.md"):
        if "vendor" in md.relative_to(ROOT).parts:
            continue
        # A #section anchor names a heading; the file must exist (headings are not checked).
        for target, line in re.findall(r"\]\((\./[^):)#]+)(?:#[^):)]*)?(?::(\d+))?\)", md.read_text()):
            path = (md.parent / target).resolve()
            if not path.exists() or (line and int(line) > len(path.read_text().splitlines())):
                broken.append(f"{md.relative_to(ROOT)} -> {target}{':' + line if line else ''}")
    rows.append(("documentation-links-resolve", not broken, broken))
    for model, expressions in (("plane", PLANE), ("space", SPACE), ("stage", STAGE)):
        rows.extend((name, bool(value), None) for name, value in evaluate(model, expressions).items())
    offline = lambda html: 'src="http' not in html and 'href="http' not in html  # noqa: E731
    for case in cases:
        report = build_sample["build"](work / f"motion-{case.stem}", case)
        html = (work / f"motion-{case.stem}/index.html").read_text()
        shell = (work / f"motion-{case.stem}/plate-shell.html").read_text()
        rows.append(
            (
                f"motion-{case.stem}-builds-offline",
                len(report["images"]) == len(profiles) * len(javascript)
                and offline(html)
                and "data:image/" not in shell,
                len(report["images"]),
            )
        )
    for lesson in ("plane", "space"):
        report = build_math["build"](work / f"math-{lesson}", lesson)
        html = (work / f"math-{lesson}/index.html").read_text()
        rows.append(
            (
                f"math-{lesson}-builds-without-images",
                report["image_components"] == 0 and offline(html) and "<math" in html,
                None,
            )
        )
    report = build_stage["build"](work / "stage")
    html = (work / "stage/index.html").read_text()
    rows.append(
        (
            "stage-sample-builds-offline-with-every-look-and-skin",
            report["image_components"] == 0
            and offline(html)
            and html.count("data-stage-look=") == len(report["looks"]) == 11
            and html.count("data-stage-skin=") == len(report["skins"]) == 3
            and all(f'id="{key}"' in html for key in report["sample_skins"]),
            report["looks"] + report["skins"],
        )
    )
    report = build_gallery["build"](work / "sheet")
    html = (work / "sheet/index.html").read_text()
    rows.append(
        (
            "sample-sheet-combines-four-samples",
            report["samples"] == ["motion", "plane", "space", "stage"]
            and html.count('role="tabpanel"') == 4
            and offline(html),
            report["samples"],
        )
    )
    refused = []
    for name, call in (
        ("motion", lambda p: build_sample["build"](p, cases[0])),
        ("math", lambda p: build_math["build"](p)),
        ("sheet", lambda p: build_gallery["build"](p)),
        ("stage", lambda p: build_stage["build"](p)),
    ):
        try:
            call(work / name / "outputs/document")
        except ValueError:
            refused.append(name)
    rows.append(("builders-refuse-selected-document-paths", refused == ["motion", "math", "sheet", "stage"], refused))
    from PIL import Image

    check_alpha = module("check_alpha.py")["inspect"]
    results = []
    for transparent in (False, True):
        image = Image.new("RGBA", (20, 20), (100, 120, 140, 0 if transparent else 255))
        image.putpixel((10, 10), (100, 120, 140, 255))
        path = work / f"alpha-{transparent}.png"
        image.save(path)
        results.append(check_alpha(path)["ok"])
    rows.append(("alpha-checker-rejects-opaque-images", results == [False, True], results))
    skins = ROOT / "samples/stage/skins"
    provenance = (skins / "README.md").read_text()
    rows.append(
        (
            "sample-skins-are-documented-and-the-tile-has-alpha",
            check_alpha(skins / "engraved-lines.png")["ok"]
            and all(
                name in provenance
                for name in ("engraved-lines.png", "harbour-wrap.jpg", "gemini-3.1-flash-image-preview")
            ),
            sorted(p.name for p in skins.iterdir()),
        )
    )
    requests = module("asset_requests.py")
    case = json.loads(cases[0].read_text())
    files = requests["requests"](case, next(iter(profiles)), "selftest", {"core": "slot-0"}, "item-placeholder")
    creates = [n for n in files if n.startswith("create-") and n != "create-style.json"]
    definitions = " ".join(files[n]["definition"] for n in creates)
    wrap = requests["component_request"](
        {"key": "hull", "role": "skin-wrap", "description": "A coastline.", "aspect_ratio": "3:2"},
        "demo-hull",
        "demo-style",
    )["definition"]
    skin_plan = requests["requests"](
        {"components": [{"key": "hull", "role": "skin-wrap", "description": "A coastline.", "aspect_ratio": "3:2"}]},
        next(iter(profiles)),
        "selftest",
    )
    try:
        requests["component_request"](
            {"key": "hull", "role": "skin-wrap", "description": "x", "aspect_ratio": "21:9"}, "x", "y"
        )
        refused_ratio = False
    except ValueError:
        refused_ratio = True
    rows.append(
        (
            "asset-requests-describe-skins-as-surfaces",
            "aspect_ratio: '3:2'" in wrap
            and "silhouette" not in wrap
            and "panorama" in wrap
            and refused_ratio
            and "--aspect-ratio 3:2" in " ".join(skin_plan["sequence.json"]["steps"]),
            None,
        )
    )
    rows.append(
        (
            "asset-requests-cover-every-component",
            len(creates) == len(case["components"])
            and "bind-slots.template.json" in files
            and not re.search(r"#[0-9a-fA-F]{6}", definitions)
            and "whole.png" in files["create-core.json"]["definition"],
            len(creates),
        )
    )
    return rows


def pipeline(work: Path, dox: list[str]) -> list[tuple[str, bool, object]]:
    """Real CLI path on a synthetic vault: N components created, generated free, bound and selected."""
    from PIL import Image

    vault, slug = work / "vault", "selftest"
    project = vault / "projects" / slug
    directory = project / "outputs/document"
    directory.mkdir(parents=True)
    (vault / "knowledge").mkdir()
    (project / "config.yaml").write_text(f"name: {slug}\ntitle: Synthetic motion self-test\naudience: Agents\n")
    slots = []
    for i in range(6):
        buffer = BytesIO()
        Image.new("RGB", (8, 8), (i * 30, 80, 140)).save(buffer, format="PNG")
        slots.append(
            f'<img id="slot-{i}" alt="Slot {i}" src="data:image/png;base64,{base64.b64encode(buffer.getvalue()).decode()}">'
        )
    document = (
        (ROOT / "samples/pipeline/document.html")
        .read_text()
        .replace(
            "</body>",
            '<section hidden id="plates" class="chapter"><p data-cue="cue-0">Dawn</p>'
            + "".join(slots)
            + "</section></body>",
        )
    )
    (directory / f"{slug}.html").write_text(document)
    shutil.copyfile(ROOT / "samples/pipeline/notes.json", directory / "notes.json")
    (directory / "presentation.json").write_text(
        json.dumps({"schema": "doxagon.authored-document/1", "document": f"{slug}.html", "notes": "notes.json"})
    )
    provider = work / "fixture-provider"
    provider.write_text(
        f"#!{sys.executable}\nimport runpy, sys\nsys.path.insert(0, {str(SCRIPTS)!r})\n"
        f"sys.argv[0] = {str(SCRIPTS / 'fixture_provider.py')!r}\nrunpy.run_path(sys.argv[0], run_name='__main__')\n"
    )
    provider.chmod(0o700)
    env = {**os.environ, "DOXAGON_ROOT": str(vault), "DOXAGON_IMAGE_GENERATOR": str(provider)}

    def cli(*args, parse=True):
        result = subprocess.run([*dox, *args], capture_output=True, text=True, env=env)
        if result.returncode:
            raise RuntimeError(f"{' '.join(args[:2])}: {(result.stderr or result.stdout)[-400:]}")
        return json.loads(result.stdout) if parse else result.stdout

    def context():
        return cli("document", "context", "--project", slug, "--json")

    def apply(request, name):
        (work / f"{name}.json").write_text(json.dumps(request))
        cli(
            "document",
            "asset-plan",
            "--project",
            slug,
            "--snapshot",
            context()["snapshot"],
            "--request",
            str(work / f"{name}.json"),
            "--output",
            str(work / f"{name}-plan.json"),
            parse=False,
        )
        cli("document", "apply", "--project", slug, str(work / f"{name}-plan.json"), parse=False)

    rows = []
    whole = next(item["id"] for item in context()["items"] if item["kind"] == "image")
    case = json.loads((ROOT / "samples/inspection.json").read_text())
    selected = {"core": "slot-0", "scanner": "slot-1"}
    files = module("asset_requests.py")["requests"](case, "studio", "selftest", selected, whole)
    for name, request in files.items():
        if name.startswith("create-"):
            apply(request, name.removesuffix(".json"))
    registry_path = directory / "authoring.json"
    keys = set(json.loads(registry_path.read_text())["assets"])
    expected = {f"selftest-{c['key']}" for c in case["components"]}
    rows.append(("pipeline-registers-every-component", expected <= keys, sorted(keys)))
    for component in selected:
        plan = work / f"{component}-generation.json"
        cli(
            "document",
            "generation-plan",
            "--project",
            slug,
            "--snapshot",
            context()["snapshot"],
            "--asset",
            f"selftest-{component}",
            "--variants",
            "1",
            "--output",
            str(plan),
            parse=False,
        )
        model = json.loads(plan.read_text())["provider"]["model"]
        job = cli("document", "generation-run", "--project", slug, "--key", f"selftest-{component}", str(plan))
        rows.append(
            (
                f"pipeline-generates-{component}-free",
                model == "motion-fixture-no-generation" and job["status"] == "succeeded",
                job["status"],
            )
        )
    apply(
        {"operation": "bind-slots", "associations": {slot: f"selftest-{name}" for name, slot in selected.items()}},
        "bind",
    )
    registry = json.loads(registry_path.read_text())
    for component, slot in selected.items():
        variant = next(iter(registry["assets"][f"selftest-{component}"]["variants"]))
        apply(
            {"operation": "select-image", "key": f"selftest-{component}", "variant": variant, "slots": [slot]},
            f"select-{component}",
        )
    html = (directory / f"{slug}.html").read_text()
    alpha = {}
    for component, slot in selected.items():
        payload = re.search(rf'<img[^>]*id="{slot}"[^>]*src="data:image/[a-z]+;base64,([^"]+)"', html)[1]
        alpha[component] = Image.open(BytesIO(base64.b64decode(payload))).convert("RGBA").getchannel("A").getextrema()
    rows.append(("pipeline-selects-transparent-components", all(v == (0, 255) for v in alpha.values()), alpha))
    validation = subprocess.run(
        [*dox, "document", "validate", "--project", slug], capture_output=True, text=True, env=env
    )
    rows.append(("pipeline-document-still-validates", validation.returncode == 0, validation.stdout[-300:]))
    return rows


def browser(work: Path) -> list[tuple[str, bool, object]]:
    rows = []
    for builder, probe, args in (
        ("build_gallery.py", "probe_gallery.py", ()),
        ("build_math_sample.py", "probe_math_sample.py", ()),
        ("build_sample.py", "probe_sample.py", (ROOT / "samples/inspection.json",)),
    ):
        name = builder.removesuffix(".py")
        module(builder)["build"](work / name, *args)
        report = module(probe)["probe"](work / name / "index.html", work / f"{name}-proof")
        rows.append((f"browser-{probe.removesuffix('.py')}", report["ok"], len(report["checks"])))
    preview = module("preview_scene.py")
    module("build_stage_sample.py")["build"](work / "stage")
    pages = [("stage-sample", (work / "stage/index.html").read_text())]
    pages += [(f"starter-{p.stem}", preview["wrap"](p)) for p in sorted((ROOT / "kit/stage/starters").glob("*.js"))]
    for name, page in pages:
        report = preview["preview"](page, work / f"preview-{name}")
        failures = [row["name"] for row in report["checks"] if not row["pass"]]
        rows.append((f"browser-preview-{name}", report["ok"], failures or len(report["checks"])))
    return rows


def run(
    output: Path | None = None, with_pipeline: bool = False, with_browser: bool = False, dox: list[str] | None = None
) -> dict:
    work = Path(tempfile.mkdtemp(prefix="motion-selftest-")) if output is None else output
    if output is not None:
        output.mkdir(parents=True, exist_ok=False)
    rows = contracts(work / "samples")
    if with_pipeline:
        command = dox or [shutil.which("dox") or "dox"]
        try:
            rows += pipeline(work / "pipeline", command)
        except (RuntimeError, OSError, KeyError, TypeError) as error:
            rows.append(("pipeline-completes", False, str(error)))
    if with_browser:
        rows += browser(work / "browser")
    report = {
        "skill": str(ROOT),
        "work": str(work),
        "checks": [{"name": n, "pass": bool(p), "detail": d} for n, p, d in rows],
    }
    report["ok"] = all(row["pass"] for row in report["checks"])
    (work / "selftest.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pipeline", action="store_true", help="Run the free image pipeline through the dox CLI")
    parser.add_argument("--browser", action="store_true", help="Build the samples and run the browser probes")
    parser.add_argument(
        "--dox", help="dox command to use, for example 'python scripts/dox.py'; defaults to dox on PATH"
    )
    parser.add_argument("--output", type=Path, help="New directory for evidence; defaults to a temporary directory")
    args = parser.parse_args()
    result = run(args.output, args.pipeline, args.browser, shlex.split(args.dox) if args.dox else None)
    print(
        json.dumps(
            {
                "ok": result["ok"],
                "checks": len(result["checks"]),
                "work": result["work"],
                "failures": [row for row in result["checks"] if not row["pass"]],
            },
            indent=2,
            default=str,
        )
    )
    raise SystemExit(0 if result["ok"] else 1)
