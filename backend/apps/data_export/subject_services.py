"""Subject export job lifecycle; storage/quota/retention reuse tenant export seams."""

import logging
import uuid
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework.exceptions import Throttled, ValidationError

from apps.accounts import rbac
from apps.audit import services as audit
from apps.makerspaces import limits
from apps.makerspaces.guards import require_feature_locked, require_module
from apps.makerspaces.member_activity_service import active_membership

from . import services, storage
from .models import DataExportJob
from .subject_archive import build_subject_archive
from .subject_boundary import subject_boundary, subject_write

logger = logging.getLogger(__name__)
SUBJECT_FIDELITY = "SUBJECT"


def own_jobs(user, makerspace_id):
    return rbac.scope_by_makerspace(user, DataExportJob.objects.all()).filter(
        makerspace_id=makerspace_id, requested_by=user, fidelity=SUBJECT_FIDELITY,
    )


def create_subject_export(user, makerspace):
    with subject_write(makerspace.pk):
        locked = require_feature_locked(makerspace, "membership.self_export")
        require_module(locked, "member_accounts")
        if active_membership(user, locked.pk) is None:
            raise ValidationError({"detail": "An active membership is required."})
        # The DB lock makes the expensive-job limit hold even if distributed throttle
        # cache is cold or two simultaneous browser requests reach different workers.
        if own_jobs(user, locked.pk).filter(created_at__gt=timezone.now() - timedelta(days=1)).exists():
            raise Throttled(wait=86400, detail="A personal export was already requested in the last day.")
        limits.check_quota(locked, "data_exports", adding=1)
        identifier = uuid.uuid4()
        job = DataExportJob.objects.create(
            id=identifier, makerspace=locked, requested_by=user,
            fidelity=SUBJECT_FIDELITY,
            object_key=f"data-exports/{locked.pk}/subjects/{identifier}.zip",
            expires_at=timezone.now() + timedelta(seconds=settings.DATA_EXPORT_RETENTION_SECONDS),
        )
        audit.record(user, "subject_export.requested", makerspace=locked, target=job)
    return job


def run_subject_export(job_id):
    candidate = rbac.scope_for_scheduled_work(DataExportJob.objects.select_related("requested_by", "makerspace").filter(
        pk=job_id, fidelity=SUBJECT_FIDELITY, status=DataExportJob.Status.PENDING,
        expires_at__gt=timezone.now(),
    )).first()
    if candidate is None:
        return None
    jobs = rbac.scope_for_scheduled_work(
        DataExportJob.objects.filter(fidelity=SUBJECT_FIDELITY), makerspace_id=candidate.makerspace_id,
    )
    with subject_boundary(candidate.makerspace_id):
        job = services._claim_job(job_id, queryset=jobs)
        if job is None:
            return None
        tempdir = None
        try:
            # Recheck access at execution; leaving while queued cannot create a fresh
            # disclosure job after the account has lost its makerspace membership.
            if active_membership(job.requested_by, job.makerspace_id) is None:
                raise ValidationError("Membership is no longer active.")
            from apps.makerspaces.guards import require_feature

            require_feature(job.makerspace, "membership.self_export")
            require_module(job.makerspace, "member_accounts")
            path, manifest, tempdir = build_subject_archive(job)
            storage.upload_archive(job.object_key, path)
            services._finalize_job(job.pk, manifest, path.stat().st_size, queryset=jobs)
        except Exception as exc:
            # No row content, addresses or provider credentials in diagnostics.
            logger.warning("subject_export_failed", extra={
                "job_id": str(job.pk), "failure_type": type(exc).__name__,
            })
            code = DataExportJob.FailureCode.INTERNAL_ERROR
            if isinstance(exc, storage.ExportStorageError):
                code = DataExportJob.FailureCode.STORAGE_ERROR
            elif isinstance(exc, DjangoValidationError) or (
                isinstance(exc, ValidationError) and isinstance(exc.detail, dict) and "limit" in exc.detail
            ):
                code = DataExportJob.FailureCode.QUOTA_EXCEEDED
            elif isinstance(exc, services.ExportDeadlineExceeded):
                code = DataExportJob.FailureCode.DEADLINE_EXCEEDED
            services._fail_job(job, code, "The personal export could not be completed.", queryset=jobs)
            audit.record(job.requested_by, "subject_export.failed",
                         makerspace=job.makerspace, target=job, meta={"failure_code": code})
        finally:
            if tempdir is not None:
                tempdir.cleanup()
    return rbac.scope_for_scheduled_work(
        DataExportJob.objects.all(), makerspace_id=candidate.makerspace_id,
    ).get(pk=job_id)


def signed_download(job, user):
    with subject_write(job.makerspace_id):
        space = require_feature_locked(job.makerspace_id, "membership.self_export")
        require_module(space, "member_accounts")
        if active_membership(user, job.makerspace_id) is None:
            raise ValidationError({"detail": "An active membership is required."})
        locked = own_jobs(user, job.makerspace_id).select_for_update().get(pk=job.pk)
        now = timezone.now()
        if locked.status != DataExportJob.Status.AVAILABLE or locked.expires_at <= now:
            raise ValidationError({"detail": "This export is not available for download."})
        ttl = min(settings.DATA_EXPORT_DOWNLOAD_TTL_SECONDS,
                  max(1, int((locked.expires_at - now).total_seconds())))
        url = storage.signed_archive_url(locked.object_key, ttl)
        audit.record(user, "subject_export.download_url_issued", makerspace=locked.makerspace,
                     target=locked, meta={"expires_in_seconds": ttl})
        return {"url": url, "expires_at": now + timedelta(seconds=ttl)}
