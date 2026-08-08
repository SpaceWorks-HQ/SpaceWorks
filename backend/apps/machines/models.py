from django.conf import settings
from django.db import models
from django.db.models import Q
from apps.encryption.mappers import ScopedPiiModelMixin, ScopedPiiQuerySet
from apps.machines.metering import MeteringUnit, validate_type_config
from apps.machines.model_fields import PreservableCreatedAtField
from apps.machines.service_file_policies import (
    default_service_file_policy,
    validate_service_file_policy,
)
from apps.machines.printer_capabilities import validate_machine_payload, validate_printer_config

# Service-request models are kept separate so the long-lived machine catalog stays
# compact; importing here preserves the app's established public model surface.
from apps.machines.models_service import (
    MachineConsumableAdjustment,
    MachineConsumablePool,
    MachineServiceRequest,
    ServiceBucket,
    ServiceQueue,
    ServiceRequestConsumption,
    ServiceRequestFile,
    get_or_create_default_bucket,
)
from apps.machines.printing_cutover_models import PrintingCutoverRepair, PrintingCutoverState

# Role -> machine/type scope links. Imported here so Django registers them with this app;
# they use string FK references, so the import order relative to MachineType/Machine below
# does not matter.
from apps.machines.models_role_scope import RoleMachineScope, RoleMachineTypeScope


class MachineType(models.Model):
    """Machine type catalog. Global built-ins (makerspace=NULL) + per-lab custom rows."""

    makerspace = models.ForeignKey(
        "makerspaces.Makerspace",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="machine_types",
    )
    slug = models.SlugField(max_length=50)
    name = models.CharField(max_length=200)
    icon = models.CharField(max_length=50, blank=True)
    is_builtin = models.BooleanField(default=False)
    # Server-controlled authorization hook: the rbac.Action a holder of which may
    # manage machines of this type (e.g. 3d_printer -> "MANAGE_PRINTING"). Blank for
    # custom types. Never client-settable.
    managing_action = models.CharField(max_length=64, blank=True, default="")
    # Versioned, server-validated capability contract.  Type packs own the
    # interpretation; an empty object keeps existing generic types unchanged.
    capability_config = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["makerspace__name", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["slug"],
                condition=Q(makerspace__isnull=True),
                name="uniq_global_machinetype_slug",
            ),
            models.UniqueConstraint(
                fields=["makerspace", "slug"],
                condition=Q(makerspace__isnull=False),
                name="uniq_lab_machinetype_slug",
            ),
            models.CheckConstraint(
                condition=(
                    Q(is_builtin=True, makerspace__isnull=True)
                    | Q(is_builtin=False, makerspace__isnull=False)
                ),
                name="machinetype_builtin_is_global",
            ),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        validate_printer_config(self, self.capability_config)
        validate_type_config(self.capability_config, is_custom=self.makerspace_id is not None)


class MakerspaceMachineTypePricing(models.Model):
    """One makerspace-local pricing decision for a global or local machine type."""

    makerspace = models.ForeignKey("makerspaces.Makerspace", on_delete=models.PROTECT, related_name="machine_type_pricing")
    machine_type = models.ForeignKey("machines.MachineType", on_delete=models.PROTECT, related_name="makerspace_pricing")
    rate_per_unit = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    flat_fee = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    payment_enabled = models.BooleanField(default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["makerspace", "machine_type"], name="uniq_makerspace_machine_type_pricing"),
            models.CheckConstraint(condition=Q(rate_per_unit__gte=0), name="machine_type_pricing_rate_nonnegative"),
            models.CheckConstraint(condition=Q(flat_fee__gte=0), name="machine_type_pricing_flat_nonnegative"),
        ]

    def clean(self):
        super().clean()
        if self.machine_type_id and self.machine_type.makerspace_id not in (None, self.makerspace_id):
            raise ValidationError("Machine type must be global or belong to this makerspace.")


class Machine(models.Model):
    class Status(models.TextChoices):
        IDLE = "idle", "Idle"
        RUNNING = "running", "Running"
        RESERVED = "reserved", "Reserved"
        MAINTENANCE = "maintenance", "Maintenance"
        OFFLINE = "offline", "Offline"

    makerspace = models.ForeignKey(
        "makerspaces.Makerspace",
        on_delete=models.CASCADE,
        related_name="machines",
    )
    machine_type = models.ForeignKey(
        MachineType,
        on_delete=models.PROTECT,
        related_name="machines",
    )
    name = models.CharField(max_length=200)
    location = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.IDLE
    )
    firmware_version = models.CharField(max_length=100, blank=True)
    camera_feed_url = models.URLField(blank=True)
    image_key = models.CharField(max_length=300, blank=True, default="")
    is_public = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    service_file_policy = models.JSONField(
        default=default_service_file_policy,
        validators=[validate_service_file_policy],
    )
    # Per-machine details interpreted only by the validated type pack.  Printer
    # model identity belongs here, not in the shared firmware field.
    type_payload = models.JSONField(default=dict, blank=True)
    # B4 provenance for the legacy printing row imported into this machine.
    legacy_print_printer_id = models.PositiveIntegerField(
        null=True, blank=True, unique=True, editable=False
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        ordering = ["makerspace__name", "name"]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        validate_machine_payload(self.machine_type, self.type_payload)


class MachineOperator(models.Model):
    """Per-machine operator assignment (many-to-many with an access level)."""

    class AccessLevel(models.TextChoices):
        OPERATE = "operate", "Operate"
        MANAGE = "manage", "Manage"
        FULL = "full", "Full"

    machine = models.ForeignKey(
        Machine, on_delete=models.CASCADE, related_name="operators"
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    access_level = models.CharField(max_length=16, choices=AccessLevel.choices)
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("machine", "user")
        ordering = ["-assigned_at"]

    def __str__(self):
        return f"{self.user} @ {self.machine} ({self.access_level})"


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
