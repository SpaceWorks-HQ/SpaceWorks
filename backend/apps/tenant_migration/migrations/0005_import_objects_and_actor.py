import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tenant_migration", "0004_sourcemigrationgate"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="tenantimportjob",
            name="actor",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="tenant_import_jobs",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.CreateModel(
            name="TenantImportObject",
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
                    "bucket_kind",
                    models.CharField(
                        choices=[
                            ("private", "Private"),
                            ("public_image", "Public image"),
                        ],
                        max_length=16,
                    ),
                ),
                ("source_key", models.CharField(max_length=1024)),
                ("staging_key", models.CharField(max_length=1024)),
                ("target_key", models.CharField(max_length=1024)),
                ("size", models.PositiveBigIntegerField()),
                ("sha256", models.CharField(max_length=64)),
                (
                    "state",
                    models.CharField(
                        choices=[
                            ("staged", "Staged"),
                            ("promoted", "Promoted"),
                            ("verified", "Verified"),
                            ("failed", "Failed"),
                            ("rolled_back", "Rolled back"),
                        ],
                        default="staged",
                        max_length=16,
                    ),
                ),
                ("claimed_at", models.DateTimeField(blank=True, null=True)),
                ("quota_charged_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "job",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="import_objects",
                        to="tenant_migration.tenantimportjob",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["job", "state"],
                        name="timport_obj_job_state_idx",
                    ),
                    models.Index(
                        fields=["state", "updated_at"],
                        name="timport_obj_state_time_idx",
                    ),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("job", "source_key"),
                        name="uniq_timport_object_source",
                    )
                ],
            },
        ),
    ]
