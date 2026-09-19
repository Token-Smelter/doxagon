"""Factory commands must never choose an operator's project implicitly."""

import os
from pathlib import Path
import subprocess
import sys

from PIL import Image
import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_drift_requires_a_project_before_reading_content():
    from click.testing import CliRunner
    from scripts.dox import cli

    result = CliRunner().invoke(cli, ["drift"])
    assert result.exit_code == 2
    assert "Missing argument 'THESIS'" in result.output


@pytest.mark.parametrize("lowres", [False, True])
def test_thumbnails_require_explicit_project_and_read_selected_vault(tmp_path, lowres):
    script = ROOT / "factory/scripts/generate_thumbnails.py"
    image = tmp_path / "vault/projects/example/outputs/presentation/slides/01/images/main/outputs/original.png"
    image.parent.mkdir(parents=True)
    Image.new("RGB", (64, 32), "blue").save(image)
    env = {**os.environ, "DOXAGON_ROOT": str(tmp_path / "vault")}
    options = ["--lowres", "--output-dir", str(tmp_path / "lowres")] if lowres else []
    missing = subprocess.run([sys.executable, str(script), *options], env=env, capture_output=True, text=True)
    assert missing.returncode == 2
    assert "--presentation" in missing.stderr
    result = subprocess.run([sys.executable, str(script), "--presentation", "example", *options], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    output = tmp_path / "lowres/01_original.jpg" if lowres else image.with_name(".thumb_original.jpg")
    assert output.is_file()
    assert Image.open(output).size == (64, 32)
