from __future__ import annotations

import json
import shutil
import unittest.mock
from pathlib import Path

import pytest

from cognitive_switchyard.config import build_runtime_paths
from cognitive_switchyard.models import SessionEvent, TaskPlan
from cognitive_switchyard.state import StateStore, initialize_state_store


def _read_fixture(repo_root: Path, relative_path: str) -> str:
    return (repo_root / relative_path).read_text(encoding="utf-8")


def _build_store(tmp_path: Path) -> tuple[StateStore, object]:
    runtime_paths = build_runtime_paths(home=tmp_path)
    store = initialize_state_store(runtime_paths)
    return store, runtime_paths


def _copy_runtime_pack(repo_root: Path, runtime_paths, pack_name: str) -> None:
    source = repo_root / "tests" / "fixtures" / "packs" / pack_name
    target = runtime_paths.packs / pack_name
    shutil.copytree(source, target)


def test_initialize_state_store_is_idempotent(tmp_path: Path) -> None:
    runtime_paths = build_runtime_paths(home=tmp_path)

    first = initialize_state_store(runtime_paths)
    second = initialize_state_store(runtime_paths)

    assert first.database_path == runtime_paths.database
    assert second.database_path == runtime_paths.database
    assert runtime_paths.database.exists()
    assert runtime_paths.sessions.exists()


def test_create_session_materializes_canonical_session_layout(tmp_path: Path) -> None:
    store, runtime_paths = _build_store(tmp_path)

    session = store.create_session(
        session_id="session-003",
        name="Packet 03 session",
        pack="valid_shell_pack",
        created_at="2026-03-09T10:00:00Z",
    )
    session_paths = runtime_paths.session_paths(session.id)

    assert session.id == "session-003"
    assert session.status == "created"
    assert session_paths.root.exists()
    assert session_paths.ready.exists()
    assert session_paths.logs.exists()
    assert session_paths.worker_logs.exists()
    assert session_paths.resolution == session_paths.root / "resolution.json"
    assert session_paths.session_log == session_paths.logs / "session.log"
    assert session_paths.verify_log == session_paths.logs / "verify.log"
    assert session_paths.worker_log(2) == session_paths.worker_logs / "2.log"


def test_session_config_json_round_trips_through_session_records(tmp_path: Path) -> None:
    store, _runtime_paths = _build_store(tmp_path)
    config_payload = {
        "worker_count": 1,
        "verification_interval": 2,
        "task_idle": 45,
        "environment": {"API_MODE": "repair"},
    }

    created = store.create_session(
        session_id="session-11c-config",
        name="Packet 11C config",
        pack="valid_shell_pack",
        created_at="2026-03-09T10:00:00Z",
        config_json=json.dumps(config_payload, sort_keys=True),
    )

    fetched = store.get_session(created.id)
    listed = store.list_sessions()

    assert json.loads(created.config_json or "{}") == config_payload
    assert json.loads(fetched.config_json or "{}") == config_payload
    assert len(listed) == 1
    assert json.loads(listed[0].config_json or "{}") == config_payload


def test_register_task_plan_persists_scheduler_fields(
    tmp_path: Path, repo_root: Path
) -> None:
    store, runtime_paths = _build_store(tmp_path)
    store.create_session(
        session_id="session-003",
        name="Packet 03 session",
        pack="valid_shell_pack",
        created_at="2026-03-09T10:00:00Z",
    )
    plan_text = _read_fixture(
        repo_root, "tests/fixtures/tasks/plan_with_constraints.plan.md"
    )
    plan = TaskPlan(
        task_id="039",
        title="Fix chunk progress counter double-counting during cross-model verification",
        depends_on=("021d", "022"),
        anti_affinity=("043",),
        exec_order=7,
        full_test_after=True,
        body="## Problem\n\nProgress can exceed 100% during verification.\n",
    )

    task = store.register_task_plan(
        session_id="session-003",
        plan=plan,
        plan_text=plan_text,
        created_at="2026-03-09T10:01:00Z",
    )
    ready_tasks = store.list_ready_tasks("session-003")
    task_path = runtime_paths.session_paths("session-003").ready / "039.plan.md"

    assert task.task_id == "039"
    assert task.depends_on == ("021d", "022")
    assert task.anti_affinity == ("043",)
    assert task.exec_order == 7
    assert task.full_test_after is True
    assert task.status == "ready"
    assert task.plan_path == task_path
    assert ready_tasks == (task,)
    assert task_path.read_text(encoding="utf-8") == plan_text


