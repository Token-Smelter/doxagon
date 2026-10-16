"""After `dox init`, every command finds the vault with nothing exported, and images are optional."""

import base64
import json
import os
import subprocess
import sys
import threading
import tomllib
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from doxagon import user_config
from doxagon.renderings.document_generation import validate_provider_capabilities

from .test_knowledge_intake import REPO

GEMINI = REPO / "src/doxagon/resources/skills/image-provider/adapters/gemini.py"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def run(home: Path, *args, cwd: Path | None = None, **env) -> subprocess.CompletedProcess:
    environment = {key: value for key, value in os.environ.items()
                   if key not in ("DOXAGON_ROOT", "DOXAGON_IMAGE_GENERATOR")}
    environment.update(HOME=str(home), DOXAGON_CONFIG=str(home / "config.toml"), PYTHONPATH=str(REPO), **env)
    return subprocess.run([sys.executable, "-c", "from scripts.dox import cli; cli()", *args],
                          cwd=cwd or home, env=environment, capture_output=True, text=True, timeout=120)


@pytest.fixture
def home(tmp_path):
    return tmp_path


def test_init_makes_the_vault_the_default_for_later_commands(home):
    assert run(home, "init", str(home / "vault")).returncode == 0
    (home / "elsewhere").mkdir()
    captured = run(home, "capture", "Defaults remove a step from onboarding", cwd=home / "elsewhere")
    assert (captured.returncode, len(list((home / "vault/knowledge/doxai").glob("d-*.md")))) == (0, 1)


def test_a_second_init_does_not_steal_the_default(home):
    run(home, "init", str(home / "first"))
    run(home, "init", str(home / "second"))
    assert user_config.configured_vault({"DOXAGON_CONFIG": str(home / "config.toml")}) == home / "first"


def test_vault_use_switches_and_refuses_non_vaults(home):
    run(home, "init", str(home / "first"))
    run(home, "init", str(home / "second"))
    switched = run(home, "vault", "use", str(home / "second"))
    refused = run(home, "vault", "use", str(home))
    assert (switched.returncode, run(home, "vault").stdout.split()[0], refused.returncode) == (
        0, str(home / "second"), 1)


def test_knowledge_commands_refuse_without_a_vault_instead_of_writing_into_the_platform(home):
    result = run(home, "capture", "This must not land in the checkout")
    assert (result.returncode, "no vault selected" in result.stderr) == (1, True)


def test_vault_default_lives_beside_other_settings(home):
    config = home / "config.toml"
    config.write_text('# mine\n[image]\nprovider = "stub"\n')
    user_config.save_vault(home, {"DOXAGON_CONFIG": str(config)})
    parsed = tomllib.loads(config.read_text())
    assert ("# mine" in config.read_text(), parsed["image"], parsed["workspaces"]["default"]["vault"]) == (
        True, {"provider": "stub"}, str(home.resolve()))


def test_doctor_passes_a_fresh_vault_with_no_image_provider(home):
    run(home, "init", str(home / "vault"))
    report = json.loads(run(home, "doctor", "--json").stdout)
    assert (report["vault_binding"]["source"], report["provider"]["ok"], report["frontend"]["ok"]) == (
        "config", True, True)


def test_doctor_fails_a_selected_adapter_that_cannot_run(home):
    run(home, "init", str(home / "vault"))
    report = json.loads(run(home, "doctor", "--json", DOXAGON_IMAGE_GENERATOR="missing-adapter").stdout)
    assert report["provider"]["ok"] is False


def test_provider_install_copies_gemini_once_with_a_private_env_file(home):
    first, second = run(home, "provider", "install", "gemini"), run(home, "provider", "install", "gemini")
    adapter, env_file = home / ".doxagon/providers/gemini", home / ".doxagon/providers/gemini.env"
    assert (first.returncode, os.access(adapter, os.X_OK), oct(env_file.stat().st_mode & 0o777),
            second.returncode) == (0, True, "0o600", 1)


def adapter(home: Path, *args, **env) -> subprocess.CompletedProcess:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GEMINI_")}
    environment.update(HOME=str(home), **env)
    return subprocess.run([sys.executable, str(GEMINI), *args], env=environment, capture_output=True, text=True,
                          timeout=60)


def test_gemini_capabilities_validate_without_a_key(home):
    capabilities = json.loads(adapter(home, "--capabilities").stdout)
    assert validate_provider_capabilities(capabilities)["max_references"] == 14


def test_gemini_without_a_key_says_where_to_put_one(home):
    (home / "prompt.txt").write_text("x")
    result = adapter(home, "--prompt-file", str(home / "prompt.txt"), "--output", str(home),
                     "--image-size", "1K", "--aspect-ratio", "1:1")
    assert (result.returncode, "~/.doxagon/providers/gemini.env" in result.stderr) == (1, True)


class FakeGemini(BaseHTTPRequestHandler):
    received: dict = {}

    def do_POST(self):
        FakeGemini.received = {"path": self.path, "key": self.headers.get("x-goog-api-key"),
                               "body": json.loads(self.rfile.read(int(self.headers["Content-Length"])))}
        reply = {"candidates": [{"content": {"parts": [
            {"text": "here"}, {"inlineData": {"mimeType": "image/png", "data": base64.b64encode(PNG).decode()}}]}}]}
        payload = json.dumps(reply).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


def test_gemini_sends_the_prompt_verbatim_with_mandates_and_writes_the_image(home):
    server = HTTPServer(("127.0.0.1", 0), FakeGemini)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    prompt = " exact\nprompt bytes \n"
    (home / "prompt.txt").write_text(prompt)
    (home / "ref.png").write_bytes(PNG)
    (home / "out").mkdir()
    try:
        result = adapter(home, "--prompt-file", str(home / "prompt.txt"), "--output", str(home / "out"),
                         "--image-size", "2K", "--aspect-ratio", "16:9", "--source", str(home / "ref.png"),
                         GEMINI_API_KEY="test-key", GEMINI_API_BASE=f"http://127.0.0.1:{server.server_port}")
    finally:
        server.shutdown()
    sent = FakeGemini.received
    parts = sent["body"]["contents"][0]["parts"]
    assert (result.returncode, (home / "out/image.png").read_bytes() == PNG, sent["key"], parts[0]["text"],
            sent["body"]["generationConfig"]["imageConfig"], "test-key" in sent["path"], "test-key" in result.stderr) == (
        0, True, "test-key", prompt, {"aspectRatio": "16:9", "imageSize": "2K"}, False, False)
