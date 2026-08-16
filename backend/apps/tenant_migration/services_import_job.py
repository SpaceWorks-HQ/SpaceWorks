from collections import Counter
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.operations.models import PeriodicTaskRun
from apps.tenant_migration.models import ImportIdentityDecision, TenantImportJob


CLEANUP_LEASE_NAME = "tenant-import-expiry-cleanup-work"
CLEANUP_LEASE_DURATION = timedelta(minutes=15)
DEFAULT_CLEANUP_BATCH_SIZE = 100


@transaction.atomic
def scrub_terminal_job(job):
    """Discard per-person provenance while preserving a PII-free aggregate result."""
    locked = TenantImportJob.objects.select_for_update().get(pk=job.pk)
    if locked.status not in TenantImportJob.TERMINAL_STATUSES:
        raise ValidationError("Only a terminal tenant import job can be scrubbed.")
    if locked.scrubbed_at is not None:
        return locked

    decisions = locked.identity_decisions.all()
    resolution_counts = Counter(decisions.values_list("identity_resolution", flat=True))
    membership_counts = Counter(
        decisions.values_list("membership_disposition", flat=True)
    )
    locked.aggregate_outcome = {
        "decision_count": decisions.count(),
        "identity_resolution": {
            value: resolution_counts[value]
            for value, _label in ImportIdentityDecision.IdentityResolution.choices
        },
        "membership_disposition": {
            value: membership_counts[value]
            for value, _label in ImportIdentityDecision.MembershipDisposition.choices
        },
    }
    decisions.delete()
    locked.source_makerspace_id = ""
    locked.source_makerspace_slug = ""
    locked.source_makerspace_name = ""
    locked.source_deployment_id = ""
    locked.storage_mode = ""
    locked.scrubbed_at = timezone.now()
    locked.save(
        update_fields=(
            "aggregate_outcome",
            "source_makerspace_id",
            "source_makerspace_slug",
            "source_makerspace_name",
            "source_deployment_id",
            "storage_mode",
            "scrubbed_at",
            "updated_at",
        )
    )
    return locked


def cleanup_expired_import_jobs(*, now=None, batch_size=DEFAULT_CLEANUP_BATCH_SIZE):
    """Delete one bounded batch of expired jobs that never acquired a tenant."""
    cleanup_at = now or timezone.now()
    if not _claim_cleanup_lease(cleanup_at):
        return 0

    # The lease transaction has committed before this potentially large cascade. This
    # mirrors the beat-less scheduler's claim-then-work shape and keeps row locks short.
    job_ids = list(
        TenantImportJob.objects.filter(
            target_makerspace__isnull=True,
            expires_at__lte=cleanup_at,
        )
        .order_by("expires_at", "pk")
        .values_list("pk", flat=True)[:batch_size]
    )
    if job_ids:
        TenantImportJob.objects.filter(pk__in=job_ids).delete()
    return len(job_ids)


@transaction.atomic
def _claim_cleanup_lease(now):
    row, created = PeriodicTaskRun.objects.select_for_update().get_or_create(
        name=CLEANUP_LEASE_NAME,
        defaults={"last_run_at": now},
    )
    if not created and now - row.last_run_at < CLEANUP_LEASE_DURATION:
        return False
    if not created:
        row.last_run_at = now
        row.save(update_fields=("last_run_at",))
    return True
