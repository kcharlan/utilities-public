"""Check shipped source files directly, including installations without Git."""
import os
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]


def project_files(root):
    for directory, directories, files in os.walk(root):
        directories[:] = [name for name in directories
                          if not name.startswith(".") and name != "__pycache__"]
        for name in files:
            yield Path(directory) / name


def test_retired_config_key_source_inventory():
    key = "legacy_combined" + "_alias"
    matches = {path.relative_to(PROJECT).as_posix() for path in project_files(PROJECT)
               if key.encode() in path.read_bytes()}
    # Only the compatibility ignore path and its regression test admit this key.
    assert matches == {
        "taxkit/config.py",
        "tests/test_config.py",
    }


def test_tests_do_not_use_fixed_temporary_paths():
    fixed_prefix = "/tm" + "p/"
    fixed_root = "/tm" + "p"
    own_file = Path(__file__).resolve()
    offenders = []
    for path in (PROJECT / "tests").rglob("*.py"):
        if path.resolve() == own_file or any(part.startswith(".") for part in path.relative_to(PROJECT).parts):
            continue
        source = path.read_text()
        if fixed_prefix in source or any(f"Path({quote}{fixed_root}{quote})" in source
                                         for quote in ("'", '"')):
            offenders.append(path.relative_to(PROJECT).as_posix())
    assert offenders == []
