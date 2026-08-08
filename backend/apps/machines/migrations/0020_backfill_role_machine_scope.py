"""Link every existing ``MANAGE_MACHINES`` role to every machine type that exists now.

Without this, `0019` would silently revoke authority on upgrade: role scoping fails closed,
so the day the tables land, every role that held ``MANAGE_MACHINES`` would hold it over
nothing. Nobody asked for that, and a permissions change nobody asked for is not a
migration's job.

The backfill deliberately links **types, not machines**. Types are the durable unit -- a
type link keeps covering machines bought after the upgrade, so an untouched deployment
behaves exactly as it did before. Machine links would freeze each role at the fleet as it
stood the day of the upgrade, and the first new printer would be unmanageable.

It is equally deliberate that this only ever runs **once**, over the types that exist at
this moment. A type created afterwards is reached by nobody until someone grants it: that
is the fail-closed semantic the feature exists to provide, and re-running the backfill
later would undo it.

Roles holding ``MANAGE_MAKERSPACE`` are skipped -- they are exempt in `role_scope`, so
links would be dead rows that misrepresent the role in the console. Memberships with a
null ``assigned_role`` have no role row to link and are exempt for the same reason.
"""

from django.db import migrations

MANAGE_MACHINES = "manage_machines"
MANAGE_MAKERSPACE = "manage_makerspace"


def forwards(apps, schema_editor):
    MakerspaceRole = apps.get_model("makerspaces", "MakerspaceRole")
    MachineType = apps.get_model("machines", "MachineType")
    RoleMachineTypeScope = apps.get_model("machines", "RoleMachineTypeScope")

    # A type is linkable to a role when it is a global built-in (makerspace NULL) or
    # belongs to that role's own makerspace. Grouped up front so the loop stays queryless.
    global_type_ids = list(
        MachineType.objects.filter(makerspace__isnull=True).values_list("id", flat=True)
    )
    per_makerspace = {}
    for type_id, makerspace_id in MachineType.objects.filter(
        makerspace__isnull=False
    ).values_list("id", "makerspace_id"):
        per_makerspace.setdefault(makerspace_id, []).append(type_id)

    links = []
    for role in MakerspaceRole.objects.all().iterator():
        granted = role.granted_actions if isinstance(role.granted_actions, list) else []
        granted = {action for action in granted if isinstance(action, str)}
        if MANAGE_MACHINES not in granted or MANAGE_MAKERSPACE in granted:
            continue
        for type_id in global_type_ids + per_makerspace.get(role.makerspace_id, []):
            links.append(
                RoleMachineTypeScope(role_id=role.pk, machine_type_id=type_id)
            )

    RoleMachineTypeScope.objects.bulk_create(links, batch_size=500, ignore_conflicts=True)


def backwards(apps, schema_editor):
    """Drop every link. `0019` removes the tables anyway; this keeps the pair reversible
    on its own so the data step can be unapplied without unapplying the schema."""
    RoleMachineTypeScope = apps.get_model("machines", "RoleMachineTypeScope")
    RoleMachineTypeScope.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("machines", "0019_role_machine_scope"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
