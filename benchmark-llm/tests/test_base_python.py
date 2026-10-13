from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

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


def test_b_production_cellar_home_with_interpreter_maps_to_opt(tmp_path):
    # The ./bench uv environment's real shape: the Cellar home still holds pythonX.Y.
    home = tmp_path / "Cellar" / "python@3.99" / "3.99.1_1" / "x" / "bin"
    _make_exe(home / EXE)
    opt = _make_exe(tmp_path / "opt" / "python@3.99" / "bin" / EXE)
    prefix = _venv_prefix(tmp_path, f"home = {home}\n")
    exe, base = _sentinels(tmp_path)
    assert _resolve(prefix, tmp_path / "base_prefix", exe, base) == (str(opt), None)


def test_cellar_executable_outside_venv_maps_to_opt(tmp_path):
    cellar = _make_exe(tmp_path / "Cellar" / "python@3.99" / "3.99.1_1" / "bin" / EXE)
    opt = _make_exe(tmp_path / "opt" / "python@3.99" / "bin" / EXE)
    prefix = tmp_path / "same_prefix"
    _, base = _sentinels(tmp_path)
    assert _resolve(prefix, prefix, str(cellar), base) == (str(opt), None)


def test_home_value_may_contain_equals(tmp_path):
    home = tmp_path / "a=b" / "bin"
    expected = _make_exe(home / EXE)
    prefix = _venv_prefix(tmp_path, f"home = {home}\n")
    exe, base = _sentinels(tmp_path)
    assert _resolve(prefix, tmp_path / "base_prefix", exe, base) == (str(expected), None)


def test_first_home_line_wins(tmp_path):
    first = _make_exe(tmp_path / "first" / "bin" / EXE)
    second = _make_exe(tmp_path / "second" / "bin" / EXE)
    prefix = _venv_prefix(tmp_path, f"home = {first.parent}\nhome = {second.parent}\n")
    exe, base = _sentinels(tmp_path)
    assert _resolve(prefix, tmp_path / "base_prefix", exe, base) == (str(first), None)


def test_crlf_pyvenv_cfg_home_is_parsed(tmp_path):
    home = tmp_path / "stable" / "bin"
    expected = _make_exe(home / EXE)
    prefix = _venv_prefix(tmp_path, None)
    (prefix / "pyvenv.cfg").write_bytes(f"home = {home}\r\nversion = 3.99.1\r\n".encode())
    exe, base = _sentinels(tmp_path)
    assert _resolve(prefix, tmp_path / "base_prefix", exe, base) == (str(expected), None)


def test_non_utf8_pyvenv_cfg_falls_back(tmp_path):
    prefix = _venv_prefix(tmp_path, None)
    (prefix / "pyvenv.cfg").write_bytes(b"home = /synthetic/\xff\xfe/bin\n")
    exe, base = _sentinels(tmp_path)
    result, warning = _resolve(prefix, tmp_path / "base_prefix", exe, base)
    assert result == base
    assert warning is not None and warning.startswith("[bench] warning:")


def test_unreadable_pyvenv_cfg_falls_back(tmp_path):
    home = tmp_path / "stable" / "bin"
    _make_exe(home / EXE)
    prefix = _venv_prefix(tmp_path, f"home = {home}\n")
    cfg = prefix / "pyvenv.cfg"
    cfg.chmod(0)
    try:
        assert not os.access(cfg, os.R_OK), "precondition: run the suite as a non-root user"
        exe, base = _sentinels(tmp_path)
        result, warning = _resolve(prefix, tmp_path / "base_prefix", exe, base)
    finally:
        cfg.chmod(0o644)
    assert result == base
    assert warning is not None and warning.startswith("[bench] warning:")


def test_home_without_interpreter_falls_back(tmp_path):
    home = tmp_path / "stable" / "bin"
    home.mkdir(parents=True)
    prefix = _venv_prefix(tmp_path, f"home = {home}\n")
    exe, base = _sentinels(tmp_path)
    result, warning = _resolve(prefix, tmp_path / "base_prefix", exe, base)
    assert result == base
    assert warning is not None and base in warning


def test_not_in_venv_without_base_executable_does_not_claim_venv(tmp_path):
    prefix = tmp_path / "same_prefix"
    exe, _ = _sentinels(tmp_path)  # does not exist, so there is no stable candidate
    result, warning = _resolve(prefix, prefix, exe, None)
    assert result == exe
    assert warning is not None and warning.startswith("[bench] warning:")
    assert "venv-from-venv" not in warning


