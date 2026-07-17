from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Mapping, Sequence

from .config import RuntimePaths, build_runtime_paths, canonical_pack_path
from .models import (
    HookInvocationResult,
    PackManifest,
    PackPreflightResult,
    PrerequisiteReport,
    PrerequisiteResult,
    ScriptPermissionIssue,
    ScriptPermissionReport,
)
from .pack_loader import iter_pack_script_files, resolve_pack_hook_path


class HookNotFoundError(FileNotFoundError):
    pass


def scan_pack_scripts_for_executable_bits(
    pack_manifest: PackManifest,
    *,
    runtime_paths: RuntimePaths | None = None,
) -> ScriptPermissionReport:
    del runtime_paths

    issues = []
    for script_path in iter_pack_script_files(pack_manifest):
        if os.access(script_path, os.X_OK):
            continue
        relative_path = script_path.relative_to(pack_manifest.root).as_posix()
        issues.append(
            ScriptPermissionIssue(
                relative_path=relative_path,
                fix_command=f"chmod +x {canonical_pack_path(pack_manifest.name, relative_path)}",
            )
        )
    return ScriptPermissionReport(ok=not issues, issues=tuple(issues))


def run_prerequisite_checks(
    pack_manifest: PackManifest,
    *,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> PrerequisiteReport:
    results = []
    command_env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    if env is not None:
        command_env.update(env)

    for prerequisite in pack_manifest.prerequisites:
        completed = subprocess.run(
            prerequisite.check,
            shell=True,
            cwd=cwd or pack_manifest.root,
            env=command_env,
            text=True,
            capture_output=True,
            check=False,
        )
        results.append(
            PrerequisiteResult(
                name=prerequisite.name,
                check=prerequisite.check,
                ok=completed.returncode == 0,
                exit_code=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
            )
        )
    return PrerequisiteReport(
        ok=all(result.ok for result in results),
        results=tuple(results),
    )


def run_short_lived_hook(
    script_path: Path,
    *,
    hook_name: str | None = None,
    args: Sequence[str] = (),
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> HookInvocationResult:
    resolved_script = script_path.resolve()
    if not resolved_script.is_file():
        raise FileNotFoundError(f"Hook script not found: {resolved_script}")

    run_cwd = (cwd or resolved_script.parent).resolve()
    # Strip CLAUDECODE so child Claude CLI sessions don't refuse to launch
    # when the orchestrator itself is running inside Claude Code.
    # Also strip COGNITIVE_SWITCHYARD_* vars so they don't leak from the
    # parent process — each hook invocation should only see the vars
    # explicitly passed via the env parameter.
    command_env = {
        k: v for k, v in os.environ.items()
        if k != "CLAUDECODE" and not k.startswith("COGNITIVE_SWITCHYARD_")
    }
    if env is not None:
        command_env.update(env)

    completed = subprocess.run(
        [str(resolved_script), *args],
        cwd=run_cwd,
        env=command_env,
        text=True,
        capture_output=True,
        check=False,
    )
    return HookInvocationResult(
        hook_name=hook_name or resolved_script.stem,
        script_path=resolved_script,
        args=tuple(args),
        cwd=run_cwd,
        ok=completed.returncode == 0,
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def run_pack_hook(
    pack_manifest: PackManifest,
    hook_name: str,
    *,
    args: Sequence[str] = (),
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> HookInvocationResult:
    hook_path = resolve_pack_hook_path(pack_manifest, hook_name)
    if hook_path is None:
        raise HookNotFoundError(f"Optional hook {hook_name!r} is not defined for pack {pack_manifest.name!r}")
    return run_short_lived_hook(
        hook_path,
        hook_name=hook_name,
        args=args,
        cwd=cwd,
        env=env,
    )


def run_pack_preflight(
    pack_manifest: PackManifest,
    *,
    runtime_paths: RuntimePaths | None = None,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> PackPreflightResult:
    permission_report = scan_pack_scripts_for_executable_bits(
        pack_manifest,
        runtime_paths=runtime_paths or build_runtime_paths(),
    )
    empty_prerequisites = PrerequisiteReport(ok=True, results=())
    if not permission_report.ok:
        return PackPreflightResult(
            ok=False,
            permission_report=permission_report,
            prerequisite_results=empty_prerequisites,
            preflight_result=None,
        )

    prerequisite_results = run_prerequisite_checks(pack_manifest, env=env, cwd=cwd)
    if not prerequisite_results.ok:
        return PackPreflightResult(
            ok=False,
            permission_report=permission_report,
            prerequisite_results=prerequisite_results,
            preflight_result=None,
        )

    hook_path = resolve_pack_hook_path(pack_manifest, "preflight")
    if hook_path is None:
        return PackPreflightResult(
            ok=True,
            permission_report=permission_report,
            prerequisite_results=prerequisite_results,
            preflight_result=None,
        )

    preflight_result = run_short_lived_hook(
        hook_path,
        hook_name="preflight",
        cwd=cwd or pack_manifest.root,
        env=env,
    )
    return PackPreflightResult(
        ok=preflight_result.ok,
        permission_report=permission_report,
        prerequisite_results=prerequisite_results,
        preflight_result=preflight_result,
    )
