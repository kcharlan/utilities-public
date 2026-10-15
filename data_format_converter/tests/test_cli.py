import json
import os
import subprocess
import sys
from datetime import date, datetime, time, timezone
from pathlib import Path

import pytest

# Match the standalone CLI's import path while loading its actual dispatch table.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
try:
    from src.data_convert import SUPPORTED_FORMATS, load_data
finally:
    sys.path.pop(0)

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


@pytest.mark.parametrize("source_format", ["toml", "yaml"])
@pytest.mark.parametrize("target_format", SUPPORTED_FORMATS)
def test_temporal_cli_matrix(tmp_path, source_format, target_format):
    sources = {
        "toml": 'when = 2030-01-02T03:04:05Z\nday = 2030-01-02\nt = 03:04:05\nname = "synthetic"\n',
        "yaml": 'when: 2030-01-02T03:04:05Z\nday: 2030-01-02\nt: "03:04:05"\nname: synthetic\n',
    }
    data = load_data(source_format, sources[source_format])
    assert data == {"when": datetime(2030, 1, 2, 3, 4, 5, tzinfo=timezone.utc), "day": date(2030, 1, 2), "t": time(3, 4, 5) if source_format == "toml" else "03:04:05", "name": "synthetic"}
    assert {key: type(value) for key, value in data.items()} == {
        "when": datetime, "day": date, "t": time if source_format == "toml" else str, "name": str,
    }
    input_file = tmp_path / f"synthetic.{source_format}"
    output_file = tmp_path / f"converted.{target_format}"
    input_file.write_text(sources[source_format], encoding="utf-8")
    result = run_cli(["--input", str(input_file), "--to", target_format, "--output", str(output_file)])
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    loaded = load_data("json" if target_format == "jsonc" else target_format, output_file.read_text(encoding="utf-8"))
    if target_format == "xml":
        assert set(loaded) == {"root"}
        loaded = loaded["root"]
    if target_format in ("json", "jsonc", "xml", "toon"):
        expected = {"when": "2030-01-02T03:04:05+00:00", "day": "2030-01-02", "t": "03:04:05", "name": "synthetic"}
    else:
        expected = dict(data)
        if target_format == "yaml":
            expected["t"] = "03:04:05"
    assert loaded == expected
    assert set(loaded) == {"when", "day", "t", "name"}
    assert {key: type(value) for key, value in loaded.items()} == {key: type(value) for key, value in expected.items()}

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

def test_yaml_binary_to_toon_is_a_structured_error(tmp_path):
    """Unsupported YAML binary values fail before creating an output file."""
    input_file = tmp_path / "synthetic.yaml"
    output_file = tmp_path / "synthetic.toon"
    input_file.write_text("value: !!binary c3ludGhldGlj\n", encoding="utf-8")

    result = run_cli(["--input", str(input_file), "--to", "toon", "--output", str(output_file)])

    assert result.returncode == 4
    assert result.stdout == ""
    assert len(result.stderr.splitlines()) == 1
    error = json.loads(result.stderr)
    assert error["code"] == "E_4"
    assert error["message"] == "Failed to convert data to toon."
    assert "bytes" in error["hint"]
    assert not output_file.exists()

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
