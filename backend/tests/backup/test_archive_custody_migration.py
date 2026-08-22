import importlib

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone


@pytest.mark.django_db(transaction=True)
def test_custody_backfill_is_idempotent_and_classifies_recipient_counts():
    dependencies = [
        ("makerspaces", "0064_makerspace_lifecycle_state"),
        ("accounts", "0024_social_nonce_attestation_challenge"),
    ]
    from_target = [*dependencies, ("backup", "0008_makerspace_archive_custody_state")]
    target = [
        *dependencies,
        ("backup", "0009_backfill_makerspace_archive_custody_state"),
    ]
    executor = MigrationExecutor(connection)

    try:
        executor.migrate(from_target)
        old_apps = executor.loader.project_state(from_target).apps
        Makerspace = old_apps.get_model("makerspaces", "Makerspace")
        Recipient = old_apps.get_model("backup", "MakerspaceArchiveRecipient")
        spaces = [
            Makerspace.objects.create(name=f"Count {count}", slug=f"count-{count}")
            for count in range(3)
        ]
        for count, makerspace in enumerate(spaces):
            for index in range(count):
                Recipient.objects.create(
                    makerspace_id=makerspace.pk,
                    public_recipient=f"age1migration{count}{index}",
                    fingerprint=f"{count:032x}{index:032x}",
                    label=f"Custodian {index}",
                    verified_at=timezone.now(),
                )

        executor = MigrationExecutor(connection)
        executor.migrate(target)
        new_apps = executor.loader.project_state(target).apps
        CustodyState = new_apps.get_model(
            "backup", "MakerspaceArchiveCustodyState"
        )
        expected = {
            spaces[0].pk: "floor_breached_zero",
            spaces[1].pk: "degraded_one_recipient",
            spaces[2].pk: "healthy",
        }
        first = list(
            CustodyState.objects.order_by("makerspace_id").values(
                "makerspace_id",
                "state",
                "reason_code",
                "entered_at",
                "cleared_at",
                "last_alarm_at",
                "triggering_recipient_id",
                "alarm_episode",
            )
        )
        assert {row["makerspace_id"]: row["state"] for row in first} == expected

        migration = importlib.import_module(
            "apps.backup.migrations."
            "0009_backfill_makerspace_archive_custody_state"
        )
        with connection.schema_editor() as schema_editor:
            migration.backfill_custody_states(new_apps, schema_editor)
        second = list(
            CustodyState.objects.order_by("makerspace_id").values(
                "makerspace_id",
                "state",
                "reason_code",
                "entered_at",
                "cleared_at",
                "last_alarm_at",
                "triggering_recipient_id",
                "alarm_episode",
            )
        )
        assert second == first
    finally:
        restore = MigrationExecutor(connection)
        restore.migrate(restore.loader.graph.leaf_nodes())
