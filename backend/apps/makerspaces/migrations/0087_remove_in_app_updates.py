"""Permanently remove the retired deployment updater and its stored module key."""

from django.db import migrations


# The retired app had one concrete model and no implicit many-to-many tables.
UPDATE_TABLES = ("updates_platformupdatesettings",)


def remove_update_state(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        for table in UPDATE_TABLES:
            cursor.execute(
                f"DROP TABLE IF EXISTS {schema_editor.quote_name(table)} CASCADE"
            )
        cursor.execute("DELETE FROM django_migrations WHERE app = %s", ["updates"])
    Makerspace = apps.get_model("makerspaces", "Makerspace")
    rows = Makerspace.objects.using(schema_editor.connection.alias)
    for space in rows.only("pk", "enabled_modules").iterator():
        modules = [key for key in (space.enabled_modules or []) if key != "updates"]
        if modules != space.enabled_modules:
            rows.filter(pk=space.pk).update(enabled_modules=modules)


class Migration(migrations.Migration):
    dependencies = [
        ("makerspaces", "0086_public_site_and_loans"),
    ]
    # Rewinding unrelated migrations must remain possible. The retired app's tables,
    # migration records and module selections are deliberately not recreated on reverse.
    operations = [migrations.RunPython(remove_update_state, migrations.RunPython.noop)]
