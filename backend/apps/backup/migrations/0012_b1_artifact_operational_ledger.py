import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("backup", "0011_archive_custody_alarm_delivery"),
        ("makerspaces", "0064_makerspace_lifecycle_state"),
    ]

    operations = [
        migrations.CreateModel(
            name="B1ActivationState",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("state", models.CharField(choices=[("on", "Platform readable"), ("off_pending", "Exclusion pending"), ("off_effective", "Exclusion effective")], max_length=16)),
                ("effective_artifact_id", models.UUIDField(blank=True, null=True)),
                ("effective_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("makerspace", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="b1_activation_state", to="makerspaces.makerspace")),
            ],
            options={
                "constraints": [models.CheckConstraint(condition=models.Q(models.Q(("effective_artifact_id__isnull", True), ("effective_at__isnull", True), ("state__in", ("on", "off_pending"))), models.Q(("effective_artifact_id__isnull", False), ("effective_at__isnull", False), ("state", "off_effective")), _connector="OR"), name="backup_b1_activation_effective_facts")],
            },
        ),
        migrations.CreateModel(
            name="BackupArtifactLedger",
            fields=[
                ("artifact_id", models.UUIDField(editable=False, primary_key=True, serialize=False)),
                ("capture_id", models.UUIDField(editable=False, unique=True)),
                ("archive_uuid_snapshot", models.UUIDField(editable=False, unique=True)),
                ("outer_sha256", models.CharField(max_length=64)),
                ("outer_manifest_sha256", models.CharField(max_length=64)),
                ("format", models.CharField(max_length=80)),
                ("outer_manifest", models.JSONField()),
                ("frozen_promotion_snapshot", models.JSONField()),
                ("expected_size_bytes", models.PositiveBigIntegerField()),
                ("staging_locator", models.CharField(max_length=512, unique=True)),
                ("final_locator", models.CharField(max_length=512, unique=True)),
                ("state", models.CharField(choices=[("pending", "Pending upload"), ("staging_verified", "Staging verified"), ("final_verified", "Final verified"), ("available", "Available"), ("failed", "Failed"), ("superseded", "Superseded"), ("bytes_deleted", "Managed bytes deleted")], default="pending", max_length=24)),
                ("predecessor_artifact_id_snapshot", models.UUIDField(blank=True, null=True)),
                ("predecessor_success_at_snapshot", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("staging_verified_at", models.DateTimeField(blank=True, null=True)),
                ("staging_verified_size_bytes", models.PositiveBigIntegerField(blank=True, null=True)),
                ("staging_verified_sha256", models.CharField(blank=True, max_length=64)),
                ("final_verified_at", models.DateTimeField(blank=True, null=True)),
                ("final_verified_size_bytes", models.PositiveBigIntegerField(blank=True, null=True)),
                ("final_verified_sha256", models.CharField(blank=True, max_length=64)),
                ("promoted_at", models.DateTimeField(blank=True, null=True)),
                ("superseded_at", models.DateTimeField(blank=True, null=True)),
                ("bytes_deleted_at", models.DateTimeField(blank=True, null=True)),
                ("failed_at", models.DateTimeField(blank=True, null=True)),
                ("failure_code", models.CharField(blank=True, max_length=64)),
                ("cleanup_pending", models.BooleanField(default=False)),
                ("archive", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="artifact_ledger", to="backup.backuparchive")),
            ],
            options={
                "ordering": ("-created_at",),
                "indexes": [models.Index(fields=["state", "created_at"], name="backup_art_state_created_idx")],
            },
        ),
        migrations.CreateModel(
            name="BackupArtifactComponent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("component_id", models.UUIDField(editable=False, unique=True)),
                ("kind", models.CharField(choices=[("main", "Readable main"), ("slice", "Sovereign slice")], max_length=8)),
                ("makerspace_id_snapshot", models.BigIntegerField(blank=True, null=True)),
                ("ciphertext_path", models.CharField(max_length=512)),
                ("ciphertext_sha256", models.CharField(max_length=64)),
                ("size_bytes", models.PositiveBigIntegerField()),
                ("storage_state", models.CharField(choices=[("pending", "Pending"), ("available", "Available"), ("bytes_deleted", "Managed bytes deleted")], default="pending", max_length=16)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("available_at", models.DateTimeField(blank=True, null=True)),
                ("bytes_deleted_at", models.DateTimeField(blank=True, null=True)),
                ("artifact", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="components", to="backup.backupartifactledger")),
            ],
            options={
                "ordering": ("artifact_id", "kind", "makerspace_id_snapshot", "pk"),
                "constraints": [
                    models.UniqueConstraint(fields=("artifact", "kind", "makerspace_id_snapshot"), name="uniq_backup_artifact_component", nulls_distinct=False),
                    models.CheckConstraint(condition=models.Q(models.Q(("kind", "main"), ("makerspace_id_snapshot__isnull", True)), models.Q(("kind", "slice"), ("makerspace_id_snapshot__isnull", False)), _connector="OR"), name="backup_component_kind_matches_tenant"),
                ],
            },
        ),
        migrations.CreateModel(
            name="BackupComponentRecipient",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("fingerprint", models.CharField(max_length=64)),
                ("associated_at", models.DateTimeField(auto_now_add=True)),
                ("tombstoned_at", models.DateTimeField(blank=True, null=True)),
                ("component", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="recipient_associations", to="backup.backupartifactcomponent")),
            ],
            options={
                "ordering": ("component_id", "pk"),
                "constraints": [models.UniqueConstraint(fields=("component", "fingerprint"), name="uniq_backup_component_recipient")],
            },
        ),
    ]
