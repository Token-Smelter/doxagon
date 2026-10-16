"""Structured vault data for agent skills, and parsing of their answers.

The platform calls no model. A skill reads a context document from a
`dox <command> --context` call, judges it, and returns an answer that
`--response` validates before anything is written. Contexts are JSON so an
agent, or a sub-agent it delegates to, consumes them without scraping.
"""

from __future__ import annotations

import re
import textwrap
from typing import Any, Iterable

import frontmatter
import yaml

from doxagon import config


def vocabulary() -> dict[str, Any]:
    """Return the edge types (with descriptions) and registered domains."""
    schema = (yaml.safe_load(config.SCHEMA_FILE.read_text()) or {}) if config.SCHEMA_FILE.exists() else {}
    edge_types = {
        name: (spec or {}).get("description", "") if isinstance(spec, dict) else ""
        for name, spec in (schema.get("edge_types") or {}).items()
    }
    domains = ((schema.get("tag_prefixes") or {}).get("domain") or {}).get("values") or []
    return {"edge_types": edge_types, "domains": sorted(domains)}


def beliefs(slugs: Iterable[str] | None = None, *, with_body: bool = False) -> list[dict[str, Any]]:
    """Return doxai as slug, belief, status and tags, optionally with the body."""
    wanted = set(slugs) if slugs is not None else None
    entries = []
    for path in sorted(config.DOXAI_DIR.glob("d-*.md")) if config.DOXAI_DIR.exists() else []:
        if wanted is not None and path.stem not in wanted:
            continue
        post = frontmatter.load(path)
        entry = {"slug": path.stem, "belief": post.get("belief", ""), "status": post.get("status", "draft"),
                 "tags": post.get("tags") or []}
        if with_body:
            entry["body"] = post.content.strip()
        entries.append(entry)
    return entries


def read_logos() -> dict[str, Any]:
    if not config.LOGOS_FILE.exists():
        return {"edges": []}
    data = yaml.safe_load(config.LOGOS_FILE.read_text()) or {}
    data["edges"] = [normalize_edge(edge) for edge in data.get("edges") or []]
    return data


def normalize_edge(edge: Any) -> dict[str, Any]:
    if isinstance(edge, list):
        return {"source": edge[0], "target": edge[1], "type": edge[2] if len(edge) > 2 else "supports"}
    return dict(edge)


def edge_key(edge: dict[str, Any]) -> tuple[str, str, str]:
    return (edge.get("source", ""), edge.get("target", ""), edge.get("type", ""))


DOMAIN_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def register_domain(name: str, *, force: bool = False) -> list[str]:
    """Add `name` to the controlled domain list, editing only that list.

    Returns the registered domains that look like misspellings of `name`;
    when there are any and `force` is false, nothing is written. The schema is
    edited as text and re-parsed, and the write is refused unless the only
    difference is the new value, so a hand-formatted schema keeps its comments
    and layout.
    """
    from doxagon.validation import similar_domains

    if not DOMAIN_NAME.match(name):
        raise ValueError(f"{name!r} is not a domain name; use lowercase words joined by hyphens")
    path = config.SCHEMA_FILE
    text = path.read_text(encoding="utf-8")
    before = yaml.safe_load(text) or {}
    current = vocabulary()["domains"]
    if name in current:
        raise ValueError(f"domain {name!r} is already registered")
    similar = similar_domains(name, current)
    if similar and not force:
        return similar

    match = re.search(r"^([ \t]*domain:[ \t]*\n(?:[ \t]+[^\n]*\n)*?[ \t]+values:[ \t]*)\[([^\]]*)\]", text, re.M)
    if not match:
        raise ValueError(f"{path.name} has no `values: [...]` list under tag_prefixes.domain; add {name!r} by hand")
    values = [*(((before.get("tag_prefixes") or {}).get("domain") or {}).get("values") or []), name]
    listing = "[" + ", ".join(values) + "]"
    continuation = re.search(r"\n([ \t]+)", match.group(2))
    if continuation:  # keep a wrapped list wrapped, at its own indentation
        lead = len(match.group(1).rsplit("\n", 1)[-1])
        listing = textwrap.fill(listing, width=88, initial_indent=" " * lead, subsequent_indent=continuation.group(1),
                                break_long_words=False, break_on_hyphens=False)[lead:]
    edited = text[:match.start()] + match.group(1) + listing + text[match.end():]
    after = yaml.safe_load(edited) or {}
    expected = yaml.safe_load(text) or {}
    expected.setdefault("tag_prefixes", {}).setdefault("domain", {})["values"] = values
    if after != expected or (before.get("tag_prefixes") or {}).get("domain") is None:
        raise ValueError(f"could not edit {path.name} safely; add {name!r} to tag_prefixes.domain.values by hand")
    path.write_text(edited, encoding="utf-8")
    return similar


def parse_blocks(text: str, name: str) -> list[dict[str, Any]]:
    """Parse every `===NAME=== ... ===END_NAME===` block as YAML.

    A block that is not a YAML mapping is returned as `{"_invalid": text}` so
    the caller can refuse it instead of silently dropping it.
    """
    blocks = []
    for match in re.finditer(rf"==={name}===(.*?)===END_{name}===", text, re.DOTALL):
        content = match.group(1).strip()
        try:
            parsed = yaml.safe_load(content)
        except yaml.YAMLError:
            parsed = None
        blocks.append(parsed if isinstance(parsed, dict) else {"_invalid": content[:200]})
    return blocks
