from __future__ import annotations

import os
import shutil
from pathlib import Path
from textwrap import dedent

import pytest

from cognitive_switchyard.config import build_runtime_paths
from cognitive_switchyard.hook_runner import (
    HookNotFoundError,
    run_pack_preflight,
    run_pack_hook,
    run_prerequisite_checks,
    run_short_lived_hook,
    scan_pack_scripts_for_executable_bits,
)
from cognitive_switchyard.pack_loader import load_pack_manifest


def _write_pack(tmp_path: Path, manifest: str) -> Path:
    pack_root = tmp_path / "pack-under-test"
    (pack_root / "scripts").mkdir(parents=True)
    (pack_root / "pack.yaml").write_text(dedent(manifest).strip() + "\n", encoding="utf-8")
    return pack_root


def _write_script(path: Path, contents: str, *, executable: bool) -> None:
    path.write_text(dedent(contents).lstrip(), encoding="utf-8")
    mode = path.stat().st_mode
    if executable:
        path.chmod(mode | 0o111)
    else:
        path.chmod(mode & ~0o111)


def test_script_scan_reports_all_non_executable_files_with_canonical_chmod_hints(
    tmp_path: Path,
) -> None:
    pack_root = _write_pack(
        tmp_path,
        """
        name: sample-pack
        description: Scan pack scripts.
        version: 1.2.3

        phases:
          resolution:
            enabled: true
            executor: script
            script: scripts/resolve
          execution:
            enabled: true
            executor: shell
            command: scripts/execute
        """,
    )
    _write_script(pack_root / "scripts" / "execute", "#!/bin/sh\nexit 0\n", executable=True)
    _write_script(pack_root / "scripts" / "preflight", "#!/bin/sh\nexit 0\n", executable=False)
    _write_script(
        pack_root / "scripts" / "isolate_start.py",
        "#!/usr/bin/env python3\nprint('ok')\n",
        executable=False,
    )
    _write_script(pack_root / "scripts" / "resolve", "#!/bin/sh\nexit 0\n", executable=False)

    manifest = load_pack_manifest(pack_root)

    report = scan_pack_scripts_for_executable_bits(
        manifest,
        runtime_paths=build_runtime_paths(Path("/tmp/runtime-home")),
    )

    assert report.ok is False
    assert [issue.relative_path for issue in report.issues] == [
        "scripts/isolate_start.py",
        "scripts/preflight",
        "scripts/resolve",
    ]
    assert [issue.fix_command for issue in report.issues] == [
        "chmod +x ~/.cognitive_switchyard/packs/sample-pack/scripts/isolate_start.py",
        "chmod +x ~/.cognitive_switchyard/packs/sample-pack/scripts/preflight",
        "chmod +x ~/.cognitive_switchyard/packs/sample-pack/scripts/resolve",
    ]


def test_prerequisite_checks_return_structured_results_in_declared_order(tmp_path: Path) -> None:
    pack_root = _write_pack(
        tmp_path,
        """
        name: prerequisite-pack
        description: Prerequisite ordering.
        version: 1.2.3

        prerequisites:
          - name: First check
            check: printf 'first-out'
          - name: Second check
            check: printf 'second-err' >&2; exit 7

        phases:
          execution:
            enabled: true
            executor: shell
            command: scripts/execute
        """,
    )
    _write_script(pack_root / "scripts" / "execute", "#!/bin/sh\nexit 0\n", executable=True)

    manifest = load_pack_manifest(pack_root)

    results = run_prerequisite_checks(manifest, env={"PATH": os.environ["PATH"]})

    assert results.ok is False
    assert [result.name for result in results.results] == ["First check", "Second check"]
    assert results.results[0].ok is True
    assert results.results[0].exit_code == 0
    assert results.results[0].stdout == "first-out"
    assert results.results[0].stderr == ""
    assert results.results[1].ok is False
    assert results.results[1].exit_code == 7
    assert results.results[1].stdout == ""
    assert results.results[1].stderr == "second-err"


