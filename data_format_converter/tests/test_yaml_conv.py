from collections import OrderedDict
from datetime import date, datetime, time, timezone

import pytest
from yaml.representer import RepresenterError
from src.converters.yaml_conv import load_yaml, dump_yaml


@pytest.fixture
def sample_data():
    return OrderedDict([
        ("a", "hello"),
        ("nested", OrderedDict([
            ("x", 3.14),
            ("y", True),
        ])),
        ("z", 1),
    ])


@pytest.fixture
def sample_yaml_string():
    return """a: hello
nested:
  x: 3.14
  y: true
z: 1
"""


def test_load_yaml_valid(sample_data, sample_yaml_string):
    """Ensures valid YAML strings parse into Python objects."""
    loaded = load_yaml(sample_yaml_string)
    assert loaded["a"] == "hello"
    assert loaded["nested"]["x"] == 3.14
    assert loaded == {"a": "hello", "nested": {"x": 3.14, "y": True}, "z": 1}


def test_dump_yaml(sample_data, sample_yaml_string):
    """Ensures dumping YAML sorts keys and uses block style."""
    dumped = dump_yaml(sample_data)
    assert dumped == sample_yaml_string


def test_dump_preserves_order():
    data = OrderedDict([("name", "example"), ("id", 1)])
    dumped = dump_yaml(data).splitlines()
    assert dumped[0] == "name: example"
    assert dumped[1] == "id: 1"


@pytest.mark.parametrize("value", [
    date(2030, 1, 2), datetime(2030, 1, 2, 3, 4, 5, 123456),
    datetime(2030, 1, 2, 3, 4, 5, tzinfo=timezone.utc), time(3, 4, 5, 123456),
    "2030-01-02", "2030-01-02T03:04:05Z", "03:04:05", "synthetic",
])
def test_yaml_temporal_policy(value):
    expected_value = value.isoformat() if isinstance(value, time) else value
    data = OrderedDict([("value", value), ("nested", {"items": [value]}), ("name", "synthetic")])
    loaded = load_yaml(dump_yaml(data))
    assert loaded == {"value": expected_value, "nested": {"items": [expected_value]}, "name": "synthetic"}
    assert type(loaded["value"]) is type(expected_value)
    assert type(loaded["nested"]["items"][0]) is type(expected_value)


def test_dump_yaml_unknown_type_rejected():
    with pytest.raises(RepresenterError, match="cannot represent an object"):
        dump_yaml({"nested": [object()]})
