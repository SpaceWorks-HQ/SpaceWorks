"""Register a host-authenticated disaster archive before restore supervision."""

from datetime import timedelta
import hmac
import os
import uuid

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit import services as audit
from apps.backup import storage
from apps.backup.digests import SUPPORTED_ARCHIVE_FORMATS, sha256_file
from apps.backup.models import BackupArchive, PlatformBackupSettings, RestoreOperation


def import_disaster_archive(actor, encrypted_path, manifest, *, expected_sha256=None):
    try:
        archive_id = uuid.UUID(str(manifest["archive_id"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationError("The imported archive manifest has no valid archive id.") from exc
    if (
        manifest.get("format") not in SUPPORTED_ARCHIVE_FORMATS
        or manifest.get("scope") != BackupArchive.Scope.DEPLOYMENT
    ):
        raise ValidationError("Only a Phase 5A full-deployment archive can be imported.")
    if not manifest.get("age_encrypted"):
        raise ValidationError("The imported archive is not declared age-encrypted.")
    path = os.fspath(encrypted_path)
    size = os.path.getsize(path)
    if size <= 0:
        raise ValidationError("The imported archive is empty.")
    archive_sha256 = sha256_file(path)
    if expected_sha256 is not None and not hmac.compare_digest(
        str(expected_sha256), archive_sha256
    ):
        raise ValidationError("The imported archive sha256 does not match the expected digest.")
    if BackupArchive.objects.filter(pk=archive_id).exists():
        raise ValidationError("This archive is already registered on the target deployment.")
    object_key = f"backup-archives/deployment/{archive_id}.tar.age"
    storage.upload_archive(object_key, path)
    try:
        with transaction.atomic():
            retention = PlatformBackupSettings.load().retention_days
            archive = BackupArchive.objects.create(
                id=archive_id,
                scope=BackupArchive.Scope.DEPLOYMENT,
                requested_by=actor,
                status=BackupArchive.Status.AVAILABLE,
                object_key=object_key,
                manifest=manifest,
                size_bytes=size,
                archive_sha256=archive_sha256,
                age_encrypted=True,
                completed_at=timezone.now(),
                expires_at=timezone.now() + timedelta(days=retention),
            )
            audit.record(actor, "backup.archive_imported", target=archive)
            from apps.backup.restore_services import request_restore

            restore = request_restore(actor, archive, RestoreOperation.Kind.DISASTER)
    except Exception:
        storage.delete_archive(object_key)
        raise
    return restore
