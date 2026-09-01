import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True)
def test_machine_type_backfill_uses_only_ordered_durable_provenance_and_reverses():
    # `makerspaces` is pinned to its leaf in both targets on purpose. `project_state`
    # replays only the named targets and their dependencies, so without it the historical
    # `Makerspace` model is BEHIND the real table -- it would not know about columns like
    # `discord_webhook_url`, and since Django applies field defaults in Python rather than
    # in DDL, the INSERT omits them and Postgres rejects a NOT NULL column.
    makerspaces_leaf = ("makerspaces", "0061_makerspace_archive_request")
    from_target = [
        makerspaces_leaf,
        ("machines", "0020_backfill_role_machine_scope"),
        ("procurement", "0006_kernel_printing_references"),
    ]
    target = [
        makerspaces_leaf,
        ("machines", "0020_backfill_role_machine_scope"),
        ("procurement", "0007_tobuyitem_machine_type"),
    ]
    executor = MigrationExecutor(connection)

    try:
        executor.migrate(from_target)
        old_apps = executor.loader.project_state(from_target).apps
        Makerspace = old_apps.get_model("makerspaces", "Makerspace")
        MachineType = old_apps.get_model("machines", "MachineType")
        Machine = old_apps.get_model("machines", "Machine")
        Pool = old_apps.get_model("machines", "MachineConsumablePool")
        ToBuyItem = old_apps.get_model("procurement", "ToBuyItem")

        space = Makerspace.objects.create(name="Migration lab", slug="migration-lab")
        result_type = MachineType.objects.create(
            makerspace=space, slug="result-type", name="Result type"
        )
        source_type = MachineType.objects.create(
            makerspace=space, slug="source-type", name="Source type"
        )
        pool_type = MachineType.objects.create(
            makerspace=space, slug="pool-type", name="Pool type"
        )
        result_machine = Machine.objects.create(
            makerspace=space, machine_type=result_type, name="Result machine"
        )
        source_machine = Machine.objects.create(
            makerspace=space, machine_type=source_type, name="Source machine"
        )
        pool_machine = Machine.objects.create(
            makerspace=space, machine_type=pool_type, name="Pool machine"
        )

        def pool(name, machine=None):
            return Pool.objects.create(
                makerspace=space,
                machine=machine,
                material=name,
                initial_grams="100.00",
                remaining_grams="100.00",
            )

        source_pool = pool("source", source_machine)
        resulting_pool = pool("resulting", pool_machine)
        shared_pool = pool("shared")
        rows = {
            "result": ToBuyItem.objects.create(
                makerspace=space,
                kind="printing",
                name="result",
                resulting_machine=result_machine,
            ),
            "source": ToBuyItem.objects.create(
                makerspace=space,
                kind="printing",
                name="source",
                source_pool=source_pool,
            ),
            "pool": ToBuyItem.objects.create(
                makerspace=space,
                kind="printing",
                name="pool",
                resulting_pool=resulting_pool,
            ),
            "priority": ToBuyItem.objects.create(
                makerspace=space,
                kind="printing",
                name="priority",
                resulting_machine=result_machine,
                source_pool=source_pool,
                resulting_pool=resulting_pool,
            ),
            "shared": ToBuyItem.objects.create(
                makerspace=space,
                kind="printing",
                name="Filament restock: guessed name must not count",
                source_pool=shared_pool,
            ),
            "none": ToBuyItem.objects.create(
                makerspace=space,
                kind="printing",
                name="3D printer-looking name must not count",
            ),
        }

        executor = MigrationExecutor(connection)
        executor.migrate(target)
        new_apps = executor.loader.project_state(target).apps
        NewToBuyItem = new_apps.get_model("procurement", "ToBuyItem")
        stamped = {
            key: NewToBuyItem.objects.get(pk=row.pk).machine_type_id
            for key, row in rows.items()
        }
        assert stamped == {
            "result": result_type.pk,
            "source": source_type.pk,
            "pool": pool_type.pk,
            "priority": result_type.pk,
            "shared": None,
            "none": None,
        }

        # Running the backwards migration exercises the explicit NULL-clearing reverse
        # before Django removes the column.
        executor = MigrationExecutor(connection)
        executor.migrate(from_target)
    finally:
        restore = MigrationExecutor(connection)
        restore.migrate(restore.loader.graph.leaf_nodes())
