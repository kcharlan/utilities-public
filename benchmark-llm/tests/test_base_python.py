from __future__ import annotations

import re
import subprocess
from pathlib import Path

from benchmark_llm.util import resolve_base_python

VERSION = (3, 99)
EXE = "python3.99"


def _make_exe(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n")
    path.chmod(0o755)
    return path


def _venv_prefix(tmp_path: Path, cfg_text: str | None) -> Path:
    prefix = tmp_path / "venv"
    prefix.mkdir()
    if cfg_text is not None:
        (prefix / "pyvenv.cfg").write_text(cfg_text)
    return prefix


def _sentinels(tmp_path: Path) -> tuple[str, str]:
    return (
        str(tmp_path / "sentinel" / "exe" / EXE),
        str(tmp_path / "sentinel" / "base" / EXE),
    )


def _resolve(prefix: Path, base_prefix: Path, executable: str, base_executable: str | None):
    return resolve_base_python(
        executable=executable,
        prefix=str(prefix),
        base_prefix=str(base_prefix),
        version=VERSION,
        base_executable=base_executable,
    )


def test_a_venv_home_stable_dir(tmp_path):
    home = tmp_path / "stable" / "bin"
    expected = _make_exe(home / EXE)
    prefix = _venv_prefix(tmp_path, f"home = {home}\nversion = 3.99.1\n")
    exe, base = _sentinels(tmp_path)
    result, warning = _resolve(prefix, tmp_path / "base_prefix", exe, base)
    assert (result, warning) == (str(expected), None)


def test_b_cellar_home_maps_to_opt(tmp_path):
    home = tmp_path / "Cellar" / "python@3.99" / "3.99.1_1" / "x" / "bin"
    home.mkdir(parents=True)
    opt = _make_exe(tmp_path / "opt" / "python@3.99" / "bin" / EXE)
    prefix = _venv_prefix(tmp_path, f"home = {home}\n")
    exe, base = _sentinels(tmp_path)
    result, warning = _resolve(prefix, tmp_path / "base_prefix", exe, base)
    assert (result, warning) == (str(opt), None)


def test_c_cellar_home_without_opt_warns(tmp_path):
    home = tmp_path / "Cellar" / "python@3.99" / "3.99.1_1" / "x" / "bin"
    cellar = _make_exe(home / EXE)
    prefix = _venv_prefix(tmp_path, f"home = {home}\n")
    exe, base = _sentinels(tmp_path)
    result, warning = _resolve(prefix, tmp_path / "base_prefix", exe, base)
    assert result == str(cellar)
    assert warning is not None
    assert warning.startswith("[bench] warning:")
    assert "\n" not in warning
    assert str(cellar) in warning


def test_d1_venv_without_pyvenv_cfg_falls_back_to_base_executable(tmp_path):
    prefix = _venv_prefix(tmp_path, None)
    exe, base = _sentinels(tmp_path)
    result, warning = _resolve(prefix, tmp_path / "base_prefix", exe, base)
    assert result == base
    assert warning is not None
    assert warning.startswith("[bench] warning:")
    assert base in warning
    assert "venv-from-venv" not in warning


def test_d2_pyvenv_cfg_without_home_falls_back_to_base_executable(tmp_path):
    prefix = _venv_prefix(tmp_path, "version = 3.99.1\ninclude-system-site-packages = false\n")
    exe, base = _sentinels(tmp_path)
    result, warning = _resolve(prefix, tmp_path / "base_prefix", exe, base)
    assert result == base
    assert warning is not None
    assert warning.startswith("[bench] warning:")
    assert base in warning
    assert "venv-from-venv" not in warning


def test_d3_venv_without_base_executable_warns_venv_interpreter(tmp_path):
    prefix = _venv_prefix(tmp_path, None)
    exe, _ = _sentinels(tmp_path)
    result, warning = _resolve(prefix, tmp_path / "base_prefix", exe, None)
    assert result == exe
    assert warning is not None
    assert warning.startswith("[bench] warning:")
    assert exe in warning
    assert "venv interpreter" in warning
    assert "venv-from-venv" in warning


def test_e_not_in_venv_uses_executable_unresolved(tmp_path):
    real = _make_exe(tmp_path / "real" / EXE)
    link_dir = tmp_path / "links"
    link_dir.mkdir()
    link = link_dir / EXE
    link.symlink_to(real)
    prefix = tmp_path / "same_prefix"
    _, base = _sentinels(tmp_path)
    result, warning = _resolve(prefix, prefix, str(link), base)
    assert (result, warning) == (str(link), None)


def test_f_symlinked_home_not_resolved(tmp_path):
    real_dir = tmp_path / "real_bin"
    _make_exe(real_dir / EXE)
    link_home = tmp_path / "linked_bin"
    link_home.symlink_to(real_dir, target_is_directory=True)
    prefix = _venv_prefix(tmp_path, f"home = {link_home}\n")
    exe, base = _sentinels(tmp_path)
    result, warning = _resolve(prefix, tmp_path / "base_prefix", exe, base)
    assert (result, warning) == (str(link_home / EXE), None)


def test_home_key_is_case_insensitive_and_splits_on_first_equals(tmp_path):
    home = tmp_path / "stable" / "bin"
    expected = _make_exe(home / EXE)
    prefix = _venv_prefix(tmp_path, f"Home=  {home}  \n")
    exe, base = _sentinels(tmp_path)
    result, warning = _resolve(prefix, tmp_path / "base_prefix", exe, base)
    assert (result, warning) == (str(expected), None)


# --- 4.4 static guard on bundled example scripts ---------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]
VENV_CREATION = re.compile(r"-m\s*venv|venv\.create|virtualenv|\buv\s+venv\b")
REBUILD = '"${BENCH_BASE_PYTHON:?BENCH_BASE_PYTHON is not set}" -m venv --clear .venv'
CREATE = '"${BENCH_BASE_PYTHON:?BENCH_BASE_PYTHON is not set}" -m venv .venv'


def _tracked_example_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z", "examples"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
    ).stdout
    names = [n for n in out.decode("utf-8").split("\0") if n]
    assert names, "git ls-files examples returned nothing"
    return [PROJECT_ROOT / n for n in names]


