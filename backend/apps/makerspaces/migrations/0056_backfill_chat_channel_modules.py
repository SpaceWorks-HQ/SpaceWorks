"""Turn the new `slack` and `mattermost` module keys ON for existing makerspaces.

The `email` backfill in 0050 exists for exactly this reason and this is the same trap.
Slack and Mattermost were previously governed by webhook presence alone -- configure a
webhook and alerts flowed. Now a module key ANDs in front of that check, and modules are
opt-in, so every upgrading space would have its chat alerts silently muted the moment
this deploys: no operator action, no error, no log they would think to read.

Backfilled UNCONDITIONALLY, not only for spaces that already hold a webhook. Granting
the key restores the old rule exactly -- "webhook presence governs sending" -- including
for a space that configures Slack for the first time next month. Backfilling only
already-configured spaces would leave that space adding a webhook and finding it
silently inert, which is the same failure one step later.

`discord` is deliberately NOT backfilled: it is a brand-new capability that nobody was
using, so the opt-in default is the correct one for it.
"""

from django.db import migrations

MODULE_KEYS = ("slack", "mattermost")


def enable_chat_modules(apps, schema_editor):
    Makerspace = apps.get_model("makerspaces", "Makerspace")
    for makerspace in Makerspace.objects.all().iterator():
        modules = set(makerspace.enabled_modules or [])
        if modules.issuperset(MODULE_KEYS):
            continue
        makerspace.enabled_modules = sorted(modules | set(MODULE_KEYS))
        makerspace.save(update_fields=["enabled_modules"])


def disable_chat_modules(apps, schema_editor):
    Makerspace = apps.get_model("makerspaces", "Makerspace")
    for makerspace in Makerspace.objects.all().iterator():
        modules = set(makerspace.enabled_modules or [])
        if modules.isdisjoint(MODULE_KEYS):
            continue
        makerspace.enabled_modules = sorted(modules - set(MODULE_KEYS))
        makerspace.save(update_fields=["enabled_modules"])


class Migration(migrations.Migration):
    dependencies = [("makerspaces", "0055_discord_webhook_and_channel_status")]

    operations = [migrations.RunPython(enable_chat_modules, disable_chat_modules)]
