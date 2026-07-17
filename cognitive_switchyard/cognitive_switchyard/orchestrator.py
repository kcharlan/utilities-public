from __future__ import annotations

import logging
import time
from functools import partial

_logger = logging.getLogger(__name__)
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from .agent_runtime import build_agent_runtime
from .hook_runner import HookNotFoundError, run_pack_hook, run_pack_preflight
from .models import BackendRuntimeEvent
from .models import (
    EffectiveSessionRuntimeConfig,
    FixerAttemptResult,
    OrchestratorResult,
    OrchestratorStartupFailure,
    PackManifest,
    PackPreflightResult,
    PersistedTask,
    build_effective_planner_count,
    build_effective_session_runtime_config,
)
from .parsers import ArtifactParseError, extract_commit_description, parse_progress_line, parse_task_plan
from .planning_runtime import _INTAKE_META_FILES, prepare_session_for_execution
from .recovery import recover_execution_session
from .scheduler import select_next_task
from .state import StateStore
from .verification_runtime import (
    build_task_failure_context,
    build_verification_failure_context,
    parse_test_summary,
    run_verification_command,
)
from .worker_manager import (
    WorkerManager,
    WorkerStatusSidecarError,
)


def execute_session(
    *,
    store: StateStore,
    session_id: str,
    pack_manifest: PackManifest,
    env: Mapping[str, str] | None = None,
    poll_interval: float = 0.1,
    kill_grace_period: float = 5.0,
    skip_preflight: bool = False,
    fixer_executor: Callable[..., FixerAttemptResult] | None = None,
    runtime_event_sink: Callable[[BackendRuntimeEvent], None] | None = None,
) -> OrchestratorResult:
    session = store.get_session(session_id)

    def _exec_output_callback(phase: str, line: str) -> None:
        if runtime_event_sink is None:
            return
        detail_prefix = "##DETAIL## "
        if line.startswith(detail_prefix):
            detail_text = line[len(detail_prefix):]
            _publish_runtime_event(
                runtime_event_sink,
                "progress_detail",
                session_id=session_id,
                data={
                    "worker_slot": -1,
                    "task_id": f"__phase_{phase}__",
                    "detail": detail_text,
                    "timestamp": _timestamp(),
                    "phase": phase,
                },
            )
            return
        _publish_runtime_event(
            runtime_event_sink,
            "log_line",
            session_id=session_id,
            data={
                "worker_slot": -1,
                "task_id": f"__phase_{phase}__",
                "line": line,
                "timestamp": _timestamp(),
                "phase": phase,
            },
        )

    fixer_executor = _resolve_default_fixer_executor(
        pack_manifest=pack_manifest,
        session_root=store.runtime_paths.session_paths(session_id).root,
        fixer_executor=fixer_executor,
        output_line_callback=_exec_output_callback,
    )
    effective_runtime_config = build_effective_session_runtime_config(
        session=session,
        pack_manifest=pack_manifest,
        default_poll_interval=poll_interval,
    )
    env = _merged_runtime_env(env, effective_runtime_config, pack_manifest=pack_manifest)
    if session.status not in {"created", "idle", "running", "paused", "verifying", "auto_fixing"}:
        raise ValueError(
            "Execution supports only 'created', 'idle', 'running', 'paused', 'verifying', or 'auto_fixing' sessions, "
            f"got {session.status!r}"
        )

    initial_status = session.status
    if initial_status in {"running", "paused", "verifying", "auto_fixing"}:
        if session.started_at is None:
            session = store.update_session_status(
                session_id,
                status=initial_status,
                started_at=_timestamp(),
            )
        recover_execution_session(
            store=store,
            session_id=session_id,
            pack_manifest=pack_manifest,
            env=env,
            kill_grace_period=kill_grace_period,
        )
        if initial_status == "paused":
            return OrchestratorResult(
                session_id=session_id,
                started=True,
                session_status="paused",
            )
        if initial_status in {"verifying", "auto_fixing"}:
            store.write_session_runtime_state(
                session_id,
                verification_pending=True,
                verification_reason=(
                    "recovery_replay"
                    if session.runtime_state.verification_reason is None
                    else session.runtime_state.verification_reason
                ),
            )
            _publish_state_update(runtime_event_sink, session_id)
    else:
        session = store.get_session(session_id)

    if not skip_preflight:
        preflight_result = _run_startup_preflight(
            store=store,
            session_id=session_id,
            pack_manifest=pack_manifest,
            env=env,
            started=(initial_status not in {"created", "idle"}),
        )
        if preflight_result is not None:
            return preflight_result

    if initial_status in {"created", "idle"}:
        runtime_state = store.get_session(session_id).runtime_state
        # Re-initialize run counters when this is a fresh start (run_started_at not yet set)
        # or when resuming from idle (a new run — previous run's run_started_at is stale).
        if runtime_state.run_started_at is None or initial_status == "idle":
            run_started_at = _timestamp()
            new_run_number = runtime_state.run_number + 1
            store.update_session_status(
                session_id,
                status="running",
                started_at=run_started_at if initial_status == "created" else None,
            )
            store.write_session_runtime_state(
                session_id,
                run_number=new_run_number,
                run_started_at=run_started_at,
                completed_since_verification=0,
                verification_pending=False,
                verification_reason=None,
                verification_started_at=None,
                auto_fix_context=None,
                auto_fix_task_id=None,
                auto_fix_attempt=0,
                last_fix_summary=None,
                dispatch_frozen=False,
                dispatch_frozen_reason=None,
            )
            event_msg = "Execution started." if initial_status == "created" else f"Run #{new_run_number} started."
            store.append_event(
                session_id,
                timestamp=run_started_at,
                event_type="session.running" if initial_status == "created" else "run.started",
                message=event_msg,
            )
        else:
            # Run was pre-started (e.g. set before the planning phase in start_session()
            # for a "created" session) — just transition status to "running", preserving
            # the original timestamp and run counters.
            store.update_session_status(session_id, status="running")
        session = store.get_session(session_id)

    done_count_at_run_start = len(store.list_done_tasks(session_id))
    manager = WorkerManager(
        default_task_idle=effective_runtime_config.task_idle,
        default_task_max=effective_runtime_config.task_max,
        kill_grace_period=kill_grace_period,
    )
    session_paths = store.runtime_paths.session_paths(session_id)
    session_started_at = session.started_at
    # Use monotonic clock for session timeout to avoid wall-clock drift (NTP, suspend/resume).
    # On restart, fall back to wall-clock elapsed since the original start timestamp.
    _session_monotonic_start = time.monotonic() - _elapsed_since_timestamp(session_started_at)

    while True:
        verified_this_iteration = False
        if (
            effective_runtime_config.session_max > 0
            and (time.monotonic() - _session_monotonic_start) >= effective_runtime_config.session_max
        ):
            return _abort_session_for_timeout(
                store=store,
                session_id=session_id,
                pack_manifest=pack_manifest,
                manager=manager,
                poll_interval=effective_runtime_config.poll_interval,
                session_timeout=effective_runtime_config.session_max,
                env=env,
                runtime_event_sink=runtime_event_sink,
            )

        _collect_finished_workers(
            store=store,
            session_id=session_id,
            pack_manifest=pack_manifest,
            effective_runtime_config=effective_runtime_config,
            manager=manager,
            env=env,
            fixer_executor=fixer_executor,
            runtime_event_sink=runtime_event_sink,
        )

        current_session = store.get_session(session_id)
        active_tasks = store.list_active_tasks(session_id)
        if current_session.status == "aborted":
            return _abort_session(
                store=store,
                session_id=session_id,
                pack_manifest=pack_manifest,
                manager=manager,
                poll_interval=poll_interval,
                reason="Session aborted by operator.",
                env=env,
            )
        if current_session.status == "paused":
            if active_tasks:
                time.sleep(effective_runtime_config.poll_interval)
                continue
            return OrchestratorResult(
                session_id=session_id,
                started=True,
                session_status="paused",
                blocked_tasks=tuple(task.task_id for task in store.list_blocked_tasks(session_id)),
            )

        ready_tasks = list(store.list_ready_tasks(session_id))
        blocked_tasks = store.list_blocked_tasks(session_id)
        done_tasks = store.list_done_tasks(session_id)

        if pack_manifest.verification.enabled:
            pending_runtime_state = store.get_session(session_id).runtime_state
            if (
                not pending_runtime_state.verification_pending
                and not pending_runtime_state.dispatch_frozen
                and effective_runtime_config.verification_interval > 0
            ):
                forward_count = (
                    pending_runtime_state.completed_since_verification + len(active_tasks)
                )
                if forward_count >= effective_runtime_config.verification_interval:
                    if (
                        pending_runtime_state.completed_since_verification
                        >= effective_runtime_config.verification_interval
                    ):
                        # Threshold already met by completed tasks — set verification_pending directly
                        store.write_session_runtime_state(
                            session_id,
                            verification_pending=True,
                            verification_reason="interval",
                            dispatch_frozen=True,
                            dispatch_frozen_reason="interval_threshold",
                        )
                    else:
                        # Threshold met only when counting active tasks — freeze dispatch,
                        # but don't set verification_pending yet (tasks still running)
                        store.write_session_runtime_state(
                            session_id,
                            dispatch_frozen=True,
                            dispatch_frozen_reason="interval_threshold",
                        )
                    _publish_state_update(runtime_event_sink, session_id)
                    pending_runtime_state = store.get_session(session_id).runtime_state

            if pending_runtime_state.verification_pending:
                if active_tasks:
                    time.sleep(effective_runtime_config.poll_interval)
                    continue
                verification_result = _run_pending_verification(
                    store=store,
                    session_id=session_id,
                    pack_manifest=pack_manifest,
                    effective_runtime_config=effective_runtime_config,
                    env=env,
                    fixer_executor=fixer_executor,
                    runtime_event_sink=runtime_event_sink,
                )
                if verification_result is not None:
                    return verification_result
                verified_this_iteration = True
                ready_tasks = list(store.list_ready_tasks(session_id))
                active_tasks = store.list_active_tasks(session_id)
                blocked_tasks = store.list_blocked_tasks(session_id)
                done_tasks = store.list_done_tasks(session_id)

        if not ready_tasks and not active_tasks:
            if blocked_tasks:
                return OrchestratorResult(
                    session_id=session_id,
                    started=True,
                    session_status=store.get_session(session_id).status,
                    blocked_tasks=tuple(task.task_id for task in blocked_tasks),
                )
            # Final verification: run once before declaring session complete,
            # even if the interval threshold hasn't been reached yet.
            # Skip if no tasks were completed during this run (avoids spurious
            # verification on new runs that find no new work to process).
            if pack_manifest.verification.enabled:
                final_runtime_state = store.get_session(session_id).runtime_state
                if not final_runtime_state.verification_pending and len(done_tasks) > done_count_at_run_start and not verified_this_iteration:
                    store.write_session_runtime_state(
                        session_id,
                        verification_pending=True,
                        verification_reason="final",
                    )
                    _publish_state_update(runtime_event_sink, session_id)
                    final_verification_result = _run_pending_verification(
                        store=store,
                        session_id=session_id,
                        pack_manifest=pack_manifest,
                        effective_runtime_config=effective_runtime_config,
                        env=env,
                        fixer_executor=fixer_executor,
                        runtime_event_sink=runtime_event_sink,
                    )
                    if final_verification_result is not None:
                        return final_verification_result
            idle_at = _timestamp()
            # Accumulate run duration into session total
            runtime_state = store.get_session(session_id).runtime_state
            run_seconds = _elapsed_since_timestamp(runtime_state.run_started_at) if runtime_state.run_started_at else 0
            new_accumulated = runtime_state.accumulated_elapsed_seconds + int(run_seconds)
            store.update_session_status(session_id, status="idle")
            store.write_session_runtime_state(
                session_id,
                accumulated_elapsed_seconds=new_accumulated,
                last_run_elapsed_seconds=max(1, int(run_seconds)),
            )
            store.append_event(
                session_id,
                timestamp=idle_at,
                event_type="run.completed",
                message=f"Run #{runtime_state.run_number} completed. Session idle — add more tickets or end session.",
            )
            _publish_state_update(runtime_event_sink, session_id)
            return OrchestratorResult(
                session_id=session_id,
                started=True,
                session_status="idle",
            )

        # Dispatch freeze gate: FTA task is running, or forward-looking interval threshold met.
        # When frozen but verification_pending is False, active tasks are still draining.
        # Once all active tasks have drained, promote to verification_pending so the
        # verification block above will run it on the next iteration.
        rt_state = store.get_session(session_id).runtime_state
        if rt_state.dispatch_frozen and not rt_state.verification_pending:
            if not active_tasks:
                # All tasks drained — promote to verification_pending.
                store.write_session_runtime_state(
                    session_id,
                    verification_pending=True,
                    verification_reason=rt_state.dispatch_frozen_reason or "dispatch_freeze",
                )
                _publish_state_update(runtime_event_sink, session_id)
                # Fall through to next iteration where verification_pending block handles it
            time.sleep(effective_runtime_config.poll_interval)
            continue

        active_ids = {task.task_id for task in active_tasks}
        done_ids = {task.task_id for task in done_tasks}
        available_slots = _available_slots(effective_runtime_config.worker_count, active_tasks)

        for slot_number in available_slots:
            _publish_worker_runtime_events(
                runtime_event_sink=runtime_event_sink,
                session_id=session_id,
                pack_manifest=pack_manifest,
                snapshot=None,
            )
            next_task = select_next_task(
                ready_tasks,
                completed_task_ids=done_ids,
                active_task_ids=active_ids,
            )
            if next_task is None:
                break
            # FTA alignment: delay FTA tasks until dispatching them would align
            # with the verification interval (projected == interval).  This
            # makes the FTA verification double as the interval verification.
            # Only defer when there are enough remaining tasks to actually
            # reach the interval; otherwise the FTA fires at its natural position.
            if (
                next_task.full_test_after
                and pack_manifest.verification.enabled
                and effective_runtime_config.verification_interval > 0
            ):
                current_rt = store.get_session(session_id).runtime_state
                projected = (
                    current_rt.completed_since_verification
                    + len(active_ids)
                    + 1  # this task, if dispatched
                )
                all_task_count = len(store.list_all_tasks(session_id))
                remaining = all_task_count - len(done_ids) - len(active_ids)
                can_reach_interval = (
                    current_rt.completed_since_verification + remaining
                    >= effective_runtime_config.verification_interval
                )
                if (
                    projected < effective_runtime_config.verification_interval
                    and can_reach_interval
                ):
                    # Not aligned yet — try to find a non-FTA task instead.
                    non_fta_task = select_next_task(
                        ready_tasks,
                        completed_task_ids=done_ids,
                        active_task_ids=active_ids,
                        exclude_fta=True,
                    )
                    if non_fta_task is not None:
                        next_task = non_fta_task
            ready_tasks = [task for task in ready_tasks if task.task_id != next_task.task_id]
            # Per-task forward-looking interval check: prevent over-dispatching within a
            # single iteration when dispatching multiple slots simultaneously.
            # FTA tasks always dispatch (they set their own freeze on success).
            if (
                pack_manifest.verification.enabled
                and effective_runtime_config.verification_interval > 0
                and not next_task.full_test_after
            ):
                current_rt = store.get_session(session_id).runtime_state
                per_task_forward_count = (
                    current_rt.completed_since_verification
                    + len(active_ids)
                    + 1  # this task, if dispatched
                )
                if per_task_forward_count > effective_runtime_config.verification_interval:
                    store.write_session_runtime_state(
                        session_id,
                        dispatch_frozen=True,
                        dispatch_frozen_reason="interval_threshold",
                    )
                    _publish_state_update(runtime_event_sink, session_id)
                    break
            workspace_path = _prepare_workspace(
                pack_manifest=pack_manifest,
                session_paths=session_paths,
                slot_number=slot_number,
                task=next_task,
                env=env,
            )
            if workspace_path is None:
                blocked_task = store.project_task(
                    session_id,
                    next_task.task_id,
                    status="blocked",
                    timestamp=_timestamp(),
                )
                active_ids.discard(blocked_task.task_id)
                store.append_event(
                    session_id,
                    timestamp=_timestamp(),
                    event_type="task.blocked",
                    task_id=blocked_task.task_id,
                    message=f"Task {blocked_task.task_id} ({blocked_task.title}) blocked: isolation setup failed.",
                )
                _publish_task_status_change(
                    runtime_event_sink,
                    session_id=session_id,
                    task_id=blocked_task.task_id,
                    old_status=next_task.status,
                    new_status="blocked",
                    worker_slot=None,
                    notes=f"Task {blocked_task.task_id} ({blocked_task.title}) blocked: isolation setup failed.",
                )
                _publish_state_update(runtime_event_sink, session_id)
                continue

            started_at = _timestamp()
            active_task = store.project_task(
                session_id,
                next_task.task_id,
                status="active",
                worker_slot=slot_number,
                timestamp=started_at,
            )
            try:
                pid = manager.dispatch(
                    slot_number=slot_number,
                    pack_manifest=pack_manifest,
                    task_plan_path=active_task.plan_path,
                    workspace_path=workspace_path,
                    log_path=session_paths.worker_log(slot_number),
                    task_log_path=session_paths.task_log(active_task.task_id),
                    env=env,
                )
            except Exception as exc:
                _logger.exception(
                    "Dispatch failed for task %s slot %d: %s",
                    next_task.task_id,
                    slot_number,
                    exc,
                )
                store.project_task(
                    session_id,
                    next_task.task_id,
                    status="blocked",
                    timestamp=_timestamp(),
                )
                store.append_event(
                    session_id,
                    timestamp=_timestamp(),
                    event_type="task.blocked",
                    task_id=next_task.task_id,
                    message=f"Task {next_task.task_id} ({next_task.title}) blocked: dispatch failed: {exc}",
                )
                _publish_task_status_change(
                    runtime_event_sink,
                    session_id=session_id,
                    task_id=next_task.task_id,
                    old_status="active",
                    new_status="blocked",
                    worker_slot=None,
                    notes=f"Task {next_task.task_id} ({next_task.title}) blocked: dispatch failed: {exc}",
                    started_at=started_at,
                )
                _publish_state_update(runtime_event_sink, session_id)
                continue
            store.write_worker_recovery_metadata(
                session_id,
                slot_number=slot_number,
                task_id=active_task.task_id,
                workspace_path=workspace_path,
                pid=pid,
            )
            active_ids.add(active_task.task_id)
            store.append_event(
                session_id,
                timestamp=started_at,
                event_type="task.dispatched",
                task_id=active_task.task_id,
                message=f"Dispatched task {active_task.task_id} ({active_task.title}) to worker slot {slot_number}.",
            )
            _publish_task_status_change(
                runtime_event_sink,
                session_id=session_id,
                task_id=active_task.task_id,
                old_status=next_task.status,
                new_status="active",
                worker_slot=slot_number,
                notes=f"Dispatched task {active_task.task_id} ({active_task.title}) to worker slot {slot_number}.",
                started_at=started_at,
            )
            _publish_state_update(runtime_event_sink, session_id)
            # FTA freeze: once an FTA task is dispatched, stop dispatching further tasks.
            # The freeze gate at the top of the loop (dispatch_frozen=True,
            # verification_pending=False) will prevent new dispatches until the FTA task
            # completes and verification passes.
            if active_task.full_test_after:
                store.write_session_runtime_state(
                    session_id,
                    dispatch_frozen=True,
                    dispatch_frozen_reason="fta_task_active",
                )
                _publish_state_update(runtime_event_sink, session_id)
                break

        # Deadlock detection: ready tasks exist but none are eligible and no
        # workers are running, so nothing can ever make progress.
        active_tasks_now = store.list_active_tasks(session_id)
        if ready_tasks and not active_tasks_now:
            # Re-check whether any ready task is actually eligible.
            done_ids_now = {t.task_id for t in store.list_done_tasks(session_id)}
            active_ids_now: set[str] = set()
            eligible = select_next_task(
                ready_tasks,
                completed_task_ids=done_ids_now,
                active_task_ids=active_ids_now,
            )
            if eligible is None:
                blocked_dep_details = ", ".join(
                    f"{t.task_id} (waiting on {', '.join(d for d in t.depends_on if d not in done_ids_now)})"
                    for t in ready_tasks
                    if any(d not in done_ids_now for d in t.depends_on)
                )
                message = f"Deadlock: ready tasks exist but none are eligible and no workers are active. Blocked: {blocked_dep_details or 'anti-affinity or unknown'}"
                store.append_event(
                    session_id,
                    timestamp=_timestamp(),
                    event_type="session.deadlock",
                    message=message,
                )
                return OrchestratorResult(
                    session_id=session_id,
                    started=True,
                    session_status=store.get_session(session_id).status,
                    blocked_tasks=tuple(t.task_id for t in ready_tasks),
                )

        time.sleep(effective_runtime_config.poll_interval)