def test_example_scripts_create_venvs_only_from_bench_base_python():
    offenders = []
    for path in _tracked_example_files():
        text = path.read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), start=1):
            if VENV_CREATION.search(line) and "BENCH_BASE_PYTHON" not in line:
                offenders.append(f"{path.relative_to(PROJECT_ROOT)}:{number}: {line}")
    assert not offenders, "\n".join(offenders)


def test_example_scripts_use_exact_base_python_venv_lines():
    policy = (PROJECT_ROOT / "examples/policy-engine/scripts/run_checks.sh").read_text(encoding="utf-8")
    cron_run = (PROJECT_ROOT / "examples/cron-eval/scripts/run_checks.sh").read_text(encoding="utf-8")
    cron_prepare = (PROJECT_ROOT / "examples/cron-eval/scripts/prepare.sh").read_text(encoding="utf-8")
    assert REBUILD in policy.splitlines()
    assert REBUILD in cron_run.splitlines()
    prepare_lines = [l for l in cron_prepare.splitlines() if CREATE in l]
    assert prepare_lines and all("--clear" not in l for l in prepare_lines)
    assert cron_run.index(REBUILD) < cron_run.index("source .venv/bin/activate")


def test_model_command_env_never_receives_bench_base_python():
    from benchmark_llm.util import build_model_command_env

    result = build_model_command_env(
        {"PATH": "/synthetic/bin", "BENCH_BASE_PYTHON": "/synthetic/bin/python3.99"},
        {"EXTRA": "1"},
    )
    assert "BENCH_BASE_PYTHON" not in result
    assert result["PATH"] == "/synthetic/bin"
    assert result["EXTRA"] == "1"


def test_policy_engine_rebuild_precedes_activate():
    policy = (PROJECT_ROOT / "examples/policy-engine/scripts/run_checks.sh").read_text(encoding="utf-8")
    assert policy.index(REBUILD) < policy.index("source .venv/bin/activate")
