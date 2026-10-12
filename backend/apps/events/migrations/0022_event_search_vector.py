import django.contrib.postgres.indexes
import django.contrib.postgres.search
from django.db import migrations

from apps.inventory.search import vector_trigger_sql

FORWARD, REVERSE = vector_trigger_sql(
    "events_event",
    [("title", "A"), ("location", "B"), ("description", "D")],
    trigger_name="event_search_vector_trg",
)


class Migration(migrations.Migration):
    dependencies = [
        ("events", "0021_offline_and_station_checkin"),
        ("inventory", "0010_inventoryproduct_search_vector"),
    ]

    operations = [
        migrations.AddField(
            model_name="event",
            name="search_vector",
            field=django.contrib.postgres.search.SearchVectorField(editable=False, null=True),
        ),
        migrations.AddIndex(
            model_name="event",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["search_vector"], name="event_search_gin"
            ),
        ),
        migrations.RunSQL(FORWARD, REVERSE),
    ]
