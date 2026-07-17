from __future__ import annotations

import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping, TextIO

from .models import PackManifest, WorkerAlert, WorkerProgressState, WorkerResult, WorkerSnapshot
from .pack_loader import resolve_pack_hook_path
from .parsers import ArtifactParseError, parse_progress_line, parse_status_sidecar

_logger = __import__("logging").getLogger(__name__)

# Defense-in-depth: if Claude/Codex has exited (result line in output file) but
# the execute script is still alive and silent, terminate after this many seconds.
_STALE_EXECUTE_SECONDS = 30.0


class WorkerManagerError(RuntimeError):
    pass


class WorkerResultError(WorkerManagerError):
    pass


class WorkerStatusSidecarError(WorkerResultError):
    pass


@dataclass
class _ActiveWorker:
    slot_number: int
    task_id: str
    task_plan_path: Path
    workspace_path: Path
    log_path: Path
    task_log_path: Path | None
    process: subprocess.Popen[str]
    log_handle: TextIO
    task_log_handle: TextIO | None
    started_at: float
    last_output_at: float
    task_idle: float
    task_max: float
    progress_format: str
    sidecar_format: str
    last_detail_content: str | None = None
    progress: WorkerProgressState = field(default_factory=WorkerProgressState)
    pending_lines: list[str] = field(default_factory=list)
    pending_alerts: list[WorkerAlert] = field(default_factory=list)
    timed_out: bool = False
    timeout_kind: str | None = None
    failure_reason: str | None = None
    terminate_sent_at: float | None = None
    kill_escalated: bool = False
    finalized: bool = False
    collected: bool = False
    idle_warning_emitted: bool = False
    task_max_warning_emitted: bool = False
    readers: list[threading.Thread] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)


