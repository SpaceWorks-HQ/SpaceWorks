"""Source-superadmin lifecycle for encrypted tenant migration exports."""

import os
import re
import tempfile
import uuid
import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.accounts.models import User
from apps.data_export import services as export_services, storage
from apps.data_export.models import DataExportJob
from apps.data_export.types import Fidelity
from apps.makerspaces import limits
from apps.makerspaces.models import Makerspace

from .admission import compute_pending_closure, validate_snapshot_approval
from .archive_envelope import build_tenant_migration_archive
from .models_protocol import DisclosureClosureApproval, TenantMigrationExportJob
from .protocol_errors import (
    ClosureAdmissionError,
    ClosureChangedError,
    TransitionConflictError,
)
from . import source_gate

AGE_RECIPIENT = re.compile(r"\A(?:age1|age-plugin-)[A-Za-z0-9_-]{16,}\Z")
logger = logging.getLogger(__name__)


def create_migration_export_job(*, actor, makerspace, approval, target_age_recipient):
    _require_superadmin(actor)
    recipient = str(target_age_recipient).strip()
    if not AGE_RECIPIENT.fullmatch(recipient):
        raise ValueError("A valid target-superadmin age recipient is required.")
    current = compute_pending_closure(makerspace)
    validate_snapshot_approval(approval, current["identities"])
    now, job_id = timezone.now(), uuid.uuid4()
    with transaction.atomic():
        locked = Makerspace.objects.select_for_update().get(pk=makerspace.pk)
        approval = DisclosureClosureApproval.objects.select_for_update().get(pk=approval.pk)
        if approval.makerspace_id != locked.pk or approval.revoked_at is not None:
            raise ClosureChangedError("The disclosure approval is not active for this tenant.")
        limits.check_quota(locked, "data_exports", adding=1)
        job = DataExportJob.objects.create(
            id=job_id,
            makerspace=locked,
            requested_by=actor,
            fidelity=Fidelity.PORTABLE.value,
            object_key=f"tenant-migrations/{locked.pk}/{job_id}.tar.age",
            expires_at=now + timedelta(seconds=settings.DATA_EXPORT_RETENTION_SECONDS),
        )
        TenantMigrationExportJob.objects.create(
            export_job=job,
            disclosure_approval=approval,
            closure_digest=approval.closure_digest,
            target_age_recipient=recipient,
        )
        audit.record(
            actor,
            "tenant_migration.export_requested",
            makerspace=locked,
            target=job,
            meta={
                "export_id": str(job.pk),
                "closure_digest": approval.closure_digest,
                "identity_count": len(approval.identity_ids),
                "approved_count": len(approval.approved_identity_ids),
                "format_version": 1,
            },
        )
    return job


def run_migration_export_job(job_id):
    job = export_services._claim_job(job_id)
    if job is None:
        return None
    migration = TenantMigrationExportJob.objects.select_related(
        "disclosure_approval"
    ).get(export_job=job)
    tempdir = tempfile.TemporaryDirectory(prefix="spaceworks-migration-")
    output = os.path.join(tempdir.name, "tenant-migration.tar.age")
    try:
        path, manifest, digest = build_tenant_migration_archive(
            job.makerspace,
            output,
            actor=job.requested_by,
            disclosure_approval=migration.disclosure_approval,
            recipient=migration.target_age_recipient,
        )
        size = os.path.getsize(path)
        storage.upload_archive(job.object_key, path, "application/octet-stream")
        export_services._finalize_job(job.pk, manifest, size)
        TenantMigrationExportJob.objects.filter(export_job=job).update(
            archive_digest=digest
        )
    except ClosureAdmissionError as exc:
        export_services._fail_job(job, DataExportJob.FailureCode.INTEGRITY_ERROR, str(exc))
    except Exception:
        logger.exception(
            "tenant_migration_export_failed",
            extra={"job_id": str(job.pk), "makerspace_id": job.makerspace_id},
        )
        export_services._fail_job(
            job, DataExportJob.FailureCode.INTERNAL_ERROR,
            "The migration export failed unexpectedly.",
        )
    finally:
        tempdir.cleanup()
    return DataExportJob.objects.filter(pk=job_id).first()


def claim_completed_export(*, migration_export, actor):
    """Reassert the archive's fenced Part 9 gate authority before cutover."""
    _require_superadmin(actor)
    migration = TenantMigrationExportJob.objects.select_related(
        "export_job__makerspace"
    ).get(pk=migration_export.pk)
    export_job = migration.export_job
    if (
        export_job.status != DataExportJob.Status.AVAILABLE
        or not migration.archive_digest
    ):
        raise TransitionConflictError("The migration archive is not complete.")

    gate_data = (export_job.manifest or {}).get("source", {}).get("gate", {})
    try:
        owner_id = uuid.UUID(str(gate_data["owner_id"]))
        fencing_token = int(gate_data["fencing_token"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TransitionConflictError(
            "The migration archive has no valid source-gate authority."
        ) from exc
    if fencing_token < 1:
        raise TransitionConflictError(
            "The migration archive has no valid source-gate authority."
        )

    lease = source_gate.claim(
        export_job.makerspace,
        actor,
        owner_id=owner_id,
        fencing_token=fencing_token,
    )
    return source_gate.heartbeat(lease)


def _require_superadmin(actor):
    if not (
        getattr(actor, "is_superuser", False)
        or getattr(actor, "role", None) == User.Role.SUPERADMIN
    ):
        raise PermissionError("Only a source superadmin may manage a PORTABLE export.")
