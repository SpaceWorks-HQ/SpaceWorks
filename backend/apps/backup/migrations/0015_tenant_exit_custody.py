import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ("backup", "0014_b1_artifact_ledger_guards"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="MakerspaceTenantExitCustodyState",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("state", models.CharField(choices=[("healthy", "Healthy"), ("degraded_one_recipient", "Degraded: one recipient"), ("floor_breached_zero", "Floor breached: zero")], default="healthy", max_length=32)),
                ("reason_code", models.CharField(blank=True, max_length=64)),
                ("entered_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("cleared_at", models.DateTimeField(blank=True, null=True)),
                ("last_alarm_at", models.DateTimeField(blank=True, null=True)),
                ("alarm_episode", models.PositiveBigIntegerField(default=0)),
                ("alarm_revision", models.PositiveBigIntegerField(default=0)),
                ("makerspace", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="tenant_exit_custody_state", to="makerspaces.makerspace")),
                ("triggering_recipient", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="triggered_tenant_exit_custody_states", to="backup.makerspacearchiverecipient")),
            ],
        ),
        migrations.CreateModel(
            name="TenantExitCustodyAlarmDelivery",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("alarm_revision", models.PositiveBigIntegerField()),
                ("cycle", models.PositiveIntegerField(default=0)),
                ("channel", models.CharField(choices=[("tenant_inapp", "Tenant in-app"), ("tenant_email", "Tenant email"), ("operator_email", "Operator email")], max_length=32)),
                ("recipient_ref", models.BigIntegerField(blank=True, null=True)),
                ("claim_token", models.UUIDField(blank=True, null=True)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("sending", "Sending"), ("sent", "Sent"), ("failed", "Failed"), ("exhausted", "Exhausted")], default="pending", max_length=16)),
                ("attempts", models.PositiveIntegerField(default=0)),
                ("claimed_at", models.DateTimeField(blank=True, null=True)),
                ("next_attempt_at", models.DateTimeField(blank=True, null=True)),
                ("last_error", models.CharField(blank=True, max_length=200)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("email_log", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="tenant_exit_custody_alarm_deliveries", to="integrations.emaillog")),
                ("makerspace", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="tenant_exit_custody_alarm_deliveries", to="makerspaces.makerspace")),
                ("notification", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="tenant_exit_custody_alarm_deliveries", to="notifications.notification")),
                ("recipient_user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="tenant_exit_custody_alarm_deliveries", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ("created_at", "pk"),
                "indexes": [
                    models.Index(fields=["status", "next_attempt_at", "claimed_at"], name="backup_texit_status_idx"),
                    models.Index(fields=["makerspace", "alarm_revision", "cycle"], name="backup_texit_revision_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(condition=models.Q(recipient_ref__isnull=False), fields=("makerspace", "alarm_revision", "cycle", "channel", "recipient_ref"), name="uniq_tenant_exit_alarm_targeted"),
                    models.UniqueConstraint(condition=models.Q(recipient_ref__isnull=True), fields=("makerspace", "alarm_revision", "cycle", "channel"), name="uniq_tenant_exit_alarm_untargeted"),
                    models.CheckConstraint(condition=(models.Q(channel="tenant_inapp", recipient_ref__isnull=True) | models.Q(channel__in=("tenant_email", "operator_email"), recipient_ref__isnull=False)), name="tenant_exit_alarm_channel_ref"),
                ],
            },
        ),
    ]
