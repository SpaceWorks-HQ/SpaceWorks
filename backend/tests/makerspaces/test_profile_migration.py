import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True)
def test_timezone_backfill_uses_deployment_timezone(settings):
    settings.TIME_ZONE = "Asia/Kolkata"
    executor = MigrationExecutor(connection)
    before = [("makerspaces", "0076_station_operator_leases")]
    after = [("makerspaces", "0077_makerspace_location_profile")]
    leaves = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate(before)
        old_apps = executor.loader.project_state(before).apps
        old_space = old_apps.get_model("makerspaces", "Makerspace").objects.create(
            name="Backfilled profile", slug="profile-backfill",
        )
        executor = MigrationExecutor(connection)
        executor.migrate(after)
        current_apps = executor.loader.project_state(after).apps
        lab = current_apps.get_model("makerspaces", "Makerspace").objects.get(pk=old_space.pk)
        assert lab.timezone == "Asia/Kolkata"
        assert lab.country == "" and lab.opening_hours == {}
    finally:
        MigrationExecutor(connection).migrate(leaves)
