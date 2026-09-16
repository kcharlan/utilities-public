import pytest
import json
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
