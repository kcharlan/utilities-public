from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import json
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from .hook_runner import run_pack_hook
from .models import (
    PackManifest,
    PlanningPhaseResult,
    ResolutionGraph,
    ResolutionPhaseResult,
    ResolutionTask,
    SessionPreparationResult,
    StagedTaskPlan,
    build_effective_planner_count,
)
from .parsers import (
    ArtifactParseError,
    parse_resolution_json,
    parse_staged_task_plan,
    parse_task_plan,
)
from .agent_runtime import ClaudeCliRuntimeError
from .state import StateStore

_logger = __import__("logging").getLogger(__name__)

PlannerAgent = Callable[..., str]
ResolverAgent = Callable[..., str]

# Files placed in intake/ that are metadata, not work items.
_INTAKE_META_FILES = frozenset({"CLAUDE.md", "NEXT_SEQUENCE"})


def prepare_session_for_execution(
    *,
    store: StateStore,
    session_id: str,
    pack_manifest: PackManifest,
    planner_agent: PlannerAgent | None = None,
    resolver_agent: ResolverAgent | None = None,
    effective_planner_count: int | None = None,
    env: dict[str, str] | None = None,
    on_status_change: Callable[[str], None] | None = None,
    on_pipeline_event: Callable[[str, dict], None] | None = None,
) -> SessionPreparationResult:
    session = store.get_session(session_id)
    if session.status not in {"created", "planning", "resolving"}:
        raise ValueError(
            "Planning/resolution supports only 'created', 'planning', or 'resolving' sessions, "
            f"got {session.status!r}"
        )

    def _emit_pipeline_event(event_type: str, detail: dict | None = None) -> None:
        if on_pipeline_event is not None:
            on_pipeline_event(event_type, detail or {})

    def _set_status(status: str) -> None:
        store.update_session_status(session_id, status=status)
        if on_status_change is not None:
            on_status_change(status)
        _emit_pipeline_event("status_change", {"status": status})

    session_paths = store.runtime_paths.session_paths(session_id)
    _recover_claimed_items(session_paths)

    # Collect any pre-existing review items (from a previous run)
    pre_review = _task_ids_from_paths(session_paths.review.glob("*.plan.md"))

    _set_status("planning")
    planning = run_planning_phase(
        store=store,
        session_id=session_id,
        pack_manifest=pack_manifest,
        planner_agent=planner_agent,
        effective_planner_count=effective_planner_count,
        env=env,
        on_pipeline_event=on_pipeline_event,
    )

    # Merge all review IDs (pre-existing + newly produced)
    all_review_ids = tuple(sorted(set(pre_review) | set(planning.review_task_ids)))

    # If nothing was staged (all items went to review) AND no pre-existing
    # staged plans remain (e.g. from a prior run that halted at resolution),
    # we can't proceed.  Pre-existing staged plans are legitimate work that
    # still needs resolution — this happens when a conflict is resolved and
    # the session is restarted.
    pre_existing_staged = _task_ids_from_paths(session_paths.staging.glob("*.plan.md"))
    if not planning.staged_task_ids and not pre_existing_staged:
        _set_status("created")
        return SessionPreparationResult(
            session_id=session_id,
            review_task_ids=all_review_ids,
        )

    _set_status("resolving")
    resolution = run_resolution_phase(
        store=store,
        session_id=session_id,
        pack_manifest=pack_manifest,
        resolver_agent=resolver_agent,
        env=env,
        on_pipeline_event=on_pipeline_event,
    )
    _set_status("created")
    return SessionPreparationResult(
        session_id=session_id,
        ready_task_ids=resolution.ready_task_ids,
        review_task_ids=all_review_ids,
        resolution_conflicts=resolution.conflicts if resolution.conflicts else (),
    )


