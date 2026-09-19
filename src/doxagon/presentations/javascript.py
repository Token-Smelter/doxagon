"""Non-executing lexical scan of author JavaScript.

The validator must decide which modules a checkpoint pins, and which host
escapes it reaches for, without ever running author code. A raw regular
expression sweep cannot do that: it reads ``import`` inside a string literal as
a statement, and it cannot follow a ``from`` clause that sits behind a comment.

This module lexes the source the way a JavaScript tokenizer does — comments,
string and template literals, and regular expression literals are recognized,
and a template's ``${...}`` substitutions are lexed as the code they are — and
exposes two views of it:

``module_specifiers``
    every static ``import``/``export`` site in code position with the module
    specifier it pins, or ``None`` when the site pins nothing static.
``code_projection``
    the same text with every comment, string, regex span, and template literal
    chunk blanked to spaces, so a containment pattern matches executable code
    only while every byte offset, and therefore every reported line, is
    preserved. Substituted code survives the projection; only the literal text
    around it is blanked. Optional chaining is canonicalized in the same pass:
    ``a?.b`` projects as ``a .b`` and an optional call ``a?.(x)`` projects as
    ``a  (x)``, so one member or call pattern covers both the plain and the
    optional spelling of every escape and brokered host API.

Ambiguity is resolved in the refusing direction. Where a ``/`` could open a
regular expression or divide a value, it divides: blanking a span hides code
from containment, so the lexer never blanks on a guess.

Nothing here evaluates, transpiles, or subprocesses the source.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

SCAN_POLICY = "doxagon-javascript-static-module-scan/2"

_LINE_TERMINATORS = "\n\r\u2028\u2029"
_IDENTIFIER = re.compile(r"(?:[^\W\d]|\$)[\w$]*")
_NUMBER = re.compile(r"(?:\d[\w.]*|\.\d[\w.]*)")
_MODULE_KEYWORDS = frozenset({"import", "export"})
# After one of these a `/` opens a regular expression; after a value it divides.
_REGEX_AFTER_KEYWORD = frozenset(
    {"return", "typeof", "instanceof", "in", "of", "new", "delete", "void", "throw", "case", "do", "else", "yield", "await"}
)
# Punctuation after which a `/` divides rather than opening a regex. `}` is
# listed because a block close and an object-literal close are indistinguishable
# without a parser, and reading a division as a regex would blank live code.
_DIVIDES_AFTER = frozenset({")", "]", "}"})
_SKIPPED = frozenset({"comment", "string", "template", "regex"})
# `?.` is optional chaining unless a digit follows it, where the spec keeps the
# `?` a conditional operator and `.5` a number.
_OPTIONAL_CHAIN = re.compile(r"\?\.(?!\d)")


@dataclass(frozen=True)
class Token:
    """One lexical token in code position.

    ``value`` is the raw inner text of a string literal. Escape sequences are
    deliberately left undecoded: a specifier written with escapes cannot equal
    a registered key, so it is refused rather than silently resolved.
    """

    kind: str
    value: str
    start: int


def tokenize(text: str) -> tuple[Token, ...]:
    """Every code-position token, with comments and regex literals dropped."""

    return tuple(
        Token(kind, _value(text, kind, start, end), start)
        for kind, start, end in _spans(text)
        if kind not in {"comment", "regex"}
    )


def code_projection(text: str) -> str:
    """Blank every comment, string, template chunk, and regex span, preserving offsets."""

    characters = list(text)
    for kind, start, end in _spans(text):
        if kind in _SKIPPED:
            for index in range(start, end):
                if characters[index] not in "\r\n":
                    characters[index] = " "
    _blank_optional_chains(characters)
    return "".join(characters)


def _blank_optional_chains(characters: list[str]) -> None:
    """Rewrite optional chaining in place as the plain syntax it stands for.

    ``eval?.(source)`` and ``navigator?.clipboard`` are the same reach for the
    same host as ``eval(source)`` and ``navigator.clipboard``; only the
    punctuation between the parts differs. Blanking the `?` of every optional
    chain — and its `.` when the chain is a call — leaves whitespace a member or
    call pattern already tolerates, so a single pattern per escape covers both
    spellings. Blanking only ever widens what a containment pattern can see, and
    every offset is preserved because each blanked byte becomes one space.

    Literals are already spaces when this runs, so a `?.` seen here is code.
    """

    text = "".join(characters)
    for match in _OPTIONAL_CHAIN.finditer(text):
        characters[match.start()] = " "
        following = match.end()
        while following < len(text) and text[following].isspace():
            following += 1
        if following < len(text) and text[following] == "(":
            characters[match.start() + 1] = " "


def module_specifiers(text: str) -> tuple[tuple[int, str | None], ...]:
    """Locate every static import/export site and the specifier it pins, if any.

    A site whose specifier is ``None`` is an ``import`` the validator cannot pin
    to registered bytes, which is refused rather than ignored. ``export`` sites
    without a ``from`` clause export local bindings and pin nothing.
    """

    tokens = tokenize(text)
    sites: list[tuple[int, str | None]] = []
    for position, token in enumerate(tokens):
        if token.kind != "name" or token.value not in _MODULE_KEYWORDS:
            continue
        previous = tokens[position - 1] if position else None
        if previous is not None and previous.kind == "punct" and previous.value == ".":
            continue
        following = tokens[position + 1] if position + 1 < len(tokens) else None
        if token.value == "import":
            if following is not None and following.kind == "punct" and following.value in {"(", "."}:
                continue  # dynamic import() and import.meta are judged as unsafe code, not as pins
            if following is not None and following.kind == "string":
                sites.append((token.start, following.value))
                continue
        specifier = _from_clause(tokens, position + 1)
        if specifier is not None:
            sites.append((token.start, specifier))
        elif token.value == "import":
            sites.append((token.start, None))
    return tuple(sites)


def _from_clause(tokens: tuple[Token, ...], start: int) -> str | None:
    """Return the specifier of the ``from`` clause bounding this statement."""

    for position in range(start, len(tokens)):
        token = tokens[position]
        if token.kind == "punct" and token.value == ";":
            return None
        if token.kind == "name" and token.value in _MODULE_KEYWORDS:
            return None
        if token.kind == "name" and token.value == "from":
            following = tokens[position + 1] if position + 1 < len(tokens) else None
            return following.value if following is not None and following.kind == "string" else None
    return None


def _value(text: str, kind: str, start: int, end: int) -> str:
    if kind != "string":
        return text[start:end]
    closed = end - start > 1 and text[end - 1] == text[start]
    return text[start + 1 : end - 1 if closed else end]


def _spans(text: str) -> tuple[tuple[str, int, int], ...]:
    """Every lexical span of the source as ``(kind, start, end)``, in source order."""

    spans, _ = _scan(text, 0, closing=False)
    return tuple(spans)


def _scan(text: str, index: int, closing: bool) -> tuple[list[tuple[str, int, int]], int]:
    """Lex from ``index``, returning the spans and the offset the scan stopped at.

    With ``closing`` set the scan is inside a template substitution: it stops at
    the ``}`` that closes the substitution and leaves that brace to the
    enclosing literal.
    """

    spans: list[tuple[str, int, int]] = []
    previous: tuple[str, int, int] | None = None
    depth = 0
    length = len(text)
    while index < length:
        character = text[index]
        if character.isspace():
            index += 1
            continue
        if closing and character == "}" and not depth:
            return spans, index
        if character == "`":
            literal, end = _template_spans(text, index)
            spans.extend(literal)
            previous = literal[-1]
            index = max(end, index + 1)
            continue
        if text.startswith(("//", "/*"), index):
            span = ("comment", index, _end_of_comment(text, index))
        elif character in "\"'":
            span = ("string", index, _end_of_quoted(text, index, character))
        elif character == "/" and _regex_allowed(previous, text):
            span = ("regex", index, _end_of_regex(text, index))
        else:
            match = _IDENTIFIER.match(text, index) or _NUMBER.match(text, index)
            if match is not None:
                span = ("name" if match.re is _IDENTIFIER else "number", index, match.end())
            else:
                span = ("punct", index, index + 1)
                if character == "{":
                    depth += 1
                elif character == "}" and depth:
                    depth -= 1
        spans.append(span)
        if span[0] != "comment":
            previous = span
        index = max(span[2], index + 1)
    return spans, index


def _template_spans(text: str, index: int) -> tuple[list[tuple[str, int, int]], int]:
    """Lex one template literal into blanked literal chunks and live substitution code.

    A chunk span runs from the opening backtick or the ``}`` that closed the
    previous substitution up to and including the next ``${`` or the closing
    backtick, so the literal text is blanked while the substituted expressions
    stay visible to containment and capability scanning.
    """

    spans: list[tuple[str, int, int]] = []
    chunk = index
    position = index + 1
    length = len(text)
    while position < length:
        character = text[position]
        if character == "\\":
            position += 2
            continue
        if character == "`":
            spans.append(("template", chunk, position + 1))
            return spans, position + 1
        if text.startswith("${", position):
            spans.append(("template", chunk, position + 2))
            code, end = _scan(text, position + 2, closing=True)
            spans.extend(code)
            chunk = end
            position = max(end, position + 2)
            continue
        position += 1
    spans.append(("template", chunk, length))  # an unterminated literal never parses as a module
    return spans, length


def _regex_allowed(previous: tuple[str, int, int] | None, text: str) -> bool:
    """Decide whether a `/` opens a regex literal or divides the previous value.

    This is the standard preceding-token heuristic. A misjudgement can only
    mis-lex the remainder of one line, because an unterminated regex scan stops
    at the next line terminator.
    """

    if previous is None:
        return True
    kind, start, end = previous
    if kind in {"string", "template", "number", "regex"}:
        return False
    if kind == "name":
        return text[start:end] in _REGEX_AFTER_KEYWORD
    return text[start:end] not in _DIVIDES_AFTER


def _end_of_comment(text: str, index: int) -> int:
    if text.startswith("//", index):
        return _end_of_line(text, index + 2)
    end = text.find("*/", index + 2)
    return len(text) if end < 0 else end + 2


def _end_of_line(text: str, index: int) -> int:
    while index < len(text) and text[index] not in _LINE_TERMINATORS:
        index += 1
    return index


def _end_of_quoted(text: str, index: int, quote: str) -> int:
    position = index + 1
    while position < len(text):
        character = text[position]
        if character == "\\":
            position += 2
            continue
        if character == quote:
            return position + 1
        if character in "\n\r":
            return position  # an unterminated literal never parses as a module
        position += 1
    return len(text)


def _end_of_regex(text: str, index: int) -> int:
    position = index + 1
    in_class = False
    while position < len(text):
        character = text[position]
        if character == "\\":
            position += 2
            continue
        if character in _LINE_TERMINATORS:
            return position
        if character == "[":
            in_class = True
        elif character == "]":
            in_class = False
        elif character == "/" and not in_class:
            position += 1
            while position < len(text) and (text[position].isalnum() or text[position] in "_$"):
                position += 1
            return position
        position += 1
    return len(text)