@pytest.mark.parametrize(
    ("versioned", "component"),
    [
        ("uv/python/cpython-3.99.1-synthetic/bin", "cpython-3.99.1-synthetic"),
        ("pyenv/versions/3.99.1/bin", "3.99.1"),
    ],
    ids=["uv", "pyenv"],
)
def test_versioned_non_homebrew_home_warns(tmp_path, versioned, component):
    home = tmp_path / versioned
    expected = _make_exe(home / EXE)
    prefix = _venv_prefix(tmp_path, f"home = {home}\n")
    exe, base = _sentinels(tmp_path)
    result, warning = _resolve(prefix, tmp_path / "base_prefix", exe, base)
    assert result == str(expected)
    assert warning is not None and warning.startswith("[bench] warning:")
    assert "\n" not in warning
    assert str(expected) in warning
    assert f"is under a versioned directory ({component})" in warning


# --- 4.4 static guard on bundled example scripts ---------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SHELL_VENV_CREATION = re.compile(r"""-m\s*["']?venv\b|\bvirtualenv\b|\buv\s+venv\b|venv\.create|\bEnvBuilder\b""")
PYTHON_VENV_CREATION = re.compile(
    r"""\bimport[ \t]+[\w \t,]*\bvenv\b|\bfrom\s+venv\s+import\b|\bEnvBuilder\b|venv\.create"""
    r"""|["']-m["']\s*,\s*["']venv["']|\bvirtualenv\b|-m\s*["']?venv\b"""
    r"""|run_module\(\s*["']venv["']|["']uv["']\s*,\s*["']venv["']"""
)
SHELL_COMMAND_SPLIT = re.compile(r"\|\||&&|\|&|(?<![<>])&(?![>&])|;|\||\$\(|`|(?:^|\s)\(")
SHELL_COMMAND_PREFIX = re.compile(
    r"^(?:(?:if|then|elif|else|do|while|until|!|exec|command|time)\s+|\w+=\S*\s+)*"
)
BASE_PYTHON_HEAD = re.compile(
    r"""^"\$(?:BENCH_BASE_PYTHON|\{BENCH_BASE_PYTHON(?::\?[^}]*)?\})"(?:\s|$)"""
)
CHECK = ': "${BENCH_BASE_PYTHON:?BENCH_BASE_PYTHON is not set}"'
REMOVE = "rm -rf -- .venv"
REBUILD = '"$BENCH_BASE_PYTHON" -m venv .venv'
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


def _venv_creation_offenses(name: str, text: str) -> list[str]:
    """Return "name:line: text" for each venv creation not run by "$BENCH_BASE_PYTHON".

    Python files may not create venvs at all. Every other file is read as shell:
    continuations are joined, each logical line is split into commands, and a
    command that creates a venv must start with the BENCH_BASE_PYTHON expansion.
    Limits: it cannot follow eval, functions, aliases or variables that hold a
    command, and it cannot see venvs created at run time by a model or
    indirectly by a tool such as `uv sync`.
    """
    lines = text.splitlines()
    if name.endswith(".py"):
        offenses = []
        for match in PYTHON_VENV_CREATION.finditer(text):
            number = text.count("\n", 0, match.start()) + 1
            offenses.append(f"{name}:{number}: {lines[number - 1].strip()}")
        return offenses
    offenses = []
    index = 0
    while index < len(lines):
        start = index
        logical = lines[index]
        while logical.endswith("\\") and index + 1 < len(lines):
            index += 1
            logical = logical[:-1] + " " + lines[index]
        index += 1
        for segment in SHELL_COMMAND_SPLIT.split(logical):
            command = SHELL_COMMAND_PREFIX.sub("", segment.strip())
            if SHELL_VENV_CREATION.search(command) and not BASE_PYTHON_HEAD.match(command):
                offenses.append(f"{name}:{start + 1}: {logical.strip()}")
    return offenses


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("prepare.sh", '"${BENCH_BASE_PYTHON:?x}" -m venv .venv || python3 -m venv .venv\n'),
        ("run_checks.sh", "python3 -m \\\nvenv .venv\n"),
        ("run_checks.sh", 'python3 -m "venv" .venv\n'),
        ("run_checks.sh", "python3 -m 'venv' .venv\n"),
        ("run_checks.sh", "python3 -mvenv .venv\n"),
        ("run_checks.sh", "if [ ! -d .venv ]; then python3 -m venv .venv; fi\n"),
        ("run_checks.sh", "SYNTHETIC=1 python3 -m venv .venv\n"),
        ("run_checks.sh", "out=$(python3 -m venv .venv)\n"),
        ("run_checks.sh", "uv venv .venv\n"),
        ("bench.yaml", "    run: python3 -m venv .venv\n"),
        ("step.py", 'subprocess.run([sys.executable, "-m", "venv", ".venv"])\n'),
        ("step.py", 'subprocess.run(\n    [\n        sys.executable,\n        "-m",\n        "venv",\n    ]\n)\n'),
        ("step.py", 'import venv\nvenv.EnvBuilder(with_pip=True).create(".venv")\n'),
        ("run_checks.sh", "\"$BENCH_BASE_PYTHON\" -c x & python3 -m venv .venv\n"),
        ("run_checks.sh", "\"$BENCH_BASE_PYTHON\" -c x |& python3 -m venv .venv\n"),
        ("step.py", 'from venv import create\ncreate(".venv")\n'),
        ("run_checks.sh", "\"$BENCH_BASE_PYTHON\" - <<'EOF'\nfrom venv import EnvBuilder\nEnvBuilder().create(\".venv\")\nEOF\n"),
        ("step.py", 'import runpy\nrunpy.run_module("venv", run_name="__main__")\n'),
        ("step.py", 'subprocess.run(["uv", "venv", ".venv"])\n'),
    ],
    ids=[
        "same-line-or", "continuation", "double-quoted-module", "single-quoted-module",
        "joined-flag", "inline-if", "env-prefix", "command-substitution", "uv-venv",
        "yaml-run", "py-list", "py-multiline-list", "py-envbuilder", "background-amp", "pipe-amp", "py-from-import",
        "heredoc-envbuilder", "py-runpy", "py-uv-list",
    ],
)
def test_venv_creation_guard_flags_bypass_forms(name, text):
    assert _venv_creation_offenses(name, text)