def start_session(
    *,
    store: StateStore,
    session_id: str,
    pack_manifest: PackManifest,
    planner_agent=None,
    resolver_agent=None,
    env: Mapping[str, str] | None = None,
    poll_interval: float = 0.1,
    kill_grace_period: float = 5.0,
    fixer_executor: Callable[..., FixerAttemptResult] | None = None,
    runtime_event_sink: Callable[[BackendRuntimeEvent], None] | None = None,
) -> OrchestratorResult:
    session = store.get_session(session_id)
    planner_agent, resolver_agent, fixer_executor = _resolve_default_agent_callables(
        pack_manifest=pack_manifest,
        session_root=store.runtime_paths.session_paths(session_id).root,
        planner_agent=planner_agent,
        resolver_agent=resolver_agent,
        fixer_executor=fixer_executor,
        runtime_event_sink=runtime_event_sink,
        session_id=session_id,
    )
    if session.status in {"running", "paused", "verifying", "auto_fixing"}:
        return execute_session(
            store=store,
            session_id=session_id,
            pack_manifest=pack_manifest,
            env=env,
            poll_interval=poll_interval,
            kill_grace_period=kill_grace_period,
            fixer_executor=fixer_executor,
            runtime_event_sink=runtime_event_sink,
        )
    if session.status not in {"created", "idle", "planning", "resolving"}:
        raise ValueError(
            "Start supports only 'created', 'idle', 'planning', 'resolving', 'running', 'paused', "
            "'verifying', or 'auto_fixing' sessions, "
            f"got {session.status!r}"
        )

    # Merge session config environment into env so planning/resolution phases
    # receive COGNITIVE_SWITCHYARD_REPO_ROOT and other session-level vars.
    effective_runtime_config = build_effective_session_runtime_config(
        session=session,
        pack_manifest=pack_manifest,
        default_poll_interval=poll_interval,
    )
    env = _merged_runtime_env(env, effective_runtime_config, pack_manifest=pack_manifest)

    preflight_result = _run_startup_preflight(
        store=store,
        session_id=session_id,
        pack_manifest=pack_manifest,
        env=env,
        started=False,
    )
    if preflight_result is not None:
        return preflight_result

    # Set run_started_at and run_number BEFORE planning begins so that timers
    # are visible from the first second of the run (during planning/resolving).
    session = store.get_session(session_id)
    if session.status == "created":
        run_started_at = _timestamp()
        runtime_state = session.runtime_state
        new_run_number = runtime_state.run_number + 1
        store.update_session_status(
            session_id,
            status=session.status,  # keep "created" — planning_runtime will change it
            started_at=run_started_at,
        )
        store.write_session_runtime_state(
            session_id,
            run_number=new_run_number,
            run_started_at=run_started_at,
            completed_since_verification=0,
        )
        store.append_event(
            session_id,
            timestamp=run_started_at,
            event_type="run.started",
            message=f"Run #{new_run_number} started.",
        )
        session = store.get_session(session_id)  # refresh after update
    elif session.status == "idle":
        # Check whether there are new intake files worth planning.
        session_paths = store.runtime_paths.session_paths(session_id)
        has_new_intake = any(
            p.suffix == ".md" and p.name not in _INTAKE_META_FILES
            for p in session_paths.intake.iterdir()
        ) if session_paths.intake.is_dir() else False

        has_ready = any(session_paths.ready.glob("*.plan.md")) if session_paths.ready.is_dir() else False
        has_blocked = any(session_paths.blocked.glob("*.plan.md")) if session_paths.blocked.is_dir() else False

        if not has_new_intake and not has_ready and not has_blocked:
            return OrchestratorResult(
                session_id=session_id,
                started=False,
                session_status="idle",
            )

        run_started_at = _timestamp()
        runtime_state = session.runtime_state
        new_run_number = runtime_state.run_number + 1
        store.write_session_runtime_state(
            session_id,
            run_number=new_run_number,
            run_started_at=run_started_at,
            completed_since_verification=0,
        )
        store.append_event(
            session_id,
            timestamp=run_started_at,
            event_type="run.started",
            message=f"Run #{new_run_number} started.",
        )
        store.update_session_status(session_id, status="created")
        session = store.get_session(session_id)  # refresh after update

    def _on_preparation_status_change(status: str) -> None:
        if runtime_event_sink is not None:
            runtime_event_sink(BackendRuntimeEvent(
                message_type="preparation_status",
                session_id=session_id,
                data={"type": "preparation_status", "status": status},
            ))

    def _on_pipeline_event(event_type: str, detail: dict) -> None:
        if runtime_event_sink is not None:
            runtime_event_sink(BackendRuntimeEvent(
                message_type="pipeline_event",
                session_id=session_id,
                data={"type": "pipeline_event", "event": event_type, **detail},
            ))
        # Persist to event store so it appears in recent_events
        store.append_event(
            session_id,
            timestamp=_timestamp(),
            event_type=event_type,
            message=_format_pipeline_event_message(event_type, detail),
        )

    preparation = prepare_session_for_execution(
        store=store,
        session_id=session_id,
        pack_manifest=pack_manifest,
        planner_agent=planner_agent,
        resolver_agent=resolver_agent,
        effective_planner_count=build_effective_planner_count(
            session=session,
            pack_manifest=pack_manifest,
        ),
        env=dict(env) if env is not None else None,
        on_status_change=_on_preparation_status_change,
        on_pipeline_event=_on_pipeline_event,
    )
    # Resolution conflicts with no ready tasks → cannot proceed
    if preparation.resolution_conflicts and not preparation.ready_task_ids:
        return OrchestratorResult(
            session_id=session_id,
            started=False,
            session_status=store.get_session(session_id).status,
            review_tasks=preparation.review_task_ids,
            resolution_conflicts=preparation.resolution_conflicts,
        )
    # No ready tasks at all (e.g. all items went to review)
    if not preparation.ready_task_ids:
        return OrchestratorResult(
            session_id=session_id,
            started=False,
            session_status=store.get_session(session_id).status,
            review_tasks=preparation.review_task_ids,
        )
    # Ready tasks exist — execute them (review items stay parked in review/)
    result = execute_session(
        store=store,
        session_id=session_id,
        pack_manifest=pack_manifest,
        env=env,
        poll_interval=poll_interval,
        kill_grace_period=kill_grace_period,
        skip_preflight=True,
        fixer_executor=fixer_executor,
        runtime_event_sink=runtime_event_sink,
    )
    # Carry through review info so callers know some items were parked
    if preparation.review_task_ids:
        return OrchestratorResult(
            session_id=result.session_id,
            started=result.started,
            session_status=result.session_status,
            blocked_tasks=result.blocked_tasks,
            review_tasks=preparation.review_task_ids,
            resolution_conflicts=result.resolution_conflicts,
            startup_failure=result.startup_failure,
        )
    return result


