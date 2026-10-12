from django.conf import settings
from django.db import models
from django.db.models import Q


class EvidencePhoto(models.Model):
    """Evidence object record; database triggers are the real guard.

    Identity and content columns are immutable. The only permitted UPDATE is the
    one-way ``consumption_state`` transition to ``consumed`` made by a consuming
    workflow (``apps.evidence.consumption``). Attached issue/return/accountability
    evidence is never deleted; only a post-marker presign proven ``unconsumed`` may be
    removed, by the default-off abandoned-upload cleanup under an exact-ID database
    authorization and a permanent cleanup receipt. Instance ``save()``/``delete()``
    still refuse every mutation.
    """

    class EvidenceType(models.TextChoices):
        ISSUE = "issue", "Issue"
        RETURN = "return", "Return"

    class ConsumptionState(models.TextChoices):
        # Every pre-migration and imported row: never a cleanup candidate.
        LEGACY_UNKNOWN = "legacy_unknown", "Legacy (unknown)"
        # Only the two production presign views create this.
        UNCONSUMED = "unconsumed", "Unconsumed"
        CONSUMED = "consumed", "Consumed"

    makerspace = models.ForeignKey(
        "makerspaces.Makerspace",
        on_delete=models.PROTECT,
        related_name="evidence_photos",
    )
    evidence_type = models.CharField(max_length=20, choices=EvidenceType.choices)
    object_key = models.CharField(max_length=512, unique=True)
    content_type = models.CharField(max_length=128, blank=True)
    size_bytes = models.PositiveBigIntegerField(null=True, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
    )
    consumption_state = models.CharField(
        max_length=16,
        choices=ConsumptionState.choices,
        default=ConsumptionState.LEGACY_UNKNOWN,
        db_default=ConsumptionState.LEGACY_UNKNOWN,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(
                    consumption_state__in=("legacy_unknown", "unconsumed", "consumed")
                ),
                name="ck_evidence_consumption_state",
            )
        ]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise RuntimeError("EvidencePhoto rows are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("EvidencePhoto rows are immutable.")

    def __str__(self):
        return f"{self.evidence_type} evidence {self.pk}"


class EvidenceUploadFinalization(models.Model):
    """Mutable coordination state kept separate from immutable evidence metadata."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROMOTING = "promoting", "Promoting"
        FINALIZED = "finalized", "Finalized"

    # PROTECT, not CASCADE: cleanup and tenant purge delete this sidecar explicitly so
    # Django's collector can never pre-empt the photo-delete trigger's checks.
    evidence = models.OneToOneField(
        EvidencePhoto,
        on_delete=models.PROTECT,
        primary_key=True,
        related_name="upload_finalization",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
    )
    claim_token = models.UUIDField(null=True, blank=True)
    size_bytes = models.PositiveBigIntegerField(null=True, blank=True)
    content_type = models.CharField(max_length=128, blank=True)
    quota_charged = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)


from apps.evidence.retention_models import (  # noqa: E402,F401
    EvidenceAbandonedUploadReceipt,
    EvidenceObjectRetentionState,
    EvidenceRetentionPolicy,
)
