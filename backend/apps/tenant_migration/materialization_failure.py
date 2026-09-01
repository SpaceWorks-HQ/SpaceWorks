"""Failure classification and cleanup for tenant materialization."""

from django.utils import timezone

from apps.encryption.cache import dek_cache

from .insertion_errors import (
    ImportCompletionAuditError,
    ImportPromotionClaimLost,
    ImportPromotionInProgress,
    MaterializationAlreadyCommitted,
)
from .models_import_job import TenantImportJob
from .object_import import rollback_import_objects


_NON_CLEANUP_FAILURES = (
    ImportCompletionAuditError,
    ImportPromotionClaimLost,
    ImportPromotionInProgress,
    MaterializationAlreadyCommitted,
)


def handle_materialization_failure(*, job, target, error):
    """Clean owned partial work, or preserve work owned by another execution."""
    if isinstance(error, _NON_CLEANUP_FAILURES):
        return

    now = timezone.now()
    failed_active = TenantImportJob.objects.filter(
        pk=job.pk,
        status__in=(
            TenantImportJob.Status.MATERIALIZING,
            TenantImportJob.Status.FINALIZING,
        ),
    ).update(
        status=TenantImportJob.Status.FAILED,
        terminal_at=now,
        updated_at=now,
    )
    if not failed_active:
        # A replacement that completed the import owns its objects. Other states
        # represent an ordinary failure and must preserve the original error.
        if TenantImportJob.objects.filter(
            pk=job.pk, status=TenantImportJob.Status.COMPLETED
        ).exists():
            raise ImportPromotionClaimLost(
                "The import execution was superseded before failure cleanup."
            ) from error
        return

    if target is not None:
        dek_cache.invalidate(target.pk)
    rollback_job = TenantImportJob.objects.select_related(
        "target_makerspace", "actor"
    ).get(pk=job.pk)
    rollback_import_objects(rollback_job)