def run_planning_phase(
    *,
    store: StateStore,
    session_id: str,
    pack_manifest: PackManifest,
    planner_agent: PlannerAgent | None = None,
    effective_planner_count: int | None = None,
    env: dict[str, str] | None = None,
    on_pipeline_event: Callable[[str, dict], None] | None = None,
) -> PlanningPhaseResult:
    session_paths = store.runtime_paths.session_paths(session_id)
    session = store.get_session(session_id)
    _recover_claimed_items(session_paths)
    staged_task_ids: list[str] = []
    review_task_ids: list[str] = []

    def _emit(event_type: str, detail: dict | None = None) -> None:
        if on_pipeline_event is not None:
            on_pipeline_event(event_type, detail or {})

    # --- Plan ID collision detection ---
    # Check if any intake item's numeric prefix already exists in done/ as a
    # completed plan.  Collisions indicate duplicate work and must be rejected.
    intake_paths = sorted(
        (p for p in session_paths.intake.iterdir()
         if p.suffix == ".md" and p.name not in _INTAKE_META_FILES),
        key=_claim_sort_key,
    )
    collisions: list[str] = []
    for intake_path in intake_paths:
        prefix = intake_path.name.split("_", 1)[0].split(".", 1)[0]
        done_matches = list(session_paths.done.glob(f"{prefix}_*.plan.md")) + list(
            session_paths.done.glob(f"{prefix}-*.plan.md")
        )
        if done_matches:
            collisions.append(
                f"{intake_path.name} collides with done: "
                + ", ".join(p.name for p in sorted(done_matches))
            )
    if collisions:
        _emit("plan_id_collision", {"collisions": collisions})
        raise ValueError(
            "Plan ID collisions with completed plans: " + "; ".join(collisions)
        )

    # --- Guard 1: skip intake items whose task ID already exists in a live
    # pipeline directory (staging, ready, review, or an active worker slot). ---
    active_slot_dirs = [
        d for d in session_paths.workers.iterdir()
        if d.is_dir()
    ] if session_paths.workers.is_dir() else []
    live_dirs = [session_paths.staging, session_paths.ready, session_paths.review] + active_slot_dirs

    skip_prefixes: set[str] = set()
    for live_dir in live_dirs:
        if not live_dir.is_dir():
            continue
        for plan_path in live_dir.glob("*.plan.md"):
            prefix = plan_path.name.split("_", 1)[0].split("-", 1)[0].split(".", 1)[0]
            skip_prefixes.add(prefix)

    skipped_intake: list[Path] = []
    surviving_intake: list[Path] = []
    for intake_path in intake_paths:
        prefix = intake_path.name.split("_", 1)[0].split(".", 1)[0]
        if prefix in skip_prefixes:
            _logger.warning(
                "Skipping intake item %s — task ID %s already exists in a live pipeline directory",
                intake_path.name, prefix,
            )
            _emit("intake_skipped_duplicate", {"file": intake_path.name, "task_id": prefix})
            skipped_intake.append(intake_path)
        else:
            surviving_intake.append(intake_path)
    intake_paths = surviving_intake

    # Determine the working directory for agent invocations.  If the session
    # environment specifies a repo root (e.g. a git worktree), use that so the
    # planner can read the actual codebase.  Fall back to the session pipeline
    # directory.
    agent_cwd = Path(env["COGNITIVE_SWITCHYARD_REPO_ROOT"]) if env and "COGNITIVE_SWITCHYARD_REPO_ROOT" in env else session_paths.root

    if pack_manifest.phases.planning.enabled:
        if env is None or "COGNITIVE_SWITCHYARD_REPO_ROOT" not in env:
            raise ValueError(
                "COGNITIVE_SWITCHYARD_REPO_ROOT is required in env when agent planning is enabled"
            )
        if planner_agent is None:
            raise ValueError("planner_agent is required when planning is enabled")
        planner_count = effective_planner_count
        if planner_count is None:
            planner_count = build_effective_planner_count(
                session=session,
                pack_manifest=pack_manifest,
            )
        planner_count = max(1, planner_count or 1)
        lock = threading.Lock()
        stop_event = threading.Event()

        def claim_next_intake_path() -> Path | None:
            with lock:
                if stop_event.is_set():
                    return None
                for intake_path in sorted(
                    (p for p in session_paths.intake.iterdir()
                     if p.suffix == ".md" and p.name not in _INTAKE_META_FILES),
                    key=_claim_sort_key,
                ):
                    prefix = intake_path.name.split("_", 1)[0].split(".", 1)[0]
                    if prefix in skip_prefixes:
                        continue
                    claimed_path = session_paths.claimed / intake_path.name
                    try:
                        intake_path.replace(claimed_path)
                    except FileNotFoundError:
                        continue
                    _emit("file_claimed", {"file": intake_path.name})
                    return claimed_path
                return None

        def planner_worker() -> None:
            while not stop_event.is_set():
                claimed_path = claim_next_intake_path()
                if claimed_path is None:
                    return
                planner_task_id = f"__planner_{claimed_path.stem}__"
                _emit("planner_started", {
                    "file": claimed_path.name,
                    "planner_task_id": planner_task_id,
                })
                try:
                    plan_text = planner_agent(
                        model=pack_manifest.phases.planning.model,
                        prompt_path=pack_manifest.phases.planning.prompt,
                        intake_path=claimed_path,
                        intake_text=claimed_path.read_text(encoding="utf-8"),
                        session_root=agent_cwd,
                        pack_manifest=pack_manifest,
                    )
                    staged_plan = parse_staged_task_plan(plan_text, source=claimed_path)
                    target_dir = (
                        session_paths.review if _needs_review(staged_plan.body) else session_paths.staging
                    )
                    target_path = target_dir / f"{staged_plan.task_id}.plan.md"
                    # Guard 2: remove stale copies before writing
                    _clear_task_from_dirs(
                        staged_plan.task_id,
                        [session_paths.staging, session_paths.review, session_paths.ready],
                        exclude=target_path,
                    )
                    _atomic_write_text(target_path, plan_text)
                    claimed_path.unlink(missing_ok=True)
                    dest = "review" if target_dir == session_paths.review else "staging"
                    with lock:
                        if target_dir == session_paths.review:
                            review_task_ids.append(staged_plan.task_id)
                        else:
                            staged_task_ids.append(staged_plan.task_id)
                    _emit("file_planned", {"task_id": staged_plan.task_id, "destination": dest})
                    _emit("planner_finished", {
                        "file": claimed_path.name,
                        "planner_task_id": planner_task_id,
                    })
                except ArtifactParseError:
                    # Planner returned unparseable output.  Before creating an
                    # error entry, check whether the agent already wrote plan
                    # files directly (agent did its own file I/O).  If so, the
                    # return text is just a conversational summary — skip it.
                    task_prefix = claimed_path.stem.split("_", 1)[0]
                    agent_wrote_files = (
                        any(session_paths.staging.glob(f"{task_prefix}*.plan.md"))
                        or any(session_paths.review.glob(f"{task_prefix}*.plan.md"))
                    )
                    if agent_wrote_files:
                        # Agent handled file management itself.  Catalogue what
                        # it wrote so the pipeline accounts for the files.
                        for p in sorted(session_paths.review.glob(f"{task_prefix}*.plan.md")):
                            tid = p.name.removesuffix(".plan.md")
                            with lock:
                                if tid not in review_task_ids:
                                    review_task_ids.append(tid)
                            _emit("file_planned", {"task_id": tid, "destination": "review"})
                        for p in sorted(session_paths.staging.glob(f"{task_prefix}*.plan.md")):
                            tid = p.name.removesuffix(".plan.md")
                            with lock:
                                if tid not in staged_task_ids:
                                    staged_task_ids.append(tid)
                            _emit("file_planned", {"task_id": tid, "destination": "staging"})
                        claimed_path.unlink(missing_ok=True)
                        _emit("planner_finished", {
                            "file": claimed_path.name,
                            "planner_task_id": planner_task_id,
                        })
                    else:
                        # Genuine parse failure — send raw output to review
                        error_header = (
                            f"---\nPLAN_ID: {task_prefix}\nPRIORITY: normal\n"
                            f"ESTIMATED_SCOPE: unknown\nDEPENDS_ON: none\n"
                            f"FULL_TEST_AFTER: no\n---\n\n"
                        )
                        error_body = (
                            "## Questions for Review\n\n"
                            "1. **Planner output was unparseable.** "
                            "The raw output is preserved below for inspection.\n\n"
                            "---\n\n"
                            f"```\n{plan_text[:2000]}\n```\n"
                        )
                        review_path = session_paths.review / f"{task_prefix}.plan.md"
                        _atomic_write_text(review_path, error_header + error_body)
                        claimed_path.unlink(missing_ok=True)
                        with lock:
                            review_task_ids.append(task_prefix)
                        _emit("file_planned", {"task_id": task_prefix, "destination": "review"})
                        _emit("planner_finished", {
                            "file": claimed_path.name,
                            "planner_task_id": planner_task_id,
                        })
                except Exception as exc:
                    # Item-level failure: send to review so other items can proceed.
                    task_prefix = claimed_path.stem.split("_", 1)[0]
                    error_header = (
                        f"---\nPLAN_ID: {task_prefix}\nPRIORITY: normal\n"
                        f"ESTIMATED_SCOPE: unknown\nDEPENDS_ON: none\n"
                        f"FULL_TEST_AFTER: no\n---\n\n"
                    )
                    error_body = (
                        "## Questions for Review\n\n"
                        f"1. **Planner failed with {type(exc).__name__}.** "
                        "The error detail is preserved below for inspection.\n\n"
                        "---\n\n"
                        f"```\n{str(exc)[:2000]}\n```\n"
                    )
                    review_path = session_paths.review / f"{task_prefix}.plan.md"
                    _atomic_write_text(review_path, error_header + error_body)
                    claimed_path.unlink(missing_ok=True)
                    with lock:
                        review_task_ids.append(task_prefix)
                    _emit("file_planned", {"task_id": task_prefix, "destination": "review"})
                    _emit("planner_finished", {
                        "file": claimed_path.name,
                        "planner_task_id": planner_task_id,
                    })

        with ThreadPoolExecutor(max_workers=planner_count) as executor:
            futures = {executor.submit(planner_worker) for _ in range(planner_count)}
            for future in futures:
                future.result()
    else:
        invalid_inputs = [path.name for path in intake_paths if path.suffixes[-2:] != [".plan", ".md"]]
        if invalid_inputs:
            raise ValueError(
                "planning-disabled packs only accept intake .plan.md files: "
                + ", ".join(sorted(invalid_inputs))
            )
        for intake_path in intake_paths:
            plan_text = intake_path.read_text(encoding="utf-8")
            staged_plan = parse_staged_task_plan(plan_text, source=intake_path)
            target_path = session_paths.staging / f"{staged_plan.task_id}.plan.md"
            intake_path.replace(target_path)
            staged_task_ids.append(staged_plan.task_id)
            _emit("file_planned", {"task_id": staged_plan.task_id, "destination": "staging"})

    return PlanningPhaseResult(
        session_id=session_id,
        staged_task_ids=tuple(sorted(staged_task_ids)),
        review_task_ids=tuple(sorted(review_task_ids)),
    )