def test_register_task_plan_rejects_missing_session_without_writing_plan_file(
    tmp_path: Path, repo_root: Path
) -> None:
    store, runtime_paths = _build_store(tmp_path)
    plan_text = _read_fixture(
        repo_root, "tests/fixtures/tasks/plan_with_constraints.plan.md"
    )
    plan = TaskPlan(
        task_id="039",
        title="Fix chunk progress counter double-counting during cross-model verification",
    )

    with pytest.raises(KeyError, match="Unknown session: session-003"):
        store.register_task_plan(
            session_id="session-003",
            plan=plan,
            plan_text=plan_text,
            created_at="2026-03-09T10:01:00Z",
        )

    task_path = runtime_paths.session_paths("session-003").ready / "039.plan.md"
    assert not task_path.exists()
    assert not runtime_paths.session_paths("session-003").root.exists()


def test_register_task_plan_rejects_duplicate_task_without_overwriting_plan(
    tmp_path: Path, repo_root: Path
) -> None:
    store, runtime_paths = _build_store(tmp_path)
    store.create_session(
        session_id="session-003",
        name="Packet 03 session",
        pack="valid_shell_pack",
        created_at="2026-03-09T10:00:00Z",
    )
    original_plan_text = _read_fixture(
        repo_root, "tests/fixtures/tasks/plan_with_constraints.plan.md"
    )
    updated_plan_text = original_plan_text + "\nDuplicate write should not land.\n"
    plan = TaskPlan(
        task_id="039",
        title="Fix chunk progress counter double-counting during cross-model verification",
    )

    store.register_task_plan(
        session_id="session-003",
        plan=plan,
        plan_text=original_plan_text,
        created_at="2026-03-09T10:01:00Z",
    )

    with pytest.raises(KeyError, match="Task already exists: session-003/039"):
        store.register_task_plan(
            session_id="session-003",
            plan=plan,
            plan_text=updated_plan_text,
            created_at="2026-03-09T10:02:00Z",
        )

    task_path = runtime_paths.session_paths("session-003").ready / "039.plan.md"
    assert task_path.read_text(encoding="utf-8") == original_plan_text


def test_project_task_between_ready_worker_done_and_blocked_states(
    tmp_path: Path, repo_root: Path
) -> None:
    store, runtime_paths = _build_store(tmp_path)
    store.create_session(
        session_id="session-003",
        name="Packet 03 session",
        pack="valid_shell_pack",
        created_at="2026-03-09T10:00:00Z",
    )
    plan_text = _read_fixture(
        repo_root, "tests/fixtures/tasks/plan_with_constraints.plan.md"
    )
    plan = TaskPlan(
        task_id="039",
        title="Fix chunk progress counter double-counting during cross-model verification",
        depends_on=("021d", "022"),
        anti_affinity=("043",),
        exec_order=7,
        full_test_after=True,
        body="## Problem\n\nProgress can exceed 100% during verification.\n",
    )
    store.register_task_plan(
        session_id="session-003",
        plan=plan,
        plan_text=plan_text,
        created_at="2026-03-09T10:01:00Z",
    )

    active = store.project_task(
        "session-003",
        "039",
        status="active",
        worker_slot=1,
        timestamp="2026-03-09T10:02:00Z",
    )
    active_path = runtime_paths.session_paths("session-003").workers / "1" / "039.plan.md"
    assert active.status == "active"
    assert active.worker_slot == 1
    assert active.plan_path == active_path
    assert active_path.exists()
    assert store.list_ready_tasks("session-003") == ()
    assert store.list_active_tasks("session-003") == (active,)
    assert store.list_worker_slots("session-003")[0].current_task_id == "039"

    done = store.project_task(
        "session-003",
        "039",
        status="done",
        timestamp="2026-03-09T10:03:00Z",
    )
    done_path = runtime_paths.session_paths("session-003").done / "039.plan.md"
    assert done.status == "done"
    assert done.worker_slot is None
    assert done.plan_path == done_path
    assert done_path.exists()
    assert store.list_active_tasks("session-003") == ()
    assert store.list_done_tasks("session-003") == (done,)
    assert store.list_worker_slots("session-003")[0].status == "idle"

    blocked = store.project_task(
        "session-003",
        "039",
        status="blocked",
        timestamp="2026-03-09T10:04:00Z",
    )
    blocked_path = runtime_paths.session_paths("session-003").blocked / "039.plan.md"
    assert blocked.status == "blocked"
    assert blocked.plan_path == blocked_path
    assert blocked_path.exists()
    assert store.get_task("session-003", "039") == blocked


