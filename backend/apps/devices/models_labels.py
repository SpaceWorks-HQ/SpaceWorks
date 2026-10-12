"""Label delivery history and immutable per-operation result receipts. No artifacts."""
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class LabelPrintCommand(models.Model):
    class Result(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCEEDED = "succeeded", "Succeeded"
        RETRYABLE_FAILED = "retryable_failed", "Retryable failure"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    command = models.OneToOneField("devices.DeviceCommand", on_delete=models.CASCADE,
                                   related_name="label_print")
    makerspace = models.ForeignKey("makerspaces.Makerspace", on_delete=models.CASCADE)
    device = models.ForeignKey("devices.Device", on_delete=models.CASCADE)
    batch = models.ForeignKey("operations.QrPrintBatch", null=True, blank=True,
                              on_delete=models.SET_NULL, related_name="label_commands")
    request_id = models.UUIDField()
    batch_id_snapshot = models.PositiveBigIntegerField()
    batch_title_snapshot = models.CharField(max_length=200)
    item_count_snapshot = models.PositiveIntegerField()
    result = models.CharField(max_length=24, choices=Result.choices, default=Result.PENDING)
    result_code = models.CharField(max_length=32, blank=True)
    result_message = models.CharField(max_length=160, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("-created_at", "-id")
        constraints = [
            models.UniqueConstraint(fields=("makerspace", "request_id"), name="label_request_unique"),
            models.CheckConstraint(condition=Q(item_count_snapshot__gte=1), name="label_items_positive"),
            models.CheckConstraint(
                condition=(Q(result__in=["pending", "retryable_failed"], completed_at__isnull=True)
                           | Q(result__in=["succeeded", "failed"], completed_at__isnull=False)),
                name="label_terminal_completion",
            ),
        ]


class LabelPrintResult(models.Model):
    """One receipt per device operation, retained across all subsequent retries."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    makerspace = models.ForeignKey("makerspaces.Makerspace", on_delete=models.CASCADE)
    label_command = models.ForeignKey(LabelPrintCommand, on_delete=models.CASCADE,
                                      related_name="result_receipts")
    operation_id = models.UUIDField()
    # Original report fields, not the exhaustion-adjusted outcome.
    outcome = models.CharField(max_length=24, choices=LabelPrintCommand.Result.choices)
    result_code = models.CharField(max_length=32)
    response_result = models.CharField(max_length=24, choices=LabelPrintCommand.Result.choices)
    response_command_status = models.CharField(max_length=24)
    response_completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("makerspace", "operation_id"), name="label_operation_unique"),
            models.CheckConstraint(condition=Q(outcome__in=["succeeded", "retryable_failed", "failed"]),
                                   name="label_receipt_is_result"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise RuntimeError("Label result receipts are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("Label result receipts are immutable.")
