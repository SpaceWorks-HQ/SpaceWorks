from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("backup", "0015_tenant_exit_custody")]

    operations = [
        migrations.CreateModel(
            name="B1RestoreOperationState",
            fields=[
                ("operation_id", models.UUIDField(editable=False, primary_key=True, serialize=False)),
                ("artifact_id", models.UUIDField(editable=False)),
                ("capture_id", models.UUIDField(editable=False)),
                ("main_component_id", models.UUIDField(editable=False)),
                ("outer_ciphertext_sha256", models.CharField(editable=False, max_length=64)),
                ("outer_manifest_sha256", models.CharField(editable=False, max_length=64)),
                ("source_proof_sha256", models.CharField(editable=False, max_length=64)),
                ("sibling_database_name", models.CharField(editable=False, max_length=63)),
                ("sibling_database_oid", models.PositiveBigIntegerField(editable=False)),
                ("sibling_server_identity", models.CharField(editable=False, max_length=255)),
                ("stage", models.CharField(choices=[("verified", "Outer artifact verified"), ("main_restored", "Readable main restored"), ("roles_recreated", "Roles and grants recreated"), ("state_rehydrated", "Private state rehydrated"), ("enforcement_installed", "Enforcement installed"), ("catalog_verified", "Catalog and reservations verified"), ("objects_verified", "Main objects verified"), ("quarantine_verified", "Sibling quarantine verified"), ("cutover_ready", "Authenticated cutover handoff ready"), ("failed", "Failed closed")], default="verified", max_length=32)),
                ("fence_continuity_digest", models.CharField(blank=True, max_length=64)),
                ("object_journal_evidence_sha256", models.CharField(blank=True, max_length=64)),
                ("quarantine_evidence_sha256", models.CharField(blank=True, max_length=64)),
                ("cutover_attestation", models.JSONField(blank=True, default=dict)),
                ("failure_code", models.CharField(blank=True, max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name="B1RestoreComponentState",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("operation_id", models.UUIDField(editable=False)),
                ("artifact_id", models.UUIDField(editable=False)),
                ("capture_id", models.UUIDField(editable=False)),
                ("component_id", models.UUIDField(editable=False)),
                ("makerspace_id_snapshot", models.PositiveBigIntegerField(editable=False)),
                ("ciphertext_sha256", models.CharField(editable=False, max_length=64)),
                ("state", models.CharField(choices=[("pending", "Pending"), ("dependency_wait", "Waiting for a dependency"), ("merging", "Merging"), ("restored", "Restored"), ("failed", "Failed")], max_length=24)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(fields=("operation_id", "component_id"), name="uniq_b1_restore_operation_component"),
                    models.UniqueConstraint(fields=("artifact_id", "component_id"), name="uniq_b1_restore_artifact_component"),
                    models.UniqueConstraint(condition=models.Q(("state", "restored"), _negated=True), fields=("makerspace_id_snapshot",), name="uniq_b1_active_component_per_space"),
                ]
            },
        ),
        migrations.CreateModel(
            name="B1ReservationEntry",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("operation_id", models.UUIDField(editable=False)),
                ("component_id", models.UUIDField(editable=False)),
                ("registry_identity", models.CharField(editable=False, max_length=64)),
                ("kind", models.CharField(choices=[("commitment", "High-entropy commitment"), ("numeric_range", "Numeric range"), ("broad_fence", "Broad data fence"), ("relationship_fence", "Relationship fence"), ("object_namespace", "Object namespace fence")], editable=False, max_length=32)),
                ("definition_sha256", models.CharField(editable=False, max_length=64)),
                ("safe_payload", models.JSONField(default=dict, editable=False)),
                ("installed_at", models.DateTimeField(blank=True, null=True)),
                ("catalog_verified_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "constraints": [models.UniqueConstraint(fields=("operation_id", "component_id", "registry_identity", "kind"), name="uniq_b1_component_reservation")]
            },
        ),
        migrations.CreateModel(
            name="B1FenceContinuity",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("operation_id", models.UUIDField(editable=False)),
                ("registry_identity", models.CharField(editable=False, max_length=64)),
                ("definition_sha256", models.CharField(editable=False, max_length=64)),
                ("trigger_oids", models.JSONField(default=list, editable=False)),
                ("installed_at", models.DateTimeField(auto_now_add=True)),
                ("last_verified_at", models.DateTimeField(auto_now=True)),
                ("enabled", models.BooleanField(default=True, editable=False)),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(fields=("operation_id", "registry_identity"), name="uniq_b1_fence_continuity"),
                    models.CheckConstraint(condition=models.Q(("enabled", True)), name="b1_fence_continuity_enabled"),
                ]
            },
        ),
    ]
