"""Resumable post-commit finalization for a tenant import."""

from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit

from .insertion_errors import ImportCompletionAuditError, ImportVerificationError
from .models_import_job import TenantImportJob
from .object_import import promote_import_objects
from .object_verification import verify_import_objects


def finalize_import_job(job, *, actor):
    """Promote remaining objects, verify them, and durably complete once."""
    job = TenantImportJob.objects.select_related("target_makerspace").get(pk=job.pk)
    if job.status == TenantImportJob.Status.COMPLETED:
        return job
    if job.status != TenantImportJob.Status.FINALIZING:
        raise ImportVerificationError("The import is not ready for finalization.")

    promote_import_objects(job)
    job.refresh_from_db()
    verify_import_objects(job)
    job, _completed_now = _commit_completion(job.pk, actor=actor)
    return job


@transaction.atomic
def _commit_completion(job_id, *, actor):
    # No `select_related("target_makerspace")` here: that FK is NULLABLE, and Postgres
    # rejects `FOR UPDATE` on the nullable side of an outer join. It lazy-loads in one
    # extra query, which is free next to the writes this transaction already performs.
    job = TenantImportJob.objects.select_for_update().get(pk=job_id)
    if job.status == TenantImportJob.Status.COMPLETED:
        return job, False
    if job.status != TenantImportJob.Status.FINALIZING:
        raise ImportVerificationError("The import finalization claim is no longer valid.")
    if not job.materialization_report:
        raise ImportVerificationError("The durable materialization report is missing.")
    job.verification_report = job.materialization_report
    job.status = TenantImportJob.Status.COMPLETED
    job.terminal_at = timezone.now()
    job.save(
        update_fields=("verification_report", "status", "terminal_at", "updated_at")
    )
    report = job.verification_report
    try:
        audit.record(
            actor,
            "tenant_migration.import_completed",
            makerspace=job.target_makerspace,
            target=job,
            meta={
                "import_id": str(job.pk),
                "model_count": len(report["imported"]),
                "identity_count": (
                    report["identities_linked"] + report["identities_created"]
                ),
                "format_version": 1,
            },
        )
    except Exception as exc:
        raise ImportCompletionAuditError(
            "The import completion audit entry could not be recorded."
        ) from exc
    return job, True
