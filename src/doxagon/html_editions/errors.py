"""Typed, path-safe failures for HTML Edition operations."""

from __future__ import annotations


class HtmlEditionError(ValueError):
    """A public diagnostic that intentionally contains no filesystem path."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)
