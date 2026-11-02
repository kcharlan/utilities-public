import json
import shutil
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

# Define the path to the CLI script
PROJECT_DIR = Path(__file__).resolve().parents[1]
CLI_PATH = PROJECT_DIR / "src/data_convert.py"
TEST_DATA_DIR = PROJECT_DIR / "tests/data"

def run_cli(args, cwd):
    """Helper function to run the CLI and capture output."""
    command = [sys.executable, str(CLI_PATH)] + [str(arg) for arg in args]
    return subprocess.run(command, capture_output=True, text=True, cwd=cwd)


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
    result = run_cli(["--input", str(input_file), "--to", target_format, "--output", str(output_file)], cwd=tmp_path)
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

@pytest.mark.parametrize("source_format,target_format", [
    ("json", "xml"), ("xml", "jsonc"), ("toon", "json"),
    ("json", "yaml"), ("yaml", "json"), ("json", "toml"), ("toml", "json"),
])
def test_sample_fixture_converts(tmp_path, source_format, target_format):
    output_file = tmp_path / f"output.{target_format}"
    result = run_cli(["--input", TEST_DATA_DIR / f"sample.{source_format}",
                      "--to", target_format, "--output", output_file], cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    output = output_file.read_text(encoding="utf-8")
    loaded = load_data("json" if target_format == "jsonc" else target_format, output)
    if target_format == "xml" or source_format == "xml":
        assert loaded == {"root": {"a": "hello", "nested": {"x": "3.14", "y": "true"}, "z": "1"}}
    else:
        assert loaded == {"a": "hello", "nested": {"x": 3.14, "y": True}, "z": 1}


def test_json_empty_list_to_xml_is_a_structured_error(tmp_path):
    input_file = tmp_path / "input.json"
    output_file = tmp_path / "output.xml"
    input_file.write_text('{"root":{"keep":1,"empty":[]}}', encoding="utf-8")
    result = run_cli(["--input", str(input_file), "--to", "xml", "--output", str(output_file)], cwd=tmp_path)

    assert result.returncode == 4
    error = json.loads(result.stderr)
    assert error["code"] == "E_4"
    assert "empty" in error["hint"]
    assert not output_file.exists()

def test_json_with_null_to_toml_errors(tmp_path):
    """Ensures TOML conversion fails gracefully when null values are present."""
    input_file = TEST_DATA_DIR / "cli_test_2.json"
    output_file = tmp_path / "null_output.toml"
    result = run_cli(["--input", input_file, "--to", "toml", "--output", output_file], cwd=tmp_path)

    assert result.returncode == 4
    assert "TOML does not support null values" in result.stderr
    assert not output_file.exists()

def test_yaml_binary_to_toon_is_a_structured_error(tmp_path):
    """Unsupported YAML binary values fail before creating an output file."""
    input_file = tmp_path / "synthetic.yaml"
    output_file = tmp_path / "synthetic.toon"
    input_file.write_text("value: !!binary c3ludGhldGlj\n", encoding="utf-8")

    result = run_cli(["--input", str(input_file), "--to", "toon", "--output", str(output_file)], cwd=tmp_path)

    assert result.returncode == 4
    assert result.stdout == ""
    assert len(result.stderr.splitlines()) == 1
    error = json.loads(result.stderr)
    assert error["code"] == "E_4"
    assert error["message"] == "Failed to convert data to toon."
    assert "bytes" in error["hint"]
    assert not output_file.exists()

def test_default_output_filename(tmp_path):
    """Tests the default output filename generation."""
    input_file = tmp_path / "sample.json"
    shutil.copyfile(TEST_DATA_DIR / "sample.json", input_file)
    project_output = PROJECT_DIR / "sample.xml"
    assert not project_output.exists()
    result = run_cli(["--input", input_file, "--to", "xml"], cwd=tmp_path)
    
    assert result.returncode == 0
    assert (tmp_path / "sample.xml").exists()
    assert not project_output.exists()

def test_input_file_not_found(tmp_path):
    """Tests that the CLI exits with an error if the input file is not found."""
    result = run_cli(["--input", "nonexistent.json", "--to", "xml"], cwd=tmp_path)
    
    assert result.returncode == 3
    assert "Input file not found" in result.stderr

def test_non_utf8_input_is_a_structured_error(tmp_path):
    input_file = tmp_path / "in.json"
    output_file = tmp_path / "out.yaml"
    input_file.write_bytes(b'{"a": "\xff"}')

    result = run_cli(["--input", str(input_file), "--to", "yaml", "--output", str(output_file)], cwd=tmp_path)

    assert result.returncode == 3
    assert result.stdout == ""
    assert len(result.stderr.splitlines()) == 1
    assert json.loads(result.stderr)["code"] == "E_3"
    assert not output_file.exists()

def test_invalid_format_conversion(tmp_path):
    """Tests that the CLI handles parsing errors gracefully."""
    # Try to convert an XML file as if it were JSON
    # The CLI will detect the format as json because of the extension, but fail to parse
    bad_input = TEST_DATA_DIR / "sample.xml"
    # Create a dummy json file with xml content
    dummy_input = tmp_path / "bad.json"
    shutil.copyfile(bad_input, dummy_input)

    result = run_cli(["--input", dummy_input, "--to", "toon"], cwd=tmp_path)
    
    assert result.returncode == 3
    assert "Failed to parse input file" in result.stderr
