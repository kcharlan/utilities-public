import json
import os
import subprocess
import sys

import pytest
import yaml

try:
    import tomllib  # type: ignore[attr-defined]
except ModuleNotFoundError:  # pragma: no cover - exercised in 3.10
    import tomli as tomllib  # type: ignore

from src.converters.toon_conv import load_toon
from src.converters.xml_conv import load_xml

# Define the path to the CLI script
CLI_PATH = "src/data_convert.py"
TEST_DATA_DIR = "tests/data"
OUTPUT_DIR = "tests/output"

# Data for the two test cases
DATASET_1 = {
  "name": "First Dataset",
  "type": "test",
  "data": {
    "items": [
      { "id": 101, "value": "A" },
      { "id": 102, "value": "B" }
    ],
    "metadata": {
      "timestamp": "2025-11-11T10:00:00Z",
      "source": "test-generator"
    }
  }
}

DATASET_2 = {
    "user": "test_user_2",
    "permissions": ["read", "write"],
    "config": {
        "theme": "dark",
        "notifications": {
            "email": True,
            "sms": False
        }
    },
    "status": None
}

FORMATS = ['json', 'xml', 'toon', 'yaml', 'toml']


def contains_none(value):
    if value is None:
        return True
    if isinstance(value, dict):
        return any(contains_none(v) for v in value.values())
    if isinstance(value, list):
        return any(contains_none(v) for v in value)
    return False


ROUND_TRIP_CASES = [
    (dataset_id, from_format, to_format)
    for dataset_id, dataset in ((1, DATASET_1), (2, DATASET_2))
    for from_format in FORMATS
    for to_format in FORMATS
    if from_format != to_format
    and not ('toml' in (from_format, to_format) and contains_none(dataset))
]

# Fixture to ensure the output directory exists and is clean
@pytest.fixture(scope="module", autouse=True)
def setup_output_dir():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    yield
    # Clean up generated files
    for f in os.listdir(OUTPUT_DIR):
        try:
            os.remove(os.path.join(OUTPUT_DIR, f))
        except OSError:
            pass # Ignore if file is already gone
    os.rmdir(OUTPUT_DIR)

def run_cli(args):
    """Helper function to run the CLI."""
    command = [sys.executable, CLI_PATH] + args
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, f"""CLI command failed: {' '.join(command)}
{result.stderr}"""
    return result

def get_loader(format_ext):
    """Returns the appropriate loader function for a given format."""
    if format_ext == 'json':
        return json.load
    if format_ext == 'yaml':
        return yaml.safe_load
    if format_ext == 'xml':
        return lambda f: load_xml(f.read())
    if format_ext == 'toon':
        return lambda f: load_toon(f.read())
    if format_ext == 'toml':
        return lambda f: tomllib.loads(f.read())
    raise ValueError(f"No loader for format: {format_ext}")


def deep_compare(d1, d2):
    """
    Recursively compares two dictionaries, coercing types for comparison.
    """
    if isinstance(d1, dict) and isinstance(d2, dict):
        if sorted(d1.keys()) != sorted(d2.keys()):
            return False
        return all(deep_compare(d1[k], d2[k]) for k in d1)
    if isinstance(d1, list) and isinstance(d2, list):
        if len(d1) != len(d2):
            return False
        return all(deep_compare(i1, i2) for i1, i2 in zip(d1, d2))
    
    s1 = str(d1).lower() if isinstance(d1, bool) else str(d1)
    s2 = str(d2).lower() if isinstance(d2, bool) else str(d2)
    
    if s1 == 'none' and s2 == 'none':
        return True

    try:
        return float(s1) == float(s2)
    except (ValueError, TypeError):
        return s1 == s2

@pytest.mark.parametrize("dataset_id,from_format,to_format", ROUND_TRIP_CASES)
def test_round_trip_conversion(dataset_id, from_format, to_format):
    # 1. Prepare source file
    source_filename = f"source_{dataset_id}_{from_format}_{to_format}.{from_format}"
    source_path = os.path.join(OUTPUT_DIR, source_filename)
    json_source_path = os.path.join(TEST_DATA_DIR, f"cli_test_{dataset_id}.json")
    run_cli(["--input", json_source_path, "--to", from_format, "--output", source_path])

    # 2. Convert to intermediate format
    intermediate_filename = f"intermediate_{dataset_id}_{from_format}_{to_format}.{to_format}"
    intermediate_path = os.path.join(OUTPUT_DIR, intermediate_filename)
    run_cli(["--input", source_path, "--to", to_format, "--output", intermediate_path])

    # 3. Convert back to source format
    final_filename = f"final_{dataset_id}_{from_format}_{to_format}.{from_format}"
    final_path = os.path.join(OUTPUT_DIR, final_filename)
    run_cli(["--input", intermediate_path, "--to", from_format, "--output", final_path])

    # 4. Load and compare
    loader = get_loader(from_format)
    with open(final_path, 'r') as f:
        final_data = loader(f)

    with open(source_path, 'r') as f:
        original_data = get_loader(from_format)(f)

    if from_format != 'xml' and to_format == 'xml':
        final_data = final_data.get('root', final_data)
    
    assert deep_compare(final_data, original_data)