def run_resolution_phase(
    *,
    store: StateStore,
    session_id: str,
    pack_manifest: PackManifest,
    resolver_agent: ResolverAgent | None = None,
    env: dict[str, str] | None = None,
    on_pipeline_event: Callable[[str, dict], None] | None = None,
) -> ResolutionPhaseResult:
    session_paths = store.runtime_paths.session_paths(session_id)
    _recover_resolution_inputs(store=store, session_id=session_id)
    input_paths = _resolution_input_paths(session_paths)
    staged_plans: dict[str, StagedTaskPlan] = {}
    task_source_paths: dict[str, Path] = {}
    for path in input_paths:
        plan = parse_staged_task_plan(path.read_text(encoding="utf-8"), source=path)
        staged_plans[plan.task_id] = plan
        task_source_paths[plan.task_id] = path
    if not staged_plans:
        session_paths.resolution.unlink(missing_ok=True)
        return ResolutionPhaseResult(session_id=session_id)

    if on_pipeline_event is not None:
        on_pipeline_event("resolver_started", {"plan_count": len(staged_plans)})

    if pack_manifest.phases.resolution.executor == "passthrough":
        resolution = _build_passthrough_resolution(staged_plans)
        _atomic_write_text(session_paths.resolution, _serialize_resolution_graph(resolution))
    elif pack_manifest.phases.resolution.executor == "script":
        result = run_pack_hook(
            pack_manifest,
            "resolve",
            args=(str(session_paths.root),),
            cwd=session_paths.root,
            env=env,
        )
        if not result.ok:
            raise RuntimeError(f"resolve hook failed: {result.stderr or result.stdout}".strip())
        if not session_paths.resolution.is_file():
            raise RuntimeError("resolve hook did not write resolution.json")
        resolution = parse_resolution_json(
            session_paths.resolution.read_text(encoding="utf-8"),
            source=session_paths.resolution,
        )
        _atomic_write_text(session_paths.resolution, _serialize_resolution_graph(resolution))
    elif pack_manifest.phases.resolution.executor == "agent":
        if resolver_agent is None:
            raise ValueError("resolver_agent is required when agent resolution is enabled")
        if env is None or "COGNITIVE_SWITCHYARD_REPO_ROOT" not in env:
            raise ValueError(
                "COGNITIVE_SWITCHYARD_REPO_ROOT is required in env when agent resolution is enabled"
            )
        # Use repo root for agent cwd so the resolver can read the actual codebase.
        resolver_cwd = Path(env["COGNITIVE_SWITCHYARD_REPO_ROOT"])
        try:
            resolution_text = resolver_agent(
                model=pack_manifest.phases.resolution.model,
                prompt_path=pack_manifest.phases.resolution.prompt,
                session_root=resolver_cwd,
                staged_plans=tuple(staged_plans.values()),
                plan_paths=input_paths,
                pack_manifest=pack_manifest,
            )
        except (ClaudeCliRuntimeError, Exception) as exc:
            # Agent resolver failed (API error, timeout, etc.).  Move all
            # staged plans to review so the pipeline can continue on the
            # next run instead of crashing the session.
            _logger.error("Resolution agent failed: %s", exc)
            if on_pipeline_event is not None:
                on_pipeline_event("resolver_error", {"error": str(exc)})
            for task_id, source_path in task_source_paths.items():
                if source_path.exists():
                    review_dest = session_paths.review / source_path.name
                    source_path.replace(review_dest)
            return ResolutionPhaseResult(
                session_id=session_id,
                conflicts=(f"Resolution agent failed: {exc}",),
            )
        _atomic_write_text(session_paths.resolution, resolution_text)
        resolution = parse_resolution_json(
            session_paths.resolution.read_text(encoding="utf-8"),
            source=session_paths.resolution,
        )
        _atomic_write_text(session_paths.resolution, _serialize_resolution_graph(resolution))
    else:
        raise ValueError(
            f"Unsupported resolution executor: {pack_manifest.phases.resolution.executor!r}"
        )

    conflicts = list(resolution.conflicts)

    # The resolver may use filename-derived IDs (e.g. "001_reprocess_pipeline_recovery")
    # while staged plans use the PLAN_ID metadata field (e.g. "001").  Build a mapping
    # from filename stems to canonical PLAN_IDs so we can normalize.
    _stem_to_plan_id: dict[str, str] = {}
    for plan_id, src_path in task_source_paths.items():
        stem = src_path.stem  # e.g. "001_reprocess_pipeline_recovery.plan" → need .plan removed
        if stem.endswith(".plan"):
            stem = stem[: -len(".plan")]
        _stem_to_plan_id[stem] = plan_id

    def _normalize_task_id(tid: str) -> str:
        """Map a resolution task_id to the canonical staged-plan PLAN_ID."""
        if tid in staged_plans:
            return tid
        return _stem_to_plan_id.get(tid, tid)

    resolved_by_id = {_normalize_task_id(task.task_id): task for task in resolution.tasks}

    # Identify tasks that cannot advance: missing from resolution, or flagged by
    # resolution-level conflicts (unknown/circular dependencies).
    tainted_task_ids: set[str] = set()

    missing = sorted(task_id for task_id in staged_plans if task_id not in resolved_by_id)
    if missing:
        conflicts.append("unresolved plans: " + ", ".join(missing))
        tainted_task_ids.update(missing)

    # Parse per-task conflict strings to find affected task IDs (e.g.
    # "unknown dependency 999 referenced by 036", "circular dependency detected at 036").
    _REFERENCED_BY_RE = re.compile(r"referenced by (\S+)")
    _CIRCULAR_AT_RE = re.compile(r"circular dependency detected at (\S+)")
    for conflict_msg in resolution.conflicts:
        for pattern in (_REFERENCED_BY_RE, _CIRCULAR_AT_RE):
            m = pattern.search(conflict_msg)
            if m:
                tainted_task_ids.add(_normalize_task_id(m.group(1)))

    # Move tainted tasks to review so they don't block the pipeline.
    for task_id in sorted(tainted_task_ids):
        source_path = task_source_paths.get(task_id)
        if source_path is not None and source_path.exists():
            review_dest = session_paths.review / source_path.name
            source_path.replace(review_dest)
            if on_pipeline_event is not None:
                reason = "not included in resolution graph" if task_id in missing else "resolution conflict"
                on_pipeline_event("file_review", {"task_id": task_id, "reason": reason})

    ready_task_ids: list[str] = []
    for task_id, resolution_task in sorted(
        resolved_by_id.items(),
        key=lambda item: (item[1].exec_order, item[0]),
    ):
        if task_id in tainted_task_ids:
            continue
        staged_plan = staged_plans.get(task_id)
        if staged_plan is None:
            continue
        ready_text = rewrite_staged_plan_as_ready(
            staged_plan,
            depends_on=resolution_task.depends_on,
            anti_affinity=resolution_task.anti_affinity,
            exec_order=resolution_task.exec_order,
        )
        ready_path = session_paths.ready / f"{task_id}.plan.md"
        # Guard 3: remove stale copies before writing to ready/
        _clear_task_from_dirs(
            task_id,
            [session_paths.review, session_paths.staging, session_paths.done],
            exclude=ready_path,
        )
        _atomic_write_text(ready_path, ready_text)
        source_path = task_source_paths.get(task_id)
        if source_path is not None and source_path.exists() and source_path != ready_path:
            source_path.unlink(missing_ok=True)
        plan = parse_task_plan(ready_text, source=ready_path)
        store.upsert_ready_task_plan(
            session_id=session_id,
            plan=plan,
            plan_text=ready_text,
            created_at=_timestamp(),
        )
        ready_task_ids.append(task_id)
        if on_pipeline_event is not None:
            on_pipeline_event("file_resolved", {"task_id": task_id})

    # Clean up any remaining source files for resolved tasks
    resolved_source_paths = {task_source_paths[tid] for tid in ready_task_ids if tid in task_source_paths}
    for staged_path in session_paths.staging.glob("*.plan.md"):
        if staged_path in resolved_source_paths:
            staged_path.unlink(missing_ok=True)

    if on_pipeline_event is not None:
        on_pipeline_event("resolver_finished", {"ready_count": len(ready_task_ids)})

    return ResolutionPhaseResult(
        session_id=session_id,
        ready_task_ids=tuple(ready_task_ids),
        conflicts=tuple(conflicts) if conflicts else (),
    )


