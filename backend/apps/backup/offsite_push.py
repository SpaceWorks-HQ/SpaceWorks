"""Fan finished archives out to every active offsite destination and verify each copy.

The push never runs under `deployment_operation_lock` or any row lock while it talks
to a destination: a slow or dead destination must not block backup work, and an
outage is recorded on the journal row and retried with a bounded backoff. Nothing here
changes `BackupRun` or `BackupArchive` state, so a destination failure can never fail a
backup run.
"""

import logging
import uuid
from datetime import timedelta

from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.utils import timezone

from apps.audit import services as audit
from apps.backup import offsite_client, storage
from apps.backup.models import (
    BackupArchive,
    BackupArtifactLedger,
    BackupDestination,
    BackupDestinationUpload,
)


logger = logging.getLogger(__name__)
BACKOFF_BASE_SECONDS = 300
BACKOFF_CAP_SECONDS = 6 * 3600
CLAIM_SECONDS = 6 * 3600


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
    for archive in eligible_archives(now)[:limit]:
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


def push_due_uploads(limit=10):
    pushed = 0
    for upload_id in _due_ids(limit):
        holder = _claim(upload_id)
        if holder is None:
            continue
        _push_one(upload_id, holder)
        pushed += 1
    return pushed


def _due_ids(limit):
    now = timezone.now()
    return list(
        BackupDestinationUpload.objects.filter(
            Q(state=BackupDestinationUpload.State.PENDING, next_attempt_at__lte=now)
            | Q(state=BackupDestinationUpload.State.UPLOADING, claimed_until__lt=now),
            destination__enabled=True,
            destination__retired_at__isnull=True,
        )
        .order_by("next_attempt_at", "pk")
        .values_list("pk", flat=True)[:limit]
    )


@transaction.atomic
def _claim(upload_id):
    now = timezone.now()
    row = (
        BackupDestinationUpload.objects.select_for_update(skip_locked=True)
        .filter(
            Q(state=BackupDestinationUpload.State.PENDING, next_attempt_at__lte=now)
            | Q(state=BackupDestinationUpload.State.UPLOADING, claimed_until__lt=now),
            pk=upload_id,
        )
        .first()
    )
    if row is None:
        return None
    holder = uuid.uuid4()
    BackupDestinationUpload.objects.filter(pk=row.pk).update(
        state=BackupDestinationUpload.State.UPLOADING,
        holder=holder,
        claimed_until=now + timedelta(seconds=CLAIM_SECONDS),
        attempts=F("attempts") + 1,
        updated_at=now,
    )
    return holder


def _push_one(upload_id, holder):
    row = BackupDestinationUpload.objects.select_related("destination").get(pk=upload_id)
    archive = BackupArchive.objects.filter(pk=row.archive_id_snapshot).first()
    if (
        archive is None
        or archive.status != BackupArchive.Status.AVAILABLE
        or archive.expires_at is None
        or archive.expires_at <= timezone.now()
    ):
        _abandon(row, holder)
        return
    destination = row.destination
    source = None
    try:
        s3 = offsite_client.destination_client(destination)
        try:
            source = storage.client().get_object(
                Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=archive.object_key
            )["Body"]
        except (BotoCoreError, ClientError) as exc:
            raise offsite_client.OffsiteDestinationError("source_unavailable") from exc
        sent_size, sent_sha256 = offsite_client.stream_copy(
            source, s3, destination.bucket, row.remote_locator
        )
        if sent_size != row.expected_size_bytes or sent_sha256 != row.expected_sha256:
            logger.critical(
                "backup_offsite_source_digest_mismatch",
                extra={"archive_id": str(row.archive_id_snapshot)},
            )
            raise offsite_client.OffsiteDestinationError("source_digest_mismatch")
        offsite_client.put_index(s3, destination.bucket, row.remote_locator, _index_facts(row))
        size, sha256 = offsite_client.read_back(
            s3, destination.bucket, row.remote_locator,
            expected_size=row.expected_size_bytes, expected_sha256=row.expected_sha256,
        )
    except offsite_client.OffsiteDestinationError as exc:
        _record_failure(row, holder, exc.code)
        return
    except Exception:
        logger.exception(
            "backup_offsite_push_unexpected_failure",
            extra={"upload_id": row.pk, "destination_id": destination.pk},
        )
        _record_failure(row, holder, "unexpected_error")
        return
    finally:
        if source is not None and hasattr(source, "close"):
            source.close()
    _record_verified(row, holder, size, sha256)


