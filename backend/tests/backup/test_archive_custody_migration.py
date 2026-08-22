import importlib
from datetime import timedelta

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


@pytest.mark.django_db(transaction=True)
def test_not_applicable_migration_reconstructs_every_coupled_field_both_ways():
    # Pin every app whose real table is ahead in BOTH states. MigrationExecutor's
    # project_state otherwise replays only named targets and their dependencies, so a
    # historical model can omit a real non-null column and make fixture INSERTs fail.
    pinned = [
        ("accounts", "0024_social_nonce_attestation_challenge"),
        ("makerspaces", "0064_makerspace_lifecycle_state"),
        ("integrations", "0024_machinetypeemailtemplate"),
        ("notifications", "0001_initial"),
    ]
    from_target = [*pinned, ("backup", "0009_backfill_makerspace_archive_custody_state")]
    target = [*pinned, ("backup", "0010_archive_custody_not_applicable")]
    executor = MigrationExecutor(connection)

    try:
        executor.migrate(from_target)
        old_apps = executor.loader.project_state(from_target).apps
        Makerspace = old_apps.get_model("makerspaces", "Makerspace")
        Recipient = old_apps.get_model("backup", "MakerspaceArchiveRecipient")
        CustodyState = old_apps.get_model("backup", "MakerspaceArchiveCustodyState")
        now = timezone.now()
        old_states = ("healthy", "degraded_one_recipient", "floor_breached_zero")
        effective_counts = {"healthy": 2, "degraded_one_recipient": 1, "floor_breached_zero": 0}
        seeded = {}

        for enabled in (True, False):
            for index, old_state in enumerate(old_states):
                slug = f"scope-{int(enabled)}-{index}"
                space = Makerspace.objects.create(
                    name=slug,
                    slug=slug,
                    superadmin_access_enabled=enabled,
                )
                for number in range(effective_counts[old_state]):
                    Recipient.objects.create(
                        makerspace_id=space.pk,
                        public_recipient=f"age1effective{int(enabled)}{index}{number}",
                        fingerprint=f"{int(enabled)}{index}{number}".zfill(64),
                        label=f"Effective {number}",
                        verified_at=now,
                    )
                trigger = Recipient.objects.create(
                    makerspace_id=space.pk,
                    public_recipient=f"age1trigger{int(enabled)}{index}",
                    fingerprint=f"9{int(enabled)}{index}".zfill(64),
                    label="Trigger",
                )
                entered_at = now - timedelta(days=10 + index)
                cleared_at = now - timedelta(days=5 + index)
                last_alarm_at = now - timedelta(days=2 + index)
                CustodyState.objects.create(
                    makerspace_id=space.pk,
                    state=old_state,
                    reason_code="seed_reason",
                    entered_at=entered_at,
                    cleared_at=cleared_at,
                    last_alarm_at=last_alarm_at,
                    triggering_recipient_id=trigger.pk,
                    alarm_episode=7,
                )
                space.refresh_from_db()
                seeded[space.pk] = {
                    "enabled": enabled,
                    "old_state": old_state,
                    "entered_at": entered_at,
                    "cleared_at": cleared_at,
                    "last_alarm_at": last_alarm_at,
                    "updated_at": space.updated_at,
                }

        executor = MigrationExecutor(connection)
        executor.migrate(target)
        new_apps = executor.loader.project_state(target).apps
        NewCustodyState = new_apps.get_model("backup", "MakerspaceArchiveCustodyState")
        forward = {
            row.makerspace_id: row
            for row in NewCustodyState.objects.order_by("makerspace_id")
        }
        for makerspace_id, values in seeded.items():
            row = forward[makerspace_id]
            expected_state = "not_applicable" if values["enabled"] else values["old_state"]
            assert row.state == expected_state
            assert row.reason_code == (
                ""
                if expected_state in ("healthy", "not_applicable")
                else "recipient_count_below_floor"
            )
            assert row.entered_at == values["entered_at"]
            assert row.cleared_at == (
                values["updated_at"] if expected_state == "not_applicable"
                else values["cleared_at"] if expected_state == "healthy"
                else None
            )
            assert row.last_alarm_at == (
                values["last_alarm_at"]
                if not values["enabled"] and expected_state != "healthy"
                else None
            )
            assert row.triggering_recipient_id is None
            assert row.alarm_episode == 7

        executor = MigrationExecutor(connection)
        executor.migrate(from_target)
        reversed_apps = executor.loader.project_state(from_target).apps
        ReversedCustodyState = reversed_apps.get_model(
            "backup", "MakerspaceArchiveCustodyState"
        )
        for makerspace_id, values in seeded.items():
            row = ReversedCustodyState.objects.get(makerspace_id=makerspace_id)
            assert row.state == values["old_state"]
            assert row.reason_code == (
                "" if row.state == "healthy" else "recipient_count_below_floor"
            )
            assert row.entered_at == values["entered_at"]
            assert (row.cleared_at is not None) == (row.state == "healthy")
            assert row.last_alarm_at == (
                values["last_alarm_at"]
                if not values["enabled"] and row.state != "healthy"
                else None
            )
            assert row.triggering_recipient_id is None
            assert row.alarm_episode == 7
    finally:
        restore = MigrationExecutor(connection)
        restore.migrate(restore.loader.graph.leaf_nodes())
