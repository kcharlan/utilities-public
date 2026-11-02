"""Check shipped source files directly, including installations without Git."""
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]


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
