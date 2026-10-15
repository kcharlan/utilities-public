import pytest
import json
from datetime import date, datetime, time, timezone
from src.converters.json_conv import load_json, dump_pretty, dump_compact

@pytest.fixture
def sample_data():
    return {"z": 1, "a": "hello", "nested": {"y": True, "x": 3.14}}

@pytest.fixture
def sample_data_pretty_string():
    return '''{
  "a": "hello",
  "nested": {
    "x": 3.14,
    "y": true
  },
  "z": 1
}'''

@pytest.fixture
def sample_data_compact_string():
    return '{"a":"hello","nested":{"x":3.14,"y":true},"z":1}'

def test_load_json_valid(sample_data, sample_data_compact_string):
    """Tests that valid JSON strings are parsed correctly."""
    loaded_data = load_json(sample_data_compact_string)
    assert loaded_data["a"] == "hello"
    assert loaded_data["nested"]["y"] is True
    assert loaded_data == {"a": "hello", "z": 1, "nested": {"x": 3.14, "y": True}}


def test_load_json_invalid():
    """Tests that invalid JSON raises a json.JSONDecodeError."""
    with pytest.raises(json.JSONDecodeError):
        load_json('{"a": 1, "b":,}')

def test_dump_pretty(sample_data, sample_data_pretty_string):
    """Tests pretty-printing with sorted keys and 2-space indents."""
    assert dump_pretty(sample_data) == sample_data_pretty_string

def test_dump_compact(sample_data, sample_data_compact_string):
    """Tests compact printing with sorted keys and no extra whitespace."""
    assert dump_compact(sample_data) == sample_data_compact_string


@pytest.mark.parametrize("writer", [dump_pretty, dump_compact])
@pytest.mark.parametrize("value", [
    date(2030, 1, 2), datetime(2030, 1, 2, 3, 4, 5, 123456),
    datetime(2030, 1, 2, 3, 4, 5, tzinfo=timezone.utc), time(3, 4, 5, 123456),
])
def test_dump_temporal_as_iso(writer, value):
    data = {"value": value, "nested": {"items": [value, {"day": value}]}, "name": "synthetic"}
    expected = {"value": value.isoformat(), "nested": {"items": [value.isoformat(), {"day": value.isoformat()}]}, "name": "synthetic"}
    loaded = load_json(writer(data))
    assert loaded == expected
    assert type(loaded["value"]) is str


@pytest.mark.parametrize("writer", [dump_pretty, dump_compact])
def test_dump_unknown_type_rejected(writer):
    with pytest.raises(TypeError, match="Object of type object is not.*serializable"):
        writer({"nested": [object()]})
