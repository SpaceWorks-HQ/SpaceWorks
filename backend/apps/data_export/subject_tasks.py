"""Celery and beat-less recovery for personal exports."""

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from apps.accounts import rbac
from apps.audit import services as audit
from apps.tenant_migration.gate_runtime import fanout_tenant_write

from . import services
from .models import DataExportJob
from .subject_services import SUBJECT_FIDELITY, run_subject_export


@shared_task(max_retries=0)
def run_subject_export_task(job_id):
    run_subject_export(job_id)


@shared_task(max_retries=0)
def sweep_subject_exports_task():
    counts = {"processed": 0, "skipped": 0}
    jobs = rbac.scope_for_scheduled_work(DataExportJob.objects.filter(
        fidelity=SUBJECT_FIDELITY,
        status__in=(DataExportJob.Status.PENDING, DataExportJob.Status.RUNNING),
        expires_at__gt=timezone.now(),
    )).order_by("created_at")[:20]
    for job in jobs:
        with fanout_tenant_write(job.makerspace_id, operation="subject_export_recovery",
                                counts=counts) as process:
            if not process:
                continue
            if job.status == DataExportJob.Status.RUNNING:
                if job.deadline_at and job.deadline_at < timezone.now():
                    with transaction.atomic():
                        locked = rbac.scope_for_scheduled_work(
                            DataExportJob.objects.all(), makerspace_id=job.makerspace_id,
                        ).select_for_update().get(pk=job.pk)
                        if locked.status == "running" and locked.deadline_at < timezone.now():
                            services._fail_job(locked, DataExportJob.FailureCode.DEADLINE_EXCEEDED,
                                               "The personal export worker deadline expired.",
                                               queryset=rbac.scope_for_scheduled_work(
                                                   DataExportJob.objects.all(), makerspace_id=job.makerspace_id,
                                               ))
                            audit.record(locked.requested_by, "subject_export.failed",
                                         makerspace=locked.makerspace, target=locked,
                                         meta={"failure_code": DataExportJob.FailureCode.DEADLINE_EXCEEDED})
                continue
            if job.expires_at > timezone.now():
                run_subject_export(job.pk)
                counts["processed"] += 1
    return counts
