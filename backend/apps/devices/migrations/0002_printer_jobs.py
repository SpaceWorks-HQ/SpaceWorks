"""Durable printer delivery and immutable terminal claims (phase 7b)."""
import uuid
from django.conf import settings
from django.db import migrations, models
from django.db.models import Q
from django.utils import timezone

from ._printer_claim_guards import GUARD_SQL, DROP_GUARD_SQL

class Migration(migrations.Migration):
    dependencies = [("devices", "0001_device_identity"), ("machines", "0024_certifications"), ("encryption", "0007_tenant_import_fence_operation"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(
            name='DeviceCommand',
            fields=[
                ('id', models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ('makerspace', models.ForeignKey('makerspaces.Makerspace', on_delete=models.CASCADE)),
                ('device', models.ForeignKey('devices.Device', on_delete=models.CASCADE, related_name='commands')),
                ('device_key_version', models.PositiveIntegerField()),
                ('kind', models.CharField(max_length=32, default='printer_job')),
                ('status', models.CharField(max_length=24, choices=[('queued', 'Queued'), ('leased', 'Leased'), ('acknowledged', 'Acknowledged'), ('delivery_failed', 'Delivery failed'), ('cancelled', 'Cancelled')], default='queued')),
                ('attempts', models.PositiveIntegerField(default=0)),
                ('next_attempt_at', models.DateTimeField(default=timezone.now)),
                ('lease_token_digest', models.CharField(max_length=64, null=True, blank=True)),
                ('lease_expires_at', models.DateTimeField(null=True, blank=True)),
                ('acknowledged_at', models.DateTimeField(null=True, blank=True)),
                ('last_error_code', models.CharField(max_length=48, blank=True)),
                ('created_by', models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')),
                ('created_at', models.DateTimeField(default=timezone.now)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'indexes': [models.Index(fields=['device', 'status', 'next_attempt_at'], name='device_command_delivery_idx')],
                'constraints': [models.CheckConstraint(condition=~Q(status='leased') | Q(lease_token_digest__isnull=False) & Q(lease_expires_at__isnull=False), name='device_command_lease_complete')],
            },
        ),
        migrations.CreateModel(
            name='PrinterDeviceBinding',
            fields=[
                ('id', models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ('makerspace', models.ForeignKey('makerspaces.Makerspace', on_delete=models.CASCADE)),
                ('device', models.OneToOneField('devices.Device', on_delete=models.CASCADE, related_name='printer_binding')),
                ('machine', models.OneToOneField('machines.Machine', null=True, blank=True, on_delete=models.SET_NULL, related_name='printer_device_binding')),
                ('enabled', models.BooleanField(default=True)),
                ('auto_apply_terminal', models.BooleanField(default=False)),
                ('created_by', models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')),
                ('created_at', models.DateTimeField(default=timezone.now)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
            },
        ),
        migrations.CreateModel(
            name='PrinterJob',
            fields=[
                ('id', models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ('command', models.OneToOneField('devices.DeviceCommand', on_delete=models.CASCADE, related_name='printer_job')),
                ('makerspace', models.ForeignKey('makerspaces.Makerspace', on_delete=models.CASCADE)),
                ('device', models.ForeignKey('devices.Device', on_delete=models.CASCADE)),
                ('machine', models.ForeignKey('machines.Machine', null=True, blank=True, on_delete=models.SET_NULL)),
                ('service_request', models.ForeignKey('machines.MachineServiceRequest', null=True, blank=True, on_delete=models.SET_NULL)),
                ('machine_id_snapshot', models.PositiveBigIntegerField()),
                ('machine_name', models.CharField(max_length=200)),
                ('service_request_id_snapshot', models.PositiveBigIntegerField()),
                ('service_request_name', models.CharField(max_length=120)),
                ('external_job_id', models.CharField(max_length=120)),
                ('state', models.CharField(max_length=24, choices=[('awaiting', 'Awaiting'), ('reported', 'Reported'), ('applied', 'Applied'), ('needs_review', 'Needs review'), ('cancelled', 'Cancelled')], default='awaiting')),
                ('telemetry_state', models.CharField(max_length=16, blank=True)),
                ('progress_percent', models.PositiveSmallIntegerField(null=True, blank=True)),
                ('telemetry_at', models.DateTimeField(null=True, blank=True)),
                ('terminal_operation_id', models.UUIDField(null=True, blank=True)),
                ('report_sha256', models.CharField(max_length=64, blank=True)),
                ('outcome', models.CharField(max_length=16, choices=[('completed', 'Completed'), ('failed', 'Failed')], blank=True)),
                ('actual_minutes', models.PositiveIntegerField(null=True, blank=True)),
                ('failure_reason', models.TextField(blank=True)),
                ('percent_complete', models.PositiveSmallIntegerField(null=True, blank=True)),
                ('actual_grams', models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)),
                ('actual_quantity', models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)),
                ('reported_at', models.DateTimeField(null=True, blank=True)),
                ('applied_at', models.DateTimeField(null=True, blank=True)),
                ('processed_by', models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')),
                ('created_at', models.DateTimeField(default=timezone.now)),
            ],
            options={
                'constraints': [models.UniqueConstraint(fields=['device', 'external_job_id'], name='printer_external_job_once'), models.UniqueConstraint(fields=['device', 'terminal_operation_id'], name='printer_operation_once'), models.UniqueConstraint(fields=['service_request'], condition=Q(state__in=['awaiting', 'reported', 'needs_review']), name='printer_live_request_once'), models.CheckConstraint(condition=Q(actual_grams__isnull=True) | Q(actual_quantity__isnull=True), name='printer_metering_xor'), models.CheckConstraint(condition=Q(actual_grams__isnull=True) | Q(actual_grams__gte=0), name='printer_grams_nonnegative'), models.CheckConstraint(condition=Q(actual_quantity__isnull=True) | Q(actual_quantity__gte=0), name='printer_quantity_nonnegative'), models.CheckConstraint(condition=Q(percent_complete__isnull=True) | Q(percent_complete__lte=100), name='printer_percent_range'), models.CheckConstraint(condition=Q(progress_percent__isnull=True) | Q(progress_percent__lte=100), name='printer_progress_range'), models.CheckConstraint(condition=Q(reported_at__isnull=True) | Q(terminal_operation_id__isnull=False) & ~Q(report_sha256='') & Q(actual_minutes__isnull=False) & Q(outcome__in=['completed', 'failed']), name='printer_terminal_complete'), models.CheckConstraint(condition=~Q(outcome='failed') | ~Q(failure_reason='') & Q(percent_complete__isnull=False), name='printer_failure_complete')],
            },
        ),
        migrations.CreateModel(
            name='PrinterJobConsumption',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('job', models.ForeignKey('devices.printerjob', on_delete=models.CASCADE, related_name='consumptions')),
                ('machine_consumable', models.ForeignKey('machines.MachineConsumable', null=True, blank=True, on_delete=models.SET_NULL)),
                ('machine_consumable_id_snapshot', models.PositiveBigIntegerField()),
                ('quantity', models.DecimalField(max_digits=12, decimal_places=2)),
            ],
            options={
                'constraints': [models.UniqueConstraint(fields=['job', 'machine_consumable_id_snapshot'], name='printer_consumable_once'), models.CheckConstraint(condition=Q(quantity__gt=0), name='printer_consumption_positive')],
            },
        ),
        migrations.AlterField(model_name="deviceevent", name="event_type", field=models.CharField(max_length=32, choices=[('created', 'Created'), ('updated', 'Updated'), ('enrollment_created', 'Enrollment created'), ('enrolled', 'Enrolled'), ('rotation_started', 'Rotation started'), ('rotated', 'Rotated'), ('revoked', 'Revoked'), ('heartbeat', 'Heartbeat'), ('printer_bound', 'printer bound'), ('printer_unbound', 'printer unbound'), ('printer_job_created', 'printer job created'), ('command_leased', 'command leased'), ('command_acknowledged', 'command acknowledged'), ('command_delivery_failed', 'command delivery failed'), ('printer_telemetry_received', 'printer telemetry received'), ('printer_result_claimed', 'printer result claimed'), ('printer_result_applied', 'printer result applied'), ('printer_result_needs_review', 'printer result needs review'), ('printer_job_cancelled', 'printer job cancelled')])),
        migrations.RunSQL(GUARD_SQL, DROP_GUARD_SQL),
    ]
