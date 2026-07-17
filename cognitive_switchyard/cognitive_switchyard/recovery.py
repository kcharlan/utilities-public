from __future__ import annotations

import logging
import os
import shutil
import signal
import time
from pathlib import Path
from typing import Mapping

_logger = logging.getLogger(__name__)

from .hook_runner import HookNotFoundError, run_pack_hook
from .models import PackManifest, RecoveryResult
from .parsers import ArtifactParseError, parse_status_sidecar
from .state import StateStore


def recover_execution_session(
    *,
    store: StateStore,
    session_id: str,
    pack_manifest: PackManifest,
    env: Mapping[str, str] | None = None,
    kill_grace_period: float = 5.0,
) -> RecoveryResult:
    session = store.get_session(session_id)
    session_paths = store.runtime_paths.session_paths(session_id)
    preserved_done: list[str] = []
    reverted_ready: list[str] = []
    warnings: list[str] = []

    for worker_dir in sorted(path for path in session_paths.workers.iterdir() if path.is_dir()):
        if not worker_dir.name.isdigit():
            continue
        slot_number = int(worker_dir.name)
        metadata = store.read_worker_recovery_metadata(session_id, slot_number=slot_number)
        for plan_path in sorted(worker_dir.glob("*.plan.md")):
            task_id = plan_path.name.removesuffix(".plan.md")
            workspace_path = (
                metadata.workspace_path
                if metadata is not None and metadata.task_id == task_id
                else session_paths.root
            )
            status, warning = _classify_worker_result(
                plan_path,
                sidecar_format=pack_manifest.status.sidecar_format,
            )
            if warning is not None:
                warnings.append(warning)
                store.append_event(
                    session_id,
                    timestamp=_timestamp(),
                    event_type="session.recovery_warning",
                    task_id=task_id,
                    message=warning,
                )

            if status == "done":
                if not _run_isolate_end(
                    pack_manifest=pack_manifest,
                    slot_number=slot_number,
                    task_id=task_id,
                    workspace_path=workspace_path,
                    final_status="done",
                    env=env,
                ):
                    warning = f"Recovery isolate_end failed while preserving completed task {task_id}."
                    warnings.append(warning)
                    store.append_event(
                        session_id,
                        timestamp=_timestamp(),
                        event_type="session.recovery_warning",
                        task_id=task_id,
                        message=warning,
                    )
                store.project_task(
                    session_id,
                    task_id,
                    status="done",
                    timestamp=_timestamp(),
                )
                preserved_done.append(task_id)
                # Clear metadata only after project_task has committed. Wrap in
                # try/except so a failure to clear does not abort the recovery
                # loop — the orphaned metadata will be cleaned up on the next pass. F-7 fix.
                try:
                    store.clear_worker_recovery_metadata(session_id, slot_number=slot_number)
                except Exception:
                    _logger.warning("Failed to clear recovery metadata for slot %d; will be cleaned up on next recovery", slot_number)
                continue

            if metadata is not None and metadata.pid is not None:
                _terminate_pid(metadata.pid, kill_grace_period=kill_grace_period)

            isolate_end_ok = _run_isolate_end(
                pack_manifest=pack_manifest,
                slot_number=slot_number,
                task_id=task_id,
                workspace_path=workspace_path,
                final_status="blocked",
                env=env,
            )
            if not isolate_end_ok:
                cleanup_warning = _cleanup_workspace_after_failed_isolate_end(
                    session_root=session_paths.root,
                    workspace_path=workspace_path,
                    task_id=task_id,
                )
                warnings.append(cleanup_warning)
                store.append_event(
                    session_id,
                    timestamp=_timestamp(),
                    event_type="session.recovery_warning",
                    task_id=task_id,
                    message=cleanup_warning,
                )

            _delete_worker_sidecar_if_present(plan_path)
            store.project_task(
                session_id,
                task_id,
                status="ready",
            )
            reverted_ready.append(task_id)
            # F-7 fix: clear metadata only after project_task has committed.
            try:
                store.clear_worker_recovery_metadata(session_id, slot_number=slot_number)
            except Exception:
                _logger.warning("Failed to clear recovery metadata for slot %d; will be cleaned up on next recovery", slot_number)

    orphan_warnings = cleanup_orphaned_workspaces(
        session_paths=session_paths,
        pack_manifest=pack_manifest,
        env=env,
        store=store,
        session_id=session_id,
    )
    warnings.extend(orphan_warnings)

    reconcile_filesystem_projection(
        store=store,
        session_id=session_id,
        session_status=session.status,
    )
    return RecoveryResult(
        session_id=session_id,
        preserved_done_task_ids=tuple(preserved_done),
        reverted_ready_task_ids=tuple(reverted_ready),
        warnings=tuple(warnings),
    )