@pytest.mark.parametrize(
    "text",
    [
        '"${BENCH_BASE_PYTHON:?BENCH_BASE_PYTHON is not set}" -m venv .venv\n',
        '"$BENCH_BASE_PYTHON" -m venv .venv\n',
        '"$BENCH_BASE_PYTHON" -m venv .venv >/dev/null 2>&1\n',
        'if [ ! -d .venv ]; then\n  "${BENCH_BASE_PYTHON:?BENCH_BASE_PYTHON is not set}" -m venv .venv\nfi\n',
        ': "${BENCH_BASE_PYTHON:?BENCH_BASE_PYTHON is not set}"\nrm -rf -- .venv\n"$BENCH_BASE_PYTHON" -m venv .venv\n',
        '"$BENCH_BASE_PYTHON" -m venv .venv &>/dev/null\n',
        '"$BENCH_BASE_PYTHON" -m venv .venv >&2\n',
        "source .venv/bin/activate\npython -m pip install pytest==9.1.1\n",
    ],
    ids=["checked-expansion", "plain-expansion", "redirect-2to1", "if-block", "rebuild-form",
         "redirect-amp-gt", "redirect-gt-amp", "no-creation"],
)
def test_venv_creation_guard_accepts_base_python_forms(text):
    assert _venv_creation_offenses("run_checks.sh", text) == []


def test_example_scripts_create_venvs_only_from_bench_base_python():
    offenders = []
    for path in _tracked_example_files():
        name = str(path.relative_to(PROJECT_ROOT))
        offenders.extend(_venv_creation_offenses(name, path.read_text(encoding="utf-8")))
    assert not offenders, "\n".join(offenders)


def test_example_scripts_use_exact_base_python_venv_lines():
    policy = (PROJECT_ROOT / "examples/policy-engine/scripts/run_checks.sh").read_text(encoding="utf-8")
    cron_run = (PROJECT_ROOT / "examples/cron-eval/scripts/run_checks.sh").read_text(encoding="utf-8")
    cron_prepare = (PROJECT_ROOT / "examples/cron-eval/scripts/prepare.sh").read_text(encoding="utf-8")
    for text in (policy, cron_run):
        lines = text.splitlines()
        assert (
            lines.index(CHECK)
            < lines.index(REMOVE)
            < lines.index(REBUILD)
            < lines.index("source .venv/bin/activate")
        )
        assert "--clear" not in text
    prepare_lines = [l for l in cron_prepare.splitlines() if CREATE in l]
    assert prepare_lines and all("--clear" not in l for l in prepare_lines)


def test_model_command_env_never_receives_bench_base_python():
    from benchmark_llm.util import build_model_command_env

    result = build_model_command_env(
        {"PATH": "/synthetic/bin", "BENCH_BASE_PYTHON": "/synthetic/bin/python3.99"},
        {"EXTRA": "1"},
    )
    assert "BENCH_BASE_PYTHON" not in result
    assert result["PATH"] == "/synthetic/bin"
    assert result["EXTRA"] == "1"
