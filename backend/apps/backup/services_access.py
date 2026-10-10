"""Download-token and retained-byte lifecycle for completed archives."""

import hashlib
import hmac
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit import services as audit
from apps.backup import storage
from apps.backup.artifact_ledger import mark_managed_bytes_deleted
from apps.backup.models import BackupArchive, BackupArtifactLedger


class DownloadTokenError(RuntimeError):
    pass


@transaction.atomic
def issue_download_token(archive, actor):
    locked = BackupArchive.objects.select_for_update().get(pk=archive.pk)
    if (
        locked.status != BackupArchive.Status.AVAILABLE
        or locked.expires_at is None
        or locked.expires_at <= timezone.now()
    ):
        raise ValidationError("This backup archive is not available for download.")
    raw = secrets.token_urlsafe(32)
    locked.download_token_digest = hashlib.sha256(raw.encode()).hexdigest()
    locked.download_token_expires_at = timezone.now() + timedelta(
        seconds=settings.BACKUP_DOWNLOAD_TTL_SECONDS
    )
    locked.download_token_consumed_at = None
    locked.save(update_fields=(
        "download_token_digest", "download_token_expires_at",
        "download_token_consumed_at", "updated_at",
    ))
    audit.record(
        actor, "backup.download_url_issued", makerspace=locked.makerspace,
        target=locked, meta={"archives_outside_purge_guarantee": True},
    )
    return raw, locked.download_token_expires_at


@transaction.atomic
def consume_download_token(archive_id, raw):
    archive = BackupArchive.objects.select_for_update().filter(pk=archive_id).first()
    now = timezone.now()
    expected = hashlib.sha256(raw.encode()).hexdigest()
    valid = bool(
        archive
        and archive.status == BackupArchive.Status.AVAILABLE
        and archive.expires_at
        and archive.expires_at > now
        and archive.download_token_digest and archive.download_token_consumed_at is None
        and archive.download_token_expires_at and archive.download_token_expires_at > now
        and hmac.compare_digest(archive.download_token_digest, expected)
    )
    if not valid:
        raise DownloadTokenError("The backup download is invalid, expired, or already used.")
    archive.download_token_consumed_at = now
    archive.save(update_fields=("download_token_consumed_at", "updated_at"))
    audit.record(None, "backup.downloaded", makerspace=archive.makerspace, target=archive)
    return archive


def purge_expired_archives(limit=100):
    """Delete managed bytes of archives past retention.

    Rows already marked EXPIRED (kept because a restore references them) are excluded:
    re-selecting them every run let 100 of them starve every newer expired archive of
    pruning forever. Non-terminal rows are never pruned underneath a running build.
    """
    archives = list(
        BackupArchive.objects.filter(
            expires_at__lte=timezone.now(),
            status__in=(BackupArchive.Status.AVAILABLE, BackupArchive.Status.FAILED),
        ).order_by("expires_at", "pk")[:limit]
    )
    deleted = 0
    for archive in archives:
        if not storage.delete_archive(archive.object_key):
            continue
        # Single archives use a per-attempt directory; compound artifacts use one
        # file. Keep the row retryable until both staging layouts are gone.
        if not storage.delete_archive_prefix(f"backup-archives/staging/{archive.pk}/"):
            continue
        if not storage.delete_archive(storage.staging_locator(archive.pk)):
            continue
        if archive.staging_object_key and not storage.delete_archive(archive.staging_object_key):
            continue
        ledger = BackupArtifactLedger.objects.filter(pk=archive.pk).first()
        if ledger and ledger.staging_locator and not storage.delete_archive(ledger.staging_locator):
            continue
        if ledger and ledger.state in {
            BackupArtifactLedger.State.AVAILABLE,
            BackupArtifactLedger.State.SUPERSEDED,
        }:
            mark_managed_bytes_deleted(ledger.artifact_id)
        kept = archive.restores.exists()
        audit.record(
            None,
            "backup.archive_pruned",
            makerspace=archive.makerspace,
            target=archive,
            meta={
                "scope": archive.scope,
                "row_kept_for_restore_history": kept,
                "archives_outside_purge_guarantee": True,
            },
        )
        if kept:
            archive.status = BackupArchive.Status.EXPIRED
            archive.size_bytes = 0
            archive.download_token_digest = ""
            archive.download_token_expires_at = None
            archive.save(update_fields=(
                "status", "size_bytes", "download_token_digest",
                "download_token_expires_at", "updated_at",
            ))
        else:
            archive.delete()
        deleted += 1
    return deleted