def test_pack_preflight_hook_runs_only_after_permission_and_prerequisite_success(
    tmp_path: Path,
) -> None:
    runtime_paths = build_runtime_paths(Path("/tmp/preflight-runtime"))
    marker = tmp_path / "preflight-marker.txt"

    permission_pack = _write_pack(
        tmp_path / "permission-pack",
        f"""
        name: permission-pack
        description: Permission gate.
        version: 1.2.3

        phases:
          execution:
            enabled: true
            executor: shell
            command: scripts/execute
        """,
    )
    _write_script(permission_pack / "scripts" / "execute", "#!/bin/sh\nexit 0\n", executable=False)
    _write_script(
        permission_pack / "scripts" / "preflight",
        f"#!/bin/sh\necho permission >> {marker}\n",
        executable=True,
    )

    permission_result = run_pack_preflight(
        load_pack_manifest(permission_pack),
        runtime_paths=runtime_paths,
    )

    assert permission_result.ok is False
    assert permission_result.preflight_result is None
    assert marker.exists() is False

    prereq_pack = _write_pack(
        tmp_path / "prereq-pack",
        f"""
        name: prereq-pack
        description: Prerequisite gate.
        version: 1.2.3

        prerequisites:
          - name: Missing tool
            check: exit 3

        phases:
          execution:
            enabled: true
            executor: shell
            command: scripts/execute
        """,
    )
    _write_script(prereq_pack / "scripts" / "execute", "#!/bin/sh\nexit 0\n", executable=True)
    _write_script(
        prereq_pack / "scripts" / "preflight",
        f"#!/bin/sh\necho prereq >> {marker}\n",
        executable=True,
    )

    prereq_result = run_pack_preflight(
        load_pack_manifest(prereq_pack),
        runtime_paths=runtime_paths,
        env={"PATH": os.environ["PATH"]},
    )

    assert prereq_result.ok is False
    assert prereq_result.permission_report.ok is True
    assert prereq_result.prerequisite_results.ok is False
    assert prereq_result.preflight_result is None
    assert marker.exists() is False

    success_pack = _write_pack(
        tmp_path / "success-pack",
        f"""
        name: success-pack
        description: Successful preflight.
        version: 1.2.3

        prerequisites:
          - name: Env available
            check: test \"$PACK_OK\" = \"yes\"

        phases:
          execution:
            enabled: true
            executor: shell
            command: scripts/execute
        """,
    )
    _write_script(success_pack / "scripts" / "execute", "#!/bin/sh\nexit 0\n", executable=True)
    _write_script(
        success_pack / "scripts" / "preflight",
        f"#!/bin/sh\necho success >> {marker}\nprintf 'preflight-ok'\n",
        executable=True,
    )

    success_result = run_pack_preflight(
        load_pack_manifest(success_pack),
        runtime_paths=runtime_paths,
        env={"PATH": os.environ["PATH"], "PACK_OK": "yes"},
    )

    assert success_result.ok is True
    assert success_result.preflight_result is not None
    assert success_result.preflight_result.exit_code == 0
    assert success_result.preflight_result.stdout == "preflight-ok"
    assert marker.read_text(encoding="utf-8") == "success\n"


def test_short_lived_hook_runs_with_positional_args_and_working_directory(tmp_path: Path) -> None:
    script_path = tmp_path / "echo_args.py"
    _write_script(
        script_path,
        """
        #!/usr/bin/env python3
        import os
        import sys

        print(os.getcwd())
        print("|".join(sys.argv[1:]))
        """,
        executable=True,
    )
    cwd = tmp_path / "workspace"
    cwd.mkdir()

    result = run_short_lived_hook(script_path, args=["alpha", "beta"], cwd=cwd)

    assert result.ok is True
    assert result.exit_code == 0
    assert result.stdout.splitlines() == [str(cwd), "alpha|beta"]
    assert result.stderr == ""


def test_builtin_claude_code_preflight_reports_missing_claude_or_git_prerequisites_cleanly(
    repo_root: Path,
) -> None:
    pack_root = repo_root / "cognitive_switchyard" / "builtin_packs" / "claude-code"
    manifest = load_pack_manifest(pack_root)

    result = run_pack_preflight(
        manifest,
        runtime_paths=build_runtime_paths(Path("/tmp/runtime-home")),
        env={"PATH": "/definitely-missing"},
    )

    assert result.ok is False
    assert result.permission_report.ok is True
    assert result.preflight_result is None
    assert [entry.name for entry in result.prerequisite_results.results] == [
        "Claude CLI available",
        "Git available",
        "jq available",
    ]
    assert result.prerequisite_results.results[0].ok is False
    assert result.prerequisite_results.results[1].ok is False
    assert result.prerequisite_results.results[2].ok is False
    assert "command -v claude" in result.prerequisite_results.results[0].check
    assert "command -v git" in result.prerequisite_results.results[1].check
    assert "command -v jq" in result.prerequisite_results.results[2].check


