from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


def _write_executable(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def _dependency_fingerprint(root: Path) -> str:
    files = [
        "requirements.txt",
        "requirements-dev.txt",
        "pyproject.toml",
        "poetry.lock",
        "uv.lock",
        "setup.py",
        "setup.cfg",
        "tox.ini",
        "pytest.ini",
    ]
    digest = hashlib.sha256()
    for rel in files:
        path = root / rel
        if not path.is_file():
            continue
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


@pytest.mark.parametrize("pack_name", ["claude-code", "codex", "codex-hybrid"])
def test_builtin_verify_uses_source_repo_venv_for_worktree_sessions_and_runs_from_repo_root(
    tmp_path: Path,
    repo_root: Path,
    pack_name: str,
) -> None:
    pack_root = repo_root / "cognitive_switchyard" / "builtin_packs" / pack_name
    worktree_root = tmp_path / "worktree-repo"
    source_root = tmp_path / "source-repo"
    worktree_root.mkdir()
    source_root.mkdir()
    (worktree_root / "tests").mkdir()
    (worktree_root / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    (source_root / "requirements.txt").write_text("pytest\n", encoding="utf-8")

    trace_path = tmp_path / f"{pack_name}-source-trace.txt"
    _write_executable(
        source_root / ".venv" / "bin" / "python",
        """#!/bin/sh
set -eu
if [ "$*" = "-m pytest --version" ]; then
  exit 0
fi
{
  pwd
  printf '%s\\n' "$*"
} > "$TRACE_PATH"
exit 0
""",
    )

    result = subprocess.run(
        [str(pack_root / "scripts" / "verify"), str(tmp_path / "session-root")],
        capture_output=True,
        text=True,
        env={
            "PATH": os.environ["PATH"],
            "TRACE_PATH": str(trace_path),
            "COGNITIVE_SWITCHYARD_PACK_ROOT": str(pack_root),
            "COGNITIVE_SWITCHYARD_REPO_ROOT": str(worktree_root),
            "COGNITIVE_SWITCHYARD_SOURCE_REPO": str(source_root),
        },
    )

    assert result.returncode == 0, result.stderr or result.stdout
    trace_lines = trace_path.read_text(encoding="utf-8").splitlines()
    assert trace_lines == [
        str(worktree_root),
        "-m pytest tests --tb=short -q",
    ]


@pytest.mark.parametrize("pack_name", ["claude-code", "codex", "codex-hybrid"])
def test_builtin_verify_uses_existing_session_env_when_source_repo_env_is_stale(
    tmp_path: Path,
    repo_root: Path,
    pack_name: str,
) -> None:
    pack_root = repo_root / "cognitive_switchyard" / "builtin_packs" / pack_name
    target_root = tmp_path / "repo-root"
    source_root = tmp_path / "source-repo"
    session_root = tmp_path / "session-root"
    target_root.mkdir()
    source_root.mkdir()
    session_root.mkdir()
    (target_root / "tests").mkdir()
    (target_root / "requirements.txt").write_text("pytest==8.2.0\n", encoding="utf-8")
    (source_root / "requirements.txt").write_text("pytest==7.4.0\n", encoding="utf-8")

    source_trace = tmp_path / f"{pack_name}-source-trace.txt"
    session_trace = tmp_path / f"{pack_name}-session-trace.txt"
    home_dir = tmp_path / "home"
    bootstrap_trace = tmp_path / f"{pack_name}-bootstrap-trace.txt"
    path_trace = tmp_path / f"{pack_name}-path-trace.txt"

    _write_executable(
        source_root / ".venv" / "bin" / "python",
        """#!/bin/sh
set -eu
echo source > "$SOURCE_TRACE"
exit 99
""",
    )
    _write_executable(
        home_dir / ".cognitive_switchyard_venv" / "bin" / "pytest",
        """#!/bin/sh
set -eu
echo bootstrap > "$BOOTSTRAP_TRACE"
exit 99
""",
    )

    fake_bin = tmp_path / "bin"
    _write_executable(
        fake_bin / "pytest",
        """#!/bin/sh
set -eu
{
  pwd
  printf '%s\\n' "$*"
} > "$PATH_TRACE"
exit 0
""",
    )

    env_dir = session_root / "verify_envs" / "repo-root"
    _write_executable(
        env_dir / "bin" / "python",
        """#!/bin/sh
set -eu
if [ "$*" = "-m pytest --version" ]; then
  exit 0
fi
{
  pwd
  printf '%s\\n' "$*"
} > "$SESSION_TRACE"
exit 0
""",
    )
    (env_dir / "bootstrap_state.json").write_text(
        json.dumps(
            {
                "fingerprint": _dependency_fingerprint(target_root),
                "target_dir": str(target_root.resolve()),
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(pack_root / "scripts" / "verify"), str(session_root)],
        capture_output=True,
        text=True,
        env={
            "HOME": str(home_dir),
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "BOOTSTRAP_TRACE": str(bootstrap_trace),
            "PATH_TRACE": str(path_trace),
            "SOURCE_TRACE": str(source_trace),
            "SESSION_TRACE": str(session_trace),
            "COGNITIVE_SWITCHYARD_PACK_ROOT": str(pack_root),
            "COGNITIVE_SWITCHYARD_REPO_ROOT": str(target_root),
            "COGNITIVE_SWITCHYARD_SOURCE_REPO": str(source_root),
        },
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert not bootstrap_trace.exists(), "Verify script must not use the switchyard bootstrap venv"
    assert not path_trace.exists(), "Verify script must not fall back to PATH/Homebrew pytest"
    assert not source_trace.exists(), "Verify script must not use a stale source-repo env"
    trace_lines = session_trace.read_text(encoding="utf-8").splitlines()
    assert trace_lines == [
        str(target_root),
        "-m pytest tests --tb=short -q",
    ]


@pytest.mark.parametrize("pack_name", ["claude-code", "codex", "codex-hybrid"])
def test_builtin_verify_bootstraps_session_env_when_no_existing_python_env_exists(
    tmp_path: Path,
    repo_root: Path,
    pack_name: str,
) -> None:
    pack_root = repo_root / "cognitive_switchyard" / "builtin_packs" / pack_name
    target_root = tmp_path / "repo-root"
    session_root = tmp_path / "session-root"
    trace_path = tmp_path / f"{pack_name}-bootstrapped-trace.txt"

    target_root.mkdir()
    session_root.mkdir()
    (target_root / "tests").mkdir()
    (target_root / "pytest").mkdir()
    (target_root / "pytest" / "__init__.py").write_text("", encoding="utf-8")
    (target_root / "pytest" / "__main__.py").write_text(
        (
            "from __future__ import annotations\n"
            "\n"
            "import os\n"
            "import sys\n"
            "from pathlib import Path\n"
            "\n"
            "if sys.argv[1:] == ['--version']:\n"
            "    print('pytest 0')\n"
            "    raise SystemExit(0)\n"
            "\n"
            "trace_path = Path(os.environ['TRACE_PATH'])\n"
            "trace_path.write_text(Path.cwd().as_posix() + '\\n' + ' '.join(sys.argv), encoding='utf-8')\n"
        ),
        encoding="utf-8",
    )
    (target_root / "setup.py").write_text(
        (
            "from setuptools import setup\n"
            "\n"
            "setup(\n"
            "    name='fake-pytest-runner',\n"
            "    version='0.1.0',\n"
            "    packages=['pytest'],\n"
            ")\n"
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [str(pack_root / "scripts" / "verify"), str(session_root)],
        capture_output=True,
        text=True,
        env={
            "PATH": os.environ["PATH"],
            "TRACE_PATH": str(trace_path),
            "COGNITIVE_SWITCHYARD_PACK_ROOT": str(pack_root),
            "COGNITIVE_SWITCHYARD_REPO_ROOT": str(target_root),
        },
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert "Bootstrapping session verification env at" in (result.stderr + result.stdout)
    assert (session_root / "verify_envs" / "repo-root" / "bin" / "python").exists()
    trace_lines = trace_path.read_text(encoding="utf-8").splitlines()
    assert trace_lines == [
        str(target_root),
        f"{target_root / 'pytest' / '__main__.py'} tests --tb=short -q",
    ]


@pytest.mark.parametrize("pack_name", ["claude-code", "codex", "codex-hybrid"])
def test_builtin_verify_bootstraps_session_env_from_source_repo_python_when_available(
    tmp_path: Path,
    repo_root: Path,
    pack_name: str,
) -> None:
    pack_root = repo_root / "cognitive_switchyard" / "builtin_packs" / pack_name
    target_root = tmp_path / "repo-root"
    source_root = tmp_path / "source-repo"
    session_root = tmp_path / "session-root"
    trace_path = tmp_path / f"{pack_name}-source-bootstrap-trace.txt"
    source_bootstrap_trace = tmp_path / f"{pack_name}-source-bootstrap-python.txt"
    path_bootstrap_trace = tmp_path / f"{pack_name}-path-bootstrap-python.txt"
    real_python3 = shutil.which("python3")
    assert real_python3 is not None

    target_root.mkdir()
    source_root.mkdir()
    session_root.mkdir()
    (target_root / "tests").mkdir()
    (target_root / "requirements.txt").write_text("pytest==8.2.0\n", encoding="utf-8")
    (source_root / "requirements.txt").write_text("pytest==7.4.0\n", encoding="utf-8")
    (target_root / "pytest").mkdir()
    (target_root / "pytest" / "__init__.py").write_text("", encoding="utf-8")
    (target_root / "pytest" / "__main__.py").write_text(
        (
            "from __future__ import annotations\n"
            "\n"
            "import os\n"
            "import sys\n"
            "from pathlib import Path\n"
            "\n"
            "if sys.argv[1:] == ['--version']:\n"
            "    print('pytest 0')\n"
            "    raise SystemExit(0)\n"
            "\n"
            "trace_path = Path(os.environ['TRACE_PATH'])\n"
            "trace_path.write_text(Path.cwd().as_posix() + '\\n' + ' '.join(sys.argv), encoding='utf-8')\n"
        ),
        encoding="utf-8",
    )
    (target_root / "setup.py").write_text(
        (
            "from setuptools import setup\n"
            "\n"
            "setup(\n"
            "    name='fake-pytest-runner',\n"
            "    version='0.1.0',\n"
            "    packages=['pytest'],\n"
            ")\n"
        ),
        encoding="utf-8",
    )

    fake_bin = tmp_path / "bin"
    _write_executable(
        fake_bin / "python3",
        f"""#!/bin/sh
set -eu
if [ "${{1:-}}" = "-m" ] && [ "${{2:-}}" = "venv" ]; then
  echo path-python3 > "$PATH_BOOTSTRAP_TRACE"
  exit 99
fi
exec "{real_python3}" "$@"
""",
    )
    _write_executable(
        source_root / ".venv" / "bin" / "python",
        f"""#!/bin/sh
set -eu
if [ "${{1:-}}" = "-m" ] && [ "${{2:-}}" = "venv" ]; then
  echo source-python > "$SOURCE_BOOTSTRAP_TRACE"
fi
exec "{real_python3}" "$@"
""",
    )

    result = subprocess.run(
        [str(pack_root / "scripts" / "verify"), str(session_root)],
        capture_output=True,
        text=True,
        env={
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "TRACE_PATH": str(trace_path),
            "SOURCE_BOOTSTRAP_TRACE": str(source_bootstrap_trace),
            "PATH_BOOTSTRAP_TRACE": str(path_bootstrap_trace),
            "COGNITIVE_SWITCHYARD_PACK_ROOT": str(pack_root),
            "COGNITIVE_SWITCHYARD_REPO_ROOT": str(target_root),
            "COGNITIVE_SWITCHYARD_SOURCE_REPO": str(source_root),
        },
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert source_bootstrap_trace.read_text(encoding="utf-8").strip() == "source-python"
    assert not path_bootstrap_trace.exists(), "Verify script must not use PATH python3 for venv bootstrap when repo python exists"
    trace_lines = trace_path.read_text(encoding="utf-8").splitlines()
    assert trace_lines == [
        str(target_root),
        f"{target_root / 'pytest' / '__main__.py'} tests --tb=short -q",
    ]