def test_successful_session_summary_round_trips_and_trim_preserves_only_history_artifacts(
    tmp_path: Path, repo_root: Path
) -> None:
    store, runtime_paths = _build_store(tmp_path)
    _copy_runtime_pack(repo_root, runtime_paths, "valid_shell_pack")
    session = store.create_session(
        session_id="session-12a-summary",
        name="Packet 12A summary",
        pack="valid_shell_pack",
        created_at="2026-03-09T10:00:00Z",
        config_json=json.dumps({"worker_count": 1}, sort_keys=True),
    )
    plan_text = _read_fixture(
        repo_root, "tests/fixtures/tasks/plan_with_constraints.plan.md"
    )
    plan = TaskPlan(task_id="039", title="Trim me")
    store.register_task_plan(
        session_id=session.id,
        plan=plan,
        plan_text=plan_text,
        created_at="2026-03-09T10:01:00Z",
    )
    store.project_task(
        session.id,
        "039",
        status="done",
        timestamp="2026-03-09T10:02:00Z",
    )
    session_paths = runtime_paths.session_paths(session.id)
    session_paths.intake.joinpath("draft.md").write_text("# draft\n", encoding="utf-8")
    session_paths.claimed.joinpath("claimed.plan.md").write_text("# claimed\n", encoding="utf-8")
    session_paths.staging.joinpath("staged.plan.md").write_text("# staged\n", encoding="utf-8")
    session_paths.review.joinpath("review.plan.md").write_text("# review\n", encoding="utf-8")
    session_paths.ready.joinpath("ready.plan.md").write_text("# ready\n", encoding="utf-8")
    session_paths.worker_dir(0).mkdir(parents=True, exist_ok=True)
    session_paths.worker_dir(0).joinpath("worker.plan.md").write_text("# active\n", encoding="utf-8")
    session_paths.blocked.joinpath("blocked.plan.md").write_text("# blocked\n", encoding="utf-8")
    session_paths.worker_log(0).parent.mkdir(parents=True, exist_ok=True)
    session_paths.worker_log(0).write_text("worker log\n", encoding="utf-8")
    session_paths.verify_log.write_text("verify log\n", encoding="utf-8")
    session_paths.resolution.write_text('{"tasks":[]}\n', encoding="utf-8")
    store.append_event(
        session.id,
        timestamp="2026-03-09T10:03:00Z",
        event_type="session.completed",
        message="All tasks completed successfully.",
    )
    store.update_session_status(
        session.id,
        status="completed",
        started_at="2026-03-09T10:00:30Z",
        completed_at="2026-03-09T10:03:00Z",
    )

    summary = store.write_successful_session_summary(session.id)
    reread_summary = store.read_session_summary(session.id)

    assert summary == reread_summary
    assert summary["session"]["id"] == session.id
    assert summary["session"]["status"] == "completed"
    assert summary["session"]["config"] == {"worker_count": 1}
    assert summary["session"]["effective_runtime_config"] == {
        "worker_count": 1,
        "verification_interval": 4,
        "timeouts": {
            "task_idle": 420,
            "task_max": 0,
            "session_max": 14400,
        },
        "auto_fix": {
            "enabled": False,
            "max_attempts": 2,
        },
        "poll_interval": 0.05,
        "environment": {},
    }
    assert summary["session"]["duration_seconds"] == 150
    assert summary["tasks"] == [
        {
            "task_id": "039",
            "title": "Trim me",
            "status": "done",
            "depends_on": [],
            "anti_affinity": [],
            "exec_order": 1,
            "full_test_after": False,
            "created_at": "2026-03-09T10:01:00Z",
            "started_at": None,
            "completed_at": "2026-03-09T10:02:00Z",
        }
    ]
    assert summary["artifacts"] == {
        "summary_path": "summary.json",
        "resolution_path": "resolution.json",
        "session_log_path": "logs/session.log",
    }

    store.trim_successful_session_artifacts(session.id)
    store.trim_successful_session_artifacts(session.id)

    kept_files = sorted(
        path.relative_to(session_paths.root).as_posix()
        for path in session_paths.root.rglob("*")
        if path.is_file()
    )
    assert kept_files == [
        "logs/session.log",
        "resolution.json",
        "summary.json",
    ]
    assert not session_paths.intake.exists()
    assert not session_paths.worker_logs.exists()
    assert store.read_session_summary(session.id) == summary


