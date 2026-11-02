import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

from src.converters.toon_conv import load_toon
from src.converters.xml_conv import load_xml

# Define the path to the CLI script
CLI_PATH = Path(__file__).resolve().parents[1] / "src/data_convert.py"
TEST_DATA_DIR = Path(__file__).resolve().parent / "data"

# Data for the two test cases
DATASETS = {i: json.loads((TEST_DATA_DIR / f"cli_test_{i}.json").read_text()) for i in (1, 2)}

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
    for dataset_id, dataset in DATASETS.items()
    for from_format in FORMATS
    for to_format in FORMATS
    if from_format != to_format
    and not ('toml' in (from_format, to_format) and contains_none(dataset))
]

def run_cli(args, cwd):
    """Helper function to run the CLI."""
    command = [sys.executable, str(CLI_PATH)] + [str(arg) for arg in args]
    result = subprocess.run(command, capture_output=True, text=True, cwd=cwd)
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
def test_round_trip_conversion(tmp_path, dataset_id, from_format, to_format):
    # 1. Prepare source file
    source_filename = f"source_{dataset_id}_{from_format}_{to_format}.{from_format}"
    source_path = tmp_path / source_filename
    json_source_path = TEST_DATA_DIR / f"cli_test_{dataset_id}.json"
    run_cli(["--input", json_source_path, "--to", from_format, "--output", source_path], cwd=tmp_path)

    # 2. Convert to intermediate format
    intermediate_filename = f"intermediate_{dataset_id}_{from_format}_{to_format}.{to_format}"
    intermediate_path = tmp_path / intermediate_filename
    run_cli(["--input", source_path, "--to", to_format, "--output", intermediate_path], cwd=tmp_path)

    # 3. Convert back to source format
    final_filename = f"final_{dataset_id}_{from_format}_{to_format}.{from_format}"
    final_path = tmp_path / final_filename
    run_cli(["--input", intermediate_path, "--to", from_format, "--output", final_path], cwd=tmp_path)

    # 4. Load and compare
    loader = get_loader(from_format)
    with open(final_path, 'r') as f:
        final_data = loader(f)

    original_data = DATASETS[dataset_id]
    if 'xml' in (from_format, to_format):
        final_data = final_data.get('root', final_data)
        assert deep_compare(final_data, original_data)
    else:
        assert final_data == original_data
