"""Restore-from-offsite: put a verified offsite copy back into the primary store.

Rehydration is for a deployment whose database survived but whose primary bucket did
not: the archive row is still `AVAILABLE`, its bytes are gone, and an offsite copy
was read back and verified. The copy is fetched and verified locally, uploaded to a
fresh staging key, verified there, promoted create-only to the archive's own locator
and verified again. `request_restore` and the host
preflight (signature, format, compatibility) run exactly as for any other archive.

A fresh host with no surviving database uses `manage.py fetch_offsite_archive` and the
existing `scripts/import-backup.sh` instead.
"""

import logging
import os
import tempfile
import uuid

from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit import services as audit
from apps.backup import offsite_client, storage
from apps.backup.models import BackupArchive, BackupDestination, BackupDestinationUpload
from apps.backup.offsite_push import OffsiteIntegrityError, expected_facts


logger = logging.getLogger(__name__)


def validate_rehydration(archive, destination):
    """Side-effect-free admission; returns the verified journal row."""
    if archive.status != BackupArchive.Status.AVAILABLE or (
        archive.expires_at is None or archive.expires_at <= timezone.now()
    ):
        raise ValidationError("Only an available, unexpired archive can be rehydrated.")
    if destination.retired_at is not None:
        raise ValidationError("A retired destination cannot be read.")
    upload = BackupDestinationUpload.objects.filter(
        destination=destination,
        archive_id_snapshot=archive.pk,
        state=BackupDestinationUpload.State.BYTES_VERIFIED,
    ).first()
    if upload is None:
        raise ValidationError("This destination holds no verified copy of the archive.")
    try:
        size, sha256, _source = expected_facts(archive)
    except OffsiteIntegrityError as exc:
        raise ValidationError(str(exc)) from exc
    if size != upload.expected_size_bytes or sha256 != upload.expected_sha256:
        raise ValidationError("The offsite journal disagrees with the archive ledger.")
    try:
        present = storage.object_exists(archive.object_key)
    except storage.BackupStorageError as exc:
        raise ValidationError("The primary archive store could not be inspected.") from exc
    if present:
        raise ValidationError("The primary copy is present; there is nothing to rehydrate.")
    return upload


def rehydrate_archive(archive_id, destination_id, actor=None):
    """Fetch, verify and create-only promote one offsite copy. Returns True on success.

    The copy is spooled to a private temporary file and verified there first: the
    staging and final writes use seekable bodies. `If-None-Match: *` makes the final
    write create-only, so a copy that
    reappeared meanwhile is never overwritten.
    """
    archive = BackupArchive.objects.get(pk=archive_id)
    destination = BackupDestination.objects.get(pk=destination_id)
    upload = validate_rehydration(archive, destination)
    expected = {
        "expected_size": upload.expected_size_bytes,
        "expected_sha256": upload.expected_sha256,
    }
    staging = f"backup-archives/staging/{archive.pk}/rehydrate-{uuid.uuid4()}.tar.age"
    with tempfile.TemporaryDirectory(prefix="spaceworks-rehydrate-") as workdir:
        path = os.path.join(workdir, "archive.tar.age")
        try:
            s3 = offsite_client.destination_client(destination)
            with open(path, "wb") as sink:
                offsite_client.read_back(
                    s3, destination.bucket, upload.remote_locator, sink=sink, **expected
                )
            storage.upload_staging(staging, path)
            storage.stream_verify(staging, **expected)
            storage.create_final_from_staging(staging, archive.object_key)
            storage.stream_verify(archive.object_key, **expected)
        except (offsite_client.OffsiteDestinationError, storage.BackupStorageError) as exc:
            code = getattr(exc, "code", type(exc).__name__)
            logger.error(
                "backup_offsite_rehydrate_failed",
                extra={"archive_id": str(archive.pk), "destination_id": destination.pk,
                       "error_code": code},
            )
            audit.record(
                actor, "backup.archive_rehydrate_failed", target=archive,
                meta={"destination_id": destination.pk, "error_code": str(code)[:64]},
            )
            return False
        finally:
            # A crash leaves this attempt under the archive's retention prefix.
            # Cleanup failure must never demote a verified immutable final copy.
            storage.delete_archive(staging)
    audit.record(
        actor,
        "backup.archive_rehydrated",
        target=archive,
        meta={
            "destination_id": destination.pk,
            "size_bytes": upload.expected_size_bytes,
            "integrity_source": upload.integrity_source,
        },
    )
    return True
