import pytest


@pytest.fixture(autouse=True)
def isolated_user_config(tmp_path_factory, monkeypatch):
    """Keep the developer's ~/.config/doxagon/config.toml out of every test."""
    monkeypatch.setenv("DOXAGON_CONFIG", str(tmp_path_factory.mktemp("user-config") / "config.toml"))
