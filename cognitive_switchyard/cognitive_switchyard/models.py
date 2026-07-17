from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ValidationFinding:
    path: str
    message: str


@dataclass(frozen=True)
class PlanningPhaseConfig:
    enabled: bool = False
    executor: str = "agent"
    runtime: str = "claude"
    model: str | None = None
    reasoning_effort: str | None = None
    prompt: Path | None = None
    max_instances: int = 1


@dataclass(frozen=True)
class ResolutionPhaseConfig:
    enabled: bool = True
    executor: str = "agent"
    runtime: str = "claude"
    model: str | None = None
    reasoning_effort: str | None = None
    prompt: Path | None = None
    script: Path | None = None


@dataclass(frozen=True)
class ExecutionPhaseConfig:
    enabled: bool = True
    executor: str = "shell"
    model: str | None = None
    reasoning_effort: str | None = None
    prompt: Path | None = None
    command: Path | None = None
    max_workers: int = 2


@dataclass(frozen=True)
class VerificationConfig:
    enabled: bool = False
    command: str | None = None
    interval: int = 4


@dataclass(frozen=True)
class AutoFixConfig:
    enabled: bool = False
    max_attempts: int = 2
    runtime: str = "claude"
    model: str | None = None
    reasoning_effort: str | None = None
    prompt: Path | None = None


@dataclass(frozen=True)
class IsolationConfig:
    type: str = "none"
    setup: Path | None = None
    teardown: Path | None = None


@dataclass(frozen=True)
class PrerequisiteCheck:
    name: str
    check: str


@dataclass(frozen=True)
class TimeoutConfig:
    task_idle: int = 420
    task_max: int = 0
    session_max: int = 14400


@dataclass(frozen=True)
class StatusConfig:
    progress_format: str = "##PROGRESS##"
    sidecar_format: str = "key-value"


@dataclass(frozen=True)
class PhaseConfigSet:
    planning: PlanningPhaseConfig = field(default_factory=PlanningPhaseConfig)
    resolution: ResolutionPhaseConfig = field(default_factory=ResolutionPhaseConfig)
    execution: ExecutionPhaseConfig = field(default_factory=ExecutionPhaseConfig)


@dataclass(frozen=True)
class PackManifest:
    root: Path
    name: str
    description: str
    version: str
    phases: PhaseConfigSet
    verification: VerificationConfig = field(default_factory=VerificationConfig)
    auto_fix: AutoFixConfig = field(default_factory=AutoFixConfig)
    isolation: IsolationConfig = field(default_factory=IsolationConfig)
    prerequisites: list[PrerequisiteCheck] = field(default_factory=list)
    timeouts: TimeoutConfig = field(default_factory=TimeoutConfig)
    status: StatusConfig = field(default_factory=StatusConfig)


@dataclass(frozen=True)
class ScriptPermissionIssue:
    relative_path: str
    fix_command: str


@dataclass(frozen=True)
class ScriptPermissionReport:
    ok: bool
    issues: tuple[ScriptPermissionIssue, ...] = ()


@dataclass(frozen=True)
class PrerequisiteResult:
    name: str
    check: str
    ok: bool
    exit_code: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class PrerequisiteReport:
    ok: bool
    results: tuple[PrerequisiteResult, ...] = ()


@dataclass(frozen=True)
class HookInvocationResult:
    hook_name: str
    script_path: Path
    args: tuple[str, ...]
    cwd: Path
    ok: bool
    exit_code: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class PackPreflightResult:
    ok: bool
    permission_report: ScriptPermissionReport
    prerequisite_results: PrerequisiteReport
    preflight_result: HookInvocationResult | None = None


@dataclass(frozen=True)
class ScheduledTask:
    task_id: str
    title: str
    depends_on: tuple[str, ...] = ()
    anti_affinity: tuple[str, ...] = ()
    exec_order: int = 1
    full_test_after: bool = False


@dataclass(frozen=True)
class TaskPlan(ScheduledTask):
    body: str = ""


@dataclass(frozen=True)
class StagedTaskPlan:
    task_id: str
    title: str
    metadata: dict[str, str]
    declared_depends_on: tuple[str, ...] = ()
    full_test_after: bool = False
    body: str = ""


