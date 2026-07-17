import pytest
from src.converters.toon_conv import load_toon, dump_toon, ToonUnavailable

@pytest.fixture
def sample_data():
    return {"a": 1, "b": "test", "c": [1, "two", True]}

def test_load_simple_toon():
    """Tests loading a simple key-value TOON string."""
    text = 'key1: "value1"\nkey2: 123\nkey3: true'
    expected = {"key1": "value1", "key2": 123, "key3": True}
    assert load_toon(text) == expected

def test_load_with_list():
    """Tests loading a TOON string with a list."""
    # The new library uses comma-separated values for primitive lists
    text = 'items[4]: 1, "two", false, null'
    expected = {"items": [1, "two", False, None]}
    assert load_toon(text) == expected

def test_dump_simple_dict(sample_data):
    """Tests dumping a simple dictionary to a TOON string."""
    # The new library has a specific format for lists
    expected_string = 'a: 1\nb: test\nc[3]: 1,two,true'
    assert dump_toon(sample_data) == expected_string

def test_round_trip(sample_data):
    """Tests that dumping and then loading a dictionary preserves its data."""
    dumped = dump_toon(sample_data)
    reloaded = load_toon(dumped)
    assert reloaded == sample_data

def test_dump_set_as_list():
    """Tests that dumping a set converts it to a list."""
    data = {"a": {1, 2, 3}}
    dumped = dump_toon(data)
    reloaded = load_toon(dumped)
    # The set should be converted to a list, order is not guaranteed
    assert isinstance(reloaded['a'], list)
    assert sorted(reloaded['a']) == [1, 2, 3]

def test_load_empty():
    """Tests loading an empty or whitespace string."""
    assert load_toon("") == {}
    assert load_toon(" \n ") == {}
