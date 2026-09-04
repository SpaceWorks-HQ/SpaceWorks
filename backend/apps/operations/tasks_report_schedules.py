from celery import shared_task

from apps.operations.report_schedule_services import run_report_schedules


@shared_task(name="apps.operations.tasks_report_schedules.run_report_schedules_task")
def run_report_schedules_task():
    return run_report_schedules()
