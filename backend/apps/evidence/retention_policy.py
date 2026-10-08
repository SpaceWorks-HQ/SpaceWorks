from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import BigIntegerField, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.audit import services as audit
from apps.evidence.abandoned_upload_candidates import (
    InvalidAbandonedPolicy,
    abandoned_policy,
    abandoned_queryset,
    minimum_age,
)
from apps.evidence.models import (
    EvidenceAbandonedUploadReceipt,
    EvidenceObjectRetentionState,
    EvidencePhoto,
    EvidenceRetentionPolicy,
)
from apps.makerspaces.models import Makerspace


POLICY_FIELDS = (
    "object_retention_days",
    "abandoned_upload_cleanup_enabled",
    "abandoned_upload_retention_days",
)


def effective_retention_days(makerspace_id):
    override = EvidenceRetentionPolicy.objects.filter(
        makerspace_id=makerspace_id
    ).values_list("object_retention_days", flat=True).first()
    return override or settings.EVIDENCE_OBJECT_RETENTION_DAYS


def policy_payload(makerspace):
    override = EvidenceRetentionPolicy.objects.filter(
        makerspace=makerspace
    ).values_list("object_retention_days", flat=True).first()
    enabled, platform, abandoned_override, abandoned_effective = abandoned_policy(
        makerspace.pk
    )
    return {
        "makerspace_id": makerspace.pk,
        "platform_default_days": settings.EVIDENCE_OBJECT_RETENTION_DAYS,
        "override_days": override,
        "effective_days": override or settings.EVIDENCE_OBJECT_RETENTION_DAYS,
        "object_expiry_enabled": settings.EVIDENCE_OBJECT_EXPIRY_ENABLED,
        "abandoned_upload_cleanup_enabled": enabled,
        "abandoned_upload_platform_default_days": platform,
        "abandoned_upload_override_days": abandoned_override,
        "abandoned_upload_effective_days": abandoned_effective,
        "abandoned_upload_global_enabled": settings.EVIDENCE_ABANDONED_UPLOAD_CLEANUP_ENABLED,
    }


def _snapshot(policy):
    if policy is None:
        return {"object_retention_days": None, "abandoned_upload_cleanup_enabled": False,
                "abandoned_upload_retention_days": None}
    return {name: getattr(policy, name) for name in POLICY_FIELDS}


def update_policy(makerspace, actor, changes):
    """Partial update: only supplied keys change; the row exists only while non-default."""
    with transaction.atomic():
        locked = Makerspace.objects.select_for_update().get(pk=makerspace.pk)
        policy = EvidenceRetentionPolicy.objects.select_for_update().filter(
            makerspace=locked
        ).first()
        old = _snapshot(policy)
        new = {**old, **{key: changes[key] for key in POLICY_FIELDS if key in changes}}
        is_default = (
            new["object_retention_days"] is None
            and not new["abandoned_upload_cleanup_enabled"]
            and new["abandoned_upload_retention_days"] is None
        )
        if is_default:
            if policy is not None:
                policy.delete()
        elif policy is None:
            EvidenceRetentionPolicy.objects.create(makerspace=locked, **new)
        else:
            for name, value in new.items():
                setattr(policy, name, value)
            policy.save(update_fields=(*POLICY_FIELDS, "updated_at"))
        audit.record(
            actor,
            "evidence.retention_policy_updated",
            makerspace=locked,
            target=locked,
            meta={
                "old_effective_days": old["object_retention_days"]
                or settings.EVIDENCE_OBJECT_RETENTION_DAYS,
                "new_effective_days": new["object_retention_days"]
                or settings.EVIDENCE_OBJECT_RETENTION_DAYS,
                "override_cleared": new["object_retention_days"] is None,
                "old_abandoned_upload_cleanup_enabled": old["abandoned_upload_cleanup_enabled"],
                "new_abandoned_upload_cleanup_enabled": new["abandoned_upload_cleanup_enabled"],
                "old_abandoned_upload_retention_days": old["abandoned_upload_retention_days"],
                "new_abandoned_upload_retention_days": new["abandoned_upload_retention_days"],
            },
        )
    return policy_payload(locked)


def object_candidates(makerspace, *, as_of=None):
    as_of = as_of or timezone.now()
    days = effective_retention_days(makerspace.pk)
    cutoff = as_of - timedelta(days=days)
    return (
        EvidencePhoto.objects.filter(makerspace=makerspace, created_at__lte=cutoff)
        .exclude(
            object_retention_state__status__in=(
                EvidenceObjectRetentionState.Status.EXPIRED,
                EvidenceObjectRetentionState.Status.CLEANING,
            )
        )
        .order_by("created_at", "pk")
    ), days, cutoff


def _candidate_bytes(queryset):
    return queryset.aggregate(
        candidate_bytes=Coalesce(
            Sum(
                Coalesce("upload_finalization__size_bytes", "size_bytes"),
                output_field=BigIntegerField(),
            ),
            Value(0),
            output_field=BigIntegerField(),
        )
    )["candidate_bytes"]


def preview_abandoned_uploads(makerspace, *, limit, as_of=None):
    """Read-only: no locks, report rollup, storage call or write."""
    as_of = as_of or timezone.now()
    _enabled, _platform, _override, effective = abandoned_policy(makerspace.pk)
    receipts = EvidenceAbandonedUploadReceipt.objects.filter(
        source_makerspace_id_snapshot=makerspace.pk
    )
    try:
        cutoff = as_of - minimum_age(effective)
    except InvalidAbandonedPolicy:
        cutoff, count, size = None, 0, 0
    else:
        queryset = abandoned_queryset(makerspace.pk, cutoff)
        count, size = queryset.count(), _candidate_bytes(queryset)
    return {
        "abandoned_upload_cutoff": cutoff,
        "abandoned_upload_candidates": count,
        "abandoned_upload_candidate_bytes": size,
        "abandoned_upload_has_more": count > limit,
        "late_write_receipts": receipts.count(),
        "late_write_receipts_due": receipts.filter(next_reconcile_at__lte=as_of).count(),
    }


def preview_object_expiry(makerspace, *, limit, as_of=None):
    as_of = as_of or timezone.now()
    queryset, days, cutoff = object_candidates(makerspace, as_of=as_of)
    count = queryset.count()
    return {
        "as_of": as_of,
        "policy_days": days,
        "cutoff": cutoff,
        "object_candidates": count,
        "candidate_bytes": _candidate_bytes(queryset),
        "has_more": count > limit,
        **preview_abandoned_uploads(makerspace, limit=limit, as_of=as_of),
    }
