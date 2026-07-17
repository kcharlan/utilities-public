"""Regression tests for reconcile_filesystem_projection returning a structured diff
and scanning all session directories (claimed, staging, review, ready, done, blocked,
workers/). Plan 007: Add rescan button."""
from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from cognitive_switchyard.config import build_runtime_paths
from cognitive_switchyard.models import TaskPlan
from cognitive_switchyard.state import StateStore, initialize_state_store


def _build_store(tmp_path: Path) -> tuple[StateStore, object]:
    runtime_paths = build_runtime_paths(home=tmp_path)
    store = initialize_state_store(runtime_paths)
    return store, runtime_paths


def _register_task(
    store: StateStore,
    *,
    session_id: str,
    task_id: str,
) -> None:
    store.register_task_plan(
        session_id=session_id,
        plan=TaskPlan(task_id=task_id, title=f"Task {task_id}", depends_on=()),
        plan_text=dedent(
            f"""
            ---
            PLAN_ID: {task_id}
            DEPENDS_ON: none
            ANTI_AFFINITY: none
            EXEC_ORDER: 1
            FULL_TEST_AFTER: no
            ---

            # Plan: Task {task_id}
            """
        ).lstrip(),
        created_at="2026-03-09T10:00:00Z",
    )


def _create_session(store: StateStore, session_id: str) -> object:
    return store.create_session(
        session_id=session_id,
        name=f"Rescan test {session_id}",
        pack="test-pack",
        created_at="2026-03-09T10:00:00Z",
    )


def test_reconcile_returns_structured_diff_when_task_moves(tmp_path: Path) -> None:
    """reconcile_filesystem_projection returns reconciled list with old/new statuses."""
    store, runtime_paths = _build_store(tmp_path)
    session = _create_session(store, "s-reconcile-diff")
    _register_task(store, session_id=session.id, task_id="001")

    # Move file from ready → done on filesystem; DB still says ready
    session_paths = runtime_paths.session_paths(session.id)
    plan_src = session_paths.ready / "001.plan.md"
    plan_dst = session_paths.done / "001.plan.md"
    plan_src.rename(plan_dst)

    result = store.reconcile_filesystem_projection(session.id)

    assert len(result["reconciled"]) == 1
    entry = result["reconciled"][0]
    assert entry["task_id"] == "001"
    assert entry["old_status"] == "ready"
    assert entry["new_status"] == "done"
    assert result["orphaned"] == []
    assert result["unchanged"] == 0

    # DB should reflect new state
    assert store.get_task(session.id, "001").status == "done"


def test_reconcile_returns_orphaned_when_plan_file_missing(tmp_path: Path) -> None:
    """Tasks whose plan files are deleted on disk appear in orphaned list and become blocked."""
    store, runtime_paths = _build_store(tmp_path)
    session = _create_session(store, "s-orphan")
    _register_task(store, session_id=session.id, task_id="002")

    session_paths = runtime_paths.session_paths(session.id)
    (session_paths.ready / "002.plan.md").unlink()

    result = store.reconcile_filesystem_projection(session.id)

    assert result["orphaned"] == ["002"]
    assert result["reconciled"] == []
    assert store.get_task(session.id, "002").status == "blocked"


def test_reconcile_noop_returns_unchanged_count(tmp_path: Path) -> None:
    """When filesystem matches DB, reconciled and orphaned are empty, unchanged equals task count."""
    store, runtime_paths = _build_store(tmp_path)
    session = _create_session(store, "s-noop")
    _register_task(store, session_id=session.id, task_id="010")
    _register_task(store, session_id=session.id, task_id="011")

    result = store.reconcile_filesystem_projection(session.id)

    assert result["reconciled"] == []
    assert result["orphaned"] == []
    assert result["unchanged"] == 2


def test_reconcile_detects_files_in_claimed_staging_review(tmp_path: Path) -> None:
    """Files in claimed/, staging/, and review/ (not just ready/done/blocked) are detected."""
    store, runtime_paths = _build_store(tmp_path)
    session = _create_session(store, "s-new-dirs")
    _register_task(store, session_id=session.id, task_id="020")
    _register_task(store, session_id=session.id, task_id="021")
    _register_task(store, session_id=session.id, task_id="022")

    session_paths = runtime_paths.session_paths(session.id)
    # Move tasks into claimed, staging, review
    (session_paths.ready / "020.plan.md").rename(session_paths.claimed / "020.plan.md")
    (session_paths.ready / "021.plan.md").rename(session_paths.staging / "021.plan.md")
    (session_paths.ready / "022.plan.md").rename(session_paths.review / "022.plan.md")

    result = store.reconcile_filesystem_projection(session.id)

    statuses = {e["task_id"]: e["new_status"] for e in result["reconciled"]}
    assert statuses["020"] == "planning"
    assert statuses["021"] == "staged"
    assert statuses["022"] == "review"
    assert result["orphaned"] == []


def test_reconcile_clears_started_at_and_worker_slot_when_task_moves_backward(tmp_path: Path) -> None:
    """Moving a task from active back to ready clears started_at and worker_slot."""
    store, runtime_paths = _build_store(tmp_path)
    session = _create_session(store, "s-backward")
    _register_task(store, session_id=session.id, task_id="030")

    # Simulate task that was active
    store.project_task(
        session.id,
        "030",
        status="active",
        worker_slot=0,
        timestamp="2026-03-09T10:01:00Z",
    )

    # Move plan from workers/0/ back to ready/ on filesystem
    session_paths = runtime_paths.session_paths(session.id)
    (session_paths.workers / "0" / "030.plan.md").rename(session_paths.ready / "030.plan.md")

    result = store.reconcile_filesystem_projection(session.id)

    assert len(result["reconciled"]) == 1
    assert result["reconciled"][0]["old_status"] == "active"
    assert result["reconciled"][0]["new_status"] == "ready"

    task = store.get_task(session.id, "030")
    assert task.worker_slot is None
    assert task.started_at is None
