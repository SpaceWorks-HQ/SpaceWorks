"""Short transactional lifecycle operations around the long-running export."""

import hashlib
import hmac
import logging
import os
import secrets
import uuid
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit import services as audit
from apps.data_export import storage
from apps.data_export.models import DataExportJob
from apps.data_export.runner import (
    ExportDeadlineExceeded,
    ExportIntegrityError,
    build_archive,
)
from apps.data_export.types import Fidelity
from apps.makerspaces import limits
from apps.makerspaces.models import Makerspace

logger = logging.getLogger(__name__)


class DownloadTokenError(RuntimeError):
    pass


def create_export_job(actor, makerspace):
    """Serialize the quota check and creation on the tenant row lock."""
    now = timezone.now()
    job_id = uuid.uuid4()
    with transaction.atomic():
        locked = Makerspace.objects.select_for_update().get(pk=makerspace.pk)
        limits.check_quota(locked, "data_exports", adding=1)
        job = DataExportJob.objects.create(
            id=job_id,
            makerspace=locked,
            requested_by=actor,
            fidelity=Fidelity.REDACTED.value,
            object_key=f"data-exports/{locked.pk}/{job_id}.zip",
            expires_at=now + timedelta(seconds=settings.DATA_EXPORT_RETENTION_SECONDS),
        )
        audit.record(
            actor,
            "data_export.requested",
            makerspace=locked,
            target=job,
            meta={
                "fidelity": Fidelity.REDACTED.value,
                **_row_count_meta(job),
            },
        )
    return job


def run_export_job(job_id):
    job = _claim_job(job_id)
    if job is None:
        return None
    tempdir = None
    try:
        zip_path, manifest, tempdir = build_archive(job)
        size = os.path.getsize(zip_path)
        storage.upload_archive(job.object_key, zip_path)
        _finalize_job(job.pk, manifest, size)
    except ExportDeadlineExceeded as exc:
        _fail_job(
            job,
            DataExportJob.FailureCode.DEADLINE_EXCEEDED,
            str(exc),
            {
                "deadline": {"outcome": "exhausted", "seconds": settings.DATA_EXPORT_DEADLINE_SECONDS},
                "last_dataset": exc.dataset,
                "rows_completed": exc.rows_completed,
            },
        )
    except ExportIntegrityError as exc:
        _fail_job(job, DataExportJob.FailureCode.INTEGRITY_ERROR, str(exc))
    except ValidationError as exc:
        _fail_job(job, DataExportJob.FailureCode.QUOTA_EXCEEDED, str(exc))
    except storage.ExportStorageError as exc:
        _fail_job(job, DataExportJob.FailureCode.STORAGE_ERROR, str(exc))
    except Exception as exc:  # Worker boundary: persist a typed terminal outcome.
        logger.exception(
            "data_export_failed",
            extra={"job_id": str(job.pk), "makerspace_id": job.makerspace_id},
        )
        _fail_job(
            job,
            DataExportJob.FailureCode.INTERNAL_ERROR,
            "The export failed unexpectedly.",
        )
    finally:
        if tempdir is not None:
            tempdir.cleanup()
    return DataExportJob.objects.filter(pk=job_id).first()


def _claim_job(job_id):
    now = timezone.now()
    with transaction.atomic():
        job = (
            DataExportJob.objects.select_for_update()
            .select_related("makerspace", "requested_by")
            .filter(pk=job_id)
            .first()
        )
        if job is None or job.status != DataExportJob.Status.PENDING:
            return None
        job.status = DataExportJob.Status.RUNNING
        job.started_at = now
        job.deadline_at = now + timedelta(seconds=settings.DATA_EXPORT_DEADLINE_SECONDS)
        job.failure_code = ""
        job.failure_detail = ""
        job.save(
            update_fields=(
                "status", "started_at", "deadline_at", "failure_code",
                "failure_detail", "updated_at",
            )
        )
        return job


