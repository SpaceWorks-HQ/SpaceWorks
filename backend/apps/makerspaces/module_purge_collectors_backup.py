"""What a `backup` module purge deletes -- deliberately very little.

Only the archives a Space Manager requested ad hoc (`backup_run IS NULL`, terminal
state) and their managed bytes. Everything else stays, with a reason:

* recipients and reservations -- sealed deployment slices and run-produced tenant
  archives are encrypted to them, and recipient-use history is tombstoned, never
  deleted;
* custody states and alarm outboxes -- deployment-local custody, recomputed from
  recipients;
* run-produced tenant archives and offsite copies -- they are the DEPLOYMENT's backup
  of this makerspace, which no tenant module governs.

Archives are outside the purge guarantee: copies already downloaded, deployment
artifacts and offsite copies are not reached by any purge.
"""

from apps.makerspaces.module_purge_collectors_single_model import _counts, _delete

TERMINAL = ("available", "failed", "expired")


def _ad_hoc_archives(makerspace):
    from apps.backup.models import BackupArchive

    return BackupArchive.objects.filter(
        scope=BackupArchive.Scope.MAKERSPACE,
        makerspace=makerspace,
        backup_run__isnull=True,
        status__in=TERMINAL,
    ).exclude(restores__isnull=False)


def backup_delete(makerspace, cursor):
    from django.core.exceptions import ValidationError
    from django.db import transaction

    from apps.backup import storage
    from apps.backup.models import BackupArchive

    if BackupArchive.objects.filter(
        makerspace=makerspace, backup_run__isnull=True,
        status__in=("pending", "running", "promoting"),
    ).exists():
        raise ValidationError("A makerspace archive is still being built; purge after it finishes.")
    rows = _ad_hoc_archives(makerspace)
    archive_ids = list(rows.values_list("pk", flat=True))
    deleted, labels = _delete(rows)
    # A crashed builder can leave objects that are absent from the row's current
    # staging key. Prefix I/O belongs after commit, outside the makerspace lock.
    def cleanup_staging():
        for archive_id in archive_ids:
            storage.delete_archive_prefix(f"backup-archives/staging/{archive_id}/")

    transaction.on_commit(cleanup_staging, robust=True)
    return _counts(model_labels=labels, backup_archives=deleted)


def backup_private_keys(makerspace, add):
    from apps.backup.storage_promotion import staging_locator

    for archive_id, key, staging in _ad_hoc_archives(makerspace).values_list(
        "pk", "object_key", "staging_object_key",
    ):
        add(key)
        add(staging_locator(archive_id))
        if staging:
            add(staging)