def run_session_preflight(
    *,
    store: StateStore,
    session_id: str,
    pack_manifest: PackManifest,
    env: Mapping[str, str] | None = None,
) -> PackPreflightResult:
    store.get_session(session_id)
    return run_pack_preflight(
        pack_manifest,
        runtime_paths=store.runtime_paths,
        env=env,
    )


def _resolve_default_agent_callables(
    *,
    pack_manifest: PackManifest,
    session_root: Path,
    planner_agent,
    resolver_agent,
    fixer_executor: Callable[..., FixerAttemptResult] | None,
    runtime_event_sink: Callable[[BackendRuntimeEvent], None] | None = None,
    session_id: str | None = None,
):
    runtimes: dict[str, Any] = {}

    def _agent_output_callback(phase: str, line: str) -> None:
        if runtime_event_sink is None or session_id is None:
            return
        # Per-planner task IDs are already prefixed with __planner_; other phases
        # use the generic __phase_{phase}__ convention.
        if phase.startswith("__"):
            task_id = phase
            phase_label = "planning" if phase.startswith("__planner_") else phase.strip("_")
        else:
            task_id = f"__phase_{phase}__"
            phase_label = phase

        detail_prefix = "##DETAIL## "
        if line.startswith(detail_prefix):
            detail_text = line[len(detail_prefix):]
            _publish_runtime_event(
                runtime_event_sink,
                "progress_detail",
                session_id=session_id,
                data={
                    "worker_slot": -1,
                    "task_id": task_id,
                    "detail": detail_text,
                    "timestamp": _timestamp(),
                    "phase": phase_label,
                },
            )
            return

        _publish_runtime_event(
            runtime_event_sink,
            "log_line",
            session_id=session_id,
            data={
                "worker_slot": -1,
                "task_id": task_id,
                "line": line,
                "timestamp": _timestamp(),
                "phase": phase_label,
            },
        )

    def runtime_instance(runtime_kind: str):
        runtime = runtimes.get(runtime_kind)
        if runtime is None:
            runtime = build_agent_runtime(
                runtime_kind,
                output_line_callback=_agent_output_callback,
            )
            runtimes[runtime_kind] = runtime
        return runtime

    if (
        planner_agent is None
        and pack_manifest.phases.planning.enabled
        and pack_manifest.phases.planning.executor == "agent"
    ):
        planner_runtime = runtime_instance(pack_manifest.phases.planning.runtime)
        planner_agent = partial(
            planner_runtime.planner_agent,
            reasoning_effort=pack_manifest.phases.planning.reasoning_effort,
        )

    if (
        resolver_agent is None
        and pack_manifest.phases.resolution.enabled
        and pack_manifest.phases.resolution.executor == "agent"
    ):
        resolver_runtime = runtime_instance(pack_manifest.phases.resolution.runtime)
        resolver_agent = partial(
            resolver_runtime.resolver_agent,
            reasoning_effort=pack_manifest.phases.resolution.reasoning_effort,
        )

    fixer_executor = _resolve_default_fixer_executor(
        pack_manifest=pack_manifest,
        session_root=session_root,
        fixer_executor=fixer_executor,
        runtime=runtimes.get(pack_manifest.auto_fix.runtime),
        runtime_instance=runtime_instance,
    )
    return planner_agent, resolver_agent, fixer_executor


