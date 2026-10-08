"""Per-photo state machine for abandoned-upload cleanup (claim / complete / release).

Lock order everywhere: EvidencePhoto, EvidenceUploadFinalization,
EvidenceObjectRetentionState -- the same order as attachment and Mechanism A. A
``cleaning`` state row blocks every attachment path while bytes are deleted outside the
transaction. ``complete`` is the crash boundary: quota, receipt, sidecar deletion,
the exact-ID authorized parent DELETE and the one cleanup audit commit together.
"""

from dataclasses import dataclass
from datetime import timedelta
import uuid

from django.conf import settings
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.evidence.abandoned_upload_candidates import abandoned_queryset
from apps.evidence.models import (
    EvidenceAbandonedUploadReceipt,
    EvidenceObjectRetentionState,
    EvidencePhoto,
    EvidenceUploadFinalization,
)
from apps.makerspaces import limits

RECONCILE_INTERVAL = timedelta(minutes=360)
CLEANING = EvidenceObjectRetentionState.Status.CLEANING
EXPIRED = EvidenceObjectRetentionState.Status.EXPIRED


@dataclass(frozen=True)
class CleanupClaim:
    evidence_id: int
    makerspace_id: int
    object_key: str
    token: uuid.UUID


def _lock(evidence_id):
    photo = EvidencePhoto.objects.select_for_update().filter(pk=evidence_id).first()
    if photo is None:
        return None, None, None
    finalization = EvidenceUploadFinalization.objects.select_for_update().filter(
        evidence_id=evidence_id
    ).first()
    state = EvidenceObjectRetentionState.objects.select_for_update().filter(
        evidence_id=evidence_id
    ).first()
    return photo, finalization, state


def _still_abandoned(photo, cutoff):
    return abandoned_queryset(photo.makerspace_id, cutoff).filter(pk=photo.pk).exists()


def claim(evidence_id, *, makerspace_id, cutoff, now):
    stale_before = now - timedelta(seconds=max(settings.EVIDENCE_URL_TTL_SECONDS, 60))
    with transaction.atomic():
        photo, _finalization, state = _lock(evidence_id)
        if photo is None or photo.makerspace_id != makerspace_id:
            return None
        if not _still_abandoned(photo, cutoff):
            return None
        if state is not None and state.status == CLEANING and state.claim_token:
            if state.claimed_at and state.claimed_at > stale_before:
                return None  # a live competing claim is never stolen
        token = uuid.uuid4()
        if state is None:
            EvidenceObjectRetentionState.objects.create(
                evidence=photo, status=CLEANING, claim_token=token, claimed_at=now,
            )
        else:
            # EXPIRED keeps object_expired_at/expired_size_bytes so completion knows
            # Mechanism A already released quota. EXPIRING was excluded by the query.
            state.status = CLEANING
            state.claim_token = token
            state.claimed_at = now
            state.last_error = ""
            state.save(update_fields=("status", "claim_token", "claimed_at", "last_error", "updated_at"))
        return CleanupClaim(photo.pk, photo.makerspace_id, photo.object_key, token)


def release(current, exc):
    """Leave a durable, retryable, attachment-blocking ``cleaning`` row."""
    with transaction.atomic():
        _photo, _finalization, state = _lock(current.evidence_id)
        if state is None or state.status != CLEANING or state.claim_token != current.token:
            return
        state.claim_token = None
        state.claimed_at = None
        state.last_error = f"{type(exc).__name__}: {exc}"[:500]
        state.save(update_fields=("claim_token", "claimed_at", "last_error", "updated_at"))


def _reserve(photo, now):
    """Create (or verify exactly) the receipt; any mismatch fails closed."""
    values = {
        "source_makerspace_id_snapshot": photo.makerspace_id,
        "evidence_id_snapshot": photo.pk,
        "object_key": photo.object_key,
    }
    existing = EvidenceAbandonedUploadReceipt.objects.filter(object_key=photo.object_key).first()
    if existing is None:
        try:
            with transaction.atomic():
                return EvidenceAbandonedUploadReceipt.objects.create(
                    **values, next_reconcile_at=now + RECONCILE_INTERVAL
                )
        except IntegrityError:
            existing = EvidenceAbandonedUploadReceipt.objects.filter(
                source_makerspace_id_snapshot=photo.makerspace_id,
                evidence_id_snapshot=photo.pk,
            ).first()
    if existing is None or any(getattr(existing, k) != v for k, v in values.items()):
        raise RuntimeError("Abandoned-upload receipt conflicts with its cleanup candidate.")
    return existing


def complete(current, *, cutoff, policy_days, sizes, outcomes, run_id):
    with transaction.atomic():
        photo, finalization, state = _lock(current.evidence_id)
        if photo is None or state is None:
            return None
        if state.status != CLEANING or state.claim_token != current.token:
            return None
        if not _still_abandoned(photo, cutoff):
            raise RuntimeError("Abandoned-upload recheck failed after object deletion.")
        size = (
            sizes["final"] or sizes["staging"]
            or getattr(finalization, "size_bytes", None) or photo.size_bytes or 0
        )
        released = 0
        if state.object_expired_at is None:  # Mechanism A has not already credited it
            charged = (
                settings.STORAGE_PRESIGN_METHOD != "put"
                or finalization is None
                or finalization.quota_charged
            )
            if charged and size:
                limits.free_storage(photo.makerspace, size)
                released = size
        now = timezone.now()
        _reserve(photo, now)
        if finalization is not None:
            EvidenceUploadFinalization.objects.filter(evidence_id=photo.pk).delete()
        EvidenceObjectRetentionState.objects.filter(pk=state.pk).delete()
        meta = {
            "evidence_id": photo.pk,
            "evidence_type": photo.evidence_type,
            "evidence_created_at": photo.created_at.isoformat(),
            "policy_days": policy_days,
            "cutoff": cutoff.isoformat(),
            "final_outcome": outcomes["final"],
            "staging_outcome": outcomes["staging"],
            "removed_size_bytes": size,
            "quota_released_bytes": released,
            "sweep_run_id": str(run_id),
        }
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('app.evidence_abandoned_delete_id', %s, true)",
                [str(photo.pk)],
            )
        EvidencePhoto.objects.filter(pk=photo.pk).delete()
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('app.evidence_abandoned_delete_id', '', true)")
        audit.record(
            None,
            "evidence.abandoned_upload_deleted",
            makerspace=photo.makerspace,
            target=photo.makerspace,
            meta=meta,
        )
        return {"removed_size_bytes": size, "quota_released_bytes": released}