@dataclass(frozen=True)
class TaskStatus:
    status: str
    commits: tuple[str, ...]
    tests_ran: str
    test_result: str
    blocked_reason: str | None = None
    notes: str | None = None
    tests_ran_raw: str | None = None


@dataclass(frozen=True)
class ProgressUpdate:
    task_id: str
    kind: str
    phase_name: str | None = None
    phase_index: int | None = None
    phase_total: int | None = None
    detail_message: str | None = None


@dataclass(frozen=True)
class WorkerProgressState:
    task_id: str | None = None
    phase_name: str | None = None
    phase_index: int | None = None
    phase_total: int | None = None
    detail_message: str | None = None


@dataclass(frozen=True)
class WorkerAlert:
    severity: str
    task_id: str
    worker_slot: int
    message: str


@dataclass(frozen=True)
class WorkerSnapshot:
    slot_number: int
    task_id: str
    pid: int
    workspace_path: Path
    log_path: Path
    new_output_lines: tuple[str, ...]
    progress: WorkerProgressState
    is_finished: bool
    exit_code: int | None
    timed_out: bool
    alerts: tuple[WorkerAlert, ...] = ()
    last_output_at: float = 0.0
    task_idle: float = 0.0
    worker_started_at: float = 0.0


@dataclass(frozen=True)
class WorkerResult:
    slot_number: int
    task_id: str
    pid: int
    workspace_path: Path
    log_path: Path
    exit_code: int
    timed_out: bool
    timeout_kind: str | None
    failure_reason: str | None
    kill_escalated: bool
    progress: WorkerProgressState
    status_path: Path | None = None
    status: TaskStatus | None = None


@dataclass(frozen=True)
class ResolutionTask:
    task_id: str
    depends_on: tuple[str, ...]
    anti_affinity: tuple[str, ...]
    exec_order: int


@dataclass(frozen=True)
class ResolutionGroup:
    name: str
    type: str
    members: tuple[str, ...]
    shared_resources: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResolutionGraph:
    resolved_at: str | None
    tasks: tuple[ResolutionTask, ...]
    groups: tuple[ResolutionGroup, ...] = ()
    conflicts: tuple[str, ...] = ()
    notes: str | None = None


@dataclass(frozen=True)
class SessionRuntimeState:
    completed_since_verification: int = 0
    verification_pending: bool = False
    verification_reason: str | None = None
    verification_started_at: str | None = None
    auto_fix_context: str | None = None
    auto_fix_task_id: str | None = None
    auto_fix_attempt: int = 0
    last_fix_summary: str | None = None
    run_number: int = 0
    run_started_at: str | None = None
    accumulated_elapsed_seconds: int = 0
    last_run_elapsed_seconds: int = 0
    dispatch_frozen: bool = False
    dispatch_frozen_reason: str | None = None
    last_verification_test_summary: str | None = None


@dataclass(frozen=True)
class SessionConfigOverrides:
    planner_count: int | None = None
    worker_count: int | None = None
    verification_interval: int | None = None
    task_idle: int | None = None
    task_max: int | None = None
    session_max: int | None = None
    auto_fix_enabled: bool | None = None
    auto_fix_max_attempts: int | None = None
    poll_interval: float | None = None
    environment: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.planner_count is not None:
            payload["planner_count"] = self.planner_count
        if self.worker_count is not None:
            payload["worker_count"] = self.worker_count
        if self.verification_interval is not None:
            payload["verification_interval"] = self.verification_interval
        if self.task_idle is not None:
            payload["task_idle"] = self.task_idle
        if self.task_max is not None:
            payload["task_max"] = self.task_max
        if self.session_max is not None:
            payload["session_max"] = self.session_max
        if self.auto_fix_enabled is not None:
            payload["auto_fix_enabled"] = self.auto_fix_enabled
        if self.auto_fix_max_attempts is not None:
            payload["auto_fix_max_attempts"] = self.auto_fix_max_attempts
        if self.poll_interval is not None:
            payload["poll_interval"] = self.poll_interval
        if self.environment:
            payload["environment"] = dict(self.environment)
        return payload


