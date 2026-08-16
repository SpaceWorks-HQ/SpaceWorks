import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tenant_migration", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="TenantImportJob",
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
                ("source_archive_digest", models.CharField(max_length=64)),
                ("source_makerspace_id", models.CharField(blank=True, max_length=64)),
                (
                    "source_makerspace_slug",
                    models.CharField(blank=True, max_length=100),
                ),
                (
                    "source_makerspace_name",
                    models.CharField(blank=True, max_length=200),
                ),
                (
                    "source_deployment_id",
                    models.CharField(blank=True, max_length=128),
                ),
                ("storage_mode", models.CharField(blank=True, max_length=32)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("awaiting_identity", "Awaiting identity decisions"),
                            ("ready", "Ready"),
                            ("materializing", "Materializing"),
                            ("completed", "Completed"),
                            ("failed", "Failed"),
                            ("abandoned", "Abandoned"),
                        ],
                        default="pending",
                        max_length=32,
                    ),
                ),
                ("aggregate_outcome", models.JSONField(blank=True, default=dict)),
                ("expires_at", models.DateTimeField(db_index=True)),
                ("terminal_at", models.DateTimeField(blank=True, null=True)),
                ("scrubbed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "target_makerspace",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="tenant_import_jobs",
                        to="makerspaces.makerspace",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["target_makerspace", "status", "expires_at"],
                        name="timport_target_status_exp_idx",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="ImportIdentityDecision",
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
                ("source_user_id", models.CharField(max_length=255)),
                ("source_email", models.EmailField(blank=True, max_length=254, null=True)),
                (
                    "identity_resolution",
                    models.CharField(
                        choices=[
                            ("link_existing", "Link existing account"),
                            ("create_walk_in", "Create walk-in account"),
                        ],
                        max_length=24,
                    ),
                ),
                (
                    "membership_disposition",
                    models.CharField(
                        choices=[
                            ("import_membership", "Import membership"),
                            ("no_membership", "Do not import membership"),
                        ],
                        max_length=24,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "job",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="identity_decisions",
                        to="tenant_migration.tenantimportjob",
                    ),
                ),
                (
                    "target_user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="tenant_import_identity_decisions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("job", "source_user_id"),
                        name="uniq_import_job_source_user",
                    ),
                    models.UniqueConstraint(
                        condition=models.Q(("target_user__isnull", False)),
                        fields=("job", "target_user"),
                        name="uniq_import_job_target_user",
                    ),
                ],
            },
        ),
    ]