def _finalize_job(job_id, manifest, size):
    try:
        with transaction.atomic():
            job = (
                DataExportJob.objects.select_for_update()
                .select_related("makerspace", "requested_by")
                .get(pk=job_id)
            )
            if job.status != DataExportJob.Status.RUNNING:
                raise ExportIntegrityError("The claimed export changed state before finalize.")
            limits.add_storage(job.makerspace, size)
            job.status = DataExportJob.Status.AVAILABLE
            job.accounted_size_bytes = size
            job.manifest = manifest
            job.snapshot_at = manifest["snapshot_at"]
            job.completed_at = timezone.now()
            job.save(
                update_fields=(
                    "status", "accounted_size_bytes", "manifest", "snapshot_at",
                    "completed_at", "updated_at",
                )
            )
            audit.record(
                job.requested_by,
                "data_export.completed",
                makerspace=job.makerspace,
                target=job,
                meta={
                    "fidelity": job.fidelity,
                    "row_counts": manifest["row_counts"],
                    "total_rows": manifest["total_rows"],
                },
            )
    except Exception:
        storage.delete_object(
            DataExportJob.objects.only("object_key").get(pk=job_id).object_key
        )
        raise


def _fail_job(job, code, detail, manifest=None):
    storage.delete_object(job.object_key)
    DataExportJob.objects.filter(pk=job.pk).update(
        status=DataExportJob.Status.FAILED,
        failure_code=code,
        failure_detail=detail[:500],
        manifest=manifest or {},
        completed_at=timezone.now(),
        accounted_size_bytes=0,
        download_token_digest="",
        download_token_expires_at=None,
        download_token_consumed_at=None,
        download_issued_to=None,
    )


def issue_download_token(job, actor):
    raw = secrets.token_urlsafe(32)
    now = timezone.now()
    with transaction.atomic():
        locked = DataExportJob.objects.select_for_update().select_related("makerspace").get(pk=job.pk)
        if locked.status != DataExportJob.Status.AVAILABLE or locked.expires_at <= now:
            raise ValidationError({"detail": "This export is not available for download."})
        locked.download_token_digest = _token_digest(raw)
        locked.download_token_expires_at = now + timedelta(
            seconds=settings.DATA_EXPORT_DOWNLOAD_TTL_SECONDS
        )
        locked.download_token_consumed_at = None
        locked.download_issued_to = actor
        locked.save(update_fields=(
            "download_token_digest", "download_token_expires_at",
            "download_token_consumed_at", "download_issued_to", "updated_at",
        ))
        meta = _row_count_meta(locked)
        if locked.fidelity == Fidelity.PORTABLE.value:
            try:
                format_version = locked.migration_export.format_version
            except ObjectDoesNotExist:
                format_version = 0
            meta.update(
                export_id=str(locked.pk),
                format_version=format_version,
            )
        audit.record(
            actor, "data_export.download_url_issued", makerspace=locked.makerspace,
            target=locked, meta=meta,
        )
    return raw, locked.download_token_expires_at


def consume_download_token(job_id, raw_token):
    failure = None
    claimed = None
    with transaction.atomic():
        job = (
            DataExportJob.objects.select_for_update()
            .select_related("makerspace")
            .filter(pk=job_id)
            .first()
        )
        now = timezone.now()
        valid = bool(
            job and job.status == DataExportJob.Status.AVAILABLE
            and job.download_token_digest
            and job.download_token_consumed_at is None
            and job.download_token_expires_at and job.download_token_expires_at > now
            and hmac.compare_digest(job.download_token_digest, _token_digest(raw_token))
        )
        if not valid:
            failure = DownloadTokenError("The download link is invalid, expired, or already used.")
        else:
            job.download_token_consumed_at = now
            job.save(update_fields=("download_token_consumed_at", "updated_at"))
            meta = _row_count_meta(job)
            if job.fidelity == Fidelity.PORTABLE.value:
                try:
                    format_version = job.migration_export.format_version
                except ObjectDoesNotExist:
                    format_version = 0
                meta.update(export_id=str(job.pk), format_version=format_version)
            audit.record(
                job.download_issued_to, "data_export.downloaded",
                makerspace=job.makerspace, target=job, meta=meta,
            )
            claimed = job
    if failure:
        raise failure
    return claimed


def invalidate_download_tokens_after_restore():
    """Restore hook: copied bearer digests must never remain usable."""
    return DataExportJob.objects.exclude(download_token_digest="").update(
        download_token_digest="",
        download_token_expires_at=None,
        download_token_consumed_at=None,
        download_issued_to=None,
    )


def _token_digest(raw):
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _row_count_meta(job):
    manifest = job.manifest or {}
    return {
        "row_counts": manifest.get("row_counts", {}),
        "total_rows": manifest.get("total_rows", 0),
    }
