from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q

from apps.machines.model_fields import PreservableCreatedAtField
from apps.machines.metering import ConsumablePoolUnit, MeteringUnit
from apps.machines.models_service_requests import MachineServiceRequest


class MachineConsumablePool(models.Model):
    """A makerspace gram pool with an optional compatible-machine affinity."""

    makerspace = models.ForeignKey("makerspaces.Makerspace", on_delete=models.PROTECT, related_name="machine_consumable_pools")
    machine = models.ForeignKey("machines.Machine", null=True, blank=True, on_delete=models.PROTECT, related_name="consumable_pools")
    material = models.CharField(max_length=100)
    color = models.CharField(max_length=100, blank=True)
    brand = models.CharField(max_length=100, blank=True)
    unit = models.CharField(max_length=12, choices=ConsumablePoolUnit.choices, default=ConsumablePoolUnit.GRAMS)
    lot_code = models.CharField(max_length=100, blank=True)
    initial_grams = models.DecimalField(max_digits=12, decimal_places=2)
    remaining_grams = models.DecimalField(max_digits=12, decimal_places=2)
    low_threshold_grams = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    opened_at = models.DateTimeField(null=True, blank=True)
    legacy_filament_spool_id = models.PositiveIntegerField(null=True, blank=True, unique=True, editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["makerspace", "is_active"], name="consumable_pool_scope_active_idx")]
        constraints = [
            models.CheckConstraint(condition=Q(initial_grams__gte=0), name="consumable_pool_initial_nonnegative"),
            models.CheckConstraint(condition=Q(remaining_grams__gte=0) & Q(remaining_grams__lte=models.F("initial_grams")), name="consumable_pool_balance_capped"),
        ]

    @property
    def label(self):
        return " ".join(item for item in (self.brand, self.material, self.color, self.lot_code) if item)

    def save(self, *args, **kwargs):
        if self.pk:
            original = type(self).objects.only("initial_grams").get(pk=self.pk)
            if original.initial_grams != self.initial_grams:
                raise RuntimeError("MachineConsumablePool initial grams are immutable.")
        return super().save(*args, **kwargs)


class MachineConsumableAdjustmentQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise RuntimeError("MachineConsumableAdjustment rows are append-only.")

    def delete(self):
        raise RuntimeError("MachineConsumableAdjustment rows are append-only.")


class MachineConsumableAdjustment(models.Model):
    class Kind(models.TextChoices):
        RESERVE = "reserve", "Reserve"
        RECONCILE = "reconcile", "Reconcile"
        MANUAL = "manual", "Manual"
        CORRECTION = "correction", "Correction"
        RETIRE = "retire", "Retire"

    consumable_pool = models.ForeignKey(MachineConsumablePool, on_delete=models.PROTECT, related_name="adjustments")
    makerspace = models.ForeignKey("makerspaces.Makerspace", on_delete=models.PROTECT, related_name="machine_consumable_adjustments")
    kind = models.CharField(max_length=16, choices=Kind.choices)
    quantity_delta = models.DecimalField(max_digits=12, decimal_places=2)
    metering_unit = models.CharField(max_length=12, choices=MeteringUnit.choices, default=MeteringUnit.WEIGHT)
    consumed_quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    service_request = models.ForeignKey(MachineServiceRequest, null=True, blank=True, on_delete=models.PROTECT, related_name="consumable_adjustments")
    usage_entry = models.ForeignKey("machines.MachineUsageEntry", null=True, blank=True, on_delete=models.PROTECT, related_name="consumable_adjustments")
    reason = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = PreservableCreatedAtField(auto_now_add=True)
    legacy_filament_adjustment_id = models.PositiveIntegerField(null=True, blank=True, unique=True, editable=False)

    objects = MachineConsumableAdjustmentQuerySet.as_manager()

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [models.CheckConstraint(condition=~Q(quantity_delta=0), name="consumable_adjustment_nonzero")]

    def save(self, *args, preserve_created_at=False, **kwargs):
        if self.pk:
            raise RuntimeError("MachineConsumableAdjustment rows are append-only.")
        # The cutover may preserve the historical ledger timestamp on its one
        # permitted insert.  It must never update an existing adjustment.
        if not preserve_created_at:
            return super().save(*args, **kwargs)
        self._preserve_created_at = True
        try:
            return super().save(*args, **kwargs)
        finally:
            del self._preserve_created_at


class ServiceRequestConsumptionQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise RuntimeError("ServiceRequestConsumption rows are append-only.")

    def delete(self):
        raise RuntimeError("ServiceRequestConsumption rows are append-only.")


class ServiceRequestConsumption(models.Model):
    class Measurement(models.TextChoices):
        COUNT = "count", "Count"
        GRAMS = "grams", "Grams"

    class Outcome(models.TextChoices):
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    service_request = models.ForeignKey(MachineServiceRequest, on_delete=models.PROTECT, related_name="consumptions")
    machine_consumable = models.ForeignKey("machines.MachineConsumable", on_delete=models.PROTECT, related_name="service_request_consumptions")
    measurement = models.CharField(max_length=10, choices=Measurement.choices)
    product = models.ForeignKey("inventory.InventoryProduct", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    label = models.CharField(max_length=200, blank=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0.01)])
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    outcome = models.CharField(max_length=16, choices=Outcome.choices)

    objects = ServiceRequestConsumptionQuerySet.as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["service_request", "machine_consumable"], name="uniq_service_request_consumable"),
            models.CheckConstraint(condition=Q(quantity__gt=0), name="service_req_consumption_qty_positive"),
        ]
        ordering = ["created_at"]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise RuntimeError("ServiceRequestConsumption rows are append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("ServiceRequestConsumption rows are append-only.")
