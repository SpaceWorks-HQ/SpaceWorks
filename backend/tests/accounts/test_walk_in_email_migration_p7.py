import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone


@pytest.mark.django_db(transaction=True)
def test_walk_in_email_verification_is_cleared_by_migration():
    from_target = [("accounts", "0015_backfill_is_walk_in")]
    target = [("accounts", "0016_clear_walk_in_email_verification")]
    executor = MigrationExecutor(connection)

    try:
        executor.migrate(from_target)
        old_apps = executor.loader.project_state(from_target).apps
        OldUser = old_apps.get_model("accounts", "User")
        stamp = timezone.now()
        walk_in = OldUser.objects.create(
            username="migration-walk-in-email",
            email="walk-in-migration@example.test",
            password="!",
            is_walk_in=True,
            email_verified_at=stamp,
        )
        account = OldUser.objects.create(
            username="migration-real-account-email",
            email="account-migration@example.test",
            password="!",
            is_walk_in=False,
            email_verified_at=stamp,
        )

        executor = MigrationExecutor(connection)
        executor.migrate(target)
        new_apps = executor.loader.project_state(target).apps
        NewUser = new_apps.get_model("accounts", "User")

        assert NewUser.objects.get(pk=walk_in.pk).email_verified_at is None
        assert NewUser.objects.get(pk=account.pk).email_verified_at == stamp
    finally:
        # Rewinding one app may unapply dependent migrations in other apps. Restore
        # the complete graph so later tests see the real schema, not a partial leaf.
        restore = MigrationExecutor(connection)
        restore.migrate(restore.loader.graph.leaf_nodes())
