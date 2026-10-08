"""Turn the new `backup` module key ON for every existing makerspace.

The key was placed in front of surfaces every makerspace already had (tenant archive
requests, archive-recipient enrolment), the same trap makerspaces/0056 and 0057 closed:
without this, upgrading would silently remove a space's recipient management -- and
for a superadmin-off space that is its only custody path. Unconditional, so the old
behaviour is restored exactly. Lives in `backup` rather than `makerspaces` so it does
not compete for the makerspaces migration leaf. Reverse is a no-op: removing the key
from a superadmin-off space would strand its custody surfaces.
"""

from django.db import migrations

MODULE_KEY = "backup"


def enable_backup_module(apps, schema_editor):
    Makerspace = apps.get_model("makerspaces", "Makerspace")
    for makerspace in Makerspace.objects.all().iterator():
        modules = set(makerspace.enabled_modules or [])
        if MODULE_KEY in modules:
            continue
        makerspace.enabled_modules = sorted(modules | {MODULE_KEY})
        makerspace.save(update_fields=["enabled_modules"])


class Migration(migrations.Migration):
    dependencies = [
        ("backup", "0025_offsite_destinations"),
        ("makerspaces", "0072_enable_charge_tracking_for_existing_makerspaces"),
    ]

    operations = [migrations.RunPython(enable_backup_module, migrations.RunPython.noop)]