def test_builtin_claude_code_preflight_requires_repo_root_for_git_worktree_isolation(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    source_pack_root = repo_root / "cognitive_switchyard" / "builtin_packs" / "claude-code"
    pack_root = tmp_path / "runtime-pack"
    shutil.copytree(source_pack_root, pack_root)
    manifest = load_pack_manifest(pack_root)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_script(fake_bin / "claude", "#!/bin/sh\nexit 0\n", executable=True)
    _write_script(
        fake_bin / "git",
        """
        #!/bin/sh
        if [ "$1" = "rev-parse" ] && [ "$2" = "--is-inside-work-tree" ]; then
          printf 'true\n'
          exit 0
        fi
        if [ "$1" = "rev-parse" ] && [ "$2" = "--abbrev-ref" ] && [ "$3" = "HEAD" ]; then
          printf 'feature/test\n'
          exit 0
        fi
        exit 0
        """,
        executable=True,
    )
    _write_script(fake_bin / "jq", "#!/bin/sh\nexit 0\n", executable=True)

    result = run_pack_preflight(
        manifest,
        runtime_paths=build_runtime_paths(Path("/tmp/runtime-home")),
        env={"PATH": str(fake_bin)},
    )

    assert result.ok is False
    assert result.permission_report.ok is True
    assert result.prerequisite_results.ok is True
    assert result.preflight_result is not None
    assert result.preflight_result.ok is False
    assert "COGNITIVE_SWITCHYARD_REPO_ROOT" in result.preflight_result.stderr


def test_builtin_claude_code_preflight_uses_repo_root_environment_for_git_checks(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    source_pack_root = repo_root / "cognitive_switchyard" / "builtin_packs" / "claude-code"
    pack_root = tmp_path / "runtime-pack"
    shutil.copytree(source_pack_root, pack_root)
    manifest = load_pack_manifest(pack_root)
    repo_path = tmp_path / "repo-root"
    repo_path.mkdir()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_script(fake_bin / "claude", "#!/bin/sh\nexit 0\n", executable=True)
    _write_script(
        fake_bin / "git",
        """
        #!/bin/sh
        set -eu
        expected_root="${COGNITIVE_SWITCHYARD_REPO_ROOT:?missing repo root}"
        current="$PWD"
        if [ "$1" = "-C" ]; then
          current="$2"
          shift 2
        fi
        if [ "$current" != "$expected_root" ]; then
          echo "wrong git cwd: $current" >&2
          exit 9
        fi
        if [ "$1" = "rev-parse" ] && [ "$2" = "--is-inside-work-tree" ]; then
          printf 'true\n'
          exit 0
        fi
        if [ "$1" = "rev-parse" ] && [ "$2" = "--abbrev-ref" ] && [ "$3" = "HEAD" ]; then
          printf 'feature/test\n'
          exit 0
        fi
        exit 0
        """,
        executable=True,
    )
    _write_script(fake_bin / "jq", "#!/bin/sh\nexit 0\n", executable=True)

    result = run_pack_preflight(
        manifest,
        runtime_paths=build_runtime_paths(Path("/tmp/runtime-home")),
        env={
            "PATH": str(fake_bin),
            "COGNITIVE_SWITCHYARD_REPO_ROOT": str(repo_path),
        },
    )

    assert result.ok is True
    assert result.permission_report.ok is True
    assert result.prerequisite_results.ok is True
    assert result.preflight_result is not None
    assert result.preflight_result.ok is True
    assert str(repo_path) in result.preflight_result.stdout


def test_missing_optional_pack_hook_raises_typed_error(tmp_path: Path) -> None:
    pack_root = _write_pack(
        tmp_path,
        """
        name: optional-hook-pack
        description: Missing optional hook.
        version: 1.2.3

        phases:
          execution:
            enabled: true
            executor: shell
            command: scripts/execute
        """,
    )
    _write_script(pack_root / "scripts" / "execute", "#!/bin/sh\nexit 0\n", executable=True)

    manifest = load_pack_manifest(pack_root)

    with pytest.raises(HookNotFoundError) as excinfo:
        run_pack_hook(manifest, "preflight")

    assert "Optional hook 'preflight' is not defined" in str(excinfo.value)
