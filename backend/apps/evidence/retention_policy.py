from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import BigIntegerField, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.audit import services as audit
from apps.evidence.models import (
    EvidenceObjectRetentionState,
    EvidencePhoto,
    EvidenceRetentionPolicy,
)
from apps.makerspaces.models import Makerspace


def effective_retention_days(makerspace_id):
    override = EvidenceRetentionPolicy.objects.filter(
        makerspace_id=makerspace_id
    ).values_list("object_retention_days", flat=True).first()
    return override or settings.EVIDENCE_OBJECT_RETENTION_DAYS


def policy_payload(makerspace):
    override = EvidenceRetentionPolicy.objects.filter(
        makerspace=makerspace
    ).values_list("object_retention_days", flat=True).first()
    return {
        "makerspace_id": makerspace.pk,
        "platform_default_days": settings.EVIDENCE_OBJECT_RETENTION_DAYS,
        "override_days": override,
        "effective_days": override or settings.EVIDENCE_OBJECT_RETENTION_DAYS,
        "object_expiry_enabled": settings.EVIDENCE_OBJECT_EXPIRY_ENABLED,
    }


def update_policy(makerspace, actor, object_retention_days):
    with transaction.atomic():
        locked = Makerspace.objects.select_for_update().get(pk=makerspace.pk)
        policy = EvidenceRetentionPolicy.objects.select_for_update().filter(
            makerspace=locked
        ).first()
        old_effective = (
            policy.object_retention_days
            if policy is not None
            else settings.EVIDENCE_OBJECT_RETENTION_DAYS
        )
        if object_retention_days is None:
            if policy is not None:
                policy.delete()
        elif policy is None:
            EvidenceRetentionPolicy.objects.create(
                makerspace=locked,
                object_retention_days=object_retention_days,
            )
        else:
            policy.object_retention_days = object_retention_days
            policy.save(update_fields=("object_retention_days", "updated_at"))
        new_effective = object_retention_days or settings.EVIDENCE_OBJECT_RETENTION_DAYS
        audit.record(
            actor,
            "evidence.retention_policy_updated",
            makerspace=locked,
            target=locked,
            meta={
                "old_effective_days": old_effective,
                "new_effective_days": new_effective,
                "override_cleared": object_retention_days is None,
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
            object_retention_state__status=EvidenceObjectRetentionState.Status.EXPIRED
        )
        .order_by("created_at", "pk")
    ), days, cutoff


def preview_object_expiry(makerspace, *, limit, as_of=None):
    as_of = as_of or timezone.now()
    queryset, days, cutoff = object_candidates(makerspace, as_of=as_of)
    totals = queryset.aggregate(
        candidate_bytes=Coalesce(
            Sum(
                Coalesce("upload_finalization__size_bytes", "size_bytes"),
                output_field=BigIntegerField(),
            ),
            Value(0),
            output_field=BigIntegerField(),
        )
    )
    count = queryset.count()
    return {
        "as_of": as_of,
        "policy_days": days,
        "cutoff": cutoff,
        "object_candidates": count,
        "candidate_bytes": totals["candidate_bytes"],
        "has_more": count > limit,
    }