def rewrite_staged_plan_as_ready(
    staged_plan: StagedTaskPlan,
    *,
    depends_on: tuple[str, ...],
    anti_affinity: tuple[str, ...],
    exec_order: int,
) -> str:
    metadata = dict(staged_plan.metadata)
    metadata["PLAN_ID"] = staged_plan.task_id
    metadata["DEPENDS_ON"] = ", ".join(depends_on) if depends_on else "none"
    metadata["ANTI_AFFINITY"] = ", ".join(anti_affinity) if anti_affinity else "none"
    metadata["EXEC_ORDER"] = str(exec_order)
    metadata["FULL_TEST_AFTER"] = "yes" if staged_plan.full_test_after else "no"

    ordered_keys = [
        "PLAN_ID",
        *[
            key
            for key in metadata
            if key not in {"PLAN_ID", "DEPENDS_ON", "ANTI_AFFINITY", "EXEC_ORDER", "FULL_TEST_AFTER"}
        ],
        "DEPENDS_ON",
        "ANTI_AFFINITY",
        "EXEC_ORDER",
        "FULL_TEST_AFTER",
    ]
    front_matter_lines = ["---"]
    for key in ordered_keys:
        front_matter_lines.append(f"{key}: {metadata[key]}")
    front_matter_lines.append("---")
    return "\n".join(front_matter_lines) + "\n\n" + staged_plan.body.strip() + "\n"


