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

    from apps.backup.models import BackupArchive

    if BackupArchive.objects.filter(
        makerspace=makerspace, backup_run__isnull=True,
        status__in=("pending", "running", "promoting"),
    ).exists():
        raise ValidationError("A makerspace archive is still being built; purge after it finishes.")
    deleted, labels = _delete(_ad_hoc_archives(makerspace))
    return _counts(model_labels=labels, backup_archives=deleted)


def backup_private_keys(makerspace, add):
    for key in _ad_hoc_archives(makerspace).values_list("object_key", flat=True):
        add(key)
