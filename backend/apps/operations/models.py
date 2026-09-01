from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.boxes.models import Box, QrCode
from apps.inventory.models import InventoryAsset, InventoryProduct
from apps.makerspaces.models import Makerspace

# Re-exported so `apps.operations.models.PeriodicTaskRun` resolves and Django registers
# the model, matching the barrel pattern the rest of this app uses.
from apps.operations.models_scheduling import PeriodicTaskRun  # noqa: F401,E402
from apps.operations.models_rollups import (  # noqa: F401,E402
    ReportMetricRollup,
    ReportRollupCursor,
)


class StockTransfer(models.Model):
    class Status(models.TextChoices):
        APPLIED = "applied", "Applied"
        CANCELLED = "cancelled", "Cancelled"

    makerspace = models.ForeignKey(Makerspace, on_delete=models.CASCADE, related_name="stock_transfers")
    source_container = models.ForeignKey(Box, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    destination_container = models.ForeignKey(Box, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    source_makerspace = models.ForeignKey(Makerspace, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    destination_makerspace = models.ForeignKey(Makerspace, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.APPLIED)
    created_at = models.DateTimeField(auto_now_add=True)
    applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["makerspace", "-created_at"],
                name="stocktransfer_ms_created_idx",
            ),
        ]


class StockTransferLine(models.Model):
    transfer = models.ForeignKey(StockTransfer, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(InventoryProduct, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    asset = models.ForeignKey(InventoryAsset, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    quantity = models.PositiveIntegerField(default=1)
    from_status = models.CharField(max_length=32, blank=True)
    to_status = models.CharField(max_length=32, blank=True)
    notes = models.TextField(blank=True)

    def clean(self):
        if bool(self.product_id) == bool(self.asset_id):
            raise ValidationError("Provide exactly one of product or asset.")


class StocktakeSession(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        COUNTING = "counting", "Counting"
        COMPLETED = "completed", "Completed"
        APPROVED = "approved", "Approved"
        APPLIED = "applied", "Applied"
        CANCELLED = "cancelled", "Cancelled"

    makerspace = models.ForeignKey(Makerspace, on_delete=models.CASCADE, related_name="stocktakes")
    container = models.ForeignKey(Box, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.COUNTING)
    started_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["makerspace", "status", "-started_at"],
                name="stktake_ms_status_start_idx",
            ),
        ]


class StocktakeLine(models.Model):
    class Condition(models.TextChoices):
        AVAILABLE = "available", "Available"
        DAMAGED = "damaged", "Damaged"
        LOST = "lost", "Lost"
        UNKNOWN = "unknown", "Unknown"

    stocktake = models.ForeignKey(StocktakeSession, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(InventoryProduct, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    asset = models.ForeignKey(InventoryAsset, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    container = models.ForeignKey(Box, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    expected_quantity = models.IntegerField(default=0)
    counted_quantity = models.IntegerField(default=0)
    variance_quantity = models.IntegerField(default=0)
    condition = models.CharField(max_length=20, choices=Condition.choices, default=Condition.AVAILABLE)
    notes = models.TextField(blank=True)

    def clean(self):
        if bool(self.product_id) == bool(self.asset_id):
            raise ValidationError("Provide exactly one of product or asset.")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["stocktake", "product", "condition", "container"],
                condition=models.Q(product__isnull=False),
                nulls_distinct=False,
                name="uniq_stocktake_product_bucket_container",
            ),
            models.UniqueConstraint(
                fields=["stocktake", "asset"],
                condition=models.Q(asset__isnull=False),
                name="uniq_stocktake_asset_line",
            ),
        ]


class InventoryAdjustment(models.Model):
    makerspace = models.ForeignKey(Makerspace, on_delete=models.CASCADE, related_name="inventory_adjustments")
    stocktake = models.ForeignKey(StocktakeSession, null=True, blank=True, on_delete=models.SET_NULL, related_name="adjustments")
    transfer = models.ForeignKey(StockTransfer, null=True, blank=True, on_delete=models.SET_NULL, related_name="adjustments")
    product = models.ForeignKey(InventoryProduct, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    asset = models.ForeignKey(InventoryAsset, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    delta_available = models.IntegerField(default=0)
    delta_damaged = models.IntegerField(default=0)
    delta_lost = models.IntegerField(default=0)
    reason = models.TextField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)


class StocktakeLedgerEntry(models.Model):
    class Bucket(models.TextChoices):
        AVAILABLE = "available", "Available"
        DAMAGED = "damaged", "Damaged"
        LOST = "lost", "Lost"

    makerspace = models.ForeignKey(Makerspace, on_delete=models.CASCADE, related_name="stocktake_ledger_entries")
    stocktake = models.ForeignKey(StocktakeSession, on_delete=models.CASCADE, related_name="ledger_entries")
    line = models.ForeignKey(StocktakeLine, on_delete=models.CASCADE, related_name="ledger_entries")
    product = models.ForeignKey(InventoryProduct, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    asset = models.ForeignKey(InventoryAsset, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    bucket = models.CharField(max_length=20, choices=Bucket.choices)
    delta = models.IntegerField()
    old_asset_status = models.CharField(max_length=20, blank=True)
    new_asset_status = models.CharField(max_length=20, blank=True)
    reason = models.TextField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["stocktake", "line", "bucket"],
                name="uniq_stocktake_ledger_line_bucket",
            ),
        ]
        indexes = [
            models.Index(fields=["makerspace", "created_at"]),
            models.Index(fields=["stocktake", "line"]),
        ]


class QrPrintBatch(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PRINTED = "printed", "Printed"
        ARCHIVED = "archived", "Archived"

    makerspace = models.ForeignKey(Makerspace, on_delete=models.CASCADE, related_name="qr_print_batches")
    title = models.CharField(max_length=200)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    printed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["makerspace", "-created_at"],
                name="qrbatch_ms_created_idx",
            ),
        ]


class QrPrintBatchItem(models.Model):
    batch = models.ForeignKey(QrPrintBatch, on_delete=models.CASCADE, related_name="items")
    qr_code = models.ForeignKey(QrCode, on_delete=models.PROTECT, related_name="print_items")
    label_text = models.CharField(max_length=255)
    target_type = models.CharField(max_length=20)
    target_id = models.PositiveIntegerField()
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]
        constraints = [
            models.UniqueConstraint(fields=["batch", "qr_code"], name="uniq_qr_print_batch_item_qr"),
        ]