def test_project_task_rejects_worker_slot_outside_active_state(
    tmp_path: Path, repo_root: Path
) -> None:
    store, runtime_paths = _build_store(tmp_path)
    store.create_session(
        session_id="session-003",
        name="Packet 03 session",
        pack="valid_shell_pack",
        created_at="2026-03-09T10:00:00Z",
    )
    plan_text = _read_fixture(
        repo_root, "tests/fixtures/tasks/plan_with_constraints.plan.md"
    )
    plan = TaskPlan(
        task_id="039",
        title="Fix chunk progress counter double-counting during cross-model verification",
    )
    task = store.register_task_plan(
        session_id="session-003",
        plan=plan,
        plan_text=plan_text,
        created_at="2026-03-09T10:01:00Z",
    )

    with pytest.raises(
        ValueError,
        match="worker_slot is only valid when status is active",
    ):
        store.project_task("session-003", "039", status="ready", worker_slot=1)

    assert store.get_task("session-003", "039") == task
    assert task.plan_path == runtime_paths.session_paths("session-003").ready / "039.plan.md"


def test_append_and_list_session_events_in_timestamp_order(tmp_path: Path) -> None:
    store, _runtime_paths = _build_store(tmp_path)
    store.create_session(
        session_id="session-003",
        name="Packet 03 session",
        pack="valid_shell_pack",
        created_at="2026-03-09T10:00:00Z",
    )

    later = store.append_event(
        "session-003",
        timestamp="2026-03-09T10:03:00Z",
        event_type="task.done",
        message="Task 039 completed.",
        task_id="039",
    )
    earlier = store.append_event(
        "session-003",
        timestamp="2026-03-09T10:01:00Z",
        event_type="session.created",
        message="Session initialized.",
    )

    assert later == SessionEvent(
        session_id="session-003",
        timestamp="2026-03-09T10:03:00Z",
        event_type="task.done",
        task_id="039",
        message="Task 039 completed.",
    )
    assert store.list_events("session-003") == (
        earlier,
        later,
    )


def test_write_session_runtime_state_persists_verification_and_auto_fix_fields(tmp_path: Path) -> None:
    store, _runtime_paths = _build_store(tmp_path)
    session = store.create_session(
        session_id="session-009-runtime-state",
        name="Packet 09 runtime state",
        pack="valid_shell_pack",
        created_at="2026-03-09T10:00:00Z",
    )

    runtime_state = store.write_session_runtime_state(
        session.id,
        completed_since_verification=3,
        verification_pending=True,
        verification_reason="full_test_after",
        auto_fix_context="verification_failure",
        auto_fix_task_id=None,
        auto_fix_attempt=2,
        last_fix_summary="Updated failing assertions.",
    )

    assert runtime_state.completed_since_verification == 3
    assert runtime_state.verification_pending is True
    assert runtime_state.verification_reason == "full_test_after"
    assert runtime_state.auto_fix_context == "verification_failure"
    assert runtime_state.auto_fix_attempt == 2
    assert store.get_session(session.id).runtime_state == runtime_state


