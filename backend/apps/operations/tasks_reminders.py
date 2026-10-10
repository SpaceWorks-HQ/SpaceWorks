from celery import shared_task

from apps.operations.reminder_sweeper import run_reminder_sweep


@shared_task(name="apps.operations.tasks_reminders.run_reminder_sweep_task")
def run_reminder_sweep_task():
    return run_reminder_sweep()
