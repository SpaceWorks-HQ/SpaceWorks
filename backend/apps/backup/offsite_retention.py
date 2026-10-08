"""Per-destination retention for verified offsite copies.

Each destination keeps copies for its own `retention_days`, independent of the
primary store, because a cheap cold target may keep more. One rule overrides the
window: the newest verified deployment copy, and the newest verified copy of each
tenant's run-produced archive, are never pruned from a destination. If backups stop
running, retention must not quietly empty the only offsite copy left.
"""

import logging

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.audit import services as audit
from apps.backup import offsite_client
from apps.backup.models import BackupArchive, BackupDestinationUpload


logger = logging.getLogger(__name__)


def protected_upload_ids():
    """The newest verified copy per destination and per (destination, tenant)."""
    verified = BackupDestinationUpload.objects.filter(
        state=BackupDestinationUpload.State.BYTES_VERIFIED
    )
    protected = set()
    newest = (
        verified.values("destination_id", "scope_snapshot", "makerspace_id_snapshot")
        .annotate(latest=Max("archive_completed_at_snapshot"))
    )
    for group in newest:
        row = (
            verified.filter(
                destination_id=group["destination_id"],
                scope_snapshot=group["scope_snapshot"],
                makerspace_id_snapshot=group["makerspace_id_snapshot"],
                archive_completed_at_snapshot=group["latest"],
            )
            .order_by("-pk")
            .values_list("pk", flat=True)
            .first()
        )
        if row is not None:
            protected.add(row)
    return protected


def prune_offsite_copies(limit=100):
    protected = protected_upload_ids()
    rows = list(
        BackupDestinationUpload.objects.select_related("destination")
        .filter(
            state=BackupDestinationUpload.State.BYTES_VERIFIED,
            expires_at__lte=timezone.now(),
        )
        .exclude(pk__in=protected)
        .order_by("expires_at", "pk")[:limit]
    )
    pruned = 0
    for row in rows:
        destination = row.destination
        try:
            s3 = offsite_client.destination_client(destination)
            offsite_client.delete_remote(s3, destination.bucket, row.remote_locator)
        except offsite_client.OffsiteDestinationError as exc:
            BackupDestinationUpload.objects.filter(pk=row.pk).update(
                last_error_code=exc.code[:64]
            )
            logger.warning(
                "backup_offsite_prune_failed",
                extra={"upload_id": row.pk, "destination_id": destination.pk,
                       "error_code": exc.code},
            )
            continue
        if _mark_deleted(row.pk):
            pruned += 1
    return pruned


@transaction.atomic
def _mark_deleted(upload_id):
    row = BackupDestinationUpload.objects.select_for_update().get(pk=upload_id)
    if row.state != BackupDestinationUpload.State.BYTES_VERIFIED:
        return False
    row.state = BackupDestinationUpload.State.DELETED
    row.deleted_at = timezone.now()
    row.last_error_code = ""
    row.save(update_fields=("state", "deleted_at", "last_error_code", "updated_at"))
    audit.record(
        None,
        "backup.offsite_copy_pruned",
        target=row,
        meta={
            "destination_id": row.destination_id,
            "archive_id": str(row.archive_id_snapshot),
            "scope": row.scope_snapshot,
        },
    )
    return True


def offsite_status_for(archive):
    """Per-destination copy state for one archive, for the archive serializer."""
    if archive.scope != BackupArchive.Scope.DEPLOYMENT and archive.backup_run_id is None:
        return []
    return [
        {"destination": name, "state": state, "verified_at": verified_at}
        for name, state, verified_at in BackupDestinationUpload.objects.filter(
            archive_id_snapshot=archive.pk
        ).order_by("destination__name").values_list(
            "destination__name", "state", "verified_at"
        )
    ]
