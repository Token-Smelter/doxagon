"""Admit a source into the vault as a phantasia, the first stage of the pipeline."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import frontmatter

from doxagon.config import PHANTASIAI_DIR
from doxagon.utils import generate_unique_slug

CHANNELS = ("article", "thread", "paper", "conversation", "book", "video", "notes")


def add_phantasia(
    path: Path,
    *,
    title: str | None = None,
    source: str | None = None,
    channel: str = "article",
    tags: tuple[str, ...] = (),
) -> str:
    """Copy a text source into a new phantasia and return its slug.

    The content is embedded rather than referenced so the phantasia stays
    readable after the original file moves. Binary sources are refused: a PDF
    read as text would extract garbage, so the caller converts it first.
    """
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"{path} is not UTF-8 text; convert it to Markdown or plain text first") from error
    if not content.strip():
        raise ValueError(f"{path} is empty")

    title = title or path.stem.replace("-", " ").replace("_", " ").strip() or "untitled source"
    slug = f"p-{generate_unique_slug(title, PHANTASIAI_DIR, 'p-')}"
    post = frontmatter.Post(
        f"## Source Content\n\n{content.strip()}\n",
        title=title,
        channel=channel,
        source=source or path.name,
        encountered=date.today().isoformat(),
        status="unprocessed",
        tags=list(tags),
        extracted_doxai=[],
        extracted_evidence=[],
    )
    PHANTASIAI_DIR.mkdir(parents=True, exist_ok=True)
    (PHANTASIAI_DIR / f"{slug}.md").write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")
    return slug


def list_phantasiai() -> list[dict]:
    """Return slug, title and status for each phantasia."""
    entries = []
    for item in sorted(PHANTASIAI_DIR.glob("p-*.md")) if PHANTASIAI_DIR.exists() else []:
        metadata = frontmatter.load(item).metadata
        entries.append({"slug": item.stem, "title": metadata.get("title", item.stem),
                        "status": metadata.get("status", "unknown")})
    return entries