def _resolve_default_fixer_executor(
    *,
    pack_manifest: PackManifest,
    session_root: Path,
    fixer_executor: Callable[..., FixerAttemptResult] | None,
    runtime=None,
    runtime_instance=None,
    output_line_callback=None,
) -> Callable[..., FixerAttemptResult] | None:
    if fixer_executor is not None or not pack_manifest.auto_fix.enabled:
        return fixer_executor
    if pack_manifest.auto_fix.model is None or pack_manifest.auto_fix.prompt is None:
        return fixer_executor
    runtime = runtime or (
        runtime_instance(pack_manifest.auto_fix.runtime)
        if runtime_instance is not None
        else build_agent_runtime(
            pack_manifest.auto_fix.runtime,
            output_line_callback=output_line_callback,
        )
    )
    return partial(
        runtime.fixer_executor,
        model=pack_manifest.auto_fix.model,
        reasoning_effort=pack_manifest.auto_fix.reasoning_effort,
        prompt_path=pack_manifest.auto_fix.prompt,
        session_root=session_root,
    )


def _collect_finished_workers(
    *,
    store: StateStore,
    session_id: str,
    pack_manifest: PackManifest,
    effective_runtime_config: EffectiveSessionRuntimeConfig,
    manager: WorkerManager,
    env: Mapping[str, str] | None,
    fixer_executor: Callable[..., FixerAttemptResult] | None,
    runtime_event_sink: Callable[[BackendRuntimeEvent], None] | None,
) -> None:
    for slot_number in manager.active_slot_numbers():
        try:
            _collect_single_worker(
                store=store,
                session_id=session_id,
                pack_manifest=pack_manifest,
                effective_runtime_config=effective_runtime_config,
                manager=manager,
                slot_number=slot_number,
                env=env,
                fixer_executor=fixer_executor,
                runtime_event_sink=runtime_event_sink,
            )
        except Exception as exc:
            _logger.error(
                "Unhandled error collecting worker slot %d in session %s: %s",
                slot_number, session_id, exc,
            )
            # Try to mark the task as blocked so the slot is freed.
            try:
                snapshot = manager.poll(slot_number)
                if snapshot.task_id:
                    active_task = store.get_task(session_id, snapshot.task_id)
                    _finalize_blocked_task(
                        store=store,
                        session_id=session_id,
                        pack_manifest=pack_manifest,
                        active_task=active_task,
                        slot_number=slot_number,
                        workspace_path=snapshot.workspace_path,
                        reason=f"Worker collection crashed: {exc}",
                        env=env,
                        runtime_event_sink=runtime_event_sink,
                    )
            except Exception as inner_exc:
                _logger.error(
                    "Failed to recover slot %d after collection crash: %s",
                    slot_number, inner_exc,
                )


