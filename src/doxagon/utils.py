"""Shared utilities for Doxagon."""
import re
from pathlib import Path


def generate_slug(text: str, max_length: int = 50) -> str:
    """Generate a valid filename slug from text.

    Args:
        text: The text to slugify
        max_length: Maximum length of the slug

    Returns:
        A lowercase, hyphenated slug suitable for filenames
    """
    # Lowercase and normalize
    slug = text.lower()
    # Replace common punctuation
    slug = re.sub(r"['\"]", "", slug)
    slug = re.sub(r"[:\-–—]", " ", slug)
    # Replace non-alphanumeric with hyphens
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    # Remove leading/trailing hyphens
    slug = slug.strip("-")
    # Collapse multiple hyphens
    slug = re.sub(r"-+", "-", slug)
    # Truncate to max length at word boundary
    if len(slug) > max_length:
        slug = slug[:max_length].rsplit("-", 1)[0]
    return slug


def generate_unique_slug(base: str, directory: Path, prefix: str) -> str:
    """Generate a unique slug that doesn't exist in the directory.

    Args:
        base: The base text to slugify
        directory: Directory to check for collisions
        prefix: File prefix (e.g., 'p-', 'k-', 'd-')

    Returns:
        A unique slug (without prefix)
    """
    slug = generate_slug(base)

    # Check if base slug is available
    if not (directory / f"{prefix}{slug}.md").exists():
        return slug

    # Add counter suffix until unique
    counter = 2
    while (directory / f"{prefix}{slug}-{counter}.md").exists():
        counter += 1
    return f"{slug}-{counter}"
