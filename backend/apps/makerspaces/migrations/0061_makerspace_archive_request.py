from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("makerspaces", "0060_makerspace_public_stats_show_holder_names"),
    ]

    operations = [
        migrations.CreateModel(
            name="MakerspaceArchiveRequest",
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
                ("requested_at", models.DateTimeField(auto_now_add=True)),
                ("resolved_at", models.DateTimeField(blank=True, null=True)),
                (
                    "reason",
                    models.TextField(
                        help_text=(
                            "Do not include personal data. Maximum 2,000 characters."
                        ),
                        max_length=2000,
                    ),
                ),
                ("resolution_note", models.TextField(blank=True, max_length=2000)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("approved", "Approved"),
                            ("declined", "Declined"),
                            ("withdrawn", "Withdrawn"),
                        ],
                        default="pending",
                        max_length=16,
                    ),
                ),
                (
                    "makerspace",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="archive_requests",
                        to="makerspaces.makerspace",
                    ),
                ),
                (
                    "requested_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="makerspace_archive_requests",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "resolved_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="resolved_makerspace_archive_requests",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-requested_at", "-id"],
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(("status", "pending")),
                        fields=("makerspace",),
                        name="uniq_pending_makerspace_archive_request",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(
                                ("resolved_at__isnull", True),
                                ("resolved_by__isnull", True),
                                ("status", "pending"),
                            )
                            | models.Q(
                                ("resolved_at__isnull", False),
                                (
                                    "status__in",
                                    ["approved", "declined", "withdrawn"],
                                ),
                            )
                        ),
                        name="ck_archive_request_resolution_state",
                    ),
                    models.CheckConstraint(
                        condition=(
                            ~models.Q(("status", "declined"))
                            | ~models.Q(("resolution_note", ""))
                        ),
                        name="ck_declined_archive_request_has_note",
                    ),
                    models.CheckConstraint(
                        condition=~models.Q(("reason", "")),
                        name="ck_archive_request_has_reason",
                    ),
                ],
            },
        ),
    ]
