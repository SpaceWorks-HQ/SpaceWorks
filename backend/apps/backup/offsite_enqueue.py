"""Which archives go offsite, and the journal rows that say so.

Split out of `offsite_push`: this half decides eligibility and the integrity facts a
copy must match; `offsite_push` does the remote byte work.
"""

import logging
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.utils import timezone

from apps.backup import offsite_client
from apps.backup.models import (
    BackupArchive,
    BackupArtifactLedger,
    BackupDestination,
    BackupDestinationUpload,
)


logger = logging.getLogger(__name__)


class OffsiteIntegrityError(RuntimeError):
    pass


def active_destinations():
    return BackupDestination.objects.filter(enabled=True, retired_at__isnull=True)


def eligible_archives(now=None):
    """Deployment archives plus run-produced tenant archives; never ad-hoc tenant ones."""
    now = now or timezone.now()
    return BackupArchive.objects.filter(
        Q(scope=BackupArchive.Scope.DEPLOYMENT) | Q(backup_run__isnull=False),
        status=BackupArchive.Status.AVAILABLE,
        expires_at__gt=now,
    ).order_by("completed_at", "pk")


def expected_facts(archive):
    """Return (size, sha256, source); the artifact ledger is authoritative when present."""
    ledger = BackupArtifactLedger.objects.filter(pk=archive.pk).first()
    if ledger is None:
        if not archive.archive_sha256 or not archive.size_bytes:
            raise OffsiteIntegrityError("The archive has no recorded size and digest.")
        return (
            archive.size_bytes,
            archive.archive_sha256,
            BackupDestinationUpload.IntegritySource.ARCHIVE_ROW,
        )
    if ledger.state != BackupArtifactLedger.State.AVAILABLE:
        raise OffsiteIntegrityError("The artifact ledger does not mark the archive available.")
    if (
        ledger.outer_sha256 != archive.archive_sha256
        or ledger.expected_size_bytes != archive.size_bytes
    ):
        raise OffsiteIntegrityError("The archive row and the artifact ledger disagree.")
    return (
        ledger.expected_size_bytes,
        ledger.outer_sha256,
        BackupDestinationUpload.IntegritySource.ARTIFACT_LEDGER,
    )


def enqueue_offsite_uploads(limit=200):
    """Create one journal row per (active destination, eligible archive) pair."""
    created = 0
    destinations = list(active_destinations())
    if not destinations:
        return 0
    now = timezone.now()
    # Only archives still missing a row for some active destination: slicing the full
    # eligible set instead would let `limit` already-queued archives starve the rest.
    pending = eligible_archives(now).annotate(
        covered=Count(
            "offsite_uploads",
            filter=Q(offsite_uploads__destination__in=[row.pk for row in destinations]),
            distinct=True,
        )
    ).filter(covered__lt=len(destinations))
    for archive in pending[:limit]:
        existing = set(
            BackupDestinationUpload.objects.filter(archive_id_snapshot=archive.pk)
            .values_list("destination_id", flat=True)
        )
        missing = [row for row in destinations if row.pk not in existing]
        if not missing:
            continue
        try:
            size, sha256, source = expected_facts(archive)
        except OffsiteIntegrityError:
            logger.critical(
                "backup_offsite_integrity_refused", extra={"archive_id": str(archive.pk)}
            )
            continue
        for destination in missing:
            try:
                with transaction.atomic():
                    BackupDestinationUpload.objects.create(
                        destination=destination,
                        archive=archive,
                        archive_id_snapshot=archive.pk,
                        scope_snapshot=archive.scope,
                        makerspace_id_snapshot=archive.makerspace_id,
                        format_snapshot=str((archive.manifest or {}).get("format", ""))[:80],
                        archive_completed_at_snapshot=archive.completed_at,
                        expected_size_bytes=size,
                        expected_sha256=sha256,
                        integrity_source=source,
                        remote_locator=offsite_client.remote_locator(
                            destination, archive.pk, archive.scope
                        ),
                        next_attempt_at=now,
                        expires_at=archive.completed_at
                        + timedelta(days=destination.retention_days),
                    )
            except IntegrityError:
                continue
            created += 1
    return created