def _collect_single_worker(
    *,
    store: StateStore,
    session_id: str,
    pack_manifest: PackManifest,
    effective_runtime_config: EffectiveSessionRuntimeConfig,
    manager: WorkerManager,
    slot_number: int,
    env: Mapping[str, str] | None,
    fixer_executor: Callable[..., FixerAttemptResult] | None,
    runtime_event_sink: Callable[[BackendRuntimeEvent], None] | None,
) -> None:
        snapshot = manager.poll(slot_number)
        _publish_worker_runtime_events(
            runtime_event_sink=runtime_event_sink,
            session_id=session_id,
            pack_manifest=pack_manifest,
            snapshot=snapshot,
        )
        if not snapshot.is_finished:
            return
        active_task = store.get_task(session_id, snapshot.task_id)
        try:
            result = manager.collect(slot_number)
        except WorkerStatusSidecarError as exc:
            _handle_failed_task(
                store=store,
                session_id=session_id,
                pack_manifest=pack_manifest,
                effective_runtime_config=effective_runtime_config,
                active_task=active_task,
                slot_number=slot_number,
                workspace_path=snapshot.workspace_path,
                reason=str(exc),
                log_path=snapshot.log_path,
                status_path=None,
                env=env,
                fixer_executor=fixer_executor,
                runtime_event_sink=runtime_event_sink,
            )
            return

        if result.timed_out:
            _handle_failed_task(
                store=store,
                session_id=session_id,
                pack_manifest=pack_manifest,
                effective_runtime_config=effective_runtime_config,
                active_task=active_task,
                slot_number=slot_number,
                workspace_path=result.workspace_path,
                reason=result.failure_reason or "Task timed out.",
                log_path=result.log_path,
                status_path=result.status_path,
                env=env,
                fixer_executor=fixer_executor,
                runtime_event_sink=runtime_event_sink,
                failure_kind="timeout",
            )
            return

        if result.status is None or result.status.status != "done":
            blocked_reason = (
                result.status.blocked_reason
                if result.status is not None and result.status.blocked_reason
                else f"Worker exited with status {result.exit_code}."
            )
            _handle_failed_task(
                store=store,
                session_id=session_id,
                pack_manifest=pack_manifest,
                effective_runtime_config=effective_runtime_config,
                active_task=active_task,
                slot_number=slot_number,
                workspace_path=result.workspace_path,
                reason=blocked_reason,
                log_path=result.log_path,
                status_path=result.status_path,
                env=env,
                fixer_executor=fixer_executor,
                runtime_event_sink=runtime_event_sink,
            )
            return

        if not _run_isolate_end(
            pack_manifest=pack_manifest,
            slot_number=slot_number,
            task_id=active_task.task_id,
            workspace_path=result.workspace_path,
            final_status="done",
            plan_path=active_task.plan_path,
            env=env,
        ):
            _finalize_blocked_task(
                store=store,
                session_id=session_id,
                pack_manifest=pack_manifest,
                active_task=active_task,
                slot_number=slot_number,
                workspace_path=result.workspace_path,
                reason="Isolation teardown failed.",
                env=env,
                runtime_event_sink=runtime_event_sink,
            )
            return

        completed_at = _timestamp()
        previous_status = active_task.status
        store.project_task(
            session_id,
            active_task.task_id,
            status="done",
            timestamp=completed_at,
        )
        store.clear_worker_recovery_metadata(session_id, slot_number=slot_number)
        if pack_manifest.verification.enabled:
            current_runtime_state = store.get_session(session_id).runtime_state
            store.write_session_runtime_state(
                session_id,
                completed_since_verification=current_runtime_state.completed_since_verification + 1,
                verification_pending=(
                    active_task.full_test_after or current_runtime_state.verification_pending
                ),
                verification_reason=(
                    "full_test_after"
                    if active_task.full_test_after
                    else current_runtime_state.verification_reason
                ),
            )
        store.append_event(
            session_id,
            timestamp=completed_at,
            event_type="task.completed",
            task_id=active_task.task_id,
            message=f"Task {active_task.task_id} ({active_task.title}) completed successfully.",
        )
        _publish_task_status_change(
            runtime_event_sink,
            session_id=session_id,
            task_id=active_task.task_id,
            old_status=previous_status,
            new_status="done",
            worker_slot=slot_number,
            notes=f"Task {active_task.task_id} ({active_task.title}) completed successfully.",
            elapsed=_task_elapsed(active_task.started_at, completed_at),
            started_at=active_task.started_at,
            completed_at=completed_at,
        )
        _publish_state_update(runtime_event_sink, session_id)


def _handle_failed_task(
    *,
    store: StateStore,
    session_id: str,
    pack_manifest: PackManifest,
    effective_runtime_config: EffectiveSessionRuntimeConfig,
    active_task: PersistedTask,
    slot_number: int,
    workspace_path: Path,
    reason: str,
    log_path: Path | None,
    status_path: Path | None,
    env: Mapping[str, str] | None,
    fixer_executor: Callable[..., FixerAttemptResult] | None,
    runtime_event_sink: Callable[[BackendRuntimeEvent], None] | None,
    failure_kind: str | None = None,
) -> None:
    if (
        effective_runtime_config.auto_fix_enabled
        and fixer_executor is not None
        and pack_manifest.verification.enabled
        and pack_manifest.verification.command
    ):
        # Do NOT call _run_isolate_end here — preserve the worktree so the
        # fixer can inspect/continue partial work (committed or staged changes).
        restored_task = store.project_task(session_id, active_task.task_id, status="ready")
        store.clear_worker_recovery_metadata(session_id, slot_number=slot_number)
        if _attempt_task_auto_fix(
            store=store,
            session_id=session_id,
            pack_manifest=pack_manifest,
            effective_runtime_config=effective_runtime_config,
            task=restored_task,
            log_path=log_path,
            status_path=status_path,
            env=env,
            fixer_executor=fixer_executor,
            runtime_event_sink=runtime_event_sink,
            failure_kind=failure_kind,
        ):
            # Auto-fix succeeded — tear down the worktree with "done" status.
            _run_isolate_end(
                pack_manifest=pack_manifest,
                slot_number=slot_number,
                task_id=active_task.task_id,
                workspace_path=workspace_path,
                final_status="done",
                plan_path=active_task.plan_path,
                env=env,
            )
            return
        # Auto-fix failed — tear down the worktree with "blocked" status,
        # then finalize (skip isolation end inside _finalize_blocked_task).
        _run_isolate_end(
            pack_manifest=pack_manifest,
            slot_number=slot_number,
            task_id=active_task.task_id,
            workspace_path=workspace_path,
            final_status="blocked",
            env=env,
        )
        _finalize_blocked_task(
            store=store,
            session_id=session_id,
            pack_manifest=pack_manifest,
            active_task=restored_task,
            slot_number=slot_number,
            workspace_path=workspace_path,
            reason=reason,
            run_isolation_end=False,
            env=env,
            runtime_event_sink=runtime_event_sink,
        )
        return
    _finalize_blocked_task(
        store=store,
        session_id=session_id,
        pack_manifest=pack_manifest,
        active_task=active_task,
        slot_number=slot_number,
        workspace_path=workspace_path,
        reason=reason,
        env=env,
        runtime_event_sink=runtime_event_sink,
    )


def _finalize_blocked_task(
    *,
    store: StateStore,
    session_id: str,
    pack_manifest: PackManifest,
    active_task: PersistedTask,
    slot_number: int,
    workspace_path: Path,
    reason: str,
    run_isolation_end: bool = True,
    env: Mapping[str, str] | None = None,
    runtime_event_sink: Callable[[BackendRuntimeEvent], None] | None = None,
) -> None:
    previous_status = active_task.status
    if run_isolation_end:
        _run_isolate_end(
            pack_manifest=pack_manifest,
            slot_number=slot_number,
            task_id=active_task.task_id,
            workspace_path=workspace_path,
            final_status="blocked",
            env=env,
        )
    blocked_at = _timestamp()
    store.project_task(
        session_id,
        active_task.task_id,
        status="blocked",
        timestamp=blocked_at,
    )
    store.clear_worker_recovery_metadata(session_id, slot_number=slot_number)
    store.append_event(
        session_id,
        timestamp=blocked_at,
        event_type="task.blocked",
        task_id=active_task.task_id,
        message=f"Task {active_task.task_id} ({active_task.title}) blocked: {reason}",
    )
    _publish_task_status_change(
        runtime_event_sink,
        session_id=session_id,
        task_id=active_task.task_id,
        old_status=previous_status,
        new_status="blocked",
        worker_slot=slot_number,
        notes=f"Task {active_task.task_id} ({active_task.title}) blocked: {reason}",
        elapsed=_task_elapsed(active_task.started_at, blocked_at),
        started_at=active_task.started_at,
        completed_at=blocked_at,
    )
    _publish_state_update(runtime_event_sink, session_id)


