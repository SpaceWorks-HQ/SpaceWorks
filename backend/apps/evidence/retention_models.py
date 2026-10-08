from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone


MIN_RETENTION_DAYS = 30
MAX_RETENTION_DAYS = 3650
MIN_ABANDONED_UPLOAD_DAYS = 1
MAX_ABANDONED_UPLOAD_DAYS = 3650


class EvidenceRetentionPolicy(models.Model):
    """Optional tenant override; absence means use the deployment defaults."""

    # NOT primary_key=True, for the same reason as the retention state below: tenant
    # migration supports only an auto-integer or UUID primary key.
    makerspace = models.OneToOneField(
        "makerspaces.Makerspace",
        on_delete=models.CASCADE,
        related_name="evidence_retention_policy",
    )
    # Null means "use the deployment default"; clearing one override must never erase
    # the separate abandoned-upload configuration stored on the same row.
    object_retention_days = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[
            MinValueValidator(MIN_RETENTION_DAYS),
            MaxValueValidator(MAX_RETENTION_DAYS),
        ],
    )
    abandoned_upload_cleanup_enabled = models.BooleanField(default=False)
    abandoned_upload_retention_days = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[
            MinValueValidator(MIN_ABANDONED_UPLOAD_DAYS),
            MaxValueValidator(MAX_ABANDONED_UPLOAD_DAYS),
        ],
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(object_retention_days__isnull=True)
                | Q(
                    object_retention_days__gte=MIN_RETENTION_DAYS,
                    object_retention_days__lte=MAX_RETENTION_DAYS,
                ),
                name="ck_evidence_retention_days_range",
            ),
            models.CheckConstraint(
                condition=Q(abandoned_upload_retention_days__isnull=True)
                | Q(
                    abandoned_upload_retention_days__gte=MIN_ABANDONED_UPLOAD_DAYS,
                    abandoned_upload_retention_days__lte=MAX_ABANDONED_UPLOAD_DAYS,
                ),
                name="ck_evidence_abandoned_days_range",
            ),
        ]


class EvidenceObjectRetentionState(models.Model):
    """Mutable expiry/cleanup coordination kept away from immutable photo metadata."""

    class Status(models.TextChoices):
        EXPIRING = "expiring", "Expiring"
        EXPIRED = "expired", "Expired"
        # Abandoned-upload cleanup owns the row: attachment is blocked while object
        # deletion runs outside the database transaction.
        CLEANING = "cleaning", "Cleaning"

    # NOT primary_key=True: tenant migration only supports an auto-integer or UUID
    # primary key. PROTECT, not CASCADE: Django's collector must never erase this
    # coordination row before the photo-delete trigger can see it.
    evidence = models.OneToOneField(
        "evidence.EvidencePhoto",
        on_delete=models.PROTECT,
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
                    | (
                        Q(status="cleaning")
                        & (
                            Q(claim_token__isnull=True, claimed_at__isnull=True)
                            | Q(claim_token__isnull=False, claimed_at__isnull=False)
                        )
                    )
                ),
                name="ck_evidence_retention_terminal_state",
            )
        ]


RECONCILIATION_FIELDS = frozenset(
    {"next_reconcile_at", "last_reconciled_at", "last_error", "updated_at"}
)


class ReceiptQuerySet(models.QuerySet):
    """Insert-only receipts: only the reconciler's four scheduling fields may change."""

    def update(self, **kwargs):
        raise RuntimeError("Abandoned-upload receipts are permanent; use reconcile_update().")

    def delete(self):
        raise RuntimeError("Abandoned-upload receipts are permanent and cannot be deleted.")

    def reconcile_update(self, **fields):
        extra = set(fields) - RECONCILIATION_FIELDS
        if extra:
            raise ValueError(f"Receipt fields are immutable: {sorted(extra)}.")
        fields.setdefault("updated_at", timezone.now())
        return super().update(**fields)


class EvidenceAbandonedUploadReceipt(models.Model):
    """Permanent deletion authority and key reservation for one cleaned upload.

    Deliberately FK-free: the source makerspace and photo IDs are raw snapshots so
    neither source cutover nor whole-tenant purge can cascade away the only record
    able to repair a late object write. Database triggers enforce the same contract.
    """

    source_makerspace_id_snapshot = models.PositiveBigIntegerField()
    evidence_id_snapshot = models.PositiveBigIntegerField()
    object_key = models.CharField(max_length=512, unique=True)
    next_reconcile_at = models.DateTimeField(db_index=True)
    last_reconciled_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ReceiptQuerySet.as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("source_makerspace_id_snapshot", "evidence_id_snapshot"),
                name="uq_evidence_abandoned_receipt_source",
            )
        ]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise RuntimeError("Abandoned-upload receipts are insert-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("Abandoned-upload receipts are permanent and cannot be deleted.")
