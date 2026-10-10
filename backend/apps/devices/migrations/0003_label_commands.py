"""Label commands extend the existing 7b ledger; no stored artifacts."""
import uuid

from django.conf import settings
from django.db import migrations, models
from django.db.models import Q
from django.utils import timezone

from ._label_guards import GUARD_SQL, DROP_GUARD_SQL


RESULT_CHOICES = [("pending", "Pending"), ("succeeded", "Succeeded"),
                  ("retryable_failed", "Retryable failure"), ("failed", "Failed")]


class Migration(migrations.Migration):
    dependencies = [
        ("devices", "0002_printer_jobs"),
        ("operations", "0009_report_schedules"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="LabelPrintCommand",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("command", models.OneToOneField("devices.DeviceCommand", on_delete=models.CASCADE, related_name="label_print")),
                ("makerspace", models.ForeignKey("makerspaces.Makerspace", on_delete=models.CASCADE)),
                ("device", models.ForeignKey("devices.Device", on_delete=models.CASCADE)),
                ("batch", models.ForeignKey("operations.QrPrintBatch", null=True, blank=True, on_delete=models.SET_NULL, related_name="label_commands")),
                ("request_id", models.UUIDField()),
                ("batch_id_snapshot", models.PositiveBigIntegerField()),
                ("batch_title_snapshot", models.CharField(max_length=200)),
                ("item_count_snapshot", models.PositiveIntegerField()),
                ("result", models.CharField(max_length=24, choices=RESULT_CHOICES, default="pending")),
                ("result_code", models.CharField(max_length=32, blank=True)),
                ("result_message", models.CharField(max_length=160, blank=True)),
                ("completed_at", models.DateTimeField(null=True, blank=True)),
                ("requested_by", models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")),
                ("created_at", models.DateTimeField(default=timezone.now)),
            ],
            options={"ordering": ("-created_at", "-id"), "constraints": [
                models.UniqueConstraint(fields=("makerspace", "request_id"), name="label_request_unique"),
                models.CheckConstraint(condition=Q(item_count_snapshot__gte=1), name="label_items_positive"),
                models.CheckConstraint(condition=(Q(result__in=["pending", "retryable_failed"], completed_at__isnull=True)
                    | Q(result__in=["succeeded", "failed"], completed_at__isnull=False)), name="label_terminal_completion"),
            ]},
        ),
        migrations.CreateModel(
            name="LabelPrintResult",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("makerspace", models.ForeignKey("makerspaces.Makerspace", on_delete=models.CASCADE)),
                ("label_command", models.ForeignKey("devices.LabelPrintCommand", on_delete=models.CASCADE, related_name="result_receipts")),
                ("operation_id", models.UUIDField()),
                ("outcome", models.CharField(max_length=24, choices=RESULT_CHOICES)),
                ("result_code", models.CharField(max_length=32)),
                ("response_result", models.CharField(max_length=24, choices=RESULT_CHOICES)),
                ("response_command_status", models.CharField(max_length=24)),
                ("response_completed_at", models.DateTimeField(null=True, blank=True)),
                ("created_at", models.DateTimeField(default=timezone.now)),
            ],
            options={"constraints": [
                models.UniqueConstraint(fields=("makerspace", "operation_id"), name="label_operation_unique"),
                models.CheckConstraint(condition=Q(outcome__in=["succeeded", "retryable_failed", "failed"]), name="label_receipt_is_result"),
            ]},
        ),
        migrations.AlterField(model_name="deviceevent", name="event_type", field=models.CharField(
            max_length=32, choices=[
                ("created", "Created"), ("updated", "Updated"),
                ("enrollment_created", "Enrollment created"), ("enrolled", "Enrolled"),
                ("rotation_started", "Rotation started"), ("rotated", "Rotated"),
                ("revoked", "Revoked"), ("heartbeat", "Heartbeat"),
                ("printer_bound", "printer bound"), ("printer_unbound", "printer unbound"),
                ("printer_job_created", "printer job created"), ("command_leased", "command leased"),
                ("command_acknowledged", "command acknowledged"),
                ("command_delivery_failed", "command delivery failed"),
                ("printer_telemetry_received", "printer telemetry received"),
                ("printer_result_claimed", "printer result claimed"),
                ("printer_result_applied", "printer result applied"),
                ("printer_result_needs_review", "printer result needs review"),
                ("printer_job_cancelled", "printer job cancelled"),
                ("label_command_created", "Label command created"),
                ("label_content_downloaded", "Label content downloaded"),
                ("label_command_succeeded", "Label command succeeded"),
                ("label_command_retry_scheduled", "Label command retry scheduled"),
                ("label_command_failed", "Label command failed"),
            ])),
        migrations.RunSQL(GUARD_SQL, reverse_sql=DROP_GUARD_SQL),
    ]