def _attempt_task_auto_fix(
    *,
    store: StateStore,
    session_id: str,
    pack_manifest: PackManifest,
    effective_runtime_config: EffectiveSessionRuntimeConfig,
    task: PersistedTask,
    log_path: Path | None,
    status_path: Path | None,
    env: Mapping[str, str] | None,
    fixer_executor: Callable[..., FixerAttemptResult],
    start_attempt: int = 1,
    previous_summary: str | None = None,
    runtime_event_sink: Callable[[BackendRuntimeEvent], None] | None = None,
    failure_kind: str | None = None,
) -> bool:
    session_paths = store.runtime_paths.session_paths(session_id)
    previous_verification_output: str | None = None
    for attempt in range(start_attempt, effective_runtime_config.auto_fix_max_attempts + 1):
        store.update_session_status(session_id, status="auto_fixing")
        store.write_session_runtime_state(
            session_id,
            verification_pending=True,
            verification_reason="task_auto_fix",
            auto_fix_context="task_failure",
            auto_fix_task_id=task.task_id,
            auto_fix_attempt=attempt,
            last_fix_summary=previous_summary,
        )
        store.append_event(
            session_id,
            timestamp=_timestamp(),
            event_type="session.auto_fix_started",
            task_id=task.task_id,
            message=f"Auto-fix attempt {attempt}/{effective_runtime_config.auto_fix_max_attempts} started for task {task.task_id}.",
        )
        _publish_state_update(runtime_event_sink, session_id)
        context = build_task_failure_context(
            session_id=session_id,
            task_id=task.task_id,
            attempt=attempt,
            plan_path=task.plan_path,
            status_path=status_path,
            worker_log_path=log_path,
            verify_log_path=session_paths.verify_log,
            previous_attempt_summary=previous_summary,
            previous_verification_output=previous_verification_output,
            failure_kind=failure_kind,
        )
        fix_result = fixer_executor(context)
        previous_summary = fix_result.summary or previous_summary
        store.write_session_runtime_state(
            session_id,
            last_fix_summary=previous_summary,
            auto_fix_attempt=attempt,
        )
        if not fix_result.success:
            continue
        verification = run_verification_command(
            session_root=session_paths.root,
            verify_log_path=session_paths.verify_log,
            command=pack_manifest.verification.command or "",
            env=env,
            output_line_callback=_make_verification_output_callback(runtime_event_sink, session_id),
        )
        if verification.ok:
            completed_at = _timestamp()
            previous_status = store.get_task(session_id, task.task_id).status
            store.project_task(session_id, task.task_id, status="done", timestamp=completed_at)
            store.append_event(
                session_id,
                timestamp=completed_at,
                event_type="task.completed",
                task_id=task.task_id,
                message=f"Task {task.task_id} ({task.title}) completed after auto-fix and verification pass.",
            )
            store.update_session_status(session_id, status="running")
            store.write_session_runtime_state(
                session_id,
                completed_since_verification=0,
                verification_pending=False,
                verification_reason=None,
                auto_fix_context=None,
                auto_fix_task_id=None,
                auto_fix_attempt=0,
                last_fix_summary=previous_summary,
                dispatch_frozen=False,
                dispatch_frozen_reason=None,
            )
            _publish_task_status_change(
                runtime_event_sink,
                session_id=session_id,
                task_id=task.task_id,
                old_status=previous_status,
                new_status="done",
                worker_slot=task.worker_slot,
                notes=f"Task {task.task_id} ({task.title}) completed after auto-fix and verification pass.",
                elapsed=_task_elapsed(task.started_at, completed_at),
                started_at=task.started_at,
                completed_at=completed_at,
            )
            _publish_state_update(runtime_event_sink, session_id)
            return True
        previous_verification_output = verification.output
        store.append_event(
            session_id,
            timestamp=_timestamp(),
            event_type="session.verification_failed",
            task_id=task.task_id,
            message=f"Verification failed after task auto-fix attempt.\n{verification.output}" if verification.output else "Verification failed after task auto-fix attempt.",
        )
    store.update_session_status(session_id, status="running")
    store.write_session_runtime_state(
        session_id,
        verification_pending=False,
        verification_reason=None,
        auto_fix_context=None,
        auto_fix_task_id=None,
        auto_fix_attempt=0,
        last_fix_summary=previous_summary,
        dispatch_frozen=False,
        dispatch_frozen_reason=None,
    )
    _publish_state_update(runtime_event_sink, session_id)
    return False


def _complete_task_after_auto_fix_verification(
    *,
    store: StateStore,
    session_id: str,
    task_id: str,
    runtime_event_sink: Callable[[BackendRuntimeEvent], None] | None = None,
) -> None:
    task = store.get_task(session_id, task_id)
    if task.status != "done":
        completed_at = _timestamp()
        store.project_task(session_id, task_id, status="done", timestamp=completed_at)
        store.append_event(
            session_id,
            timestamp=completed_at,
            event_type="task.completed",
            task_id=task_id,
            message=f"Task {task.task_id} ({task.title}) completed after auto-fix and verification pass.",
        )
        _publish_task_status_change(
            runtime_event_sink,
            session_id=session_id,
            task_id=task_id,
            old_status=task.status,
            new_status="done",
            worker_slot=task.worker_slot,
            notes=f"Task {task.task_id} ({task.title}) completed after auto-fix and verification pass.",
            elapsed=_task_elapsed(task.started_at, completed_at),
            started_at=task.started_at,
            completed_at=completed_at,
        )
        _publish_state_update(runtime_event_sink, session_id)


def _resume_recovered_task_auto_fix(
    *,
    store: StateStore,
    session_id: str,
    pack_manifest: PackManifest,
    effective_runtime_config: EffectiveSessionRuntimeConfig,
    env: Mapping[str, str] | None,
    fixer_executor: Callable[..., FixerAttemptResult],
    runtime_state,
    session_root: Path,
    runtime_event_sink: Callable[[BackendRuntimeEvent], None] | None = None,
) -> None:
    task = store.get_task(session_id, runtime_state.auto_fix_task_id)
    if _attempt_task_auto_fix(
        store=store,
        session_id=session_id,
        pack_manifest=pack_manifest,
        effective_runtime_config=effective_runtime_config,
        task=task,
        log_path=None,
        status_path=None,
        env=env,
        fixer_executor=fixer_executor,
        start_attempt=runtime_state.auto_fix_attempt + 1,
        previous_summary=runtime_state.last_fix_summary,
        runtime_event_sink=runtime_event_sink,
    ):
        return
    _finalize_blocked_task(
        store=store,
        session_id=session_id,
        pack_manifest=pack_manifest,
        active_task=store.get_task(session_id, runtime_state.auto_fix_task_id),
        slot_number=0,
        workspace_path=session_root,
        reason="Auto-fix retry budget exhausted after recovery.",
        run_isolation_end=False,
        env=env,
        runtime_event_sink=runtime_event_sink,
    )


def _run_pending_verification(
    *,
    store: StateStore,
    session_id: str,
    pack_manifest: PackManifest,
    effective_runtime_config: EffectiveSessionRuntimeConfig,
    env: Mapping[str, str] | None,
    fixer_executor: Callable[..., FixerAttemptResult] | None,
    runtime_event_sink: Callable[[BackendRuntimeEvent], None] | None,
) -> OrchestratorResult | None:
    session_paths = store.runtime_paths.session_paths(session_id)
    runtime_state = store.get_session(session_id).runtime_state
    verification_started_at = _timestamp()
    store.update_session_status(session_id, status="verifying")
    store.write_session_runtime_state(
        session_id,
        verification_started_at=verification_started_at,
        last_verification_test_summary=None,
        last_fix_summary=None,
        auto_fix_attempt=0,
    )
    store.append_event(
        session_id,
        timestamp=verification_started_at,
        event_type="session.verification_started",
        message="Verification started.",
    )
    _publish_state_update(runtime_event_sink, session_id)
    verification = run_verification_command(
        session_root=session_paths.root,
        verify_log_path=session_paths.verify_log,
        command=pack_manifest.verification.command or "",
        env=env,
        output_line_callback=_make_verification_output_callback(runtime_event_sink, session_id),
    )
    if verification.ok:
        if runtime_state.auto_fix_context == "task_failure" and runtime_state.auto_fix_task_id is not None:
            _complete_task_after_auto_fix_verification(
                store=store,
                session_id=session_id,
                task_id=runtime_state.auto_fix_task_id,
                runtime_event_sink=runtime_event_sink,
            )
        verified_at = _timestamp()
        test_summary = parse_test_summary(verification.output)
        store.update_session_status(session_id, status="running")
        store.write_session_runtime_state(
            session_id,
            completed_since_verification=0,
            verification_pending=False,
            verification_reason=None,
            verification_started_at=None,
            auto_fix_context=None,
            auto_fix_task_id=None,
            auto_fix_attempt=0,
            dispatch_frozen=False,
            dispatch_frozen_reason=None,
            last_verification_test_summary=test_summary,
        )
        store.append_event(
            session_id,
            timestamp=verified_at,
            event_type="session.verification_passed",
            message="Verification passed.",
        )
        _publish_state_update(runtime_event_sink, session_id)
        return None

    failed_at = _timestamp()
    store.append_event(
        session_id,
        timestamp=failed_at,
        event_type="session.verification_failed",
        message=f"Verification failed.\n{verification.output}" if verification.output else "Verification failed.",
    )
    if (
        runtime_state.auto_fix_context == "task_failure"
        and runtime_state.auto_fix_task_id is not None
        and effective_runtime_config.auto_fix_enabled
        and fixer_executor is not None
    ):
        _resume_recovered_task_auto_fix(
            store=store,
            session_id=session_id,
            pack_manifest=pack_manifest,
            effective_runtime_config=effective_runtime_config,
            env=env,
            fixer_executor=fixer_executor,
            runtime_state=runtime_state,
            session_root=session_paths.root,
            runtime_event_sink=runtime_event_sink,
        )
        return None
    if not effective_runtime_config.auto_fix_enabled or fixer_executor is None:
        store.update_session_status(session_id, status="paused")
        _publish_state_update(runtime_event_sink, session_id)
        return OrchestratorResult(
            session_id=session_id,
            started=True,
            session_status="paused",
            blocked_tasks=tuple(task.task_id for task in store.list_blocked_tasks(session_id)),
        )

    previous_summary: str | None = store.get_session(session_id).runtime_state.last_fix_summary
    previous_verification_output: str | None = None
    for attempt in range(1, effective_runtime_config.auto_fix_max_attempts + 1):
        store.update_session_status(session_id, status="auto_fixing")
        store.write_session_runtime_state(
            session_id,
            verification_pending=True,
            verification_reason="verification_failure",
            auto_fix_context="verification_failure",
            auto_fix_task_id=None,
            auto_fix_attempt=attempt,
            last_fix_summary=previous_summary,
        )
        store.append_event(
            session_id,
            timestamp=_timestamp(),
            event_type="session.auto_fix_started",
            message=f"Auto-fix attempt {attempt}/{effective_runtime_config.auto_fix_max_attempts} started for verification failure.",
        )
        _publish_state_update(runtime_event_sink, session_id)
        context = build_verification_failure_context(
            session_id=session_id,
            attempt=attempt,
            verify_log_path=session_paths.verify_log,
            previous_attempt_summary=previous_summary,
            previous_verification_output=previous_verification_output,
        )
        fix_result = fixer_executor(context)
        previous_summary = fix_result.summary or previous_summary
        store.write_session_runtime_state(
            session_id,
            last_fix_summary=previous_summary,
            auto_fix_attempt=attempt,
        )
        if not fix_result.success:
            continue
        store.update_session_status(session_id, status="verifying")
        _publish_state_update(runtime_event_sink, session_id)
        verification = run_verification_command(
            session_root=session_paths.root,
            verify_log_path=session_paths.verify_log,
            command=pack_manifest.verification.command or "",
            env=env,
            output_line_callback=_make_verification_output_callback(runtime_event_sink, session_id),
        )
        if verification.ok:
            verified_at = _timestamp()
            store.update_session_status(session_id, status="running")
            store.write_session_runtime_state(
                session_id,
                completed_since_verification=0,
                verification_pending=False,
                verification_reason=None,
                verification_started_at=None,
                auto_fix_context=None,
                auto_fix_task_id=None,
                auto_fix_attempt=0,
                last_fix_summary=previous_summary,
                dispatch_frozen=False,
                dispatch_frozen_reason=None,
            )
            store.append_event(
                session_id,
                timestamp=verified_at,
                event_type="session.verification_passed",
                message="Verification passed.",
            )
            _publish_state_update(runtime_event_sink, session_id)
            return None
        previous_verification_output = verification.output
        store.append_event(
            session_id,
            timestamp=_timestamp(),
            event_type="session.verification_failed",
            message=f"Verification failed after auto-fix attempt.\n{verification.output}" if verification.output else "Verification failed after auto-fix attempt.",
        )

    store.update_session_status(session_id, status="paused")
    _publish_state_update(runtime_event_sink, session_id)
    return OrchestratorResult(
        session_id=session_id,
        started=True,
        session_status="paused",
        blocked_tasks=tuple(task.task_id for task in store.list_blocked_tasks(session_id)),
    )


