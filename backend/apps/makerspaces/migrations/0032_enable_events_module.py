from django.db import migrations

MODULE = "events"


def enable_events(apps, schema_editor):
    Makerspace = apps.get_model("makerspaces", "Makerspace")
    for makerspace in Makerspace.objects.all().iterator():
        modules = list(makerspace.enabled_modules or [])
        if MODULE not in modules:
            modules.append(MODULE)
            makerspace.enabled_modules = modules
            makerspace.save(update_fields=["enabled_modules"])


def disable_events(apps, schema_editor):
    Makerspace = apps.get_model("makerspaces", "Makerspace")
    for makerspace in Makerspace.objects.all().iterator():
        modules = [m for m in (makerspace.enabled_modules or []) if m != MODULE]
        makerspace.enabled_modules = modules
        makerspace.save(update_fields=["enabled_modules"])


class Migration(migrations.Migration):
    dependencies = [
        ("makerspaces", "0031_subdomain_request"),
    ]

    operations = [
        migrations.RunPython(enable_events, disable_events),
    ]
