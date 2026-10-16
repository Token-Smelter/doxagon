"""The per-user Doxagon config file: which vault and which image provider to use.

`~/.config/doxagon/config.toml`, or `$DOXAGON_CONFIG`. Settings are edited as
text and the result re-parsed; a write is refused unless exactly the intended
value changed, so hand-written comments and other settings survive.
"""

from __future__ import annotations

import json
import os
import re
import tomllib
from pathlib import Path
from typing import Any, Mapping

BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")


def path(environ: Mapping[str, str] | None = None) -> Path | None:
    """$DOXAGON_CONFIG, else ~/.config/doxagon/config.toml, from the given environment only."""
    environment = os.environ if environ is None else environ
    if environment.get("DOXAGON_CONFIG"):
        return Path(environment["DOXAGON_CONFIG"]).expanduser()
    home = environment.get("HOME")
    return Path(home) / ".config" / "doxagon" / "config.toml" if home else None


def read(environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    location = path(environ)
    if location is None or not location.is_file():
        return {}
    try:
        return tomllib.loads(location.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def configured_vault(environ: Mapping[str, str] | None = None) -> Path | None:
    """The active workspace's vault, resolved like `dox workspace` resolves it."""
    settings = read(environ)
    name = settings.get("active_workspace")
    workspace = (settings.get("workspaces") or {}).get(name) if isinstance(name, str) else None
    vault = workspace.get("vault") if isinstance(workspace, dict) else None
    if not isinstance(vault, str) or not vault:
        return None
    candidate = Path(vault).expanduser()
    return candidate if candidate.is_absolute() else path(environ).parent / candidate


def set_value(section: str | None, key: str, value: str, environ: Mapping[str, str] | None = None) -> Path:
    """Set `key = value` in `[section]` (or at top level), changing nothing else."""
    location = path(environ)
    if location is None:
        raise ValueError("no config location: set DOXAGON_CONFIG or HOME")
    parts = section.split(".") if section else []
    if not BARE_KEY.match(key) or not all(BARE_KEY.match(part) for part in parts):
        raise ValueError(f"unsupported config key {section}.{key}")
    text = location.read_text(encoding="utf-8") if location.is_file() else ""
    before = tomllib.loads(text)
    line = f"{key} = {json.dumps(value)}"
    assignment = re.compile(rf"(?m)^[ \t]*{re.escape(key)}[ \t]*=.*$")

    if section is None:
        first_table = re.search(r"(?m)^\[", text)
        head, tail = (text[:first_table.start()], text[first_table.start():]) if first_table else (text, "")
        head, count = assignment.subn(line, head, count=1)
        if not count:
            head = f"{line}\n" + head
        edited = head + tail
    else:
        header = re.search(rf"(?m)^\[{re.escape(section)}\][ \t]*\n((?:(?!\[)[^\n]*\n?)*)", text)
        if header is None:
            separator = "" if not text or text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
            edited = text + separator + f"[{section}]\n{line}\n"
        else:
            body, count = assignment.subn(line, header.group(1), count=1)
            if not count:
                body = f"{line}\n" + body
            edited = text[:header.start(1)] + body + text[header.end(1):]

    expected = json.loads(json.dumps(before))
    table = expected
    for part in parts:
        table = table.setdefault(part, {})
    table[key] = value
    if tomllib.loads(edited) != expected:
        raise ValueError(f"could not edit {location} safely; set {section or ''}{'.' if section else ''}{key} by hand")
    location.parent.mkdir(parents=True, exist_ok=True)
    location.write_text(edited, encoding="utf-8")
    return location


def save_vault(vault: Path, environ: Mapping[str, str] | None = None) -> Path:
    """Make `vault` the active workspace's vault, creating a `default` workspace if none is active."""
    name = read(environ).get("active_workspace")
    if not isinstance(name, str) or not BARE_KEY.match(name):
        name = "default"
        set_value(None, "active_workspace", name, environ)
    return set_value(f"workspaces.{name}", "vault", str(vault.resolve()), environ)
