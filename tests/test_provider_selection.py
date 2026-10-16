"""The image provider is chosen once per user, in the user config, and overridable per run."""

import os
import shutil
import subprocess
import sys
import tomllib

import pytest

from doxagon.presentation_backends import provider_selection, save_provider

from .test_knowledge_intake import REPO

TEMPLATE = REPO / "src/doxagon/resources/skills/image-provider/scripts/adapter_template.py"


def test_environment_overrides_config_and_config_overrides_unset(tmp_path):
    config = tmp_path / "config.toml"
    env = {"DOXAGON_CONFIG": str(config)}
    unset = provider_selection(env)
    save_provider("chatgpt", env)
    assert (unset, provider_selection(env), provider_selection({**env, "DOXAGON_IMAGE_GENERATOR": "stub"})) == (
        ("", "unset"), ("chatgpt", "config"), ("stub", "env"))


def test_saving_changes_only_the_provider_value(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text('# mine\nactive_workspace = "home"\n\n[image]\nprovider = "old"\n\n[workspaces.home]\nmode = "local"\n')
    save_provider("new", {"DOXAGON_CONFIG": str(config)})
    text = config.read_text()
    assert ("# mine" in text, tomllib.loads(text)) == (
        True, {"active_workspace": "home", "image": {"provider": "new"}, "workspaces": {"home": {"mode": "local"}}})


@pytest.fixture
def home(tmp_path):
    providers = tmp_path / ".doxagon/providers"
    providers.mkdir(parents=True)
    shutil.copy(TEMPLATE, providers / "good")
    (providers / "good").chmod(0o755)
    (providers / "broken").write_text("#!/bin/sh\nexit 3\n")
    (providers / "broken").chmod(0o755)
    return tmp_path


def provider(home, *args):
    env = {**os.environ, "HOME": str(home), "DOXAGON_CONFIG": str(home / "config.toml"), "PYTHONPATH": str(REPO)}
    env.pop("DOXAGON_IMAGE_GENERATOR", None)
    return subprocess.run([sys.executable, "-c", "from scripts.dox import cli; cli()", "provider", *args],
                          cwd=REPO, env=env, capture_output=True, text=True, timeout=60)


def test_use_records_a_conforming_adapter_and_list_marks_it(home):
    assert provider(home, "use", "good").returncode == 0
    listing = provider(home, "list").stdout
    assert ("* good" in listing, "selected: good (config)" in listing) == (True, True)


def test_use_refuses_an_adapter_that_fails_the_free_check(home):
    result = provider(home, "use", "broken")
    assert (result.returncode, (home / "config.toml").exists()) == (1, False)
