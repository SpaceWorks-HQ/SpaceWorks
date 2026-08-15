from celery import shared_task
from django.utils import timezone

from apps.data_export.models import DataExportJob
from apps.data_export.services import run_export_job


@shared_task(bind=True, max_retries=0)
def run_data_export_task(self, job_id):
    run_export_job(job_id)


@shared_task(bind=True, max_retries=0)
def purge_expired_exports_task(self):
    expired = list(
        DataExportJob.objects.filter(expires_at__lte=timezone.now()).order_by("pk")[:100]
    )
    for job in expired:
        job.delete()
    return len(expired)
