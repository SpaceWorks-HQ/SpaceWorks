from django.db import migrations


def enable_invites(apps, schema_editor):
    Space = apps.get_model("makerspaces", "Makerspace")
    for space in Space.objects.all().iterator():
        features = list(space.enabled_features or [])
        if "staff.invitations" not in features:
            space.enabled_features = features + ["staff.invitations"]
            space.save(update_fields=["enabled_features"])


class Migration(migrations.Migration):
    dependencies = [("makerspaces", "0076_station_operator_leases")]
    operations = [migrations.RunPython(enable_invites, migrations.RunPython.noop)]