def _index_facts(row):
    """Non-secret facts a fresh host needs to find and check a copy."""
    return {
        "archive_id": str(row.archive_id_snapshot),
        "scope": row.scope_snapshot,
        "makerspace_id": row.makerspace_id_snapshot,
        "format": row.format_snapshot,
        "completed_at": row.archive_completed_at_snapshot.isoformat(),
        "size_bytes": row.expected_size_bytes,
        "sha256": row.expected_sha256,
        "integrity_source": row.integrity_source,
    }


def backoff_seconds(attempts):
    return min(BACKOFF_BASE_SECONDS * (2 ** max(attempts - 1, 0)), BACKOFF_CAP_SECONDS)


@transaction.atomic
def _record_failure(row, holder, code):
    now = timezone.now()
    current = BackupDestinationUpload.objects.select_for_update().get(pk=row.pk)
    if current.holder != holder or current.state != BackupDestinationUpload.State.UPLOADING:
        return
    current.state = BackupDestinationUpload.State.PENDING
    current.holder = None
    current.claimed_until = None
    current.last_error_code = code[:64]
    current.next_attempt_at = now + timedelta(seconds=backoff_seconds(current.attempts))
    current.save(update_fields=(
        "state", "holder", "claimed_until", "last_error_code", "next_attempt_at", "updated_at",
    ))
    BackupDestination.objects.filter(pk=current.destination_id).update(last_error_code=code[:64])
    logger.warning(
        "backup_offsite_push_failed",
        extra={
            "destination_id": current.destination_id,
            "archive_id": str(current.archive_id_snapshot),
            "error_code": code,
            "attempts": current.attempts,
        },
    )


@transaction.atomic
def _record_verified(row, holder, size, sha256):
    now = timezone.now()
    current = BackupDestinationUpload.objects.select_for_update().get(pk=row.pk)
    if current.holder != holder or current.state != BackupDestinationUpload.State.UPLOADING:
        return
    current.state = BackupDestinationUpload.State.BYTES_VERIFIED
    current.holder = None
    current.claimed_until = None
    current.uploaded_at = current.uploaded_at or now
    current.verified_at = now
    current.verified_size_bytes = size
    current.verified_sha256 = sha256
    current.last_error_code = ""
    current.save()
    BackupDestination.objects.filter(pk=current.destination_id).update(
        last_success_at=now, last_error_code=""
    )
    audit.record(
        None,
        "backup.offsite_copy_verified",
        target=current,
        meta={
            "destination_id": current.destination_id,
            "archive_id": str(current.archive_id_snapshot),
            "scope": current.scope_snapshot,
            "size_bytes": size,
            "integrity_source": current.integrity_source,
            "archives_outside_purge_guarantee": True,
        },
    )


@transaction.atomic
def _abandon(row, holder):
    current = BackupDestinationUpload.objects.select_for_update().get(pk=row.pk)
    if current.holder != holder:
        return
    current.state = BackupDestinationUpload.State.ABANDONED
    current.holder = None
    current.claimed_until = None
    current.last_error_code = "source_unavailable"
    current.save(update_fields=(
        "state", "holder", "claimed_until", "last_error_code", "updated_at",
    ))
    audit.record(
        None,
        "backup.offsite_copy_abandoned",
        target=current,
        meta={
            "destination_id": current.destination_id,
            "archive_id": str(current.archive_id_snapshot),
        },
    )
