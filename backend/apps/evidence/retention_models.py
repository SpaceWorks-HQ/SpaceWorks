from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q


MIN_RETENTION_DAYS = 30
MAX_RETENTION_DAYS = 3650


class EvidenceRetentionPolicy(models.Model):
    """Optional tenant override; absence means use the deployment default."""

    makerspace = models.OneToOneField(
        "makerspaces.Makerspace",
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="evidence_retention_policy",
    )
    object_retention_days = models.PositiveIntegerField(
        validators=[
            MinValueValidator(MIN_RETENTION_DAYS),
            MaxValueValidator(MAX_RETENTION_DAYS),
        ]
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(
                    object_retention_days__gte=MIN_RETENTION_DAYS,
                    object_retention_days__lte=MAX_RETENTION_DAYS,
                ),
                name="ck_evidence_retention_days_range",
            )
        ]


class EvidenceObjectRetentionState(models.Model):
    """Mutable expiry coordination kept away from immutable photo metadata."""

    class Status(models.TextChoices):
        EXPIRING = "expiring", "Expiring"
        EXPIRED = "expired", "Expired"

    evidence = models.OneToOneField(
        "evidence.EvidencePhoto",
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="object_retention_state",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.EXPIRING,
    )
    claim_token = models.UUIDField(null=True, blank=True)
    claimed_at = models.DateTimeField(null=True, blank=True)
    object_expired_at = models.DateTimeField(null=True, blank=True)
    expired_size_bytes = models.PositiveBigIntegerField(null=True, blank=True)
    last_error = models.CharField(max_length=500, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(
                        status="expired",
                        object_expired_at__isnull=False,
                        claim_token__isnull=True,
                        claimed_at__isnull=True,
                    )
                    | Q(
                        status="expiring",
                        object_expired_at__isnull=True,
                    )
                ),
                name="ck_evidence_retention_terminal_state",
            )
        ]
