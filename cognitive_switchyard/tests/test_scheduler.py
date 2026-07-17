from __future__ import annotations

from cognitive_switchyard.models import ScheduledTask
from cognitive_switchyard.scheduler import is_task_eligible, select_next_task


def _task(
    task_id: str,
    *,
    depends_on: tuple[str, ...] = (),
    anti_affinity: tuple[str, ...] = (),
    exec_order: int = 1,
    full_test_after: bool = False,
) -> ScheduledTask:
    return ScheduledTask(
        task_id=task_id,
        title=f"Task {task_id}",
        depends_on=depends_on,
        anti_affinity=anti_affinity,
        exec_order=exec_order,
        full_test_after=full_test_after,
    )


def test_dependencies_block_until_all_upstream_tasks_are_done() -> None:
    task = _task("039", depends_on=("021d", "022"))

    assert is_task_eligible(task, completed_task_ids={"021d"}, active_task_ids=set()) is False
    assert (
        is_task_eligible(task, completed_task_ids={"021d", "022"}, active_task_ids=set()) is True
    )


def test_active_anti_affinity_peers_block_execution() -> None:
    task = _task("039", anti_affinity=("043",))

    assert is_task_eligible(task, completed_task_ids=set(), active_task_ids={"043"}) is False
    assert is_task_eligible(task, completed_task_ids=set(), active_task_ids={"021d"}) is True


def test_next_task_selection_is_exec_order_then_task_id() -> None:
    tasks = [
        _task("043", exec_order=2),
        _task("041", exec_order=1),
        _task("040", exec_order=1, anti_affinity=("099",)),
        _task("042", exec_order=1),
    ]

    selected = select_next_task(
        tasks,
        completed_task_ids=set(),
        active_task_ids={"099"},
    )

    assert selected is not None
    assert selected.task_id == "041"


def test_exclude_fta_skips_full_test_after_tasks() -> None:
    tasks = [
        _task("001", exec_order=1, full_test_after=True),
        _task("002", exec_order=1),
        _task("003", exec_order=1),
    ]

    # Without exclude_fta, the FTA task wins (lowest task_id).
    selected = select_next_task(tasks, completed_task_ids=set(), active_task_ids=set())
    assert selected is not None
    assert selected.task_id == "001"

    # With exclude_fta, FTA task is skipped.
    selected = select_next_task(
        tasks, completed_task_ids=set(), active_task_ids=set(), exclude_fta=True,
    )
    assert selected is not None
    assert selected.task_id == "002"


def test_exclude_fta_returns_none_when_only_fta_tasks_exist() -> None:
    tasks = [
        _task("001", exec_order=1, full_test_after=True),
    ]

    selected = select_next_task(
        tasks, completed_task_ids=set(), active_task_ids=set(), exclude_fta=True,
    )
    assert selected is None
