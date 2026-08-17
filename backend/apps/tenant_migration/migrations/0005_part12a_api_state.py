import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("data_export", "0001_initial"),
        ("tenant_migration", "0004_sourcemigrationgate"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="tenantimportjob",
            name="archive_path",
            field=models.CharField(blank=True, max_length=1024),
        ),
        migrations.AddField(
            model_name="tenantimportjob",
            name="source_deployment_identity",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="tenantimportjob",
            name="failure_code",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="tenantimportjob",
            name="failure_detail",
            field=models.CharField(blank=True, max_length=500),
        ),
        migrations.AddField(
            model_name="tenantimportjob",
            name="verification_report",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.CreateModel(
            name="DisclosureClosureApproval",
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
                ("closure_digest", models.CharField(max_length=64)),
                ("identity_ids", models.JSONField(default=list)),
                ("approved_identity_ids", models.JSONField(default=list)),
                ("approved_at", models.DateTimeField(auto_now_add=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                (
                    "approved_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="approved_migration_disclosures",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "makerspace",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="migration_disclosure_approvals",
                        to="makerspaces.makerspace",
                    ),
                ),
                (
                    "revoked_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="revoked_migration_disclosures",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.AddIndex(
            model_name="disclosureclosureapproval",
            index=models.Index(
                fields=["makerspace", "closure_digest", "revoked_at"],
                name="tdisclosure_space_digest_idx",
            ),
        ),
        migrations.CreateModel(
            name="TenantMigrationExportJob",
            fields=[
                (
                    "export_job",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        related_name="migration_export",
                        serialize=False,
                        to="data_export.dataexportjob",
                    ),
                ),
                ("closure_digest", models.CharField(max_length=64)),
                ("target_age_recipient", models.CharField(max_length=256)),
                ("format_version", models.PositiveSmallIntegerField(default=1)),
                ("archive_digest", models.CharField(blank=True, max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "disclosure_approval",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="export_jobs",
                        to="tenant_migration.disclosureclosureapproval",
                    ),
                ),
            ],
        ),
    ]
