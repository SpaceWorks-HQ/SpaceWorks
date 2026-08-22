import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("backup", "0010_archive_custody_not_applicable"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("integrations", "0024_machinetypeemailtemplate"),
        ("notifications", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="makerspacearchivecustodystate",
            name="alarm_revision",
            field=models.PositiveBigIntegerField(default=0),
        ),
        migrations.CreateModel(
            name="ArchiveCustodyAlarmDelivery",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("alarm_revision", models.PositiveBigIntegerField()),
                ("cycle", models.PositiveIntegerField(default=0)),
                (
                    "channel",
                    models.CharField(
                        choices=[
                            ("tenant_inapp", "Tenant in-app"),
                            ("tenant_email", "Tenant email"),
                            ("operator_email", "Operator email"),
                        ],
                        max_length=32,
                    ),
                ),
                ("recipient_ref", models.BigIntegerField(blank=True, null=True)),
                ("claim_token", models.UUIDField(blank=True, null=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("sending", "Sending"),
                            ("sent", "Sent"),
                            ("failed", "Failed"),
                            ("exhausted", "Exhausted"),
                        ],
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("attempts", models.PositiveIntegerField(default=0)),
                ("claimed_at", models.DateTimeField(blank=True, null=True)),
                ("next_attempt_at", models.DateTimeField(blank=True, null=True)),
                ("last_error", models.CharField(blank=True, max_length=200)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "email_log",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="archive_custody_alarm_deliveries",
                        to="integrations.emaillog",
                    ),
                ),
                (
                    "makerspace",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="archive_custody_alarm_deliveries",
                        to="makerspaces.makerspace",
                    ),
                ),
                (
                    "notification",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="archive_custody_alarm_deliveries",
                        to="notifications.notification",
                    ),
                ),
                (
                    "recipient_user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="archive_custody_alarm_deliveries",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("created_at", "pk"),
                "indexes": [
                    models.Index(
                        fields=("status", "next_attempt_at", "claimed_at"),
                        name="backup_arch_status_353972_idx",
                    ),
                    models.Index(
                        fields=("makerspace", "alarm_revision", "cycle"),
                        name="backup_arch_makersp_098213_idx",
                    ),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(recipient_ref__isnull=False),
                        fields=(
                            "makerspace",
                            "alarm_revision",
                            "cycle",
                            "channel",
                            "recipient_ref",
                        ),
                        name="uniq_custody_alarm_targeted",
                    ),
                    models.UniqueConstraint(
                        condition=models.Q(recipient_ref__isnull=True),
                        fields=(
                            "makerspace",
                            "alarm_revision",
                            "cycle",
                            "channel",
                        ),
                        name="uniq_custody_alarm_untargeted",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(
                                channel="tenant_inapp",
                                recipient_ref__isnull=True,
                            )
                            | models.Q(
                                channel__in=("tenant_email", "operator_email"),
                                recipient_ref__isnull=False,
                            )
                        ),
                        name="custody_alarm_channel_requires_ref",
                    ),
                ],
            },
        ),
    ]
