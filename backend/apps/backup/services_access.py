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
    if locked.status != BackupArchive.Status.AVAILABLE or locked.expires_at <= timezone.now():
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
        archive and archive.status == BackupArchive.Status.AVAILABLE
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
    archives = list(
        BackupArchive.objects.filter(expires_at__lte=timezone.now()).order_by("pk")[:limit]
    )
    deleted = 0
    for archive in archives:
        if not storage.delete_archive(archive.object_key):
            continue
        ledger = BackupArtifactLedger.objects.filter(pk=archive.pk).first()
        if ledger and ledger.state in {
            BackupArtifactLedger.State.AVAILABLE,
            BackupArtifactLedger.State.SUPERSEDED,
        }:
            mark_managed_bytes_deleted(ledger.artifact_id)
        if archive.restores.exists():
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
