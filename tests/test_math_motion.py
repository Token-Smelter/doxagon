"""Numerical contracts for geometry-first animation, independent of its renderer."""

import json
from pathlib import Path
import runpy
import subprocess

import pytest

from doxagon import toolchain

ROOT = Path(__file__).parents[1]
KIT = ROOT / "src/doxagon/resources/skills/presentation-motion"


def node(expression):
    program = f"require({json.dumps(str(KIT / 'kit/math/model.js'))}); const m=globalThis.DoxMathModel; console.log(JSON.stringify({expression}));"
    return json.loads(subprocess.check_output(["node", "-e", program], text=True))


def test_eigenpairs_and_change_of_basis_agree():
    result = node("""(() => {
      const {P,inverseP,eigenbasisMatrix:D}=m.at(40);
      const multiply=(a,b)=>a.map(row=>b[0].map((_,j)=>row.reduce((sum,x,k)=>sum+x*b[k][j],0)));
      return {plus:m.apply(m.A,[1,1]),minus:m.apply(m.A,[1,-1]),diagonal:multiply(multiply(inverseP,m.A),P),recovered:multiply(multiply(P,D),inverseP)};
    })()""")
    assert result == {"plus": [3, 3], "minus": [1, -1], "diagonal": [[3, 0], [0, 1]], "recovered": [[2, 1], [1, 2]]}


def test_every_interpolated_grid_point_and_tip_to_tail_sum_uses_the_same_map():
    result = node("""(() => {
      let maxError=0;
      for(let t=0;t<=40;t+=0.125){
        const s=m.at(t),p=s.amount;
        for(let x=-3;x<=3;x++) for(let y=-3;y<=3;y++){
          const actual=m.apply(s.matrix,[x,y]);
          maxError=Math.max(maxError,Math.abs(actual[0]-((1+p)*x+p*y)),Math.abs(actual[1]-(p*x+(1+p)*y)));
        }
        const fromBasis=s.basisX.map((x,i)=>x+2*s.basisY[i]);
        maxError=Math.max(maxError,...s.sumEnd.map((x,i)=>Math.abs(x-fromBasis[i])));
      }
      return maxError;
    })()""")
    assert result < 1e-12


def test_search_identifies_both_invariant_lines_without_calling_other_scales_eigenvalues():
    result = node(
        "[0,45,90,135,180].map(degrees=>{const s=m.at(23,degrees*Math.PI/180);return [s.aligned,s.eigenvalue]})"
    )
    assert result == [[False, None], [True, 3], [False, None], [True, 1], [False, None]]


def test_equation_targets_and_geometry_agree_at_all_times():
    assert node("""(() => {
      for(let t=0;t<=40;t+=0.1){
        const s=m.at(t),computed=m.apply(s.operator,s.source);
        if(computed.some((x,i)=>Math.abs(x-s.target[i])>1e-12)) return false;
        if(s.aligned && s.target.some((x,i)=>Math.abs(x-s.eigenvalue*s.source[i])>1e-8)) return false;
      }
      return true;
    })()""")


def test_installed_math_builder_needs_no_images_or_gpu_bundle(tmp_path):
    toolchain.sync_agent_resources(tmp_path / "vault")
    script = tmp_path / "vault/.pi/skills/presentation-motion/scripts/build_math_sample.py"
    build = runpy.run_path(str(script))["build"]
    report = build(tmp_path / "preview")
    html = (tmp_path / "preview/index.html").read_text()
    assert (
        report["image_components"],
        report["renderer"],
        "<math " in html,
        "DoxMotionLib" in html,
        "data:image/" in html,
        'src="http' in html,
    ) == (0, "svg-mathml", True, False, False, False)


def test_math_builder_cannot_overwrite_a_selected_document(tmp_path):
    build = runpy.run_path(str(KIT / "scripts/build_math_sample.py"))["build"]
    with pytest.raises(ValueError, match="authoritative document"):
        build(tmp_path / "outputs/document")


def space(expression):
    program = (
        f"require({json.dumps(str(KIT / 'kit/math/space-model.js'))}); const m=globalThis.DoxSpaceModel; "
        f"console.log(JSON.stringify({expression}));"
    )
    return json.loads(subprocess.check_output(["node", "-e", program], text=True))


def test_3d_screw_path_ends_at_A_and_keeps_the_diagonal_with_volume_det():
    result = space("""(() => {
      let worst = 0;
      for (let s = 0; s <= 1.0001; s += 0.01) {
        const M = m.matrixAt(s), d = m.apply(M, [1, 1, 1]);
        worst = Math.max(worst, ...d.map(x => Math.abs(x - (1 + 3 * s))), Math.abs(m.det(M) - (1 + 3 * s)));
      }
      const end = m.matrixAt(1);
      return { worst, end: end.map(r => r.map(x => Math.round(x * 1e9) / 1e9)) };
    })()""")
    assert result["worst"] < 1e-12 and result["end"] == [[1, 1, 2], [2, 1, 1], [1, 2, 1]]


def test_3d_matrix_satisfies_its_cubic_characteristic_polynomial():
    assert space("""(() => {
      const A = m.A, mul = (X, Y) => X.map(r => [0, 1, 2].map(j => r.reduce((t, x, k) => t + x * Y[k][j], 0)));
      const A2 = mul(A, A), A3 = mul(A2, A);
      return A3.map((r, i) => r.map((x, j) => x - 3 * A2[i][j] - 3 * A[i][j] - 4 * (i === j)));
    })()""") == [[0, 0, 0], [0, 0, 0], [0, 0, 0]]


def test_3d_camera_looks_down_the_invariant_line_and_orbit_is_view_only():
    result = space("""(() => {
      const s = m.at(28), o = m.project([0, 0, 0], s.view, 1.2), d = m.project(s.diagonal, s.view, 1.2), turned = m.at(28, 45);
      return { offset: Math.hypot(o.x - d.x, o.y - d.y), along: s.alongDiagonal,
        same: JSON.stringify([turned.matrix, turned.images]) === JSON.stringify([s.matrix, s.images]), moved: turned.alongDiagonal > 30 };
    })()""")
    assert result["offset"] < 1e-12 and result["along"] < 1e-6 and result["same"] and result["moved"]


def test_installed_sample_sheet_combines_all_samples_offline(tmp_path):
    toolchain.sync_agent_resources(tmp_path / "vault")
    script = tmp_path / "vault/.pi/skills/presentation-motion/scripts/build_gallery.py"
    report = runpy.run_path(str(script))["build"](tmp_path / "sheet")
    html = (tmp_path / "sheet/index.html").read_text()
    assert (
        report["samples"],
        html.count('role="tabpanel"'),
        all(name in html for name in ("DoxMotion.mount", "DoxMathLesson.mount", "DoxSpaceLesson.mount")),
        'src="http' in html or 'href="http' in html,
    ) == (["motion", "plane", "space"], 3, True, False)
