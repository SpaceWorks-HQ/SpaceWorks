"""Bounded retention jobs for tenant-import rows, archives, and object journals."""

from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.operations.models import PeriodicTaskRun

from .archive_retention import schedule_import_archive_unlink
from .models_import_job import TenantImportJob


CLEANUP_LEASE_NAME = "tenant-import-expiry-cleanup-work"
CLEANUP_OBJECTS_LEASE_NAME = "tenant-import-object-cleanup-work"
CLEANUP_LEASE_DURATION = timedelta(minutes=15)
DEFAULT_CLEANUP_BATCH_SIZE = 100


def cleanup_expired_import_jobs(*, now=None, batch_size=DEFAULT_CLEANUP_BATCH_SIZE):
    """Delete pre-tenant jobs and expire archives retained by terminal target jobs."""
    cleanup_at = now or timezone.now()
    if not _claim_named_cleanup_lease(CLEANUP_LEASE_NAME, cleanup_at):
        return 0

    candidates = list(
        TenantImportJob.objects.filter(expires_at__lte=cleanup_at)
        .filter(
            Q(target_makerspace__isnull=True)
            | (
                Q(status__in=TenantImportJob.TERMINAL_STATUSES)
                & ~Q(archive_path="")
            )
        )
        .order_by("expires_at", "pk")
        .values("pk", "target_makerspace_id", "archive_path")[:batch_size]
    )
    delete_ids = [row["pk"] for row in candidates if row["target_makerspace_id"] is None]
    retained = [row for row in candidates if row["target_makerspace_id"] is not None]

    # Object-storage cleanup is external I/O and stays outside the deletion transaction.
    if delete_ids:
        from .object_import import rollback_import_objects

        for job in TenantImportJob.objects.filter(pk__in=delete_ids):
            rollback_import_objects(job)

    with transaction.atomic():
        for row in retained:
            updated = TenantImportJob.objects.filter(
                pk=row["pk"], archive_path=row["archive_path"]
            ).update(archive_path="", updated_at=timezone.now())
            if updated:
                schedule_import_archive_unlink(row["archive_path"], row["pk"])
        # The post_delete receiver schedules these paths only after this commit.
        TenantImportJob.objects.filter(pk__in=delete_ids).delete()
    return len(candidates)


def cleanup_abandoned_import_objects(*, now=None, batch_size=DEFAULT_CLEANUP_BATCH_SIZE):
    """Roll back a bounded batch of failed/abandoned object journals."""
    cleanup_at = now or timezone.now()
    if not _claim_named_cleanup_lease(CLEANUP_OBJECTS_LEASE_NAME, cleanup_at):
        return 0
    job_ids = list(
        TenantImportJob.objects.filter(
            Q(status__in=(TenantImportJob.Status.FAILED, TenantImportJob.Status.ABANDONED))
            | Q(
                expires_at__lte=cleanup_at,
                target_makerspace__lifecycle_state__in=("importing", "aborted"),
            ),
            import_objects__state__in=("staged", "promoted", "verified", "failed"),
        )
        .order_by("updated_at", "pk")
        .values_list("pk", flat=True)
        .distinct()[:batch_size]
    )
    from .object_import import rollback_import_objects

    for job in TenantImportJob.objects.filter(pk__in=job_ids).select_related(
        "target_makerspace", "actor"
    ):
        rollback_import_objects(job)
    return len(job_ids)


@transaction.atomic
def _claim_named_cleanup_lease(name, now):
    row, created = PeriodicTaskRun.objects.select_for_update().get_or_create(
        name=name,
        defaults={"last_run_at": now},
    )
    if not created and now - row.last_run_at < CLEANUP_LEASE_DURATION:
        return False
    if not created:
        row.last_run_at = now
        row.save(update_fields=("last_run_at",))
    return True
