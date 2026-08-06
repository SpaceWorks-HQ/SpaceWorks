"""Turn the new A6 master switches ON for makerspaces that already exist.

`payments.enabled`, `mobile.push` and `presence.geofence` are additive `AND`s in front
of readiness checks that already exist. A space that was charging, pushing or
classifying proximity yesterday must keep doing so after this release, and
`enabled_features` is stored per row -- a new `default_enabled=True` only affects rows
created from now on. Without this backfill the switches would read as OFF for every
existing makerspace and silently stop all three capabilities.

Same shape as `0050` for the `email` module: a one-time backfill with a working
reverse, touching only rows that lack the key.
"""

from django.db import migrations

FEATURE_KEYS = ("payments.enabled", "mobile.push", "presence.geofence")


def enable_switches(apps, schema_editor):
    Makerspace = apps.get_model("makerspaces", "Makerspace")
    for makerspace in Makerspace.objects.all().iterator():
        features = set(makerspace.enabled_features or [])
        if features.issuperset(FEATURE_KEYS):
            continue
        makerspace.enabled_features = sorted(features | set(FEATURE_KEYS))
        makerspace.save(update_fields=["enabled_features"])


def disable_switches(apps, schema_editor):
    Makerspace = apps.get_model("makerspaces", "Makerspace")
    for makerspace in Makerspace.objects.all().iterator():
        features = set(makerspace.enabled_features or [])
        if features.isdisjoint(FEATURE_KEYS):
            continue
        makerspace.enabled_features = sorted(features - set(FEATURE_KEYS))
        makerspace.save(update_fields=["enabled_features"])


class Migration(migrations.Migration):
    dependencies = [("makerspaces", "0050_enable_email_module_for_existing_makerspaces")]

    operations = [migrations.RunPython(enable_switches, disable_switches)]
