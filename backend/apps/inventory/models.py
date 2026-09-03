from django.core.exceptions import ValidationError
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models

from apps.makerspaces.models import Makerspace


class PublicAvailabilityMode(models.TextChoices):
    EXACT_COUNT = "exact_count", "Exact Count"
    STATUS_ONLY = "status_only", "Status Only"
    HIDDEN = "hidden", "Hidden"


class TrackingMode(models.TextChoices):
    QUANTITY = "quantity", "Quantity"
    INDIVIDUAL = "individual", "Individual"


class Category(models.Model):
    makerspace = models.ForeignKey(
        Makerspace,
        on_delete=models.CASCADE,
        related_name="categories",
    )
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=120)
    display_order = models.PositiveIntegerField(default=0)
    icon = models.CharField(max_length=50, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["makerspace", "slug"],
                name="uniq_category_slug_per_makerspace",
            ),
        ]
        ordering = ["display_order", "name"]
        verbose_name_plural = "Categories"

    def __str__(self) -> str:
        return f"{self.name} [{self.makerspace.slug}]"


class InventoryProduct(models.Model):
    makerspace = models.ForeignKey(
        Makerspace,
        on_delete=models.CASCADE,
        related_name="products",
    )
    box = models.ForeignKey(
        "boxes.Box",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="products",
    )
    category = models.ForeignKey(
        "Category",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="products",
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    image_key = models.CharField(max_length=300, blank=True, default="")
    # Individual-mode availability still derives from the quantity buckets until the
    # Unit service layer (Phase 6); tracking_mode is just a classification flag for now.
    tracking_mode = models.CharField(
        max_length=20,
        choices=TrackingMode.choices,
        default=TrackingMode.QUANTITY,
    )
    total_quantity = models.PositiveIntegerField(default=0)
    available_quantity = models.PositiveIntegerField(default=0)
    reserved_quantity = models.PositiveIntegerField(default=0)
    issued_quantity = models.PositiveIntegerField(default=0)
    damaged_quantity = models.PositiveIntegerField(default=0)
    lost_quantity = models.PositiveIntegerField(default=0)
    # Units pulled out of circulation for repair (e.g. rejected as broken at handover).
    # Counted within total but never available, so the usable count drops until repaired.
    needs_fix_quantity = models.PositiveIntegerField(default=0)
    is_public = models.BooleanField(default=True)
    public_self_checkout_enabled = models.BooleanField(default=False)
    show_public_count = models.BooleanField(default=False)
    public_availability_mode = models.CharField(
        max_length=20,
        choices=PublicAvailabilityMode.choices,
        default=PublicAvailabilityMode.STATUS_ONLY,
    )
    storage_location = models.CharField(max_length=200, blank=True)
    is_archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # Derived: filled by the Postgres trigger in migration 0010, never written by Django,
    # omitted from export and tenant migration (apps/inventory/search.py).
    search_vector = SearchVectorField(null=True, editable=False)

    class Meta:
        verbose_name = "Inventory item"
        verbose_name_plural = "Inventory"
        indexes = [
            models.Index(fields=["makerspace", "is_public", "is_archived"]),
            GinIndex(fields=["search_vector"], name="inventoryproduct_search_gin"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(total_quantity__gte=0),
                name="qty_total_nonneg",
            ),
            models.CheckConstraint(
                condition=models.Q(available_quantity__gte=0),
                name="qty_available_nonneg",
            ),
            models.CheckConstraint(
                condition=models.Q(reserved_quantity__gte=0),
                name="qty_reserved_nonneg",
            ),
            models.CheckConstraint(
                condition=models.Q(issued_quantity__gte=0),
                name="qty_issued_nonneg",
            ),
            models.CheckConstraint(
                condition=models.Q(damaged_quantity__gte=0),
                name="qty_damaged_nonneg",
            ),
            models.CheckConstraint(
                condition=models.Q(lost_quantity__gte=0),
                name="qty_lost_nonneg",
            ),
            models.CheckConstraint(
                condition=models.Q(needs_fix_quantity__gte=0),
                name="qty_needs_fix_nonneg",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    total_quantity__gte=(
                        models.F("available_quantity")
                        + models.F("reserved_quantity")
                        + models.F("issued_quantity")
                        + models.F("damaged_quantity")
                        + models.F("lost_quantity")
                        + models.F("needs_fix_quantity")
                    )
                ),
                name="qty_sum_within_total",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.makerspace.slug})"

    def clean(self):
        if self.box_id and self.box.makerspace_id != self.makerspace_id:
            raise ValidationError(
                {"box": "Box must belong to the same makerspace as the product."}
            )
        if self.category_id and self.category.makerspace_id != self.makerspace_id:
            raise ValidationError(
                {"category": "Category must belong to the same makerspace."}
            )


class InventoryAsset(models.Model):
    class Status(models.TextChoices):
        AVAILABLE = "available", "Available"
        RESERVED = "reserved", "Reserved"
        ISSUED = "issued", "Issued"
        DAMAGED = "damaged", "Damaged"
        LOST = "lost", "Lost"
        RETIRED = "retired", "Retired"
        MAINTENANCE = "maintenance", "Maintenance"

    makerspace = models.ForeignKey(
        Makerspace,
        on_delete=models.CASCADE,
        related_name="assets",
    )
    product = models.ForeignKey(
        InventoryProduct,
        on_delete=models.CASCADE,
        related_name="assets",
    )
    box = models.ForeignKey(
        "boxes.Box",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assets",
    )
    asset_tag = models.CharField(max_length=100)
    serial_number = models.CharField(max_length=100, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.AVAILABLE,
        db_index=True,
    )
    public_self_checkout_enabled = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["makerspace", "asset_tag"],
                name="uniq_asset_tag_per_makerspace",
            ),
        ]
        indexes = [
            models.Index(fields=["makerspace", "status"]),
        ]

    def clean(self):
        errors = {}
        if self.product_id and self.product.makerspace_id != self.makerspace_id:
            errors["product"] = "Product must belong to the same makerspace."
        if self.box_id and self.box.makerspace_id != self.makerspace_id:
            errors["box"] = "Box must belong to the same makerspace."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.asset_tag} ({self.makerspace.slug})"