def test_purge_expired_sessions_deletes_only_completed_or_aborted_sessions_older_than_retention(
    tmp_path: Path,
) -> None:
    store, runtime_paths = _build_store(tmp_path)
    expired_completed = store.create_session(
        session_id="session-expired-completed",
        name="Expired completed",
        pack="valid_shell_pack",
        created_at="2026-01-01T00:00:00Z",
    )
    expired_aborted = store.create_session(
        session_id="session-expired-aborted",
        name="Expired aborted",
        pack="valid_shell_pack",
        created_at="2026-01-01T00:00:00Z",
    )
    fresh_completed = store.create_session(
        session_id="session-fresh-completed",
        name="Fresh completed",
        pack="valid_shell_pack",
        created_at="2026-03-05T00:00:00Z",
    )
    active = store.create_session(
        session_id="session-active",
        name="Active session",
        pack="valid_shell_pack",
        created_at="2026-01-01T00:00:00Z",
    )

    store.update_session_status(
        expired_completed.id,
        status="completed",
        completed_at="2026-02-01T00:00:00Z",
    )
    store.update_session_status(
        expired_aborted.id,
        status="aborted",
        completed_at="2026-02-02T00:00:00Z",
    )
    store.update_session_status(
        fresh_completed.id,
        status="completed",
        completed_at="2026-03-09T00:00:00Z",
    )
    store.update_session_status(
        active.id,
        status="running",
        started_at="2026-03-09T12:00:00Z",
    )

    purged = store.purge_expired_sessions(
        retention_days=30,
        now="2026-03-10T12:00:00Z",
    )

    assert set(purged) == {
        "session-expired-completed",
        "session-expired-aborted",
    }
    assert not runtime_paths.session("session-expired-completed").exists()
    assert not runtime_paths.session("session-expired-aborted").exists()
    assert runtime_paths.session("session-fresh-completed").exists()
    assert runtime_paths.session("session-active").exists()
    assert {session.id for session in store.list_sessions()} == {
        "session-fresh-completed",
        "session-active",
    }


# --- Regression tests for code-audit fixes ---


def test_f1_append_event_writes_log_file_with_event_content(tmp_path: Path) -> None:
    """F-1 regression: append_event must write the session.log entry (order: log before DB)."""
    store, runtime_paths = _build_store(tmp_path)
    store.create_session(
        session_id="session-f1",
        name="F1 session",
        pack="valid_shell_pack",
        created_at="2026-03-09T10:00:00Z",
    )

    store.append_event(
        "session-f1",
        timestamp="2026-03-09T10:01:00Z",
        event_type="session.started",
        message="Started.",
    )
    store.append_event(
        "session-f1",
        timestamp="2026-03-09T10:02:00Z",
        event_type="task.done",
        message="Done.",
        task_id="task-001",
    )

    log_path = runtime_paths.session_paths("session-f1").session_log
    log_text = log_path.read_text(encoding="utf-8")
    assert "session.started" in log_text
    assert "Started." in log_text
    assert "task.done" in log_text
    assert "[task-001]" in log_text
    assert "Done." in log_text
    # DB must also have the events
    assert len(store.list_events("session-f1")) == 2


def test_f2_project_task_db_updated_before_file_move(tmp_path: Path, repo_root: Path) -> None:
    """F-2 regression: if file move fails, DB is already committed (DB-first ordering)."""
    store, runtime_paths = _build_store(tmp_path)
    store.create_session(
        session_id="session-f2",
        name="F2 session",
        pack="valid_shell_pack",
        created_at="2026-03-09T10:00:00Z",
    )
    plan_text = _read_fixture(repo_root, "tests/fixtures/tasks/plan_with_constraints.plan.md")
    store.register_task_plan(
        session_id="session-f2",
        plan=TaskPlan(task_id="t1", title="T1"),
        plan_text=plan_text,
        created_at="2026-03-09T10:01:00Z",
    )

    # Patch Path.replace to raise an OSError to simulate a failed file move.
    # The DB should already be committed at this point (F-2 fix).
    original_replace = Path.replace

    def _fail_replace(self: Path, target: Path) -> Path:
        raise OSError("Simulated file move failure")

    with unittest.mock.patch.object(Path, "replace", _fail_replace):
        with pytest.raises(OSError, match="Simulated file move failure"):
            store.project_task("session-f2", "t1", status="active", worker_slot=0)

    # DB should already be updated to "active" (DB-first ordering means the commit
    # happened before the file move attempt).
    task_in_db = store.get_task("session-f2", "t1")
    assert task_in_db.status == "active"