class WorkerManager:
    def __init__(
        self,
        *,
        default_task_idle: float | None = None,
        default_task_max: float | None = None,
        kill_grace_period: float = 5.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._default_task_idle = default_task_idle
        self._default_task_max = default_task_max
        self._kill_grace_period = kill_grace_period
        self._clock = clock or time.monotonic
        self._workers: dict[int, _ActiveWorker] = {}

    def dispatch(
        self,
        *,
        slot_number: int,
        pack_manifest: PackManifest,
        task_plan_path: Path,
        workspace_path: Path,
        log_path: Path,
        task_log_path: Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> int:
        if slot_number in self._workers and not self._workers[slot_number].collected:
            raise WorkerManagerError(f"worker slot {slot_number} is already active")

        command_path = resolve_pack_hook_path(pack_manifest, "execute")
        if command_path is None:
            raise WorkerManagerError(f"pack {pack_manifest.name!r} does not define an execute hook")

        task_plan_path = task_plan_path.resolve()
        workspace_path = workspace_path.resolve()
        log_path = log_path.resolve()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        resolved_task_log_path = task_log_path.resolve() if task_log_path is not None else None
        if resolved_task_log_path is not None:
            resolved_task_log_path.parent.mkdir(parents=True, exist_ok=True)

        started_at = self._clock()
        # Strip CLAUDECODE so child Claude CLI sessions don't refuse to launch
        # when the orchestrator itself is running inside Claude Code.
        command_env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
        if env is not None:
            command_env.update(env)
        process = subprocess.Popen(
            [str(command_path), str(task_plan_path), str(workspace_path)],
            cwd=workspace_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=command_env,
            text=True,
            bufsize=1,
        )
        log_handle = log_path.open("a", encoding="utf-8")
        task_log_handle = (
            resolved_task_log_path.open("a", encoding="utf-8")
            if resolved_task_log_path is not None
            else None
        )
        worker = _ActiveWorker(
            slot_number=slot_number,
            task_id=_task_id_from_path(task_plan_path),
            task_plan_path=task_plan_path,
            workspace_path=workspace_path,
            log_path=log_path,
            task_log_path=resolved_task_log_path,
            process=process,
            log_handle=log_handle,
            task_log_handle=task_log_handle,
            started_at=started_at,
            last_output_at=started_at,
            task_idle=(
                pack_manifest.timeouts.task_idle
                if self._default_task_idle is None
                else self._default_task_idle
            ),
            task_max=(
                pack_manifest.timeouts.task_max
                if self._default_task_max is None
                else self._default_task_max
            ),
            progress_format=pack_manifest.status.progress_format,
            sidecar_format=pack_manifest.status.sidecar_format,
        )
        self._workers[slot_number] = worker
        self._start_reader_threads(worker)
        return process.pid

    def poll(self, slot_number: int) -> WorkerSnapshot:
        worker = self._get_worker(slot_number)
        self._refresh_worker(worker)
        with worker.lock:
            new_output_lines = tuple(worker.pending_lines)
            worker.pending_lines.clear()
            progress = worker.progress
            alerts = tuple(worker.pending_alerts)
            worker.pending_alerts.clear()
        exit_code = worker.process.poll()
        with worker.lock:
            last_output_at = worker.last_output_at
            task_idle = worker.task_idle
            worker_started_at = worker.started_at
        return WorkerSnapshot(
            slot_number=worker.slot_number,
            task_id=worker.task_id,
            pid=worker.process.pid,
            workspace_path=worker.workspace_path,
            log_path=worker.log_path,
            new_output_lines=new_output_lines,
            progress=progress,
            is_finished=worker.finalized,
            exit_code=exit_code,
            timed_out=worker.timed_out,
            alerts=alerts,
            last_output_at=last_output_at,
            task_idle=task_idle,
            worker_started_at=worker_started_at,
        )

    def collect(self, slot_number: int) -> WorkerResult:
        worker = self._get_worker(slot_number)
        self._refresh_worker(worker)
        if not worker.finalized:
            raise WorkerResultError(f"worker slot {slot_number} has not finished")
        if worker.collected:
            raise WorkerResultError(f"worker slot {slot_number} was already collected")

        with worker.lock:
            worker.collected = True
        worker.process.wait(timeout=0)
        try:
            exit_code = worker.process.returncode
            assert exit_code is not None
            result = WorkerResult(
                slot_number=worker.slot_number,
                task_id=worker.task_id,
                pid=worker.process.pid,
                workspace_path=worker.workspace_path,
                log_path=worker.log_path,
                exit_code=exit_code,
                timed_out=worker.timed_out,
                timeout_kind=worker.timeout_kind,
                failure_reason=worker.failure_reason,
                kill_escalated=worker.kill_escalated,
                progress=worker.progress,
            )
            if worker.timed_out:
                return result

            status_path = _status_sidecar_path_from_plan(worker.task_plan_path)
            if not status_path.is_file():
                raise WorkerStatusSidecarError(f"missing status sidecar: {status_path}")
            try:
                status = parse_status_sidecar(
                    status_path.read_text(encoding="utf-8"),
                    source=status_path,
                    sidecar_format=worker.sidecar_format,
                )
            except (ArtifactParseError, FileNotFoundError) as exc:
                # FileNotFoundError: TOCTOU race — file deleted between is_file() and read_text(). F-3 fix.
                raise WorkerStatusSidecarError(
                    f"invalid status sidecar: {status_path}: {exc}"
                ) from exc
            return WorkerResult(
                slot_number=result.slot_number,
                task_id=result.task_id,
                pid=result.pid,
                workspace_path=result.workspace_path,
                log_path=result.log_path,
                exit_code=result.exit_code,
                timed_out=result.timed_out,
                timeout_kind=result.timeout_kind,
                failure_reason=result.failure_reason,
                kill_escalated=result.kill_escalated,
                progress=result.progress,
                status_path=status_path,
                status=status,
            )
        finally:
            self._workers.pop(slot_number, None)

    def active_slot_numbers(self) -> tuple[int, ...]:
        # Acquire each worker's lock before reading collected to avoid a data race
        # with collect() setting the flag. F-8 fix.
        result = []
        for slot_number, worker in sorted(self._workers.items()):
            with worker.lock:
                if not worker.collected:
                    result.append(slot_number)
        return tuple(result)

    def terminate(
        self,
        slot_number: int,
        *,
        reason: str,
        timeout_kind: str = "session_max",
    ) -> None:
        worker = self._get_worker(slot_number)
        now = self._clock()
        if worker.finalized:
            return
        if worker.process.poll() is not None:
            self._refresh_worker(worker)
            return
        self._terminate_worker(
            worker,
            timeout_kind=timeout_kind,
            reason=reason,
            now=now,
        )

    def _refresh_worker(self, worker: _ActiveWorker) -> None:
        with worker.lock:
            if worker.finalized:
                return

        now = self._clock()
        exit_code = worker.process.poll()
        if exit_code is None:
            self._enforce_timeouts(worker, now)
            exit_code = worker.process.poll()

        if exit_code is not None:
            self._finalize_worker(worker)

    def _enforce_timeouts(self, worker: _ActiveWorker, now: float) -> None:
        # All reads and writes of worker state fields must hold worker.lock to
        # avoid data races with the reader threads. F-4 fix.
        with worker.lock:
            if worker.terminate_sent_at is not None:
                if now - worker.terminate_sent_at >= self._kill_grace_period:
                    worker.process.kill()
                    worker.kill_escalated = True
                return

        self._emit_warning_alerts(worker, now)

        with worker.lock:
            last_output_at = worker.last_output_at
            started_at = worker.started_at

        if worker.task_idle > 0 and now - last_output_at >= worker.task_idle:
            self._terminate_worker(
                worker,
                timeout_kind="idle",
                reason=f"Worker {worker.slot_number} (task {worker.task_id}): Killed — no output for {_format_seconds(worker.task_idle)}",
                now=now,
            )
            return

        # Defense-in-depth: detect zombie execute scripts where the AI process
        # has exited (result line present in output file) but the execute script
        # is still alive.  This catches sampler hangs that survive cooperative
        # shutdown.
        #
        # Skip this check if the status sidecar already exists — the execute
        # script has completed its primary job (writing the sidecar) and is just
        # doing cleanup (killing the sampler, deleting temp files).  Killing it
        # now would leave temp files behind and trigger a false auto-fix.
        status_path = _status_sidecar_path_from_plan(worker.task_plan_path)
        if status_path.is_file():
            return

        stale_elapsed = now - last_output_at
        if stale_elapsed >= _STALE_EXECUTE_SECONDS:
            for suffix in (".claude_output", ".codex_output"):
                ndjson_path = worker.task_plan_path.with_name(worker.task_id + suffix)
                if ndjson_path.is_file():
                    try:
                        content = ndjson_path.read_text(encoding="utf-8", errors="replace")
                        if '"type": "result"' in content or '"type":"result"' in content:
                            self._terminate_worker(
                                worker,
                                timeout_kind="stale_execute",
                                reason=(
                                    f"Worker {worker.slot_number} (task {worker.task_id}): "
                                    f"Killed — AI process exited but execute script still alive "
                                    f"after {_format_seconds(stale_elapsed)}"
                                ),
                                now=now,
                            )
                            return
                    except OSError:
                        pass

        if worker.task_max > 0 and now - started_at >= worker.task_max:
            self._terminate_worker(
                worker,
                timeout_kind="task_max",
                reason=f"Worker {worker.slot_number} (task {worker.task_id}): Killed — exceeded max task time {_format_seconds(worker.task_max)}",
                now=now,
            )

    def _emit_warning_alerts(self, worker: _ActiveWorker, now: float) -> None:
        idle_elapsed = now - worker.last_output_at
        if (
            worker.task_idle > 0
            and not worker.idle_warning_emitted
            and idle_elapsed >= worker.task_idle * 0.8
        ):
            worker.idle_warning_emitted = True
            self._queue_alert(
                worker,
                severity="warning",
                message=(
                    f"Worker {worker.slot_number} (task {worker.task_id}): "
                    f"No output for {_format_seconds(idle_elapsed)} "
                    f"(timeout at {_format_seconds(worker.task_idle)})"
                ),
            )

        task_elapsed = now - worker.started_at
        if (
            worker.task_max > 0
            and not worker.task_max_warning_emitted
            and task_elapsed >= worker.task_max * 0.8
        ):
            worker.task_max_warning_emitted = True
            self._queue_alert(
                worker,
                severity="warning",
                message=(
                    f"Worker {worker.slot_number} (task {worker.task_id}): "
                    f"Task runtime {_format_seconds(task_elapsed)} is nearing "
                    f"the max limit {_format_seconds(worker.task_max)}"
                ),
            )

    def _queue_alert(self, worker: _ActiveWorker, *, severity: str, message: str) -> None:
        with worker.lock:
            worker.pending_alerts.append(
                WorkerAlert(
                    severity=severity,
                    task_id=worker.task_id,
                    worker_slot=worker.slot_number,
                    message=message,
                )
            )

    def _terminate_worker(
        self,
        worker: _ActiveWorker,
        *,
        timeout_kind: str,
        reason: str,
        now: float,
    ) -> None:
        # Acquire lock before writing timeout state fields. F-4 fix.
        with worker.lock:
            worker.timed_out = True
            worker.timeout_kind = timeout_kind
            worker.failure_reason = reason
            worker.terminate_sent_at = now
        # Queue error alert so the frontend banner escalates from warning to error
        self._queue_alert(worker, severity="error", message=reason)
        worker.process.terminate()

    def _finalize_worker(self, worker: _ActiveWorker) -> None:
        # Close stdout/stderr pipes first so any blocked readline() in the reader
        # threads returns "" immediately, allowing them to exit cleanly. F-9 fix.
        if worker.process.stdout:
            worker.process.stdout.close()
        if worker.process.stderr:
            worker.process.stderr.close()
        for reader in worker.readers:
            reader.join(timeout=5.0)
        worker.log_handle.flush()
        worker.log_handle.close()
        if worker.task_log_handle is not None:
            worker.task_log_handle.flush()
            worker.task_log_handle.close()
        worker.finalized = True

    def _start_reader_threads(self, worker: _ActiveWorker) -> None:
        assert worker.process.stdout is not None
        assert worker.process.stderr is not None
        for stream in (worker.process.stdout, worker.process.stderr):
            reader = threading.Thread(target=self._read_stream, args=(worker, stream), daemon=True)
            reader.start()
            worker.readers.append(reader)

    def _read_stream(self, worker: _ActiveWorker, stream: TextIO) -> None:
        try:
            for raw_line in iter(stream.readline, ""):
                line = raw_line.rstrip("\r\n")
                now = self._clock()
                detail_content = _extract_detail_content(line, worker.task_id, worker.progress_format)
                with worker.lock:
                    if detail_content is None:
                        # Non-detail line — always resets idle timer
                        worker.last_output_at = now
                    elif detail_content != worker.last_detail_content:
                        # Detail line with NEW content — real progress, reset timer
                        worker.last_output_at = now
                        worker.last_detail_content = detail_content
                    # else: identical detail content — true heartbeat, do NOT reset
                    worker.pending_lines.append(line)
                    try:
                        worker.log_handle.write(raw_line)
                        worker.log_handle.flush()
                        if worker.task_log_handle is not None:
                            worker.task_log_handle.write(raw_line)
                            worker.task_log_handle.flush()
                    except ValueError:
                        # Log handle was closed by _finalize_worker before this
                        # thread finished — discard the trailing output. F-18 fix.
                        break
                    worker.progress = _updated_progress_state(
                        worker.progress,
                        line,
                        worker.task_id,
                        worker.progress_format,
                    )
        except (ValueError, OSError):
            # Stream was closed by _finalize_worker or the subprocess exited
            # while readline was blocked. Exit the reader thread gracefully.
            _logger.debug(
                "Worker %s: reader thread exiting — stream closed",
                worker.task_id,
            )
        finally:
            stream.close()

    def snapshot_idle_state(self) -> dict[int, dict[str, float | str]]:
        """Return active-worker idle state using the same monotonic clock as timeout enforcement."""
        result = {}
        for slot, worker in self._workers.items():
            with worker.lock:
                result[slot] = {
                    "task_id": worker.task_id,
                    "last_output_at": worker.last_output_at,
                    "task_idle": worker.task_idle,
                    "started_at": worker.started_at,
                }
        return result

    def _get_worker(self, slot_number: int) -> _ActiveWorker:
        try:
            return self._workers[slot_number]
        except KeyError as exc:
            raise WorkerManagerError(f"unknown worker slot {slot_number}") from exc


def _task_id_from_path(task_plan_path: Path) -> str:
    return task_plan_path.name.removesuffix(".plan.md")


def _status_sidecar_path_from_plan(task_plan_path: Path) -> Path:
    plan_name = task_plan_path.name
    if plan_name.endswith(".plan.md"):
        return task_plan_path.with_name(plan_name.removesuffix(".plan.md") + ".status")
    return task_plan_path.with_suffix(".status")


def _extract_detail_content(line: str, task_id: str, progress_format: str) -> str | None:
    """Return the detail message if *line* is a progress detail marker for the given task, else None.

    Detail lines are emitted by the background sampler. If the content is
    unchanged from the previous call, the idle timer should NOT reset (true
    heartbeat). If the content has changed, it represents real progress and
    the idle timer MUST reset. Non-detail lines always reset the idle timer.
    """
    # Quick prefix check to avoid parse overhead on every line
    if not line.startswith(progress_format):
        return None
    try:
        update = parse_progress_line(line, progress_format=progress_format)
    except ArtifactParseError:
        return None
    if update.task_id == task_id and update.kind == "detail":
        return update.detail_message or ""
    return None


def _updated_progress_state(
    progress: WorkerProgressState,
    line: str,
    expected_task_id: str,
    progress_format: str,
) -> WorkerProgressState:
    try:
        update = parse_progress_line(line, progress_format=progress_format)
    except ArtifactParseError:
        return progress
    if update.task_id != expected_task_id:
        return progress

    if update.kind == "phase":
        return WorkerProgressState(
            task_id=update.task_id,
            phase_name=update.phase_name,
            phase_index=update.phase_index,
            phase_total=update.phase_total,
            detail_message=progress.detail_message,
        )
    return WorkerProgressState(
        task_id=update.task_id,
        phase_name=progress.phase_name,
        phase_index=progress.phase_index,
        phase_total=progress.phase_total,
        detail_message=update.detail_message,
    )


def _format_seconds(value: float) -> str:
    total = int(round(value))
    if total >= 60:
        minutes, seconds = divmod(total, 60)
        return f"{minutes}m {seconds}s"
    if value >= 10 or value.is_integer():
        return f"{total}s"
    return f"{value:.1f}s"