def _abort_session_for_timeout(
    *,
    store: StateStore,
    session_id: str,
    pack_manifest: PackManifest,
    manager: WorkerManager,
    poll_interval: float,
    session_timeout: int,
    env: Mapping[str, str] | None = None,
    runtime_event_sink: Callable[[BackendRuntimeEvent], None] | None,
) -> OrchestratorResult:
    reason = f"Session max timeout exceeded ({session_timeout}s)."
    store.append_event(
        session_id,
        timestamp=_timestamp(),
        event_type="session.timeout",
        message=reason,
    )
    _publish_alert(
        runtime_event_sink,
        session_id=session_id,
        severity="error",
        task_id=None,
        worker_slot=None,
        message=reason,
    )
    return _abort_session(
        store=store,
        session_id=session_id,
        pack_manifest=pack_manifest,
        manager=manager,
        poll_interval=poll_interval,
        reason=reason,
        timeout_kind="session_max",
        env=env,
        runtime_event_sink=runtime_event_sink,
    )


def _abort_session(
    *,
    store: StateStore,
    session_id: str,
    pack_manifest: PackManifest,
    manager: WorkerManager,
    poll_interval: float,
    reason: str,
    timeout_kind: str = "abort",
    env: Mapping[str, str] | None = None,
    runtime_event_sink: Callable[[BackendRuntimeEvent], None] | None = None,
) -> OrchestratorResult:
    for slot_number in manager.active_slot_numbers():
        manager.terminate(
            slot_number,
            reason=f"Killed: {reason}",
            timeout_kind=timeout_kind,
        )

    while manager.active_slot_numbers():
        for slot_number in manager.active_slot_numbers():
            # Wrap per-slot body so an exception from collect() or _finalize_blocked_task()
            # (e.g., corrupt status sidecar) does not abort the drain loop — other
            # workers must still be collected. F-5 fix.
            try:
                snapshot = manager.poll(slot_number)
                _publish_worker_runtime_events(
                    runtime_event_sink=runtime_event_sink,
                    session_id=session_id,
                    pack_manifest=pack_manifest,
                    snapshot=snapshot,
                )
                if not snapshot.is_finished:
                    continue
                result = manager.collect(slot_number)
                _finalize_blocked_task(
                    store=store,
                    session_id=session_id,
                    pack_manifest=pack_manifest,
                    active_task=store.get_task(session_id, result.task_id),
                    slot_number=result.slot_number,
                    workspace_path=result.workspace_path,
                    reason=result.failure_reason or f"Killed: {reason}",
                    env=env,
                    runtime_event_sink=runtime_event_sink,
                )
            except Exception:
                _logger.exception("Error draining worker slot %d during abort; continuing drain", slot_number)
        if manager.active_slot_numbers():
            time.sleep(poll_interval)

    aborted_at = _timestamp()
    store.update_session_status(session_id, status="aborted", completed_at=aborted_at)
    store.append_event(
        session_id,
        timestamp=aborted_at,
        event_type="session.aborted",
        message=reason,
    )
    _publish_state_update(runtime_event_sink, session_id)
    return OrchestratorResult(
        session_id=session_id,
        started=True,
        session_status="aborted",
        blocked_tasks=tuple(task.task_id for task in store.list_blocked_tasks(session_id)),
    )


def _prepare_workspace(
    *,
    pack_manifest: PackManifest,
    session_paths,
    slot_number: int,
    task: PersistedTask,
    env: Mapping[str, str] | None,
) -> Path | None:
    if pack_manifest.isolation.type == "none":
        return session_paths.root

    # Minimum safe assumption for packet 06: a non-none isolation mode without a
    # working isolate_start hook is treated as a task-blocking setup failure.
    try:
        result = run_pack_hook(
            pack_manifest,
            "isolate_start",
            args=[str(slot_number), task.task_id, str(session_paths.root)],
            cwd=session_paths.root,
            env=env,
        )
    except HookNotFoundError:
        return None
    except Exception as exc:
        _logger.error("isolate_start hook crashed for task %s: %s", task.task_id, exc)
        return None
    if not result.ok:
        return None
    workspace = result.stdout.strip()
    if not workspace:
        return None
    return Path(workspace)


def _generate_commit_message(
    plan_path: Path | None, task_id: str, slot_number: int
) -> str | None:
    """Generate a commit message from the plan file, or return None for fallback."""
    if plan_path is None or not plan_path.is_file():
        return None
    try:
        plan_text = plan_path.read_text(encoding="utf-8")
        plan = parse_task_plan(plan_text)
    except (OSError, ArtifactParseError):
        return None

    subject = f"feat: {plan.title}"
    if len(subject) > 72:
        subject = subject[:69] + "..."

    parts = [subject]
    description = extract_commit_description(plan.body)
    if description:
        parts.append("")
        parts.append(description)
    parts.append("")
    parts.append(f"Task: {task_id} (slot {slot_number})")
    return "\n".join(parts)


