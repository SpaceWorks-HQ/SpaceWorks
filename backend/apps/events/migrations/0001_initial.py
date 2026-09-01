import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("makerspaces", "0032_enable_events_module"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Event",
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
                (
                    "public_token",
                    models.UUIDField(
                        db_index=True,
                        default=uuid.uuid4,
                        editable=False,
                        unique=True,
                    ),
                ),
                ("title", models.CharField(max_length=200)),
                ("description", models.TextField(blank=True)),
                ("starts_at", models.DateTimeField()),
                ("ends_at", models.DateTimeField()),
                ("location", models.CharField(blank=True, max_length=255)),
                ("capacity", models.PositiveIntegerField(default=0)),
                ("is_public", models.BooleanField(default=False)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("published", "Published"),
                            ("cancelled", "Cancelled"),
                            ("completed", "Completed"),
                        ],
                        default="draft",
                        max_length=16,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "makerspace",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="events",
                        to="makerspaces.makerspace",
                    ),
                ),
            ],
            options={
                "ordering": ["starts_at", "id"],
                "indexes": [
                    models.Index(
                        fields=["makerspace", "status", "starts_at"],
                        name="event_ms_status_start_idx",
                    ),
                    models.Index(
                        fields=["makerspace", "is_public", "status", "ends_at"],
                        name="event_public_lookup_idx",
                    ),
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("ends_at__gte", models.F("starts_at"))),
                        name="event_ends_not_before_start",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("capacity__gte", 0)),
                        name="event_capacity_nonnegative",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="EventRegistration",
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
                ("name", models.CharField(max_length=200)),
                ("email", models.EmailField(max_length=254)),
                ("phone", models.CharField(max_length=32)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("registered", "Registered"),
                            ("waitlisted", "Waitlisted"),
                            ("cancelled", "Cancelled"),
                            ("attended", "Attended"),
                        ],
                        default="registered",
                        max_length=16,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "event",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="registrations",
                        to="events.event",
                    ),
                ),
            ],
            options={
                "ordering": ["created_at", "id"],
                "indexes": [
                    models.Index(
                        fields=["event", "status", "created_at"],
                        name="eventreg_status_fifo_idx",
                    ),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("event", "email"),
                        name="uniq_event_registration_email",
                    ),
                ],
            },
        ),
    ]
