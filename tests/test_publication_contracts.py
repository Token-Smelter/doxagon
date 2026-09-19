import json
from pathlib import Path


ROOT = Path(__file__).parents[1]


def _schema(name: str) -> dict[str, object]:
    return json.loads((ROOT / "publication" / name).read_text(encoding="utf-8"))


def _accepts(schema: dict[str, object], document: dict[str, object]) -> bool:
    properties = schema["properties"]
    required = schema["required"]
    if set(document) - set(properties) or any(name not in document for name in required):
        return False
    if document.get("format_version") != properties["format_version"]["const"]:
        return False
    for item in document["items"]:
        item_schema = properties["items"]["items"]
        item_properties = item_schema["properties"]
        if set(item) - set(item_properties) or any(name not in item for name in item_schema["required"]):
            return False
        if item["action"] not in item_properties["action"]["enum"]:
            return False
    return True


def test_policy_schema_rejects_unknown_major_and_executable_action_without_vault() -> None:
    schema = _schema("policy-v1.schema.json")
    valid = {"format_version": 1, "items": [{"logical_id": "public-guide", "classification": "public", "action": "include"}]}

    assert _accepts(schema, valid)
    assert not _accepts(schema, {**valid, "format_version": 2})
    assert not _accepts(schema, {"format_version": 1, "items": [{"logical_id": "public-guide", "classification": "public", "action": "shell"}]})


def test_bundle_schema_rejects_unknown_major_and_executable_action_without_vault() -> None:
    schema = _schema("bundle-v1.schema.json")
    valid = {"format_version": 1, "policy_digest": "0" * 64, "authority_generation": 0, "items": [{"logical_id": "public-guide", "sha256": "1" * 64, "action": "include"}]}

    assert _accepts(schema, valid)
    assert not _accepts(schema, {**valid, "format_version": 2})
    assert not _accepts(schema, {**valid, "items": [{"logical_id": "public-guide", "sha256": "1" * 64, "action": "publish"}]})