@dataclass(frozen=True)
class EffectiveSessionRuntimeConfig:
    worker_count: int
    verification_interval: int
    task_idle: int
    task_max: int
    session_max: int
    auto_fix_enabled: bool
    auto_fix_max_attempts: int
    poll_interval: float
    environment: dict[str, str] = field(default_factory=dict)
    planner_count: int | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "worker_count": self.worker_count,
            "verification_interval": self.verification_interval,
            "timeouts": {
                "task_idle": self.task_idle,
                "task_max": self.task_max,
                "session_max": self.session_max,
            },
            "auto_fix": {
                "enabled": self.auto_fix_enabled,
                "max_attempts": self.auto_fix_max_attempts,
            },
            "poll_interval": self.poll_interval,
            "environment": dict(self.environment),
        }
        if self.planner_count is not None:
            payload["planner_count"] = self.planner_count
        return payload


@dataclass(frozen=True)
class SessionRecord:
    id: str
    name: str
    pack: str
    status: str
    created_at: str
    started_at: str | None = None
    config_json: str | None = None
    completed_at: str | None = None
    runtime_state: SessionRuntimeState = field(default_factory=SessionRuntimeState)


@dataclass(frozen=True)
class PersistedTask:
    session_id: str
    task_id: str
    title: str
    status: str
    plan_path: Path
    depends_on: tuple[str, ...] = ()
    anti_affinity: tuple[str, ...] = ()
    exec_order: int = 1
    full_test_after: bool = False
    worker_slot: int | None = None
    created_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None


@dataclass(frozen=True)
class WorkerSlotRecord:
    session_id: str
    slot_number: int
    status: str
    current_task_id: str | None = None


@dataclass(frozen=True)
class SessionEvent:
    session_id: str
    timestamp: str
    event_type: str
    task_id: str | None
    message: str


@dataclass(frozen=True)
class WorkerRecoveryMetadata:
    session_id: str
    slot_number: int
    task_id: str
    workspace_path: Path
    pid: int | None = None


@dataclass(frozen=True)
class OrchestratorStartupFailure:
    reason: str
    message: str


@dataclass(frozen=True)
class OrchestratorResult:
    session_id: str
    started: bool
    session_status: str
    blocked_tasks: tuple[str, ...] = ()
    review_tasks: tuple[str, ...] = ()
    resolution_conflicts: tuple[str, ...] = ()
    startup_failure: OrchestratorStartupFailure | None = None


@dataclass(frozen=True)
class PlanningPhaseResult:
    session_id: str
    staged_task_ids: tuple[str, ...] = ()
    review_task_ids: tuple[str, ...] = ()


def parse_session_config_overrides(payload: str | dict[str, Any] | None) -> SessionConfigOverrides:
    if payload is None:
        return SessionConfigOverrides()
    if isinstance(payload, str):
        if not payload.strip():
            return SessionConfigOverrides()
        data = json.loads(payload)
    else:
        data = dict(payload)
    if not isinstance(data, dict):
        raise ValueError("session config must be a JSON object")

    environment = data.get("environment") or {}
    if not isinstance(environment, dict):
        raise ValueError("session config environment must be an object")

    normalized_environment: dict[str, str] = {}
    for key, value in environment.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ValueError("session config environment entries must be string:string")
        normalized_environment[key] = value

    return SessionConfigOverrides(
        planner_count=_optional_int(data, "planner_count", minimum=1),
        worker_count=_optional_int(data, "worker_count", minimum=1),
        verification_interval=_optional_int(data, "verification_interval", minimum=1),
        task_idle=_optional_int(data, "task_idle", minimum=0),
        task_max=_optional_int(data, "task_max", minimum=0),
        session_max=_optional_int(data, "session_max", minimum=0),
        auto_fix_enabled=_optional_bool(data, "auto_fix_enabled"),
        auto_fix_max_attempts=_optional_int(data, "auto_fix_max_attempts", minimum=1),
        poll_interval=_optional_float(data, "poll_interval", minimum=0.000001),
        environment=normalized_environment,
    )


