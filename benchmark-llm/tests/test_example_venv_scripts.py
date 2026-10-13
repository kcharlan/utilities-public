from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
POLICY_RUN_CHECKS = PROJECT_ROOT / "examples/policy-engine/scripts/run_checks.sh"
CRON_RUN_CHECKS = PROJECT_ROOT / "examples/cron-eval/scripts/run_checks.sh"
CRON_PREPARE = PROJECT_ROOT / "examples/cron-eval/scripts/prepare.sh"
VALIDATE_SCRIPTS = pytest.mark.parametrize(
    "script", [POLICY_RUN_CHECKS, CRON_RUN_CHECKS], ids=["policy", "cron"]
)

# Stand-in for BENCH_BASE_PYTHON. It never runs a real interpreter or creates a
# real venv: it logs each call and whether the venv path was a symlink, refuses
# --clear and symlinked targets, and builds a fake venv whose python only logs.
FAKE_BASE_PYTHON = r"""#!/bin/sh
dir=""
for arg in "$@"; do dir="$arg"; done
if [ -L "$dir" ]; then link=1; else link=0; fi
printf '%s link=%s\n' "$*" "$link" >> "$FAKE_BASE_LOG"
if [ "$1" != "-m" ] || [ "$2" != "venv" ]; then exit 0; fi
case " $* " in *" --clear "*) exit 64 ;; esac
if [ "$link" = 1 ]; then exit 70; fi
mkdir -p "$dir/bin"
printf 'export PATH="%s/bin:$PATH"\n' "$PWD/$dir" > "$dir/bin/activate"
cp "$FAKE_VENV_PYTHON" "$dir/bin/python"
chmod +x "$dir/bin/python"
"""
FAKE_VENV_PYTHON = r"""#!/bin/sh
printf '[%s]' "$@" >> "$FAKE_VENV_PYTHON_LOG"
printf '\n' >> "$FAKE_VENV_PYTHON_LOG"
"""
TRAP_PYTHON = r"""#!/bin/sh
printf 'bare %s %s\n' "$0" "$*" >> "$TRAP_LOG"
exit 99
"""
SHAPES = ["dir-symlink", "dangling-symlink", "regular-file", "dir-with-nested-symlink"]


def _write_exe(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)
    return path


def _bracketed(*args: str) -> str:
    return "".join(f"[{a}]" for a in args)


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


@pytest.fixture
def harness(tmp_path: Path) -> SimpleNamespace:
    trap_bin = tmp_path / "trap-bin"
    for name in ("python", "python3"):
        _write_exe(trap_bin / name, TRAP_PYTHON)
    base = _write_exe(tmp_path / "tools" / "fake-base-python3.99", FAKE_BASE_PYTHON)
    venv_python = _write_exe(tmp_path / "tools" / "fake-venv-python", FAKE_VENV_PYTHON)
    workspace = tmp_path / "work space"
    workspace.mkdir()
    logs = tmp_path / "logs"
    logs.mkdir()
    git_dir = Path(shutil.which("git")).parent
    env = {
        "HOME": str(tmp_path),
        "PATH": f"{trap_bin}:{git_dir}:/usr/bin:/bin",
        "BENCH_WORKSPACE": str(workspace),
        "BENCH_BENCHMARK_DIR": str(tmp_path / "benchmark"),
        "BENCH_RUN_DIR": str(tmp_path / "run"),
        "BENCH_HIDDEN_DIR": str(tmp_path / "hidden"),
        "BENCH_BASE_PYTHON": str(base),
        "FAKE_BASE_LOG": str(logs / "base.log"),
        "FAKE_VENV_PYTHON": str(venv_python),
        "FAKE_VENV_PYTHON_LOG": str(logs / "venv-python.log"),
        "TRAP_LOG": str(logs / "trap.log"),
    }
    return SimpleNamespace(tmp=tmp_path, workspace=workspace, logs=logs, env=env)


def _run(script: Path, harness: SimpleNamespace, **overrides: str | None):
    env = {**harness.env, **overrides}
    env = {key: value for key, value in env.items() if value is not None}
    return subprocess.run(
        ["/bin/bash", str(script)], env=env, capture_output=True, text=True, timeout=60
    )


def _plant_model_venv(workspace: Path, outside: Path, shape: str) -> None:
    outside.mkdir()
    (outside / "precious.txt").write_text("keep\n", encoding="utf-8")
    (outside / "sub").mkdir()
    (outside / "sub" / "x.txt").write_text("keep\n", encoding="utf-8")
    venv = workspace / ".venv"
    if shape == "dir-symlink":
        venv.symlink_to(outside, target_is_directory=True)
    elif shape == "dangling-symlink":
        venv.symlink_to(workspace / "missing-target")
    elif shape == "regular-file":
        venv.write_text("not a venv\n", encoding="utf-8")
    else:
        venv.mkdir()
        (venv / "lib").symlink_to(outside, target_is_directory=True)