def _build_passthrough_resolution(
    staged_plans: dict[str, StagedTaskPlan],
) -> ResolutionGraph:
    conflicts: list[str] = []
    visiting: set[str] = set()
    depth_cache: dict[str, int] = {}

    def depth(task_id: str) -> int:
        if task_id in depth_cache:
            return depth_cache[task_id]
        if task_id in visiting:
            conflicts.append(f"circular dependency detected at {task_id}")
            return 1
        visiting.add(task_id)
        staged_plan = staged_plans[task_id]
        depths = []
        for dependency_id in staged_plan.declared_depends_on:
            if dependency_id not in staged_plans:
                conflicts.append(f"unknown dependency {dependency_id} referenced by {task_id}")
                continue
            depths.append(depth(dependency_id))
        visiting.remove(task_id)
        value = (max(depths) if depths else 0) + 1
        depth_cache[task_id] = value
        return value

    tasks = []
    for task_id in sorted(staged_plans):
        staged_plan = staged_plans[task_id]
        tasks.append(
            ResolutionTask(
                task_id=task_id,
                depends_on=staged_plan.declared_depends_on,
                anti_affinity=(),
                exec_order=depth(task_id),
            )
        )
    return ResolutionGraph(
        resolved_at=_timestamp(),
        tasks=tuple(tasks),
        groups=(),
        conflicts=tuple(dict.fromkeys(conflicts)),
        notes="passthrough resolution",
    )


