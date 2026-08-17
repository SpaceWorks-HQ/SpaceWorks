from collections import Counter
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.operations.models import PeriodicTaskRun
from apps.tenant_migration.models import ImportIdentityDecision, TenantImportJob
from apps.audit import services as audit


CLEANUP_LEASE_NAME = "tenant-import-expiry-cleanup-work"
CLEANUP_LEASE_DURATION = timedelta(minutes=15)
DEFAULT_CLEANUP_BATCH_SIZE = 100


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
        source_rows = {
            str(row["id"]): row
            for row in PortableArchive(root).rows("accounts.User")
        }
    if {str(item["source_user_id"]) for item in decisions} != set(source_rows):
        raise ValidationError({"detail": "A decision is required for every archived identity."})
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
    from .materialization import materialize_tenant

    actor = User.objects.get(pk=actor_id)
    _require_superadmin(actor)
    job = TenantImportJob.objects.get(pk=job_id)
    if job.status != TenantImportJob.Status.MATERIALIZING:
        raise ValidationError({"detail": "The import has not been claimed for execution."})
    from .import_staging import decrypted_archive

    try:
        with decrypted_archive(job.archive_path) as (root, carried):
            result = materialize_tenant(
                root, job, carried, target_identity=target_identity
            )
        report = {
            "format_version": 1,
            "target_makerspace_id": result.target_makerspace_id,
            "imported": result.imported,
            "resolved": result.resolved,
            "dropped": result.dropped,
            "identities_linked": result.identities_linked,
            "identities_created": result.identities_created,
            "external_references_created": result.external_references_created,
        }
        TenantImportJob.objects.filter(pk=job.pk).update(
            status=TenantImportJob.Status.COMPLETED,
            verification_report=report,
            terminal_at=timezone.now(),
        )
        job.refresh_from_db()
        audit.record(
            actor,
            "tenant_migration.import_completed",
            makerspace=job.target_makerspace,
            target=job,
            meta={
                "import_id": str(job.pk),
                "model_count": len(result.imported),
                "identity_count": result.identities_linked + result.identities_created,
                "format_version": 1,
            },
        )
    except Exception as exc:
        TenantImportJob.objects.filter(pk=job.pk).update(
            status=TenantImportJob.Status.FAILED,
            failure_code="materialization_failed",
            failure_detail=str(exc)[:500],
            terminal_at=timezone.now(),
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


def cleanup_expired_import_jobs(*, now=None, batch_size=DEFAULT_CLEANUP_BATCH_SIZE):
    """Delete one bounded batch of expired jobs that never acquired a tenant."""
    cleanup_at = now or timezone.now()
    if not _claim_cleanup_lease(cleanup_at):
        return 0

    # The lease transaction has committed before this potentially large cascade. This
    # mirrors the beat-less scheduler's claim-then-work shape and keeps row locks short.
    job_ids = list(
        TenantImportJob.objects.filter(
            target_makerspace__isnull=True,
            expires_at__lte=cleanup_at,
        )
        .order_by("expires_at", "pk")
        .values_list("pk", flat=True)[:batch_size]
    )
    if job_ids:
        TenantImportJob.objects.filter(pk__in=job_ids).delete()
    return len(job_ids)


@transaction.atomic
def _claim_cleanup_lease(now):
    row, created = PeriodicTaskRun.objects.select_for_update().get_or_create(
        name=CLEANUP_LEASE_NAME,
        defaults={"last_run_at": now},
    )
    if not created and now - row.last_run_at < CLEANUP_LEASE_DURATION:
        return False
    if not created:
        row.last_run_at = now
        row.save(update_fields=("last_run_at",))
    return True
