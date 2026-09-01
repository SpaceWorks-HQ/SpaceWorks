from django.conf import settings
from django.db import models
from django.db.models import Q
from apps.machines.metering import MeteringUnit, validate_type_config
from apps.machines.service_file_policies import (
    default_service_file_policy,
    validate_service_file_policy,
)
from apps.machines.printer_capabilities import validate_machine_payload, validate_printer_config

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