def build_effective_session_runtime_config(
    *,
    session: SessionRecord,
    pack_manifest: PackManifest,
    default_poll_interval: float,
) -> EffectiveSessionRuntimeConfig:
    overrides = parse_session_config_overrides(session.config_json)
    planner_count = build_effective_planner_count(session=session, pack_manifest=pack_manifest)
    worker_count = pack_manifest.phases.execution.max_workers
    if overrides.worker_count is not None:
        worker_count = min(overrides.worker_count, pack_manifest.phases.execution.max_workers)
    verification_interval = (
        pack_manifest.verification.interval
        if overrides.verification_interval is None
        else overrides.verification_interval
    )
    task_idle = pack_manifest.timeouts.task_idle if overrides.task_idle is None else overrides.task_idle
    task_max = pack_manifest.timeouts.task_max if overrides.task_max is None else overrides.task_max
    session_max = (
        pack_manifest.timeouts.session_max if overrides.session_max is None else overrides.session_max
    )
    auto_fix_enabled = (
        pack_manifest.auto_fix.enabled
        if overrides.auto_fix_enabled is None
        else overrides.auto_fix_enabled
    )
    auto_fix_max_attempts = (
        pack_manifest.auto_fix.max_attempts
        if overrides.auto_fix_max_attempts is None
        else overrides.auto_fix_max_attempts
    )
    poll_interval = default_poll_interval if overrides.poll_interval is None else overrides.poll_interval
    return EffectiveSessionRuntimeConfig(
        planner_count=planner_count,
        worker_count=worker_count,
        verification_interval=verification_interval,
        task_idle=task_idle,
        task_max=task_max,
        session_max=session_max,
        auto_fix_enabled=auto_fix_enabled,
        auto_fix_max_attempts=auto_fix_max_attempts,
        poll_interval=poll_interval,
        environment=dict(overrides.environment),
    )


def build_effective_planner_count(
    *,
    session: SessionRecord,
    pack_manifest: PackManifest,
) -> int | None:
    if not pack_manifest.phases.planning.enabled:
        return None
    overrides = parse_session_config_overrides(session.config_json)
    planner_count = pack_manifest.phases.planning.max_instances
    if overrides.planner_count is not None:
        planner_count = min(overrides.planner_count, pack_manifest.phases.planning.max_instances)
    return planner_count


def _optional_int(data: dict[str, Any], key: str, *, minimum: int) -> int | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"session config {key} must be an integer")
    if value < minimum:
        raise ValueError(f"session config {key} must be >= {minimum}")
    return value


def _optional_bool(data: dict[str, Any], key: str) -> bool | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValueError(f"session config {key} must be a boolean")
    return value


def _optional_float(data: dict[str, Any], key: str, *, minimum: float) -> float | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"session config {key} must be numeric")
    value = float(value)
    if value < minimum:
        raise ValueError(f"session config {key} must be >= {minimum}")
    return value


@dataclass(frozen=True)
class ResolutionPhaseResult:
    session_id: str
    ready_task_ids: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()


@dataclass(frozen=True)
class SessionPreparationResult:
    session_id: str
    ready_task_ids: tuple[str, ...] = ()
    review_task_ids: tuple[str, ...] = ()
    resolution_conflicts: tuple[str, ...] = ()


@dataclass(frozen=True)
class RecoveryResult:
    session_id: str
    preserved_done_task_ids: tuple[str, ...] = ()
    reverted_ready_task_ids: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class FixerContext:
    context_type: str
    session_id: str
    task_id: str | None
    attempt: int
    plan_text: str | None = None
    status_text: str | None = None
    worker_log_tail: str | None = None
    verification_output: str | None = None
    previous_attempt_summary: str | None = None
    failure_kind: str | None = None


@dataclass(frozen=True)
class FixerAttemptResult:
    success: bool
    summary: str = ""


@dataclass(frozen=True)
class VerificationRunResult:
    ok: bool
    exit_code: int
    output: str
    log_path: Path


@dataclass(frozen=True)
class BackendRuntimeEvent:
    message_type: str
    session_id: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkerCardRuntimeState:
    slot_number: int
    task_id: str | None = None
    phase_name: str | None = None
    phase_index: int | None = None
    phase_total: int | None = None
    detail_message: str | None = None


