"""Periodic re-verification of offsite copies -- the identity-free half of a restore drill.

A copy verified once can still rot, be truncated or be replaced on a cold target. This
re-reads verified copies older than `REVERIFY_AFTER` and compares them with the journal
digest again. A mismatch is not repaired silently: the row returns to `pending` so the
push uploads a fresh copy, and the event is logged critical and audited. A transport
failure proves nothing either way and only records its code.

This does NOT prove an archive restores -- that needs the platform `age` identity, which
lives only on the host.
"""

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.backup import offsite_client
from apps.backup.models import BackupDestinationUpload


logger = logging.getLogger(__name__)
REVERIFY_AFTER = timedelta(days=30)


def reverify_offsite_copies(limit=5):
    cutoff = timezone.now() - REVERIFY_AFTER
    rows = list(
        BackupDestinationUpload.objects.select_related("destination")
        .filter(
            state=BackupDestinationUpload.State.BYTES_VERIFIED,
            verified_at__lte=cutoff,
            destination__enabled=True,
            destination__retired_at__isnull=True,
        )
        .order_by("verified_at", "pk")[:limit]
    )
    checked = 0
    for row in rows:
        destination = row.destination
        try:
            s3 = offsite_client.destination_client(destination)
            offsite_client.read_back(
                s3, destination.bucket, row.remote_locator,
                expected_size=row.expected_size_bytes, expected_sha256=row.expected_sha256,
            )
        except offsite_client.OffsiteDestinationError as exc:
            if exc.code == "digest_mismatch":
                _requeue(row.pk)
            else:
                BackupDestinationUpload.objects.filter(pk=row.pk).update(
                    last_error_code=exc.code[:64]
                )
            continue
        BackupDestinationUpload.objects.filter(
            pk=row.pk, state=BackupDestinationUpload.State.BYTES_VERIFIED
        ).update(verified_at=timezone.now(), last_error_code="")
        checked += 1
    return checked


@transaction.atomic
def _requeue(upload_id):
    row = BackupDestinationUpload.objects.select_for_update().get(pk=upload_id)
    if row.state != BackupDestinationUpload.State.BYTES_VERIFIED:
        return
    row.state = BackupDestinationUpload.State.PENDING
    row.verified_at = None
    row.verified_size_bytes = None
    row.verified_sha256 = ""
    row.attempts = 0
    row.next_attempt_at = timezone.now()
    row.last_error_code = "reverify_digest_mismatch"
    row.save()
    logger.critical(
        "backup_offsite_copy_corrupted",
        extra={"destination_id": row.destination_id, "archive_id": str(row.archive_id_snapshot)},
    )
    audit.record(
        None,
        "backup.offsite_copy_corrupted",
        target=row,
        meta={"destination_id": row.destination_id, "archive_id": str(row.archive_id_snapshot)},
    )
