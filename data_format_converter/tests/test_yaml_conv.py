from collections import OrderedDict

import pytest
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


def test_round_trip_yaml(sample_data):
    """Ensures dumping and loading YAML preserves the object."""
    dumped = dump_yaml(sample_data)
    reloaded = load_yaml(dumped)
    assert reloaded == dict(sample_data)


def test_dump_preserves_order():
    data = OrderedDict([("name", "example"), ("id", 1)])
    dumped = dump_yaml(data).splitlines()
    assert dumped[0] == "name: example"
    assert dumped[1] == "id: 1"