def _run_isolate_end(
    *,
    pack_manifest: PackManifest,
    slot_number: int,
    task_id: str,
    workspace_path: Path,
    final_status: str,
    plan_path: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> bool:
    if pack_manifest.isolation.type == "none":
        return True
    hook_cwd = workspace_path if workspace_path.exists() else pack_manifest.root
    args = [
        str(slot_number),
        task_id,
        str(workspace_path),
        final_status,
    ]

    # Generate commit message in Python and pass via env var so the shell
    # script doesn't need to locate/invoke plan_commit_msg.py (which fails
    # when the pack runs from the runtime copy outside the source tree).
    hook_env: dict[str, str] = dict(env) if env else {}
    commit_msg = _generate_commit_message(plan_path, task_id, slot_number)
    if commit_msg:
        hook_env["SWITCHYARD_COMMIT_MSG"] = commit_msg

    try:
        result = run_pack_hook(
            pack_manifest,
            "isolate_end",
            args=args,
            cwd=hook_cwd,
            env=hook_env if hook_env else None,
        )
    except (FileNotFoundError, HookNotFoundError):
        return False
    except Exception as exc:
        _logger.error("isolate_end hook crashed for task %s: %s", task_id, exc)
        return False
    return result.ok


def _available_slots(max_workers: int, active_tasks: tuple[PersistedTask, ...]) -> list[int]:
    active_slots = {
        task.worker_slot
        for task in active_tasks
        if task.worker_slot is not None
    }
    return [slot for slot in range(max_workers) if slot not in active_slots]


def _merged_runtime_env(
    base_env: Mapping[str, str] | None,
    effective_runtime_config: EffectiveSessionRuntimeConfig,
    *,
    pack_manifest: PackManifest,
) -> dict[str, str] | None:
    merged = dict(base_env or {})
    merged.update(effective_runtime_config.environment)
    merged["COGNITIVE_SWITCHYARD_PACK_ROOT"] = str(pack_manifest.root)
    if pack_manifest.phases.execution.reasoning_effort is not None:
        merged["CODEX_WORKER_REASONING_EFFORT"] = pack_manifest.phases.execution.reasoning_effort
    return merged


def _preflight_failure_message(preflight) -> str:
    if not preflight.permission_report.ok:
        return "Pack script permissions failed preflight."
    if not preflight.prerequisite_results.ok:
        failed = [result.name for result in preflight.prerequisite_results.results if not result.ok]
        return "Preflight prerequisites failed: " + ", ".join(failed)
    if preflight.preflight_result is not None and not preflight.preflight_result.ok:
        return f"Preflight hook failed with exit code {preflight.preflight_result.exit_code}."
    return "Preflight failed."


def _run_startup_preflight(
    *,
    store: StateStore,
    session_id: str,
    pack_manifest: PackManifest,
    env: Mapping[str, str] | None,
    started: bool,
) -> OrchestratorResult | None:
    preflight = run_session_preflight(
        store=store,
        session_id=session_id,
        pack_manifest=pack_manifest,
        env=env,
    )
    if preflight.ok:
        return None
    message = _preflight_failure_message(preflight)
    store.append_event(
        session_id,
        timestamp=_timestamp(),
        event_type="session.preflight_failed",
        message=message,
    )
    return OrchestratorResult(
        session_id=session_id,
        started=started,
        session_status=store.get_session(session_id).status,
        startup_failure=OrchestratorStartupFailure(
            reason="preflight_failed",
            message=message,
        ),
    )


def _publish_state_update(
    runtime_event_sink: Callable[[BackendRuntimeEvent], None] | None,
    session_id: str,
) -> None:
    _publish_runtime_event(runtime_event_sink, "state_update", session_id=session_id)


def _task_elapsed(started_at: str | None, ended_at: str | None) -> int:
    """Return duration in whole seconds between two ISO timestamps, or 0 if either is absent."""
    if not started_at or not ended_at:
        return 0
    try:
        start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        end = datetime.fromisoformat(ended_at.replace("Z", "+00:00"))
        return max(0, int((end - start).total_seconds()))
    except (ValueError, TypeError):
        return 0


def _publish_task_status_change(
    runtime_event_sink: Callable[[BackendRuntimeEvent], None] | None,
    *,
    session_id: str,
    task_id: str,
    old_status: str,
    new_status: str,
    worker_slot: int | None,
    notes: str,
    elapsed: int = 0,
    started_at: str | None = None,
    completed_at: str | None = None,
) -> None:
    data: dict[str, Any] = {
        "task_id": task_id,
        "old_status": old_status,
        "new_status": new_status,
        "worker_slot": worker_slot,
        "notes": notes,
        "elapsed": elapsed,
    }
    if started_at is not None:
        data["started_at"] = started_at
    if completed_at is not None:
        data["completed_at"] = completed_at
    _publish_runtime_event(
        runtime_event_sink,
        "task_status_change",
        session_id=session_id,
        data=data,
    )


def _publish_alert(
    runtime_event_sink: Callable[[BackendRuntimeEvent], None] | None,
    *,
    session_id: str,
    severity: str,
    task_id: str | None,
    worker_slot: int | None,
    message: str,
) -> None:
    payload = {"severity": severity, "message": message}
    if task_id is not None:
        payload["task_id"] = task_id
    if worker_slot is not None:
        payload["worker_slot"] = worker_slot
    _publish_runtime_event(
        runtime_event_sink,
        "alert",
        session_id=session_id,
        data=payload,
    )


def _publish_worker_runtime_events(
    *,
    runtime_event_sink: Callable[[BackendRuntimeEvent], None] | None,
    session_id: str,
    pack_manifest: PackManifest,
    snapshot,
) -> None:
    if runtime_event_sink is None or snapshot is None:
        return
    for alert in snapshot.alerts:
        _publish_runtime_event(
            runtime_event_sink,
            "alert",
            session_id=session_id,
            data={
                "severity": alert.severity,
                "task_id": alert.task_id,
                "worker_slot": alert.worker_slot,
                "message": alert.message,
            },
        )
    for line in snapshot.new_output_lines:
        timestamp = _timestamp()
        _publish_runtime_event(
            runtime_event_sink,
            "log_line",
            session_id=session_id,
            data={
                "worker_slot": snapshot.slot_number,
                "task_id": snapshot.task_id,
                "line": line,
                "timestamp": timestamp,
            },
        )
        try:
            update = parse_progress_line(line, progress_format=pack_manifest.status.progress_format)
        except ArtifactParseError:
            continue
        if update.task_id != snapshot.task_id or update.kind != "detail":
            continue
        _publish_runtime_event(
            runtime_event_sink,
            "progress_detail",
            session_id=session_id,
            data={
                "worker_slot": snapshot.slot_number,
                "task_id": snapshot.task_id,
                "detail": update.detail_message,
                "timestamp": timestamp,
            },
        )
    # Emit one idle-state event per poll cycle so the UI can show last-activity age.
    _publish_runtime_event(
        runtime_event_sink,
        "worker_idle_state",
        session_id=session_id,
        data={
            "worker_slot": snapshot.slot_number,
            "task_id": snapshot.task_id,
            "last_output_at": snapshot.last_output_at,
            "task_idle": snapshot.task_idle,
        },
    )


def _make_verification_output_callback(
    runtime_event_sink: Callable[[BackendRuntimeEvent], None] | None,
    session_id: str,
) -> Callable[[str], None] | None:
    """Return a line callback that streams verification output as log_line events."""
    if runtime_event_sink is None:
        return None

    def _callback(line: str) -> None:
        _publish_runtime_event(
            runtime_event_sink,
            "log_line",
            session_id=session_id,
            data={
                "worker_slot": -1,
                "task_id": "__phase_verification__",
                "line": line,
                "timestamp": _timestamp(),
                "phase": "verification",
            },
        )

    return _callback


def _publish_runtime_event(
    runtime_event_sink: Callable[[BackendRuntimeEvent], None] | None,
    message_type: str,
    *,
    session_id: str,
    data: dict | None = None,
) -> None:
    if runtime_event_sink is None:
        return
    runtime_event_sink(
        BackendRuntimeEvent(
            message_type=message_type,
            session_id=session_id,
            data={} if data is None else data,
        )
    )


def _format_pipeline_event_message(event_type: str, detail: dict) -> str:
    if event_type == "file_claimed":
        return f"Planner claimed {detail.get('file', '?')}"
    if event_type == "file_planned":
        return f"Plan {detail.get('task_id', '?')} → {detail.get('destination', '?')}"
    if event_type == "file_unclaimed":
        return f"Planner released {detail.get('file', '?')}"
    if event_type == "file_resolved":
        return f"Resolved {detail.get('task_id', '?')}"
    if event_type == "plan_id_collision":
        return f"Plan ID collision: {', '.join(detail.get('collisions', []))}"
    if event_type == "resolver_started":
        return f"Resolving dependencies for {detail.get('plan_count', '?')} plans"
    if event_type == "resolver_finished":
        return f"Resolution complete: {detail.get('ready_count', '?')} tasks ready"
    if event_type == "planner_started":
        return f"Planner started on {detail.get('file', '?')}"
    if event_type == "planner_finished":
        return f"Planner finished {detail.get('file', '?')}"
    return f"{event_type}: {detail}"


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _elapsed_since_timestamp(timestamp: str | None) -> float:
    if not timestamp:
        return 0.0
    return max(0.0, (datetime.now(UTC) - _parse_timestamp(timestamp)).total_seconds())


def _parse_timestamp(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value).astimezone(UTC)


_logger = logging.getLogger(__name__)
