import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "data_format_converter/src/data_convert.py"
CONVERTERS = LAUNCHER.parent / "converters"
sys.path.insert(0, str(ROOT / "tools"))
from check_uv_headers import extract_pep723, missing_declared_imports
sys.path.pop(0)


def test_header_declares_every_converter_import():
    text = LAUNCHER.read_text(encoding="utf-8")
    deps = extract_pep723(text)["dependencies"]
    for module in [LAUNCHER, *CONVERTERS.glob("*.py")]:
        assert missing_declared_imports(module, module.read_text(encoding="utf-8"), deps) == []


def test_launcher_converts_through_uv_from_another_directory(tmp_path):
    source = tmp_path / "in.json"
    output = tmp_path / "out.toml"
    source.write_text('{"synthetic": 1}', encoding="utf-8")
    result = subprocess.run(
        ["uv", "run", "--no-python-downloads", "--script", str(LAUNCHER),
         "--input", str(source), "--to", "toml", "--output", str(output)],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert tomllib.loads(output.read_text(encoding="utf-8")) == {"synthetic": 1}
