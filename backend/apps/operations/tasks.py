from celery import shared_task

from apps.makerspaces.models import Makerspace
from apps.makerspaces.servability import servable_queryset
from apps.operations.report_rollups import finalize_evidence_rollups
from apps.operations.tasks_reminders import run_reminder_sweep_task  # noqa: F401
from apps.operations.tasks_platform import run_platform_problem_checks_task
from apps.operations.tasks_admissions import sweep_membership_admissions_task  # noqa: F401


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def finalize_report_rollups_task(self):
    for makerspace in servable_queryset(Makerspace.objects.all()).iterator(chunk_size=100):
        finalize_evidence_rollups(makerspace)