def _recover_claimed_items(session_paths) -> None:
    for claimed_path in sorted(session_paths.claimed.iterdir(), key=_claim_sort_key):
        target_path = session_paths.intake / claimed_path.name
        claimed_path.replace(target_path)


def _recover_resolution_inputs(*, store: StateStore, session_id: str) -> None:
    session_paths = store.runtime_paths.session_paths(session_id)
    session_paths.resolution.unlink(missing_ok=True)
    for ready_path in sorted(session_paths.ready.glob("*.plan.md")):
        task_id = ready_path.name.removesuffix(".plan.md")
        staged_path = session_paths.staging / ready_path.name
        if not staged_path.exists():
            ready_path.replace(staged_path)
        else:
            ready_path.unlink(missing_ok=True)
        store.delete_task(session_id, task_id)


def _resolution_input_paths(session_paths) -> tuple[Path, ...]:
    staging_paths = tuple(sorted(session_paths.staging.glob("*.plan.md")))
    ready_paths = tuple(sorted(session_paths.ready.glob("*.plan.md")))
    return staging_paths + ready_paths


def _claim_sort_key(path: Path) -> tuple[int, str]:
    prefix = path.name.split("_", 1)[0].split(".", 1)[0]
    try:
        return int(prefix), path.name
    except ValueError:
        return 10_000_000, path.name


