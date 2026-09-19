"""Non-executing CSS grammar check used to positively identify `text/css` bytes.

A content-addressed storage key carries no extension, so declared `text/css`
bytes are only ever as trustworthy as the parse that admits them. Balanced
braces are not a parse: arbitrary prose has balanced braces, and so does a
JavaScript or JSON payload.

This module parses the CSS Syntax Level 3 shape — comments, strings, blocks,
at-rules, qualified rules, and declarations — and returns ``False`` at the
first parse error. A stylesheet is a non-empty sequence of rules; every
qualified rule carries a selector-shaped prelude and a block; every block entry
is a declaration (``name: value``), a nested rule, or an at-rule.
"""

from __future__ import annotations

import re

# Everything a selector may hold outside a `[]` or `()` block. Attribute
# selectors, `:not(...)` arguments, and their strings live inside those blocks.
_SELECTOR = re.compile(r"[\w\-.#*>+~,:&|\s]")
_DECLARATION_NAME = re.compile(r"--[\w-]+|-?[A-Za-z_][\w-]*")
_CLOSERS = {"{": "}", "(": ")", "[": "]"}


def is_stylesheet(text: str) -> bool:
    """Report whether the text parses as a CSS stylesheet with no parse error."""

    index: int | None = 0
    rules = 0
    while True:
        index = _skip_trivia(text, index)
        if index is None:
            return False
        if index >= len(text):
            return rules > 0
        index = _at_rule(text, index) if text[index] == "@" else _qualified_rule(text, index)
        if index is None:
            return False
        rules += 1


def _skip_trivia(text: str, index: int | None) -> int | None:
    """Skip whitespace and comments; an unterminated comment is a parse error."""

    if index is None:
        return None
    while index < len(text):
        if text[index].isspace():
            index += 1
        elif text.startswith("/*", index):
            end = text.find("*/", index + 2)
            if end < 0:
                return None
            index = end + 2
        else:
            break
    return index


def _at_rule(text: str, index: int) -> int | None:
    """Parse ``@name prelude ( block | ';' )``."""

    name = _DECLARATION_NAME.match(text, index + 1)
    if name is None:
        return None
    position = name.end()
    while position < len(text):
        character = text[position]
        if character in "\"'":
            position = _end_of_string(text, position)
        elif text.startswith("/*", position):
            position = _skip_trivia(text, position)
        elif character in "([":
            position = _end_of_block(text, position)
        elif character == ";":
            return position + 1
        elif character == "{":
            return _rule_body(text, position)
        elif character == "}":
            return None
        else:
            position += 1
        if position is None:
            return None
    return None


def _qualified_rule(text: str, index: int) -> int | None:
    """Parse ``selector-prelude { body }`` at stylesheet top level."""

    position = index
    while position < len(text):
        character = text[position]
        if text.startswith("/*", position):
            position = _skip_trivia(text, position)
        elif character == "\\":
            position += 2
        elif character in "([":
            position = _end_of_block(text, position)
        elif character == "{":
            return None if not text[index:position].strip() else _rule_body(text, position)
        elif _SELECTOR.match(character) is None:
            return None
        else:
            position += 1
        if position is None:
            return None
    return None  # a prelude that reaches end of input never closed its rule


def _rule_body(text: str, index: int) -> int | None:
    """Parse a ``{}`` body of declarations, nested rules, and at-rules."""

    position: int | None = index + 1
    while True:
        position = _skip_trivia(text, position)
        if position is None or position >= len(text):
            return None
        if text[position] == "}":
            return position + 1
        if text[position] == ";":
            position += 1  # an empty declaration is discarded, not a parse error
            continue
        position = _at_rule(text, position) if text[position] == "@" else _body_item(text, position)
        if position is None:
            return None


def _body_item(text: str, index: int) -> int | None:
    """Parse one declaration or one nested rule inside a block."""

    position = index
    while position < len(text):
        character = text[position]
        if character in "\"'":
            position = _end_of_string(text, position)
        elif text.startswith("/*", position):
            position = _skip_trivia(text, position)
        elif character in "([":
            position = _end_of_block(text, position)
        elif character == "{":
            return None if not text[index:position].strip() else _rule_body(text, position)
        elif character in ";}":
            declared = _is_declaration(text[index:position])
            return (position + 1 if character == ";" else position) if declared else None
        else:
            position += 1
        if position is None:
            return None
    return None


def _is_declaration(piece: str) -> bool:
    name, separator, value = piece.partition(":")
    return bool(separator) and _DECLARATION_NAME.fullmatch(name.strip()) is not None and bool(value.strip())


def _end_of_string(text: str, index: int) -> int | None:
    quote = text[index]
    position = index + 1
    while position < len(text):
        character = text[position]
        if character == "\\":
            position += 2
            continue
        if character == quote:
            return position + 1
        if character in "\n\r":
            return None  # CSS strings may not carry a raw newline
        position += 1
    return None


def _end_of_block(text: str, index: int) -> int | None:
    """Skip one balanced ``()``/``[]``/``{}`` block, honouring strings and comments."""

    stack = [_CLOSERS[text[index]]]
    position = index + 1
    while position < len(text) and stack:
        character = text[position]
        if character in "\"'":
            end = _end_of_string(text, position)
            if end is None:
                return None
            position = end
            continue
        if text.startswith("/*", position):
            end = _skip_trivia(text, position)
            if end is None:
                return None
            position = end
            continue
        if character == "\\":
            position += 2
            continue
        if character in _CLOSERS:
            stack.append(_CLOSERS[character])
        elif character in "}])":
            if character != stack[-1]:
                return None
            stack.pop()
        position += 1
    return None if stack else position
