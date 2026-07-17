import json
import os
import subprocess
import sys

import pytest

try:
    import tomllib  # type: ignore[attr-defined]
except ModuleNotFoundError:  # pragma: no cover - exercised in 3.10
    import tomli as tomllib  # type: ignore

# Define the path to the CLI script
CLI_PATH = "src/data_convert.py"
TEST_DATA_DIR = "tests/data"
OUTPUT_DIR = "tests/output"

# Fixture to ensure the output directory exists and is clean
@pytest.fixture(scope="module", autouse=True)
def setup_output_dir():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    yield
    # Clean up generated files
    for f in os.listdir(OUTPUT_DIR):
        os.remove(os.path.join(OUTPUT_DIR, f))
    os.rmdir(OUTPUT_DIR)

def run_cli(args):
    """Helper function to run the CLI and capture output."""
    command = [sys.executable, CLI_PATH] + args
    return subprocess.run(command, capture_output=True, text=True)

def test_json_to_xml():
    """Tests converting JSON to XML."""
    input_file = os.path.join(TEST_DATA_DIR, "sample.json")
    output_file = os.path.join(OUTPUT_DIR, "output.xml")
    result = run_cli(["--input", input_file, "--to", "xml", "--output", output_file])
    
    assert result.returncode == 0
    assert os.path.exists(output_file)
    with open(output_file, 'r') as f:
        content = f.read()
        assert '<a>hello</a>' in content
        assert '<x>3.14</x>' in content

def test_xml_to_jsonc():
    """Tests converting XML to compact JSON."""
    input_file = os.path.join(TEST_DATA_DIR, "sample.xml")
    output_file = os.path.join(OUTPUT_DIR, "output.jsonc")
    result = run_cli(["--input", input_file, "--to", "jsonc", "--output", output_file])
    
    assert result.returncode == 0
    assert os.path.exists(output_file)
    with open(output_file, 'r') as f:
        data = json.load(f)
        assert data['root']['a'] == 'hello'
        assert data['root']['nested']['y'] == 'true'

def test_toon_to_json():
    """Tests converting TOON to pretty JSON."""
    input_file = os.path.join(TEST_DATA_DIR, "sample.toon")
    output_file = os.path.join(OUTPUT_DIR, "output.json")
    result = run_cli(["--input", input_file, "--to", "json", "--output", output_file])
    
    assert result.returncode == 0
    assert os.path.exists(output_file)
    with open(output_file, 'r') as f:
        content = f.read()
        assert '"a": "hello"' in content
        assert '"z": 1' in content
        assert '  "x": 3.14' in content # Pretty print indent

def test_json_to_yaml():
    """Tests converting JSON to YAML."""
    input_file = os.path.join(TEST_DATA_DIR, "sample.json")
    output_file = os.path.join(OUTPUT_DIR, "output.yaml")
    result = run_cli(["--input", input_file, "--to", "yaml", "--output", output_file])

    assert result.returncode == 0
    assert os.path.exists(output_file)
    with open(output_file, 'r') as f:
        content = f.read()
        assert content.startswith("a: hello")
        assert "nested:\n  x: 3.14" in content

def test_yaml_to_json():
    """Tests converting YAML to pretty JSON."""
    input_file = os.path.join(TEST_DATA_DIR, "sample.yaml")
    output_file = os.path.join(OUTPUT_DIR, "output_from_yaml.json")
    result = run_cli(["--input", input_file, "--to", "json", "--output", output_file])

    assert result.returncode == 0
    assert os.path.exists(output_file)
    with open(output_file, 'r') as f:
        data = json.load(f)
        assert data["a"] == "hello"
        assert data["nested"]["y"] is True

def test_json_to_toml():
    """Tests converting JSON to TOML."""
    input_file = os.path.join(TEST_DATA_DIR, "sample.json")
    output_file = os.path.join(OUTPUT_DIR, "output.toml")
    result = run_cli(["--input", input_file, "--to", "toml", "--output", output_file])

    assert result.returncode == 0
    assert os.path.exists(output_file)
    with open(output_file, 'rb') as f:
        data = tomllib.load(f)
        assert data["a"] == "hello"
        assert data["nested"]["x"] == 3.14

def test_toml_to_json():
    """Tests converting TOML back to JSON."""
    input_file = os.path.join(TEST_DATA_DIR, "sample.toml")
    output_file = os.path.join(OUTPUT_DIR, "output_from_toml.json")
    result = run_cli(["--input", input_file, "--to", "json", "--output", output_file])

    assert result.returncode == 0
    with open(output_file, 'r') as f:
        data = json.load(f)
        assert data["z"] == 1
        assert data["nested"]["y"] is True

def test_json_with_null_to_toml_errors():
    """Ensures TOML conversion fails gracefully when null values are present."""
    input_file = os.path.join(TEST_DATA_DIR, "cli_test_2.json")
    output_file = os.path.join(OUTPUT_DIR, "null_output.toml")
    if os.path.exists(output_file):
        os.remove(output_file)
    result = run_cli(["--input", input_file, "--to", "toml", "--output", output_file])

    assert result.returncode == 4
    assert "TOML does not support null values" in result.stderr
    assert not os.path.exists(output_file)

def test_default_output_filename():
    """Tests the default output filename generation."""
    input_file = os.path.join(TEST_DATA_DIR, "sample.json")
    # The default output should be 'sample.xml' in the current directory
    expected_output_file = "sample.xml"
    if os.path.exists(expected_output_file):
        os.remove(expected_output_file)

    result = run_cli(["--input", input_file, "--to", "xml"])
    
    assert result.returncode == 0
    assert os.path.exists(expected_output_file)
    
    # Clean up the generated file
    os.remove(expected_output_file)

def test_input_file_not_found():
    """Tests that the CLI exits with an error if the input file is not found."""
    result = run_cli(["--input", "nonexistent.json", "--to", "xml"])
    
    assert result.returncode == 3
    assert "Input file not found" in result.stderr

def test_invalid_format_conversion():
    """Tests that the CLI handles parsing errors gracefully."""
    # Try to convert an XML file as if it were JSON
    # The CLI will detect the format as json because of the extension, but fail to parse
    bad_input = os.path.join(TEST_DATA_DIR, "sample.xml")
    # Create a dummy json file with xml content
    dummy_input = os.path.join(OUTPUT_DIR, "bad.json")
    with open(bad_input, 'r') as f_in, open(dummy_input, 'w') as f_out:
        f_out.write(f_in.read())

    result = run_cli(["--input", dummy_input, "--to", "toon"])
    
    assert result.returncode == 3
    assert "Failed to parse input file" in result.stderr
