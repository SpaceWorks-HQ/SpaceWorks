"""Turn the new `email` module ON for makerspaces that already exist (plan A4).

Modules are opt-in, so a newly registered key is off by default -- correct for a new
makerspace, catastrophic for an existing one. Every space upgrading into this release
was already sending mail; leaving them at the opt-in default would silently stop
membership invitations, request notifications and everything else the moment the code
deploys, with no operator action and no error.

So: a one-time backfill, not a default change. Only rows that predate the key are
touched, and the reverse removes it again so the migration is not a one-way door.
"""

from django.db import migrations

MODULE_KEY = "email"


def enable_email(apps, schema_editor):
    Makerspace = apps.get_model("makerspaces", "Makerspace")
    for makerspace in Makerspace.objects.all().iterator():
        modules = list(makerspace.enabled_modules or [])
        if MODULE_KEY in modules:
            continue
        modules.append(MODULE_KEY)
        makerspace.enabled_modules = sorted(modules)
        makerspace.save(update_fields=["enabled_modules"])


def disable_email(apps, schema_editor):
    Makerspace = apps.get_model("makerspaces", "Makerspace")
    for makerspace in Makerspace.objects.all().iterator():
        modules = list(makerspace.enabled_modules or [])
        if MODULE_KEY not in modules:
            continue
        makerspace.enabled_modules = sorted(set(modules) - {MODULE_KEY})
        makerspace.save(update_fields=["enabled_modules"])


class Migration(migrations.Migration):
    dependencies = [("makerspaces", "0049_membership_dues_and_module")]

    operations = [migrations.RunPython(enable_email, disable_email)]
