import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tenant_migration", "0002_import_coordination_state"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="DeploymentSigningKey",
            fields=[
                (
                    "id",
                    models.PositiveSmallIntegerField(
                        default=1, editable=False, primary_key=True, serialize=False
                    ),
                ),
                (
                    "deployment_id",
                    models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
                ),
                ("private_key_ciphertext", models.TextField(editable=False)),
                ("public_key", models.CharField(editable=False, max_length=44)),
                (
                    "fingerprint",
                    models.CharField(editable=False, max_length=64, unique=True),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.CreateModel(
            name="MigrationPairing",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("migration_id", models.UUIDField(unique=True)),
                ("source_tenant_id", models.CharField(max_length=64)),
                ("archive_digest", models.CharField(max_length=64)),
                ("source_deployment_id", models.CharField(max_length=128)),
                ("source_public_key", models.CharField(max_length=44)),
                ("source_fingerprint", models.CharField(max_length=64)),
                ("target_deployment_id", models.CharField(max_length=128)),
                ("target_public_key", models.CharField(max_length=44)),
                ("target_fingerprint", models.CharField(max_length=64)),
                ("approved_at", models.DateTimeField(auto_now_add=True)),
                (
                    "approved_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="approved_tenant_migration_pairings",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(
                            ("source_deployment_id", models.F("target_deployment_id")),
                            _negated=True,
                        ),
                        name="ck_tpair_distinct_deployments",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("source_fingerprint", models.F("target_fingerprint")),
                            _negated=True,
                        ),
                        name="ck_tpair_distinct_fingerprints",
                    ),
                ]
            },
        ),
        migrations.CreateModel(
            name="MigrationReceipt",
            fields=[
                (
                    "receipt_id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("format_version", models.PositiveSmallIntegerField(default=1)),
                (
                    "operation",
                    models.CharField(
                        choices=[
                            ("source_cutover", "Source cutover"),
                            ("target_abort", "Target abort"),
                        ],
                        max_length=24,
                    ),
                ),
                ("migration_id", models.UUIDField()),
                ("source_tenant_id", models.CharField(max_length=64)),
                ("archive_digest", models.CharField(max_length=64)),
                ("source_deployment_id", models.CharField(max_length=128)),
                ("target_deployment_id", models.CharField(max_length=128)),
                ("signer_fingerprint", models.CharField(max_length=64)),
                ("signature", models.CharField(max_length=88)),
                ("issued_here", models.BooleanField(default=False)),
                ("persisted_at", models.DateTimeField(auto_now_add=True)),
                (
                    "pairing",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="receipts",
                        to="tenant_migration.migrationpairing",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("pairing", "operation"),
                        name="uniq_treceipt_pairing_operation",
                    )
                ]
            },
        ),
        migrations.CreateModel(
            name="ReceiptConsumption",
            fields=[
                (
                    "receipt",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        primary_key=True,
                        related_name="consumption",
                        serialize=False,
                        to="tenant_migration.migrationreceipt",
                    ),
                ),
                (
                    "purpose",
                    models.CharField(
                        choices=[
                            ("activate_target", "Activate target"),
                            ("reopen_source", "Reopen source"),
                        ],
                        max_length=24,
                    ),
                ),
                ("consumed_at", models.DateTimeField(auto_now_add=True)),
                (
                    "consumed_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="consumed_tenant_migration_receipts",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="MigratedOutHandoff",
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
                ("archive_digest", models.CharField(max_length=64)),
                ("target_deployment_id", models.CharField(max_length=128)),
                (
                    "state",
                    models.CharField(
                        choices=[("migrated_out", "Migrated out")],
                        default="migrated_out",
                        editable=False,
                        max_length=24,
                    ),
                ),
                ("migrated_out_at", models.DateTimeField(auto_now_add=True)),
                ("reopened_at", models.DateTimeField(blank=True, null=True)),
                (
                    "abort_receipt",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="reopened_handoff",
                        to="tenant_migration.migrationreceipt",
                    ),
                ),
                (
                    "pairing",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="source_handoff",
                        to="tenant_migration.migrationpairing",
                    ),
                ),
                (
                    "reopened_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="reopened_tenant_migration_handoffs",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "source_cutover_receipt",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="source_handoff",
                        to="tenant_migration.migrationreceipt",
                    ),
                ),
                (
                    "source_tenant",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="migration_handoff",
                        to="makerspaces.makerspace",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=(
                            "source_tenant",
                            "archive_digest",
                            "target_deployment_id",
                        ),
                        name="uniq_migrated_out_handoff_binding",
                    )
                ]
            },
        ),
    ]
