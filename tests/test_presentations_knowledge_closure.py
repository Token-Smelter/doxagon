"""A knowledge closure is closed, self-contained, and stable under formatting."""

from copy import deepcopy
import json
from typing import Any, Callable

import pytest

from doxagon.presentations import knowledge
from doxagon.presentations.errors import PresentationError
from doxagon.presentations.knowledge import parse_closure

DIGEST = "a" * 64


def closure() -> dict[str, Any]:
    return {
        "schema": "doxagon.knowledge-closure/1",
        "captured_at": "2026-09-06T00:00:00Z",
        "source": {"vault_id": "vault-1", "generation": 12},
        "doxai": [
            {"id": "d-first", "belief": "First belief.", "status": "active", "confidence": 0.9, "sha256": DIGEST},
            {"id": "d-second", "belief": "Second belief.", "status": "draft", "confidence": None, "sha256": DIGEST},
        ],
        "evidence": [{"id": "e-source", "title": "A source", "sha256": DIGEST}],
        "diegeses": [{"id": "n-argument", "title": "The argument", "sha256": DIGEST, "walks": ["canonical"]}],
        "relations": [{"source": "d-first", "target": "d-second", "type": "grounds"}],
    }


def encode(record: dict[str, Any], **kwargs: Any) -> bytes:
    return json.dumps(record, **kwargs).encode("utf-8")


def test_the_same_closure_bytes_yield_the_same_digest() -> None:
    assert parse_closure(encode(closure())).digest == parse_closure(encode(closure())).digest


def test_key_order_and_whitespace_do_not_change_the_digest() -> None:
    reordered = {key: closure()[key] for key in reversed(list(closure()))}
    assert parse_closure(encode(closure(), indent=2)).digest == parse_closure(encode(reordered, sort_keys=True)).digest


def test_a_different_capture_time_is_a_different_closure() -> None:
    later = closure()
    later["captured_at"] = "2026-09-07T00:00:00Z"
    assert parse_closure(encode(closure())).digest != parse_closure(encode(later)).digest


def _set(path: list[Any], value: Any) -> Callable[[dict[str, Any]], None]:
    def mutate(record: dict[str, Any]) -> None:
        target: Any = record
        for token in path[:-1]:
            target = target[token]
        target[path[-1]] = value

    return mutate


def _duplicate_doxa(record: dict[str, Any]) -> None:
    record["doxai"].append(deepcopy(record["doxai"][0]))


@pytest.mark.parametrize(
    ("label", "mutate"),
    [
        ("unknown top-level field", _set(["extra"], 1)),
        ("unknown record field", _set(["doxai", 0, "note"], "private")),
        ("wrong schema", _set(["schema"], "doxagon.knowledge-closure/0")),
        ("bad timestamp", _set(["captured_at"], "yesterday")),
        ("duplicate doxa id", _duplicate_doxa),
        ("relation naming an unknown doxa", _set(["relations", 0, "target"], "d-elsewhere")),
        ("confidence above one", _set(["doxai", 0, "confidence"], 1.5)),
        ("boolean generation", _set(["source", "generation"], True)),
        ("evidence id with a doxa prefix", _set(["evidence", 0, "id"], "d-source")),
        ("diegesis id without its prefix", _set(["diegeses", 0, "id"], "argument")),
    ],
)
def test_a_closure_that_is_not_closed_and_self_contained_is_refused(label: str, mutate: Callable[[dict[str, Any]], None]) -> None:
    record = closure()
    mutate(record)
    with pytest.raises(PresentationError) as error:
        parse_closure(encode(record))
    # An unknown member is refused by the shared closed-record helper under its
    # own code; every other defect is the closure's.
    assert error.value.diagnostic.code in {"PRES_KNOWLEDGE_CLOSURE_INVALID", "PRES_UNKNOWN_FIELD"}, label


@pytest.mark.parametrize("raw", [b"\xff", b'{"schema": 1, "schema": 2}', b"[]"])
def test_undecodable_closure_bytes_are_refused(raw: bytes) -> None:
    with pytest.raises(PresentationError) as error:
        parse_closure(raw)
    assert error.value.diagnostic.code in {"PRES_KNOWLEDGE_CLOSURE_INVALID", "PRES_FIELD_INVALID"}


def test_an_oversized_closure_is_refused_before_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(knowledge, "MAX_CLOSURE_BYTES", 8)
    with pytest.raises(PresentationError) as error:
        parse_closure(encode(closure()))
    assert error.value.diagnostic.code == "PRES_KNOWLEDGE_CLOSURE_INVALID"
