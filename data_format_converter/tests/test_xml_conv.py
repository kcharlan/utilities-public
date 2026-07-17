import pytest
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

def test_round_trip(sample_data):
    """
    Tests that a round trip (dump -> load) preserves the structure.
    Note: Types are not preserved (int/float/bool become strings).
    """
    xml_string = dump_xml(sample_data)
    loaded_data = load_xml(xml_string)

    # Reconstruct expected data with stringified values
    expected_data = {
        "root": {
            "z": "1",
            "a": "hello",
            "nested": {
                "y": "true",
                "x": "3.14"
            },
            "items": ["item1", "item2"]
        }
    }
    assert loaded_data == expected_data
