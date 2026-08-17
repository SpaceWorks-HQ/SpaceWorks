import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tenant_migration", "0003_cutover_receipt_protocol"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SourceMigrationGate",
            fields=[
                (
                    "makerspace",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        related_name="source_migration_gate",
                        serialize=False,
                        to="makerspaces.makerspace",
                    ),
                ),
                (
                    "state",
                    models.CharField(
                        choices=[
                            ("open", "Open"),
                            ("draining", "Draining uploads"),
                            ("quiesced", "Quiesced"),
                            ("migrated_out", "Migrated out"),
                        ],
                        default="open",
                        max_length=16,
                    ),
                ),
                ("owner_id", models.UUIDField(blank=True, null=True)),
                ("fencing_token", models.PositiveBigIntegerField(default=0)),
                ("heartbeat_at", models.DateTimeField(blank=True, null=True)),
                (
                    "lease_expires_at",
                    models.DateTimeField(blank=True, db_index=True, null=True),
                ),
                ("presign_drain_until", models.DateTimeField(blank=True, null=True)),
                ("quiesced_at", models.DateTimeField(blank=True, null=True)),
                ("reopened_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "actor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="owned_source_migration_gates",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(
                            models.Q(("owner_id__isnull", True), ("state", "open")),
                            models.Q(
                                ("heartbeat_at__isnull", False),
                                ("lease_expires_at__isnull", False),
                                ("owner_id__isnull", False),
                                ("state__in", ("draining", "quiesced", "migrated_out")),
                            ),
                            _connector="OR",
                        ),
                        name="ck_source_gate_owner_state",
                    )
                ]
            },
        )
    ]
