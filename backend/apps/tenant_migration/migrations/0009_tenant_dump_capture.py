import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
import uuid


class Migration(migrations.Migration):
    dependencies = [
        ("tenant_migration", "0008_resumable_import_finalization"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="sourcemigrationgate",
            name="purpose",
            field=models.CharField(choices=[("migration", "Tenant migration"), ("copy_capture", "Tenant exit copy capture")], default="migration", max_length=24),
        ),
        migrations.CreateModel(
            name="TenantDumpCapture",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("status", models.CharField(choices=[("requested", "Requested"), ("capturing", "Capturing"), ("captured", "Captured"), ("deriving", "Deriving"), ("pending_publication", "Pending publication"), ("published", "Published"), ("refused", "Publication refused"), ("failed", "Failed")], db_index=True, default="requested", max_length=32)),
                ("source_deployment_identity", models.JSONField(default=dict)),
                ("source_makerspace_id", models.BigIntegerField()),
                ("source_makerspace_slug", models.SlugField(max_length=100)),
                ("superadmin_access_at_decision", models.BooleanField()),
                ("frozen_tenant_recipients", models.JSONField(default=list)),
                ("gate_owner_id", models.UUIDField(blank=True, null=True)),
                ("gate_fencing_token", models.PositiveBigIntegerField(default=0)),
                ("database_snapshot_at", models.DateTimeField(blank=True, null=True)),
                ("source_postgres_major", models.PositiveSmallIntegerField(default=0)),
                ("database_image_sha256", models.CharField(blank=True, max_length=64)),
                ("object_ledger", models.JSONField(blank=True, default=list)),
                ("object_ledger_sha256", models.CharField(blank=True, max_length=64)),
                ("source_encryption_mode", models.BooleanField()),
                ("catalog_digest", models.CharField(max_length=64)),
                ("capture_completed_at", models.DateTimeField(blank=True, null=True)),
                ("parent_database_sha256", models.CharField(blank=True, max_length=64)),
                ("parent_object_ledger_sha256", models.CharField(blank=True, max_length=64)),
                ("derivation_policy_sha256", models.CharField(blank=True, max_length=64)),
                ("content_ledger", models.JSONField(blank=True, default=list)),
                ("manifest", models.JSONField(blank=True, default=dict)),
                ("artifact_sha256", models.CharField(blank=True, max_length=64)),
                ("artifact_size_bytes", models.PositiveBigIntegerField(default=0)),
                ("unpublished_object_key", models.CharField(blank=True, max_length=512)),
                ("object_key", models.CharField(blank=True, max_length=512, null=True, unique=True)),
                ("download_token_digest", models.CharField(blank=True, max_length=64)),
                ("download_token_expires_at", models.DateTimeField(blank=True, null=True)),
                ("download_token_consumed_at", models.DateTimeField(blank=True, null=True)),
                ("refusal_code", models.CharField(blank=True, max_length=64)),
                ("refusal_detail", models.CharField(blank=True, max_length=500)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("published_at", models.DateTimeField(blank=True, null=True)),
                ("makerspace", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="tenant_dump_captures", to="makerspaces.makerspace")),
                ("requested_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="requested_tenant_dump_captures", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ("-created_at",),
                "indexes": [models.Index(fields=["makerspace", "status", "created_at"], name="tenant_dump_capture_idx")],
            },
        ),
    ]
