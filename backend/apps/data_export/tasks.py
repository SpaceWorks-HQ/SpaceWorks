from celery import shared_task
from django.utils import timezone

from apps.data_export.models import DataExportJob
from apps.data_export.services import run_export_job
from apps.tenant_migration.gate_runtime import fanout_tenant_write


@shared_task(bind=True, max_retries=0)
def run_data_export_task(self, job_id):
    run_export_job(job_id)


@shared_task(bind=True, max_retries=0)
def purge_expired_exports_task(self):
    expired = list(
        DataExportJob.objects.filter(expires_at__lte=timezone.now()).order_by("pk")[:100]
    )
    counts = {"deleted": 0, "skipped": 0}
    for job in expired:
        with fanout_tenant_write(
            job.makerspace_id,
            operation="expired_data_export_purge",
            counts=counts,
        ) as should_process:
            if not should_process:
                continue
            job.delete()
            counts["deleted"] += 1
    return counts
