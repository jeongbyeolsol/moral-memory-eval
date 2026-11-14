import json
from datetime import datetime, timezone

import pytest

from llmkit import DataError, LLMResponse
from llmkit.io import append_jsonl, load_json, load_jsonl, save_json, save_jsonl
from llmkit.schemas import SchemaModel


class Item(SchemaModel):
    name: str
    count: int


def test_json_and_jsonl_roundtrip(tmp_path):
    item = Item(name="한글", count=2)
    target = tmp_path / "nested" / "item.json"
    save_json(target, item)
    assert json.loads(target.read_text())["schema_version"] == "1.0"
    assert load_json(target, Item) == item
    target = tmp_path / "items.jsonl"
    save_jsonl(target, [item])
    append_jsonl(target, item)
    assert load_jsonl(target, Item) == [item, item]
    response = LLMResponse(provider="openai", model="test", text="hello")
    save_json(tmp_path / "response.json", response)
    assert load_json(tmp_path / "response.json", LLMResponse) == response


@pytest.mark.parametrize(
    "text",
    [
        "not JSON",
        "[]",
        '{"data":{"name":"x","count":1}}',
        '{"schema_version":1,"data":{"name":"x","count":1}}',
        '{"schema_version":"99","data":{"name":"x","count":1}}',
        '{"schema_version":"1.0","data":{"name":"x"}}',
        '{"schema_version":"1.0","data":{"name":"x","count":"1"}}',
        '{"schema_version":"1.0","data":{"name":"x","count":true}}',
        '{"schema_version":"1.0","data":{"name":"x","count":1,"extra":1}}',
        '{"schema_version":"1.0","extra":1,"data":{"name":"x","count":1}}',
        '{"schema_version":"1.0","data":{"name":"x","count":NaN}}',
        '{"schema_version":"1.0","data":{"name":"x","count":1,"count":2}}',
    ],
)
def test_invalid_json_has_path_context(tmp_path, text):
    target = tmp_path / "bad.json"
    target.write_text(text)
    with pytest.raises(DataError, match="bad.json"):
        load_json(target, Item)


def test_jsonl_error_has_line_number_and_rejects_blank_lines(tmp_path):
    path = tmp_path / "bad.jsonl"
    save_jsonl(path, [Item(name="x", count=1)])
    with path.open("a") as stream:
        stream.write("\n")
    with pytest.raises(DataError, match="bad.jsonl:2"):
        load_jsonl(path, Item)


def test_explicit_migration_matches_new_format(tmp_path):
    old = tmp_path / "old.json"
    old.write_text('{"schema_version":"0.1","data":{"label":"x","count":1}}')

    def migrate(record):
        data = record["data"]
        return {"schema_version": "1.0", "data": {"name": data["label"], "count": data["count"]}}

    expected = Item(name="x", count=1)
    save_json(tmp_path / "new.json", expected)
    assert load_json(old, Item, migrations={"0.1": migrate}) == load_json(
        tmp_path / "new.json", Item
    )
    old.rename(tmp_path / "old.jsonl")
    assert load_jsonl(tmp_path / "old.jsonl", Item, migrations={"0.1": migrate}) == [expected]
    with pytest.raises(DataError, match="Unsupported schema_version"):
        load_json(tmp_path / "old.jsonl", Item)


def test_migration_result_is_validated(tmp_path):
    path = tmp_path / "old.json"
    path.write_text('{"schema_version":"0.1","data":{}}')
    with pytest.raises(DataError):
        load_json(path, Item, migrations={"0.1": lambda record: record})
    with pytest.raises(DataError):
        load_json(
            path, Item, migrations={"0.1": lambda record: {"schema_version": "1.0", "data": {}}}
        )


def test_invalid_save_preserves_existing_file(tmp_path):
    path = tmp_path / "items.jsonl"
    save_jsonl(path, [Item(name="x", count=1)])
    original = path.read_bytes()
    invalid = Item.model_construct(name="x", count="wrong")
    with pytest.raises(DataError):
        save_jsonl(path, [Item(name="y", count=2), invalid])
    assert path.read_bytes() == original


def test_datetime_roundtrip(tmp_path):
    class Event(SchemaModel):
        occurred_at: datetime

    event = Event(occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    save_json(tmp_path / "event.json", event)
    assert load_json(tmp_path / "event.json", Event) == event


def test_missing_and_invalid_utf8(tmp_path):
    with pytest.raises(DataError):
        load_json(tmp_path / "absent.json", Item)
    path = tmp_path / "invalid.jsonl"
    path.write_bytes(b"\xff")
    with pytest.raises(DataError):
        load_jsonl(path, Item)