def test_f6_write_worker_recovery_metadata_creates_readable_file(tmp_path: Path) -> None:
    """F-6 regression: write_worker_recovery_metadata must produce a valid JSON file."""
    store, runtime_paths = _build_store(tmp_path)
    store.create_session(
        session_id="session-f6",
        name="F6 session",
        pack="valid_shell_pack",
        created_at="2026-03-09T10:00:00Z",
    )
    workspace = tmp_path / "ws"
    workspace.mkdir()

    store.write_worker_recovery_metadata(
        "session-f6",
        slot_number=2,
        task_id="t99",
        workspace_path=workspace,
        pid=12345,
    )

    meta = store.read_worker_recovery_metadata("session-f6", slot_number=2)
    assert meta is not None
    assert meta.task_id == "t99"
    assert meta.pid == 12345


def test_list_all_tasks_returns_tasks_across_all_statuses(
    tmp_path: Path, repo_root: Path
) -> None:
    """Carried-forward F-10 regression: list_all_tasks must return tasks in every status."""
    store, runtime_paths = _build_store(tmp_path)
    store.create_session(
        session_id="session-all",
        name="All tasks session",
        pack="valid_shell_pack",
        created_at="2026-03-09T10:00:00Z",
    )
    plan_text = _read_fixture(repo_root, "tests/fixtures/tasks/plan_with_constraints.plan.md")

    for tid in ("t1", "t2", "t3"):
        store.register_task_plan(
            session_id="session-all",
            plan=TaskPlan(task_id=tid, title=f"Task {tid}"),
            plan_text=plan_text,
            created_at="2026-03-09T10:00:00Z",
        )

    store.project_task("session-all", "t1", status="active", worker_slot=0)
    store.project_task("session-all", "t1", status="done", timestamp="2026-03-09T10:01:00Z")
    store.project_task("session-all", "t2", status="active", worker_slot=1)
    store.project_task("session-all", "t2", status="blocked", timestamp="2026-03-09T10:02:00Z")
    # t3 remains ready

    all_tasks = store.list_all_tasks("session-all")
    statuses = {t.task_id: t.status for t in all_tasks}

    assert statuses == {"t1": "done", "t2": "blocked", "t3": "ready"}
    assert len(all_tasks) == 3


def test_delete_task(tmp_path: Path) -> None:
    """delete_task removes the task row from the DB."""
    store, runtime_paths = _build_store(tmp_path)
    store.create_session(
        session_id="del-session",
        name="Delete test",
        pack="claude-code",
        created_at="2026-03-16T10:00:00Z",
    )
    plan = TaskPlan(task_id="t1", title="To delete", exec_order=1)
    store.register_task_plan(
        session_id="del-session",
        plan=plan,
        plan_text="# Plan\n",
        created_at="2026-03-16T10:00:00Z",
    )
    # Confirm task exists
    task = store.get_task("del-session", "t1")
    assert task.task_id == "t1"

    store.delete_task("del-session", "t1")

    with pytest.raises(KeyError):
        store.get_task("del-session", "t1")


def test_started_at_cleared_on_reset_to_created(tmp_path: Path) -> None:
    """Regression: started_at must be None after transitioning back to 'created'."""
    store, _ = _build_store(tmp_path)
    store.create_session(
        session_id="session-reset-1",
        name="Reset test",
        pack="claude-code",
        created_at="2026-03-16T10:00:00Z",
    )
    store.update_session_status("session-reset-1", status="running", started_at="2026-03-09T11:00:00Z")
    store.update_session_status("session-reset-1", status="created")
    session = store.get_session("session-reset-1")
    assert session.started_at is None


def test_started_at_preserved_for_non_created_transitions(tmp_path: Path) -> None:
    """started_at must survive transitions to non-'created' statuses."""
    store, _ = _build_store(tmp_path)
    store.create_session(
        session_id="session-reset-2",
        name="Preserve test",
        pack="claude-code",
        created_at="2026-03-16T10:00:00Z",
    )
    store.update_session_status("session-reset-2", status="running", started_at="2026-03-09T11:00:00Z")
    store.update_session_status("session-reset-2", status="paused")
    session = store.get_session("session-reset-2")
    assert session.started_at == "2026-03-09T11:00:00Z"
