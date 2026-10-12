from django.db import migrations


def enable_saved_views(apps, schema_editor):
    space_model = apps.get_model("makerspaces", "Makerspace")
    for space in space_model.objects.using(schema_editor.connection.alias).filter(enabled_modules__contains=["reports"]).iterator():
        if "reports.saved_views" not in space.enabled_features:
            space.enabled_features = [*space.enabled_features, "reports.saved_views"]
            space.save(using=schema_editor.connection.alias, update_fields=["enabled_features"])


class Migration(migrations.Migration):
    dependencies = [("makerspaces", "0083_membership_renewal_automation")]
    operations = [migrations.RunPython(enable_saved_views, migrations.RunPython.noop)]
