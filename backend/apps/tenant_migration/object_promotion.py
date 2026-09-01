"""Lease-claimed, resumable promotion of staged tenant objects."""

import hashlib
import hmac
import logging
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.audit import services as audit
from apps.makerspaces import limits

from . import object_storage
from .insertion_errors import (
    ImportPromotionClaimLost,
    ImportPromotionInProgress,
    ImportVerificationError,
)
from .models_import_objects import TenantImportObject
from .promotion_lease import PromotionClaimHeartbeat


PROMOTION_LEASE_DURATION = timedelta(minutes=15)


logger = logging.getLogger(__name__)


def promote_import_objects(job):
    promoted = 0
    row_ids = list(job.import_objects.order_by("pk").values_list("pk", flat=True))
    for row_id in row_ids:
        row = TenantImportObject.objects.get(pk=row_id)
        if row.state == TenantImportObject.State.VERIFIED:
            continue
        if row.state == TenantImportObject.State.PROMOTED:
            _verify_promoted_object(row)
            continue
        if row.state != TenantImportObject.State.STAGED:
            raise ImportVerificationError(
                f"Object {row.source_key!r} is not available for promotion."
            )
        claimed_at = _claim_staged_object(row)
        try:
            heartbeat = PromotionClaimHeartbeat(
                row.pk,
                claimed_at,
                lease_duration=PROMOTION_LEASE_DURATION,
            )
            try:
                with heartbeat:
                    object_storage.copy_from_staging(
                        row.staging_key,
                        row.bucket_kind,
                        row.target_key,
                        row.content_type,
                    )
            finally:
                claimed_at = heartbeat.claimed_at
            _mark_promoted_and_charge(
                row.pk, job.target_makerspace, claimed_at=claimed_at
            )
            row.refresh_from_db()
            _verify_promoted_object(row)
            promoted += 1
        except ImportPromotionClaimLost:
            # Ownership has moved. Even inspecting and conditionally cleaning the
            # target object here would race the replacement worker's promotion.
            raise
        except Exception:
            _clean_failed_promotion(
                row.pk, job.target_makerspace, claimed_at=claimed_at
            )
            raise
    rows = list(job.import_objects.order_by("pk"))
    _audit_promoted(job, promoted, rows)
    return promoted


def _claim_staged_object(row):
    claimed_at = timezone.now()
    stale_before = claimed_at - PROMOTION_LEASE_DURATION
    claimed = TenantImportObject.objects.filter(
        Q(claimed_at__isnull=True) | Q(claimed_at__lte=stale_before),
        pk=row.pk,
        state=TenantImportObject.State.STAGED,
    ).update(claimed_at=claimed_at, updated_at=claimed_at)
    if claimed != 1:
        raise ImportPromotionInProgress(
            f"Object {row.source_key!r} has an active promotion lease."
        )
    return claimed_at


def _verify_promoted_object(row):
    size, digest = object_storage.digest_object(row.bucket_kind, row.target_key)
    if size != row.size or not hmac.compare_digest(digest, row.sha256):
        raise ImportVerificationError(
            f"Promoted object checksum mismatch for {row.source_key!r}."
        )
    TenantImportObject.objects.filter(
        pk=row.pk, state=TenantImportObject.State.PROMOTED
    ).update(state=TenantImportObject.State.VERIFIED, updated_at=timezone.now())


@transaction.atomic
def _mark_promoted_and_charge(row_id, makerspace, *, claimed_at=None):
    row = TenantImportObject.objects.get(pk=row_id)
    claimed_at = row.claimed_at if claimed_at is None else claimed_at
    if row.state != TenantImportObject.State.STAGED or row.claimed_at != claimed_at:
        logger.warning(
            "tenant_import_promotion_claim_lost",
            extra={"tenant_import_object_id": row_id},
        )
        raise ImportPromotionClaimLost(
            "The object promotion claim is no longer valid."
        )
    limits.add_storage(makerspace, row.size)
    updated = TenantImportObject.objects.filter(
        pk=row_id,
        state=TenantImportObject.State.STAGED,
        claimed_at=claimed_at,
        quota_charged_at__isnull=True,
    ).update(
        state=TenantImportObject.State.PROMOTED,
        quota_charged_at=timezone.now(),
        updated_at=timezone.now(),
    )
    if updated != 1:
        logger.warning(
            "tenant_import_promotion_claim_lost",
            extra={"tenant_import_object_id": row_id},
        )
        raise ImportPromotionClaimLost("The object promotion claim was lost.")


def _clean_failed_promotion(row_id, makerspace, *, claimed_at):
    failed = _fence_failed_promotion(row_id, makerspace, claimed_at=claimed_at)
    if failed is None:
        logger.warning(
            "tenant_import_promotion_claim_lost",
            extra={"tenant_import_object_id": row_id},
        )
        raise ImportPromotionClaimLost(
            "The failed object promotion is now owned by another worker."
        )
    bucket_kind, target_key = failed
    object_storage.delete_object(bucket_kind, target_key)


@transaction.atomic
def _fence_failed_promotion(row_id, makerspace, *, claimed_at):
    row = TenantImportObject.objects.select_for_update().get(pk=row_id)
    if row.claimed_at != claimed_at or row.state not in {
        TenantImportObject.State.STAGED,
        TenantImportObject.State.PROMOTED,
    }:
        return None
    if row.quota_charged_at is not None:
        limits.free_storage(makerspace, row.size)
    row.state = TenantImportObject.State.FAILED
    row.quota_charged_at = None
    row.save(update_fields=("state", "quota_charged_at", "updated_at"))
    return row.bucket_kind, row.target_key


def _audit_promoted(job, count, rows):
    checksums = sorted(row.sha256 for row in rows)
    aggregate = hashlib.sha256("".join(checksums).encode("ascii")).hexdigest()
    audit.record(
        job.actor,
        "tenant_migration.objects_promoted",
        makerspace=job.target_makerspace,
        target=job,
        meta={
            "job_id": str(job.pk),
            "object_count": count,
            "sha256": aggregate,
        },
    )
