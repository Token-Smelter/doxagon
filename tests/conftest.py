import os
import tempfile
from pathlib import Path

import pytest

# doxagon.config selects a vault at import time, before any fixture runs, and
# falls back to the user's default vault. Point it at an empty config and a
# throwaway vault root first, so the suite can never resolve, read or write the
# developer's real vault. Tests that exercise selection itself run `dox` in a
# subprocess with their own environment.
_scratch = Path(tempfile.mkdtemp(prefix="doxagon-test-"))
os.environ["DOXAGON_CONFIG"] = str(_scratch / "config.toml")
os.environ["DOXAGON_ROOT"] = str(_scratch / "vault")


@pytest.fixture(autouse=True)
def isolated_user_config(tmp_path_factory, monkeypatch):
    """Give every test its own empty user config."""
    monkeypatch.setenv("DOXAGON_CONFIG", str(tmp_path_factory.mktemp("user-config") / "config.toml"))
