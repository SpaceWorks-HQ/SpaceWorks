from collections import Counter

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.tenant_migration.models import ImportIdentityDecision, TenantImportJob
from apps.audit import services as audit

from .import_job_cleanup import (
    CLEANUP_LEASE_NAME,
    CLEANUP_OBJECTS_LEASE_NAME,
    FINALIZATION_SWEEP_LEASE_NAME,
    cleanup_abandoned_import_objects,
    cleanup_expired_import_jobs,
    resume_expired_finalizing_import_jobs,
)


def create_import_job(*, actor, archive, source_archive_digest, expires_at):
    _require_superadmin(actor)
    from apps.backup.digests import sha256_file
    from .archive_stream import PortableArchive
    from .import_staging import decrypted_archive, stage_encrypted_upload

    archive_path = stage_encrypted_upload(archive)
    try:
        if sha256_file(archive_path) != source_archive_digest:
            raise ValidationError({"detail": "The encrypted archive digest does not match."})
        with decrypted_archive(archive_path) as (root, _carried):
            portable = PortableArchive(root)
            manifest = portable.json("migration-manifest.json")
            from .archive_envelope import FORMAT, FORMAT_VERSION
            from .pairing import _validated_identity

            if (
                manifest.get("format") != FORMAT
                or manifest.get("format_version") != FORMAT_VERSION
            ):
                raise ValidationError({"detail": "The tenant migration format is unsupported."})
            source = manifest.get("source", {}).get("makerspace", {})
            source_identity = _validated_identity(
                manifest.get("source", {}).get("deployment"), "source"
            )
            users = list(portable.rows("accounts.User"))
    except Exception:
        archive_path.unlink(missing_ok=True)
        raise
    try:
        with transaction.atomic():
            job = TenantImportJob.objects.create(
                actor=actor,
                source_archive_digest=source_archive_digest,
                source_makerspace_id=str(source.get("id", "")),
                source_makerspace_slug=str(source.get("slug", "")),
                source_makerspace_name=str(source.get("name", "")),
                source_deployment_id=str(source_identity["deployment_id"]),
                source_deployment_identity=source_identity,
                storage_mode=",".join(sorted(manifest.get("storage_mode", {}).values())),
                status=(TenantImportJob.Status.AWAITING_IDENTITY if users else TenantImportJob.Status.READY),
                archive_path=str(archive_path),
                expires_at=expires_at,
            )
            audit.record(
                actor, "tenant_migration.import_created", target=job,
                meta={
                    "import_id": str(job.pk), "identity_count": len(users),
                    "format_version": manifest.get("format_version", 0),
                    "source_archive_digest": source_archive_digest,
                },
            )
    except Exception:
        archive_path.unlink(missing_ok=True)
        raise
    return job


def submit_identity_decisions(*, actor, job, decisions):
    _require_superadmin(actor)
    from .archive_stream import PortableArchive
    from .import_staging import decrypted_archive

    with decrypted_archive(job.archive_path) as (root, _carried):
        portable = PortableArchive(root)
        source_rows = {
            str(row["id"]): row
            for row in portable.rows("accounts.User")
        }
        if {str(item["source_user_id"]) for item in decisions} != set(source_rows):
            raise ValidationError({"detail": "A decision is required for every archived identity."})
        from .identity_decision_validation import validate_membership_dispositions

        validate_membership_dispositions(portable, decisions)
    with transaction.atomic():
        locked = TenantImportJob.objects.select_for_update().get(pk=job.pk)
        if locked.status not in {
            TenantImportJob.Status.AWAITING_IDENTITY,
            TenantImportJob.Status.READY,
        }:
            raise ValidationError({"detail": "This import no longer accepts identity decisions."})
        locked.identity_decisions.all().delete()
        rows = []
        for item in decisions:
            source_id = str(item["source_user_id"])
            rows.append(
                ImportIdentityDecision(
                    job=locked,
                    source_user_id=source_id,
                    source_email=source_rows[source_id].get("email") or None,
                    identity_resolution=item["identity_resolution"],
                    membership_disposition=item["membership_disposition"],
                    target_user_id=item.get("target_user_id"),
                )
            )
        ImportIdentityDecision.objects.bulk_create(rows)
        locked.status = TenantImportJob.Status.READY
        locked.save(update_fields=("status", "updated_at"))
        audit.record(
            actor,
            "tenant_migration.identity_decisions_submitted",
            target=locked,
            meta={
                "import_id": str(locked.pk),
                "identity_count": len(rows),
                "format_version": 1,
            },
        )
    return locked


@transaction.atomic
def claim_import_job(*, actor, job):
    """Move a ready import to its single runnable state under a row lock."""
    _require_superadmin(actor)
    locked = TenantImportJob.objects.select_for_update().get(pk=job.pk)
    if locked.status != TenantImportJob.Status.READY:
        from .protocol_errors import ImportStateError

        raise ImportStateError("The import is not ready to run.")
    locked.status = TenantImportJob.Status.MATERIALIZING
    locked.save(update_fields=("status", "updated_at"))
    audit.record(
        actor, "tenant_migration.import_run_requested", target=locked,
        meta={"import_id": str(locked.pk), "format_version": 1},
    )
    return locked


