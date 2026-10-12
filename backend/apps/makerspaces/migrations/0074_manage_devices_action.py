"""Grant `manage_devices` to every protected Space Manager default role.

`roles.DEFAULT_ROLE_DEFINITIONS` now lists `manage_devices` for `space_manager`, but
`ensure_default_roles` deliberately never rewrites an existing protected row (administrator
edits win), so existing makerspaces need this one-time additive backfill. Custom roles,
Inventory Managers and Machine Managers are untouched: they receive nothing until an
administrator grants it. Nothing here depends on `devices`, so the graph stays acyclic.
"""
from django.db import migrations

ACTION = "manage_devices"


def forwards(apps, schema_editor):
    MakerspaceRole = apps.get_model("makerspaces", "MakerspaceRole")
    for role in MakerspaceRole.objects.filter(legacy_role="space_manager", is_protected=True).iterator():
        granted = list(role.granted_actions or [])
        if ACTION not in granted:
            role.granted_actions = sorted({*granted, ACTION})
            role.save(update_fields=["granted_actions"])


def backwards(apps, schema_editor):
    MakerspaceRole = apps.get_model("makerspaces", "MakerspaceRole")
    for role in MakerspaceRole.objects.filter(legacy_role="space_manager", is_protected=True).iterator():
        role.granted_actions = [action for action in (role.granted_actions or []) if action != ACTION]
        role.save(update_fields=["granted_actions"])


class Migration(migrations.Migration):
    dependencies = [
        ("makerspaces", "0073_member_card_live_per_membership"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
