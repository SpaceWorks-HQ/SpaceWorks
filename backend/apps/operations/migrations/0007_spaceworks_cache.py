from django.core.management import call_command
from django.db import migrations


def create_spaceworks_cache(apps, schema_editor):
    call_command(
        "createcachetable",
        "spaceworks_cache",
        database=schema_editor.connection.alias,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("operations", "0006_periodic_task_run"),
    ]

    operations = [
        migrations.RunPython(create_spaceworks_cache, migrations.RunPython.noop),
    ]
