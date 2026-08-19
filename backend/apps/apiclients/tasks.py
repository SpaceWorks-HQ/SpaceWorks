from celery import shared_task

from apps.apiclients.telemetry import flush_usage_observations


@shared_task(name="apps.apiclients.tasks.flush_api_client_usage_task")
def flush_api_client_usage_task():
    return flush_usage_observations()
