from celery import shared_task
from .tasks_replay import cleanup_replay_commands_task

from apps.hardware_requests.services_return_reminders import run_return_reminders


@shared_task(name="apps.hardware_requests.tasks.send_return_reminders_task")
def send_return_reminders_task():
    return run_return_reminders()
