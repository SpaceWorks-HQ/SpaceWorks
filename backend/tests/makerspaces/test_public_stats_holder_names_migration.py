import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True)
def test_existing_makerspaces_enable_holder_names_but_new_ones_default_off():
    from_target = [("makerspaces", "0059_memberprofile_show_attended_events")]
    target = [("makerspaces", "0060_makerspace_public_stats_show_holder_names")]
    executor = MigrationExecutor(connection)

    try:
        executor.migrate(from_target)
        old_apps = executor.loader.project_state(from_target).apps
        OldMakerspace = old_apps.get_model("makerspaces", "Makerspace")
        existing = OldMakerspace.objects.create(
            name="Existing private stats space",
            slug="existing-private-stats-space",
            public_stats_enabled=False,
        )

        executor = MigrationExecutor(connection)
        executor.migrate(target)
        new_apps = executor.loader.project_state(target).apps
        NewMakerspace = new_apps.get_model("makerspaces", "Makerspace")

        assert NewMakerspace.objects.get(pk=existing.pk).public_stats_show_holder_names is True
        created_after_upgrade = NewMakerspace.objects.create(
            name="New holder-private space",
            slug="new-holder-private-space",
        )
        assert created_after_upgrade.public_stats_show_holder_names is False

        # Exercise the RunPython reverse before restoring the current full graph.
        executor = MigrationExecutor(connection)
        executor.migrate(from_target)
    finally:
        restore = MigrationExecutor(connection)
        restore.migrate(restore.loader.graph.leaf_nodes())
