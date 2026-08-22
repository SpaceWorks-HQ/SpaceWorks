from datetime import timedelta

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone


@pytest.mark.django_db(transaction=True)
def test_decision_snapshot_guard_classifies_legacy_rows_before_constraint():
    """Exercise the migration because makemigrations --check does not execute migrations.

    This guards an AddConstraint validation failure that would abort an upgrade.
    """
    # `project_state` replays only named targets and their dependencies. Pinning
    # `makerspaces` to its real leaf keeps the historical model aligned with the
    # physical table, including the latest NOT NULL lifecycle column, so inserts do
    # not omit columns that PostgreSQL requires.
    makerspaces_leaf = ("makerspaces", "0064_makerspace_lifecycle_state")
    # `Makerspace` and `BackupArchive` both have foreign keys to the swappable User
    # model. Pinning `accounts` keeps that historical relation aligned with the real
    # accounts tables instead of letting the partial replay stop at an older state.
    accounts_leaf = ("accounts", "0024_social_nonce_attestation_challenge")
    from_target = [
        makerspaces_leaf,
        accounts_leaf,
        ("backup", "0005_backuparchive_superadmin_access_at_decision"),
    ]
    target = [
        makerspaces_leaf,
        accounts_leaf,
        ("backup", "0007_backuparchive_decision_snapshot_constraint"),
    ]
    executor = MigrationExecutor(connection)

    try:
        executor.migrate(from_target)
        old_apps = executor.loader.project_state(from_target).apps
        Makerspace = old_apps.get_model("makerspaces", "Makerspace")
        BackupArchive = old_apps.get_model("backup", "BackupArchive")

        space = Makerspace.objects.create(
            name="Decision snapshot migration",
            slug="decision-snapshot-migration",
        )
        expires_at = timezone.now() + timedelta(days=1)
        archives = {
            status: BackupArchive.objects.create(
                scope="makerspace",
                makerspace=space,
                status=status,
                superadmin_access_at_decision=None,
                object_key=f"backup-archives/migration-{status}.tar.age",
                expires_at=expires_at,
            )
            for status in ("pending", "running", "available", "expired")
        }
        deployment = BackupArchive.objects.create(
            scope="deployment",
            makerspace=None,
            status="available",
            superadmin_access_at_decision=None,
            object_key="backup-archives/migration-deployment.tar.age",
            expires_at=expires_at,
        )

        # Completing this migration is the primary assertion: AddConstraint validates
        # existing rows and would abort here if failed active rows were not legacy.
        executor = MigrationExecutor(connection)
        executor.migrate(target)
        new_apps = executor.loader.project_state(target).apps
        NewBackupArchive = new_apps.get_model("backup", "BackupArchive")

        for original_status in ("pending", "running"):
            migrated = NewBackupArchive.objects.get(pk=archives[original_status].pk)
            assert migrated.status == "failed"
            assert migrated.failure_detail == "legacy_decision_snapshot_absent"
            assert migrated.completed_at is not None
            assert migrated.legacy_pre_decision_snapshot is True

        for original_status in ("available", "expired"):
            migrated = NewBackupArchive.objects.get(pk=archives[original_status].pk)
            assert migrated.status == original_status
            assert migrated.legacy_pre_decision_snapshot is True

        migrated_deployment = NewBackupArchive.objects.get(pk=deployment.pk)
        assert migrated_deployment.status == "available"
        assert migrated_deployment.superadmin_access_at_decision is None
        assert migrated_deployment.legacy_pre_decision_snapshot is False

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                NewBackupArchive.objects.create(
                    scope="makerspace",
                    makerspace_id=space.pk,
                    status="pending",
                    superadmin_access_at_decision=None,
                    legacy_pre_decision_snapshot=False,
                    object_key="backup-archives/migration-invalid-new-row.tar.age",
                    expires_at=expires_at,
                )
    finally:
        restore = MigrationExecutor(connection)
        restore.migrate(restore.loader.graph.leaf_nodes())