def _needs_review(body: str) -> bool:
    return "## Questions for Review" in body


def _task_ids_from_paths(paths) -> tuple[str, ...]:
    return tuple(
        sorted(path.name.removesuffix(".plan.md") for path in paths if path.is_file())
    )


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.replace(path)


def _serialize_resolution_graph(graph: ResolutionGraph) -> str:
    payload = {
        "resolved_at": graph.resolved_at,
        "tasks": [
            {
                "task_id": task.task_id,
                "depends_on": list(task.depends_on),
                "anti_affinity": list(task.anti_affinity),
                "exec_order": task.exec_order,
            }
            for task in graph.tasks
        ],
        "groups": [
            {
                "name": group.name,
                "type": group.type,
                "members": list(group.members),
                "shared_resources": list(group.shared_resources),
            }
            for group in graph.groups
        ],
        "conflicts": list(graph.conflicts),
        "notes": graph.notes,
    }
    return json.dumps(payload, indent=2) + "\n"


def _find_existing_plan_path(session_paths, task_id: str) -> Path | None:
    for directory in (session_paths.ready, session_paths.staging):
        candidate = directory / f"{task_id}.plan.md"
        if candidate.exists():
            return candidate
    return None


def _clear_task_from_dirs(task_id: str, dirs: list[Path], *, exclude: Path | None = None) -> list[Path]:
    """Remove files matching task_id from the given directories.

    Matches both ``{task_id}.plan.md`` and ``{task_id}_*.plan.md`` /
    ``{task_id}-*.plan.md`` patterns, consistent with how other code globs
    for task files.

    Returns the list of paths that were removed.
    """
    removed: list[Path] = []
    for directory in dirs:
        if not directory.is_dir():
            continue
        for pattern in (f"{task_id}.plan.md", f"{task_id}_*.plan.md", f"{task_id}-*.plan.md"):
            for match in directory.glob(pattern):
                if exclude is not None and match == exclude:
                    continue
                match.unlink(missing_ok=True)
                removed.append(match)
    return removed


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
