"""Celery completion telemetry uses the same journal as the cron runner."""

import logging
from functools import lru_cache

from django.utils import timezone

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _task_names():
    from apps.operations.management.commands.run_scheduled_tasks import (
        SCHEDULED_TASKS, _import_task,
    )
    # Re-export barrels (notably offsite tasks) can have a different registered
    # Celery name than the scheduler's import path. Resolve the actual task name.
    names = {}
    for name, path, _ in SCHEDULED_TASKS:
        try:
            names[getattr(_import_task(path), "name", path)] = name
        except Exception as exc:
            # One unavailable optional task must not blind every other task.
            logger.warning("scheduler_task_unavailable", extra={
                "task_name": name, "error_type": type(exc).__name__,
            })
    return names


def record_periodic_completion(task_name, state):
    from apps.operations.models_scheduling import PeriodicTaskRun

    if state not in {"SUCCESS", "FAILURE"}:
        return
    try:
        name = _task_names().get(task_name)
        if name is None:
            return
        PeriodicTaskRun.objects.update_or_create(name=name, defaults={
            "last_run_at": timezone.now(),
            # Never persist task exception text: provider strings can contain secrets.
            "last_error": "TaskFailure" if state == "FAILURE" else "",
        })
    except Exception as exc:
        logger.warning("scheduler_telemetry_unavailable", extra={"error_type": type(exc).__name__})