def cleanup_orphaned_workspaces(
    *,
    session_paths,
    pack_manifest: PackManifest,
    env: Mapping[str, str] | None,
    store: StateStore,
    session_id: str,
) -> list[str]:
    """Clean up workspaces whose recovery metadata survived but had no plan file.

    After a hard crash, a worker slot may have a ``recovery.json`` pointing to a
    workspace directory even though the plan file was never written or was lost.
    The per-slot loop in ``recover_execution_session`` only processes slots that
    contain ``*.plan.md`` files, so these orphaned workspaces are leaked.

    This function re-scans worker slot directories for leftover ``recovery.json``
    files, runs ``isolate_end`` with status ``blocked`` (cleanup without merging),
    and falls back to ``shutil.rmtree`` if the hook fails.
    """
    if pack_manifest.isolation.type == "none":
        return []

    warnings: list[str] = []
    if not session_paths.workers.is_dir():
        return warnings

    for worker_dir in sorted(
        path for path in session_paths.workers.iterdir() if path.is_dir()
    ):
        if not worker_dir.name.isdigit():
            continue
        slot_number = int(worker_dir.name)
        metadata = store.read_worker_recovery_metadata(session_id, slot_number=slot_number)
        if metadata is None:
            continue

        # If we reach here, the per-slot plan loop did not clear this metadata,
        # meaning no plan file matched.  The workspace may still exist on disk.
        workspace_path = metadata.workspace_path
        task_id = metadata.task_id

        if metadata.pid is not None:
            _terminate_pid(metadata.pid, kill_grace_period=5.0)

        isolate_end_ok = _run_isolate_end(
            pack_manifest=pack_manifest,
            slot_number=slot_number,
            task_id=task_id,
            workspace_path=workspace_path,
            final_status="blocked",
            env=env,
        )
        if isolate_end_ok:
            warning = (
                f"Recovery cleaned up orphaned workspace for task {task_id} "
                f"in worker slot {slot_number} (no plan file found)."
            )
        else:
            cleanup_warning = _cleanup_workspace_after_failed_isolate_end(
                session_root=session_paths.root,
                workspace_path=workspace_path,
                task_id=task_id,
            )
            warning = (
                f"Recovery found orphaned workspace for task {task_id} "
                f"in worker slot {slot_number} (no plan file found). {cleanup_warning}"
            )

        warnings.append(warning)
        store.append_event(
            session_id,
            timestamp=_timestamp(),
            event_type="session.recovery_warning",
            task_id=task_id,
            message=warning,
        )
        store.clear_worker_recovery_metadata(session_id, slot_number=slot_number)

    return warnings


def reconcile_filesystem_projection(
    *,
    store: StateStore,
    session_id: str,
    session_status: str | None = None,
) -> None:
    store.reconcile_filesystem_projection(
        session_id,
        session_status=session_status,
    )


def _classify_worker_result(
    plan_path: Path,
    *,
    sidecar_format: str,
) -> tuple[str, str | None]:
    status_path = _status_path(plan_path)
    if not status_path.is_file():
        return "incomplete", None
    try:
        status = parse_status_sidecar(
            status_path.read_text(encoding="utf-8"),
            source=status_path,
            sidecar_format=sidecar_format,
        )
    except ArtifactParseError as exc:
        return "incomplete", f"Recovery found malformed status sidecar for {plan_path.name}: {exc}"
    if status.status == "done":
        return "done", None
    return "incomplete", f"Recovery found STATUS: {status.status} for {plan_path.name}; treating as incomplete work."


def _status_path(plan_path: Path) -> Path:
    return plan_path.with_name(plan_path.name.removesuffix(".plan.md") + ".status")


def _delete_worker_sidecar_if_present(plan_path: Path) -> None:
    status_path = _status_path(plan_path)
    if status_path.exists():
        status_path.unlink()


def _terminate_pid(pid: int, *, kill_grace_period: float) -> None:
    if not _pid_is_running(pid):
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
    deadline = time.monotonic() + kill_grace_period
    while time.monotonic() < deadline:
        if not _pid_is_running(pid):
            return
        time.sleep(0.02)
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        return
    deadline = time.monotonic() + kill_grace_period
    while time.monotonic() < deadline:
        if not _pid_is_running(pid):
            return
        time.sleep(0.02)


def _pid_is_running(pid: int) -> bool:
    try:
        waited_pid, _status = os.waitpid(pid, os.WNOHANG)
        if waited_pid == pid:
            return False
    except ChildProcessError:
        pass
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _cleanup_workspace_after_failed_isolate_end(
    *,
    session_root: Path,
    workspace_path: Path,
    task_id: str,
) -> str:
    resolved_root = session_root.resolve()
    resolved_workspace = workspace_path.resolve()
    if resolved_workspace == resolved_root or not resolved_workspace.is_relative_to(resolved_root):
        return (
            f"Recovery cleanup for {task_id} could not run isolate_end and left non-session workspace "
            f"{resolved_workspace} in place."
        )
    shutil.rmtree(resolved_workspace, ignore_errors=True)
    return (
        f"Recovery cleanup for {task_id} could not run isolate_end; forcibly removed session workspace "
        f"{resolved_workspace}."
    )


def _run_isolate_end(
    *,
    pack_manifest: PackManifest,
    slot_number: int,
    task_id: str,
    workspace_path: Path,
    final_status: str,
    env: Mapping[str, str] | None,
) -> bool:
    if pack_manifest.isolation.type == "none":
        return True
    hook_cwd = workspace_path if workspace_path.exists() else pack_manifest.root
    try:
        result = run_pack_hook(
            pack_manifest,
            "isolate_end",
            args=[str(slot_number), task_id, str(workspace_path), final_status],
            cwd=hook_cwd,
            env=env,
        )
    except (FileNotFoundError, HookNotFoundError):
        return False
    except Exception as exc:
        _logger.error("Recovery isolate_end hook crashed for task %s: %s", task_id, exc)
        return False
    return result.ok


def _timestamp() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
