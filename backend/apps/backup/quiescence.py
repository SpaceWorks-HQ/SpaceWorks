"""Pause queued writers when object storage cannot supply immutable versions."""

from celery import current_app
from django.conf import settings


BACKUP_TASKS = frozenset({
    "apps.backup.tasks.run_backup_archive_task",
    "apps.backup.tasks.scheduled_deployment_backup_task",
})


class QuiescenceError(RuntimeError):
    pass


def pause_worker_consumers():
    if settings.CELERY_TASK_ALWAYS_EAGER:
        return False
    replies = current_app.control.cancel_consumer(
        current_app.conf.task_default_queue or "celery",
        reply=True,
        timeout=5,
    )
    if not replies:
        raise QuiescenceError("No Celery worker acknowledged the backup write pause.")
    return True


def assert_workers_drained():
    if settings.CELERY_TASK_ALWAYS_EAGER:
        return
    active = current_app.control.inspect(timeout=5).active()
    if active is None:
        raise QuiescenceError("Celery worker activity could not be inspected.")
    writers = [
        task.get("name", "")
        for tasks in active.values()
        for task in tasks
        if task.get("name") not in BACKUP_TASKS
    ]
    if writers:
        raise QuiescenceError(
            "Background writers did not drain before the backup snapshot: "
            + ", ".join(sorted(set(writers)))
        )


def resume_worker_consumers(paused):
    if not paused:
        return
    current_app.control.add_consumer(
        current_app.conf.task_default_queue or "celery",
        reply=True,
        timeout=5,
    )
