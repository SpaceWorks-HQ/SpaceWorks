from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.encryption.mappers import ScopedPiiModelMixin, ScopedPiiQuerySet
from apps.machines.metering import MeteringUnit
from apps.machines.model_fields import PreservableCreatedAtField
from apps.machines.models_catalog import Machine


class MachineUsageEntryQuerySet(ScopedPiiQuerySet):
    def update(self, **kwargs):
        raise RuntimeError("MachineUsageEntry rows are append-only.")

    def delete(self):
        raise RuntimeError("MachineUsageEntry rows are append-only.")


class MachineUsageEntry(ScopedPiiModelMixin, models.Model):
    """Append-only generic and typed service-usage ledger."""

    class Source(models.TextChoices):
        MANUAL = "manual", "Manual hours"
        TYPED_MANUAL = "typed_manual", "Typed manual service"

    machine = models.ForeignKey(
        Machine, on_delete=models.CASCADE, related_name="usage_entries"
    )
    hours = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    source = models.CharField(
        max_length=16, choices=Source.choices, default=Source.MANUAL
    )
    note = models.CharField(max_length=255, blank=True)
    service_request = models.ForeignKey(
        "machines.MachineServiceRequest", null=True, blank=True,
        on_delete=models.PROTECT, related_name="usage_entries",
    )
    consumable_pool = models.ForeignKey(
        "machines.MachineConsumablePool", null=True, blank=True,
        on_delete=models.PROTECT, related_name="usage_entries",
    )
    duration_minutes = models.PositiveIntegerField(default=0)
    outcome = models.CharField(max_length=16, blank=True, default="")
    percent_complete = models.PositiveSmallIntegerField(default=100)
    reason = models.TextField(blank=True)
    consumed_grams = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    metering_unit = models.CharField(max_length=12, choices=MeteringUnit.choices, default=MeteringUnit.WEIGHT)
    consumed_quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    # Typed print usage keeps the historical manual-log contract rather than
    # flattening it into generic hours.  These are encrypted when scoped PII is
    # enabled and are deliberately absent from public projections.
    legacy_manual_print_log_id = models.PositiveIntegerField(null=True, blank=True, unique=True, editable=False)
    title = models.CharField(max_length=200, blank=True)
    requester_name = models.TextField(blank=True)
    contact_email = models.TextField(blank=True)
    contact_phone = models.TextField(blank=True)
    logged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = PreservableCreatedAtField(auto_now_add=True)

    objects = MachineUsageEntryQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["machine", "created_at"],
                name="usage_machine_created_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(hours__gte=0),
                name="machineusage_hours_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(percent_complete__gte=0, percent_complete__lte=100),
                name="machineusage_percent_complete_range",
            ),
            models.CheckConstraint(
                condition=Q(consumed_grams__gte=0),
                name="machineusage_grams_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(consumed_quantity__gte=0),
                name="machineusage_quantity_nonnegative",
            ),
        ]

    def __str__(self):
        return f"{self.machine}: {self.hours}h"

    def save(self, *args, preserve_created_at=False, **kwargs):
        if self.pk:
            raise RuntimeError("MachineUsageEntry rows are append-only.")
        # Cutover imports are append-only inserts too.  Django's auto_now_add
        # would otherwise replace the source-ledger timestamp at insert time.
        # Keep this opt-in so normal callers cannot backdate usage entries.
        if not preserve_created_at:
            return super().save(*args, **kwargs)
        self._preserve_created_at = True
        try:
            return super().save(*args, **kwargs)
        finally:
            del self._preserve_created_at


class MachineDocument(models.Model):
    """Manuals / SOP documents in the private object-storage bucket."""

    class DocType(models.TextChoices):
        MANUAL = "manual", "Manual"
        SOP = "sop", "SOP"

    machine = models.ForeignKey(
        Machine, on_delete=models.CASCADE, related_name="documents"
    )
    doc_type = models.CharField(max_length=16, choices=DocType.choices)
    object_key = models.CharField(max_length=255, unique=True)
    original_filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100)
    size_bytes = models.PositiveBigIntegerField(default=0)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.doc_type}: {self.original_filename}"


class MachineErrorLog(models.Model):
    """Append-only machine technical-fault log (distinct from M2 Incident Reporting)."""

    class Severity(models.TextChoices):
        INFO = "info", "Info"
        WARNING = "warning", "Warning"
        ERROR = "error", "Error"
        CRITICAL = "critical", "Critical"

    machine = models.ForeignKey(
        Machine, on_delete=models.CASCADE, related_name="error_logs"
    )
    severity = models.CharField(max_length=16, choices=Severity.choices)
    message = models.TextField()
    logged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.severity} @ {self.machine}"


class MachineConsumable(models.Model):
    class Measurement(models.TextChoices):
        COUNT = "count", "Count"
        GRAMS = "grams", "Grams"

    machine = models.ForeignKey(
        Machine, on_delete=models.CASCADE, related_name="consumables"
    )
    measurement = models.CharField(max_length=10, choices=Measurement.choices)
    product = models.ForeignKey(
        "inventory.InventoryProduct",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="machine_consumables",
    )
    label = models.CharField(max_length=200, blank=True)
    remaining = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    low_threshold = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    note = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["measurement", "label", "product__name"]
        unique_together = ("machine", "product")
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(measurement="count", product__isnull=False)
                    | Q(measurement="grams", product__isnull=True)
                ),
                name="machineconsumable_count_xor_grams",
            ),
        ]

    def __str__(self):
        name = self.product.name if self.product_id else self.label
        return f"{name} @ {self.machine}"
