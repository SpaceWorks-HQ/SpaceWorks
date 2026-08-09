from django.db import migrations

# Placed in front of substrate that was previously unconditional. Modules are opt-in, so
# a newly registered key is OFF for every makerspace that already exists -- correct for
# a genuinely new capability, and wrong here, because nobody asked for their payment
# surfaces, member sign-up, paired phones or updater to disappear at upgrade. This is
# the `0050` (email) and `0056` (slack/mattermost) precedent.
#
# UNCONDITIONAL, not "only spaces that already use it". Granting the key restores the
# previous rule *including* for a space that starts taking payments or pairing a phone
# next month; a usage-conditional backfill would silently withhold it from them.
BACKFILLED_KEYS = ("payments", "accounts", "mobile", "updates")

# `membership` requires `accounts` from this migration onward, so any space holding
# membership must gain accounts here or its very next save fails validation.


def add_keys(apps, schema_editor):
    Makerspace = apps.get_model("makerspaces", "Makerspace")
    for makerspace in Makerspace.objects.all().only("id", "enabled_modules").iterator():
        modules = list(makerspace.enabled_modules or [])
        missing = [key for key in BACKFILLED_KEYS if key not in modules]
        if not missing:
            continue
        makerspace.enabled_modules = sorted(set(modules) | set(missing))
        makerspace.save(update_fields=["enabled_modules"])


def remove_keys(apps, schema_editor):
    """Reverse cleanly, so the migration is not a one-way door.

    Removes only the four keys this migration adds. A space that had one of them before
    (impossible today, since the keys are new) would lose it -- accepted, because the
    alternative is an irreversible migration.
    """
    Makerspace = apps.get_model("makerspaces", "Makerspace")
    for makerspace in Makerspace.objects.all().only("id", "enabled_modules").iterator():
        modules = [key for key in (makerspace.enabled_modules or []) if key not in BACKFILLED_KEYS]
        if len(modules) != len(makerspace.enabled_modules or []):
            makerspace.enabled_modules = modules
            makerspace.save(update_fields=["enabled_modules"])


class Migration(migrations.Migration):
    dependencies = [("makerspaces", "0056_backfill_chat_channel_modules")]

    operations = [migrations.RunPython(add_keys, remove_keys)]
