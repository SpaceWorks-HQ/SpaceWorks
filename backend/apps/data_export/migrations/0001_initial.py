import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        ("makerspaces", "0061_makerspace_archive_request"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="DataExportJob",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("fidelity", models.CharField(default="REDACTED", max_length=16)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("running", "Running"), ("available", "Available"), ("failed", "Failed")], default="pending", max_length=16)),
                ("object_key", models.CharField(max_length=512, unique=True)),
                ("accounted_size_bytes", models.PositiveBigIntegerField(default=0)),
                ("manifest", models.JSONField(blank=True, default=dict)),
                ("failure_code", models.CharField(blank=True, choices=[("", "None"), ("deadline_exceeded", "Deadline exceeded"), ("integrity_error", "Integrity error"), ("storage_error", "Storage error"), ("quota_exceeded", "Quota exceeded"), ("internal_error", "Internal error")], default="", max_length=32)),
                ("failure_detail", models.CharField(blank=True, default="", max_length=500)),
                ("deadline_at", models.DateTimeField(blank=True, null=True)),
                ("snapshot_at", models.DateTimeField(blank=True, null=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("expires_at", models.DateTimeField(db_index=True)),
                ("download_token_digest", models.CharField(blank=True, default="", max_length=64)),
                ("download_token_expires_at", models.DateTimeField(blank=True, null=True)),
                ("download_token_consumed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("download_issued_to", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="issued_data_export_downloads", to=settings.AUTH_USER_MODEL)),
                ("makerspace", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="data_export_jobs", to="makerspaces.makerspace")),
                ("requested_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="data_export_jobs", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.AddIndex(
            model_name="dataexportjob",
            index=models.Index(fields=["makerspace", "status", "created_at"], name="data_export_makersp_27d27a_idx"),
        ),
    ]
