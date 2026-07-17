from __future__ import annotations

from .models import ScheduledTask


def is_task_eligible(
    task: ScheduledTask,
    *,
    completed_task_ids: set[str],
    active_task_ids: set[str],
) -> bool:
    return _dependencies_satisfied(task, completed_task_ids) and _anti_affinity_clear(
        task, active_task_ids
    )


def select_next_task(
    tasks: list[ScheduledTask] | tuple[ScheduledTask, ...],
    *,
    completed_task_ids: set[str],
    active_task_ids: set[str],
    exclude_fta: bool = False,
) -> ScheduledTask | None:
    eligible_tasks = [
        task
        for task in tasks
        if is_task_eligible(
            task,
            completed_task_ids=completed_task_ids,
            active_task_ids=active_task_ids,
        )
        and not (exclude_fta and task.full_test_after)
    ]
    if not eligible_tasks:
        return None
    return min(eligible_tasks, key=lambda task: (task.exec_order, task.task_id))


def _dependencies_satisfied(task: ScheduledTask, completed_task_ids: set[str]) -> bool:
    return all(dependency in completed_task_ids for dependency in task.depends_on)


def _anti_affinity_clear(task: ScheduledTask, active_task_ids: set[str]) -> bool:
    return all(peer not in active_task_ids for peer in task.anti_affinity)
