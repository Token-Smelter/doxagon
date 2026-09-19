"""Stable, source-located diagnostics for presentation v2 validation.

A diagnostic never carries an absolute filesystem path: it locates a failure by
JSON pointer into the manifest and/or by a revision-relative source path and
line, so a receipt can be published without leaking workspace layout.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, NoReturn


@dataclass(frozen=True)
class Diagnostic:
    """One validation finding located in the manifest and/or a source file."""

    code: str
    message: str
    pointer: str = ""
    path: str | None = None
    line: int | None = None

    @property
    def sort_key(self) -> tuple[str, str, int, str, str]:
        return (self.pointer, self.path or "", self.line or 0, self.code, self.message)

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "pointer": self.pointer,
            "path": self.path,
            "line": self.line,
        }


class PresentationError(ValueError):
    """A blocking diagnostic raised while parsing or reading one record."""

    def __init__(self, diagnostic: Diagnostic) -> None:
        self.diagnostic = diagnostic
        super().__init__(diagnostic.message)


class WorkspaceError(RuntimeError):
    """A refused workspace operation, carrying the state a caller must act on.

    A conflict answer is only useful with the revision the caller lost to, and
    a rejected candidate is only actionable with the diagnostics that rejected
    it, so both travel with the error instead of being logged and dropped.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status: int = 400,
        revision: str | None = None,
        diagnostics: tuple[Diagnostic, ...] = (),
    ) -> None:
        self.code = code
        self.message = message
        self.status = status
        self.revision = revision
        self.diagnostics = tuple(diagnostics)
        super().__init__(message)

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "revision": self.revision,
            "diagnostics": [item.as_dict() for item in self.diagnostics],
        }


def fail(code: str, message: str, pointer: str = "", path: str | None = None, line: int | None = None) -> NoReturn:
    raise PresentationError(Diagnostic(code, message, pointer, path, line))


class DiagnosticLog:
    """Collects findings so one pass reports every independent failure."""

    def __init__(self) -> None:
        self._items: list[Diagnostic] = []

    def add(self, diagnostic: Diagnostic) -> None:
        self._items.append(diagnostic)

    def fail(self, code: str, message: str, pointer: str = "", path: str | None = None, line: int | None = None) -> None:
        self.add(Diagnostic(code, message, pointer, path, line))

    @contextmanager
    def capture(self) -> Iterator[None]:
        """Record a blocking record-level failure and continue the pass."""

        try:
            yield
        except PresentationError as error:
            self.add(error.diagnostic)

    def __bool__(self) -> bool:
        return bool(self._items)

    def __len__(self) -> int:
        return len(self._items)

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(item.code for item in self.sorted())

    def sorted(self) -> tuple[Diagnostic, ...]:
        """Deterministic order so two validations emit byte-identical receipts."""

        return tuple(sorted(self._items, key=lambda item: item.sort_key))
