import django.contrib.postgres.indexes
import django.contrib.postgres.search
from django.db import migrations

from apps.inventory.search import vector_trigger_sql

FORWARD, REVERSE = vector_trigger_sql(
    "machines_machine",
    [("name", "A"), ("location", "B"), ("firmware_version", "C"), ("notes", "D")],
    trigger_name="machine_search_vector_trg",
)


class Migration(migrations.Migration):
    dependencies = [
        ("machines", "0022_consumable_pool_color_hex"),
        # pg_trgm is created once, by the inventory migration.
        ("inventory", "0010_inventoryproduct_search_vector"),
    ]

    operations = [
        migrations.AddField(
            model_name="machine",
            name="search_vector",
            field=django.contrib.postgres.search.SearchVectorField(editable=False, null=True),
        ),
        migrations.AddIndex(
            model_name="machine",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["search_vector"], name="machine_search_gin"
            ),
        ),
        migrations.RunSQL(FORWARD, REVERSE),
    ]
