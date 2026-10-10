"""The exact predicate for an abandoned (never-consumed) evidence upload.

Shared by preview, discovery and the locked rechecks so they can never disagree.
Absence of relationships is necessary but not sufficient: the positive proof is
``consumption_state=unconsumed``, which only a post-migration presign can carry. The
PostgreSQL delete guard re-checks every clause independently.
"""

from datetime import timedelta

from django.conf import settings
from django.db.models import CharField, Exists, OuterRef
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast

from apps.evidence.models import (
    EvidenceObjectRetentionState,
    EvidencePhoto,
    EvidenceRetentionPolicy,
    EvidenceUploadFinalization,
)
from apps.evidence.retention_models import (
    MAX_ABANDONED_UPLOAD_DAYS,
    MIN_ABANDONED_UPLOAD_DAYS,
)

CONSUMPTION_META_ACTIONS = ("evidence.attached", "request.issued", "problem_report.triaged")
ACTIVE_FINALIZATION = (
    EvidenceUploadFinalization.Status.PENDING,
    EvidenceUploadFinalization.Status.PROMOTING,
)


class InvalidAbandonedPolicy(ValueError):
    pass


def abandoned_policy(makerspace_id):
    """Return (tenant_enabled, platform_days, override_days, effective_days)."""
    row = EvidenceRetentionPolicy.objects.filter(makerspace_id=makerspace_id).values(
        "abandoned_upload_cleanup_enabled", "abandoned_upload_retention_days"
    ).first() or {}
    platform = settings.EVIDENCE_ABANDONED_UPLOAD_RETENTION_DAYS
    override = row.get("abandoned_upload_retention_days")
    return (
        bool(row.get("abandoned_upload_cleanup_enabled")),
        platform,
        override,
        override or platform,
    )


def minimum_age(effective_days):
    """Fail-safe age: never trust persisted days below the current presign TTL."""
    if not MIN_ABANDONED_UPLOAD_DAYS <= int(effective_days) <= MAX_ABANDONED_UPLOAD_DAYS:
        raise InvalidAbandonedPolicy("Abandoned-upload retention days are out of range.")
    return timedelta(
        seconds=max(int(effective_days) * 86400, settings.EVIDENCE_URL_TTL_SECONDS + 1)
    )


def abandoned_queryset(makerspace_id, cutoff):
    """Photos strictly older than ``cutoff`` that no workflow ever consumed."""
    from apps.audit.models import AuditLog
    from apps.hardware_requests.models import (
        HardwareRequest,
        PublicToolLoan,
        RequesterAccountability,
        ReturnEvent,
    )

    photo_id = Cast(OuterRef("pk"), output_field=CharField())
    attached_target = AuditLog.objects.filter(
        action="evidence.attached",
        target_type="evidence.evidencephoto",
        target_id=photo_id,
    )
    consumed_meta = AuditLog.objects.annotate(
        evidence_ref=KeyTextTransform("evidence_id", "meta")
    ).filter(action__in=CONSUMPTION_META_ACTIONS, evidence_ref=photo_id)
    return (
        EvidencePhoto.objects.filter(
            makerspace_id=makerspace_id,
            created_at__lt=cutoff,
            consumption_state=EvidencePhoto.ConsumptionState.UNCONSUMED,
        )
        .filter(~Exists(HardwareRequest.objects.filter(issue_evidence_id=OuterRef("pk"))))
        .filter(~Exists(ReturnEvent.objects.filter(evidence_id=OuterRef("pk"))))
        .filter(
            ~Exists(RequesterAccountability.objects.filter(evidence_photo_id=OuterRef("pk")))
        )
        .filter(~Exists(PublicToolLoan.objects.filter(return_evidence_id=OuterRef("pk"))))
        .filter(~Exists(attached_target))
        .filter(~Exists(consumed_meta))
        .filter(
            ~Exists(
                EvidenceUploadFinalization.objects.filter(
                    evidence_id=OuterRef("pk"), status__in=ACTIVE_FINALIZATION
                )
            )
        )
        .filter(
            ~Exists(
                EvidenceObjectRetentionState.objects.filter(
                    evidence_id=OuterRef("pk"),
                    status=EvidenceObjectRetentionState.Status.EXPIRING,
                )
            )
        )
        .order_by("created_at", "pk")
    )
