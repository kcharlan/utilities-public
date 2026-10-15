import pytest
from datetime import date, datetime, time, timezone
from xml.parsers.expat import ExpatError
from src.converters.xml_conv import load_xml, dump_xml

@pytest.fixture
def sample_data():
    return {
        "root": {
            "z": 1,
            "a": "hello",
            "nested": {
                "y": True,
                "x": 3.14
            },
            "items": ["item1", "item2"]
        }
    }

@pytest.fixture
def sample_xml_string():
    # Note the sorted key order: a, items, nested, z
    return '<root><a>hello</a><items>item1</items><items>item2</items><nested><x>3.14</x><y>true</y></nested><z>1</z></root>'

def test_load_xml_valid(sample_xml_string):
    """Tests that a valid XML string is parsed correctly."""
    expected_data = {
        "root": {
            "a": "hello",
            "items": ["item1", "item2"],
            "nested": {
                "x": "3.14", # xmltodict parses numbers as strings
                "y": "true"  # and booleans as strings
            },
            "z": "1"
        }
    }
    assert load_xml(sample_xml_string) == expected_data

def test_load_xml_invalid():
    """Tests that malformed XML raises an ExpatError."""
    with pytest.raises(ExpatError):
        load_xml("<root><<a></root>")

def test_dump_xml(sample_data, sample_xml_string):
    """Tests that dumping an object to XML produces a deterministic string."""
    assert dump_xml(sample_data) == sample_xml_string

def test_dump_xml_no_root():
    """Tests that dumping an object without a single root key raises an error."""
    with pytest.raises(ValueError):
        dump_xml({"a": 1, "b": 2})


@pytest.mark.parametrize("value", [
    date(2030, 1, 2), datetime(2030, 1, 2, 3, 4, 5, 123456),
    datetime(2030, 1, 2, 3, 4, 5, tzinfo=timezone.utc), time(3, 4, 5, 123456),
])
def test_dump_xml_temporal_as_iso(value):
    data = {"root": {"value": value, "nested": {"items": [value, value]}, "name": "synthetic"}}
    expected = {"root": {"value": value.isoformat(), "nested": {"items": [value.isoformat(), value.isoformat()]}, "name": "synthetic"}}
    loaded = load_xml(dump_xml(data))
    assert loaded == expected
    assert type(loaded["root"]["value"]) is str


def test_dump_xml_unknown_type_rejected():
    with pytest.raises(TypeError, match="Unsupported type for XML conversion: <class 'object'>"):
        dump_xml({"root": {"nested": [object()]}})