def run_import_job(job_id, *, actor_id, target_identity=None):
    from apps.accounts.models import User
    from .import_finalization import finalize_import_job
    from .insertion_errors import (
        ImportCompletionAuditError,
        ImportPromotionClaimLost,
        ImportPromotionInProgress,
        MaterializationAlreadyCommitted,
    )
    from .materialization import materialize_tenant

    actor = User.objects.get(pk=actor_id)
    _require_superadmin(actor)
    job = TenantImportJob.objects.get(pk=job_id)
    if job.status == TenantImportJob.Status.COMPLETED:
        return job
    if job.status not in {
        TenantImportJob.Status.MATERIALIZING,
        TenantImportJob.Status.FINALIZING,
    }:
        raise ValidationError({"detail": "The import has not been claimed for execution."})

    try:
        if job.status == TenantImportJob.Status.MATERIALIZING:
            from .import_staging import decrypted_archive

            try:
                with decrypted_archive(job.archive_path) as (root, carried):
                    materialize_tenant(
                        root, job, carried, target_identity=target_identity
                    )
            except MaterializationAlreadyCommitted:
                # A concurrent delivery won the database transaction. Its committed
                # FINALIZING state is the authority for the remaining work.
                pass
        job.refresh_from_db()
        job = finalize_import_job(job, actor=actor)
    except ImportPromotionClaimLost:
        # A replacement delivery owns finalization. Its status and objects are
        # authoritative, so this stale worker exits without changing either.
        return TenantImportJob.objects.get(pk=job.pk)
    except ImportPromotionInProgress:
        # A periodic, idempotently leased sweep requeues FINALIZING after this object
        # lease expires. It deliberately excludes jobs with any still-live claim.
        return TenantImportJob.objects.get(pk=job.pk)
    except ImportCompletionAuditError:
        # Completion and its audit entry share one transaction. Keep FINALIZING and
        # its verified objects intact so the scheduled sweep can retry that transaction.
        raise
    except Exception as exc:
        failure_detail = str(exc).strip()[:500] or type(exc).__name__
        failed_active = TenantImportJob.objects.filter(
            pk=job.pk,
            status__in=(
                TenantImportJob.Status.MATERIALIZING,
                TenantImportJob.Status.FINALIZING,
            ),
        ).update(
            status=TenantImportJob.Status.FAILED,
            failure_code="materialization_failed",
            failure_detail=failure_detail,
            terminal_at=timezone.now(),
        )
        if failed_active:
            from .object_import import rollback_import_objects

            rollback_job = TenantImportJob.objects.select_related(
                "target_makerspace", "actor"
            ).get(pk=job.pk)
            rollback_import_objects(rollback_job)
        else:
            # materialize_tenant() records FAILED before re-raising. Annotate only
            # that still-unexplained failure and never overwrite a competing reason.
            TenantImportJob.objects.filter(
                pk=job.pk,
                status=TenantImportJob.Status.FAILED,
                failure_code="",
                failure_detail="",
            ).update(
                failure_code="materialization_failed",
                failure_detail=failure_detail,
            )
        raise
    return job


def _require_superadmin(actor):
    from apps.accounts.models import User

    if not (
        getattr(actor, "is_superuser", False)
        or getattr(actor, "role", None) == User.Role.SUPERADMIN
    ):
        raise ValidationError({"detail": "Superadmin access is required."})


@transaction.atomic
def scrub_terminal_job(job):
    """Discard per-person provenance while preserving a PII-free aggregate result."""
    locked = TenantImportJob.objects.select_for_update().get(pk=job.pk)
    if locked.status not in TenantImportJob.TERMINAL_STATUSES:
        raise ValidationError("Only a terminal tenant import job can be scrubbed.")
    if locked.scrubbed_at is not None:
        return locked

    decisions = locked.identity_decisions.all()
    resolution_counts = Counter(decisions.values_list("identity_resolution", flat=True))
    membership_counts = Counter(
        decisions.values_list("membership_disposition", flat=True)
    )
    locked.aggregate_outcome = {
        "decision_count": decisions.count(),
        "identity_resolution": {
            value: resolution_counts[value]
            for value, _label in ImportIdentityDecision.IdentityResolution.choices
        },
        "membership_disposition": {
            value: membership_counts[value]
            for value, _label in ImportIdentityDecision.MembershipDisposition.choices
        },
    }
    decisions.delete()
    locked.source_makerspace_id = ""
    locked.source_makerspace_slug = ""
    locked.source_makerspace_name = ""
    locked.source_deployment_id = ""
    locked.source_deployment_identity = {}
    locked.storage_mode = ""
    locked.scrubbed_at = timezone.now()
    locked.save(
        update_fields=(
            "aggregate_outcome",
            "source_makerspace_id",
            "source_makerspace_slug",
            "source_makerspace_name",
            "source_deployment_id",
            "source_deployment_identity",
            "storage_mode",
            "scrubbed_at",
            "updated_at",
        )
    )
    return locked
