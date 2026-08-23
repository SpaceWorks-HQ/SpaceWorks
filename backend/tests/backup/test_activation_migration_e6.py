import importlib
import uuid
from datetime import timedelta

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone


@pytest.mark.django_db(transaction=True)
def test_activation_rollout_is_conservative_and_ignores_historical_artifacts():
    pinned = [
        ("accounts", "0024_social_nonce_attestation_challenge"),
        ("makerspaces", "0064_makerspace_lifecycle_state"),
        ("integrations", "0024_machinetypeemailtemplate"),
        ("notifications", "0001_initial"),
    ]
    from_target = [*pinned, ("backup", "0012_b1_artifact_operational_ledger")]
    target = [*pinned, ("backup", "0013_backfill_b1_activation_state")]
    executor = MigrationExecutor(connection)

    try:
        executor.migrate(from_target)
        old_apps = executor.loader.project_state(from_target).apps
        Makerspace = old_apps.get_model("makerspaces", "Makerspace")
        BackupArchive = old_apps.get_model("backup", "BackupArchive")
        Artifact = old_apps.get_model("backup", "BackupArtifactLedger")
        Recipient = old_apps.get_model("backup", "MakerspaceArchiveRecipient")
        enabled = Makerspace.objects.create(
            name="Rollout on",
            slug="e6-rollout-on",
            superadmin_access_enabled=True,
        )
        disabled = Makerspace.objects.create(
            name="Rollout off",
            slug="e6-rollout-off",
            superadmin_access_enabled=False,
        )
        for index in range(2):
            Recipient.objects.create(
                makerspace_id=disabled.pk,
                public_recipient=f"age1e6migration{index}",
                fingerprint=f"{index:064x}",
                label=f"Migration recipient {index}",
                verified_at=timezone.now(),
            )
        BackupArchive.objects.create(
            scope="makerspace",
            makerspace_id=disabled.pk,
            superadmin_access_at_decision=False,
            status="available",
            object_key=f"historical/{uuid.uuid4()}.tar.age",
            expires_at=timezone.now() + timedelta(days=1),
        )
        Artifact.objects.create(
            artifact_id=uuid.uuid4(),
            capture_id=uuid.uuid4(),
            archive_uuid_snapshot=uuid.uuid4(),
            outer_sha256="a" * 64,
            outer_manifest_sha256="b" * 64,
            format="historical",
            outer_manifest={},
            frozen_promotion_snapshot={},
            expected_size_bytes=1,
            staging_locator=f"historical-staging/{uuid.uuid4()}",
            final_locator=f"historical-final/{uuid.uuid4()}",
            state="failed",
        )

        executor = MigrationExecutor(connection)
        executor.migrate(target)
        new_apps = executor.loader.project_state(target).apps
        Activation = new_apps.get_model("backup", "B1ActivationState")
        assert Activation.objects.get(makerspace_id=enabled.pk).state == "on"
        disabled_state = Activation.objects.get(makerspace_id=disabled.pk)
        assert disabled_state.state == "off_pending"
        assert disabled_state.effective_artifact_id is None
        assert disabled_state.effective_at is None

        migration = importlib.import_module(
            "apps.backup.migrations.0013_backfill_b1_activation_state"
        )
        with connection.schema_editor() as schema_editor:
            migration.backfill_activation(new_apps, schema_editor)
        assert Activation.objects.filter(makerspace_id=disabled.pk).count() == 1
        assert Activation.objects.get(makerspace_id=disabled.pk).state == "off_pending"
    finally:
        restore = MigrationExecutor(connection)
        restore.migrate(restore.loader.graph.leaf_nodes())