@VALIDATE_SCRIPTS
@pytest.mark.parametrize("shape", SHAPES)
def test_validate_rebuild_never_touches_what_model_venv_points_to(harness, script, shape):
    outside = harness.tmp / "outside"
    _plant_model_venv(harness.workspace, outside, shape)

    result = _run(script, harness)

    assert result.returncode == 0, result.stderr
    assert sorted(p.relative_to(outside).as_posix() for p in outside.rglob("*")) == [
        "precious.txt",
        "sub",
        "sub/x.txt",
    ]
    venv = harness.workspace / ".venv"
    assert venv.is_dir() and not venv.is_symlink()
    assert _lines(harness.logs / "base.log") == ["-m venv .venv link=0"]
    assert _lines(harness.logs / "trap.log") == []


@VALIDATE_SCRIPTS
def test_validate_rebuild_replaces_model_created_venv(harness, script):
    stale = harness.workspace / ".venv" / "lib" / "model-installed.txt"
    stale.parent.mkdir(parents=True)
    stale.write_text("from the model\n", encoding="utf-8")

    result = _run(script, harness)

    assert result.returncode == 0, result.stderr
    assert not stale.exists()
    assert (harness.workspace / ".venv" / "bin" / "activate").is_file()


@VALIDATE_SCRIPTS
def test_validate_without_base_python_keeps_workspace_venv(harness, script):
    marker = harness.workspace / ".venv" / "marker.txt"
    marker.parent.mkdir()
    marker.write_text("keep\n", encoding="utf-8")

    result = _run(script, harness, BENCH_BASE_PYTHON=None)

    assert result.returncode != 0
    assert "BENCH_BASE_PYTHON is not set" in result.stderr
    assert marker.exists()
    assert _lines(harness.logs / "base.log") == []
    assert _lines(harness.logs / "trap.log") == []


@pytest.mark.parametrize("with_requirements", [False, True], ids=["no-reqs", "reqs"])
def test_policy_validate_installs_tools_then_requirements_then_validates(harness, with_requirements):
    if with_requirements:
        (harness.workspace / "requirements.txt").write_text("synthetic-package\n", encoding="utf-8")

    result = _run(POLICY_RUN_CHECKS, harness)

    assert result.returncode == 0, result.stderr
    env = harness.env
    expected = ["[-m][pip][install][pytest==9.1.1][PyYAML==6.0.3]"]
    if with_requirements:
        expected.append("[-m][pip][install][-r][requirements.txt]")
    expected.append(
        _bracketed(
            f"{env['BENCH_BENCHMARK_DIR']}/scripts/run_validation.py",
            env["BENCH_RUN_DIR"],
            env["BENCH_WORKSPACE"],
            env["BENCH_HIDDEN_DIR"],
        )
    )
    assert _lines(harness.logs / "venv-python.log") == expected


def _prepare_cron_inputs(harness: SimpleNamespace) -> None:
    prompt = Path(harness.env["BENCH_BENCHMARK_DIR"]) / "prompt.txt"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("synthetic prompt\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(harness.workspace)], check=True, capture_output=True)


def test_cron_prepare_creates_missing_venv_from_base_python(harness):
    _prepare_cron_inputs(harness)

    result = _run(CRON_PREPARE, harness)

    assert result.returncode == 0, result.stderr
    assert _lines(harness.logs / "base.log") == ["-m venv .venv link=0"]
    assert (harness.workspace / ".venv" / "bin" / "activate").is_file()


def test_cron_prepare_keeps_existing_venv(harness):
    _prepare_cron_inputs(harness)
    marker = harness.workspace / ".venv" / "marker.txt"
    marker.parent.mkdir()
    marker.write_text("keep\n", encoding="utf-8")

    result = _run(CRON_PREPARE, harness)

    assert result.returncode == 0, result.stderr
    assert marker.exists()
    assert _lines(harness.logs / "base.log") == []


def test_cron_validate_runs_checks_with_each_path_as_one_argument(harness):
    result = _run(CRON_RUN_CHECKS, harness)

    assert result.returncode == 0, result.stderr
    env = harness.env
    assert _lines(harness.logs / "venv-python.log") == [
        _bracketed(
            f"{env['BENCH_BENCHMARK_DIR']}/scripts/run_checks.py",
            env["BENCH_RUN_DIR"],
            env["BENCH_WORKSPACE"],
            env["BENCH_HIDDEN_DIR"],
        )
    ]