_DEFAULT_PHASE_PROGRESS_RE = re.compile(
    r"^##PROGRESS##\s+(?P<task_id>\S+)\s+\|\s+Phase:\s+(?P<phase>.+?)\s+\|\s+"
    r"(?P<index>\d+)/(?P<total>\d+)\s*$"
)


def apply_runtime_event_to_worker_card_state(
    cache: dict[int, WorkerCardRuntimeState],
    event: BackendRuntimeEvent,
) -> None:
    if event.message_type == "task_status_change":
        _apply_task_status_change(cache, event.data)
        return
    if event.message_type == "log_line":
        _apply_log_line(cache, event.data)
        return
    if event.message_type == "progress_detail":
        _apply_progress_detail(cache, event.data)


def reconstruct_worker_card_state(
    *,
    session_id: str,
    events: tuple[BackendRuntimeEvent, ...],
) -> dict[int, WorkerCardRuntimeState]:
    cache: dict[int, WorkerCardRuntimeState] = {}
    for event in events:
        if event.session_id != session_id:
            continue
        apply_runtime_event_to_worker_card_state(cache, event)
    return cache


def _apply_task_status_change(
    cache: dict[int, WorkerCardRuntimeState],
    data: dict[str, Any],
) -> None:
    worker_slot = data.get("worker_slot")
    task_id = data.get("task_id")
    if not isinstance(worker_slot, int) or not isinstance(task_id, str):
        return
    current = cache.get(worker_slot, WorkerCardRuntimeState(slot_number=worker_slot))
    if current.task_id != task_id:
        cache[worker_slot] = WorkerCardRuntimeState(
            slot_number=worker_slot,
            task_id=task_id,
        )
        return
    cache[worker_slot] = WorkerCardRuntimeState(
        slot_number=worker_slot,
        task_id=task_id,
        phase_name=current.phase_name,
        phase_index=current.phase_index,
        phase_total=current.phase_total,
        detail_message=current.detail_message,
    )


def _apply_log_line(
    cache: dict[int, WorkerCardRuntimeState],
    data: dict[str, Any],
) -> None:
    worker_slot = data.get("worker_slot")
    task_id = data.get("task_id")
    if not isinstance(worker_slot, int) or not isinstance(task_id, str):
        return
    phase_name = data.get("phase")
    phase_index = data.get("phase_num")
    phase_total = data.get("phase_total")
    if not isinstance(phase_name, str) or not isinstance(phase_index, int) or not isinstance(phase_total, int):
        line = data.get("line")
        if not isinstance(line, str):
            return
        match = _DEFAULT_PHASE_PROGRESS_RE.match(line)
        if match is None or match.group("task_id") != task_id:
            return
        phase_name = match.group("phase")
        phase_index = int(match.group("index"))
        phase_total = int(match.group("total"))
    current = cache.get(worker_slot, WorkerCardRuntimeState(slot_number=worker_slot))
    cache[worker_slot] = WorkerCardRuntimeState(
        slot_number=worker_slot,
        task_id=task_id,
        phase_name=phase_name,
        phase_index=phase_index,
        phase_total=phase_total,
        detail_message=current.detail_message if current.task_id == task_id else None,
    )


def _apply_progress_detail(
    cache: dict[int, WorkerCardRuntimeState],
    data: dict[str, Any],
) -> None:
    worker_slot = data.get("worker_slot")
    task_id = data.get("task_id")
    detail = data.get("detail")
    if not isinstance(worker_slot, int) or not isinstance(task_id, str):
        return
    current = cache.get(worker_slot, WorkerCardRuntimeState(slot_number=worker_slot))
    cache[worker_slot] = WorkerCardRuntimeState(
        slot_number=worker_slot,
        task_id=task_id,
        phase_name=current.phase_name if current.task_id == task_id else None,
        phase_index=current.phase_index if current.task_id == task_id else None,
        phase_total=current.phase_total if current.task_id == task_id else None,
        detail_message=detail if isinstance(detail, str) else None,
    )
