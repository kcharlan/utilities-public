"""Check shipped source files directly, including installations without Git."""
import ast
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
    assert matches == {
        "taxkit/config.py",
        "tests/test_config.py",
        "docs/tax2_built_page_design_spec.md",
        "docs/tax2-built-page-migration-implementation-plan.md",
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


def test_config_conflict_raise_has_one_home():
    """One shared helper owns conflict-then-raise; the launcher never inlines it."""
    message = "Output destination would replace config.yaml"
    launcher = PROJECT / "tax2"
    sources = [launcher, *sorted((PROJECT / "taxkit").glob("*.py"))]
    counts = {path.relative_to(PROJECT).as_posix(): path.read_text().count(message)
              for path in sources}
    assert sum(counts.values()) == 1, counts
    # The launcher must not import, alias, or reference config_conflict at all;
    # a helper such as ensure_no_config_conflict is the intended single home.
    def references(source):
        found = []
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.alias) and node.name.rsplit(".", 1)[-1] == "config_conflict":
                found.append(f"import {node.name}")
            elif isinstance(node, ast.Name) and node.id == "config_conflict":
                found.append(node.id)
            elif isinstance(node, ast.Attribute) and node.attr == "config_conflict":
                found.append(f".{node.attr}")
            elif isinstance(node, ast.Constant) and node.value == "config_conflict":
                found.append(repr(node.value))
        return found
    assert [bool(references(sample)) for sample in (
        "from taxkit.config import config_conflict as cc", "config_conflict(a, b)",
        "import taxkit.config\ntaxkit.config.config_conflict(a, b)",
        "import taxkit.config\ngetattr(taxkit.config, 'config_conflict')(a, b)",
        "from taxkit.config import ensure_no_config_conflict\nensure_no_config_conflict(a, b)")] == [
        True, True, True, True, False]
    assert references(launcher.read_text()) == []
