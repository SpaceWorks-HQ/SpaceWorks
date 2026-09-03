"""Grant the member-card actions to every protected Space Manager default role.

`roles.DEFAULT_ROLE_DEFINITIONS` now lists `manage_member_cards` for `space_manager`, but
`ensure_default_roles` deliberately never rewrites an existing protected row (administrator
edits win), so existing makerspaces need this one-time additive backfill. Custom roles are
untouched: they receive nothing until an administrator grants it. `scan_member_cards` is
implied by `manage_member_cards` and is therefore not stored.
"""
from django.db import migrations

ACTION = "manage_member_cards"


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
        granted = [action for action in (role.granted_actions or []) if action != ACTION]
        role.granted_actions = granted
        role.save(update_fields=["granted_actions"])


class Migration(migrations.Migration):
    dependencies = [
        ("makerspaces", "0068_member_cards"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
