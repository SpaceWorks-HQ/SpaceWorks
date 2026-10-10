from celery import shared_task

from apps.hardware_requests.replay_cleanup import cleanup_replay_commands


@shared_task(name="apps.hardware_requests.tasks_replay.cleanup_replay_commands_task")
def cleanup_replay_commands_task():
    return cleanup_replay_commands()
