import django.contrib.postgres.indexes
import django.contrib.postgres.search
from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations

from apps.inventory.search import vector_trigger_sql

FORWARD, REVERSE = vector_trigger_sql(
    "inventory_inventoryproduct",
    [("name", "A"), ("storage_location", "B"), ("tracking_mode", "C"), ("description", "D")],
    trigger_name="inventoryproduct_search_vector_trg",
)


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0009_inventoryproduct_image_key"),
    ]

    operations = [
        TrigramExtension(),
        migrations.AddField(
            model_name="inventoryproduct",
            name="search_vector",
            field=django.contrib.postgres.search.SearchVectorField(editable=False, null=True),
        ),
        migrations.AddIndex(
            model_name="inventoryproduct",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["search_vector"], name="inventoryproduct_search_gin"
            ),
        ),
        migrations.RunSQL(FORWARD, REVERSE),
    ]
