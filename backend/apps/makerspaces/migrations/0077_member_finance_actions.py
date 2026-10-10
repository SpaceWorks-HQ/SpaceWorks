"""Preserve roster and ledger access for every existing makerspace-admin role."""

from django.db import migrations

NEW_ACTIONS = {"manage_members", "view_finance", "record_payment"}


def forwards(apps, schema_editor):
    # Organization authority is also action based, with no mirrored local role. Its
    # existing admin grants need the same compatibility backfill; reach stays in RBAC.
    for label in ("makerspaces.MakerspaceRole", "organizations.OrganizationMembership"):
        Grant = apps.get_model(label)
        for grant in Grant.objects.using(schema_editor.connection.alias).all().iterator():
            actions = grant.granted_actions
            if isinstance(actions, list) and "manage_makerspace" in actions:
                grant.granted_actions = sorted(set(actions) | NEW_ACTIONS)
                grant.save(using=schema_editor.connection.alias, update_fields=["granted_actions"])


class Migration(migrations.Migration):
    dependencies = [
        ("makerspaces", "0076_station_operator_leases"),
        ("organizations", "0003_organization_presentation_and_governance"),
    ]
    # Additive grants cannot be safely reversed: an administrator may have granted or
    # edited them since the upgrade. Rolling back leaves those deliberate grants alone.
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
