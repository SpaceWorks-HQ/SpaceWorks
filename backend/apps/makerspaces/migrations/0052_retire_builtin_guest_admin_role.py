"""Convert the seeded Guest Admin role into an ordinary custom role.

Guest Admin stops being a built-in. What it must NOT do is stop existing: memberships
point at that row through a PROTECT foreign key, and authority is resolved from the row's
`granted_actions`, so deleting or recreating it would revoke every guest admin's access in
the same breath. So this converts in place -- same row, same primary key, same name, same
actions, same assignments -- and only changes what the row *is*:

* ``is_default``/``is_protected`` false, so it can now be renamed, re-scoped and (once
  nobody holds it) deleted, like any role a makerspace made for itself;
* ``legacy_role`` null, which is also what lifts the handout-only ceiling in
  ``role_services._validate_actions`` -- that check keys on this column. Widening the role
  is the point of making it custom, and it is not a permission change on its own: the
  role's actions are untouched here, and editing it still requires ``manage_makerspace``
  and cannot exceed what the editor holds.

Deliberately **not** granted: ``collect_service_request``. It ships in the same batch and
would let guest admins hand over finished machine jobs, but a migration is the wrong place
to widen real permissions on deployments whose operators never asked for it. Each
makerspace adds it to whichever role should do handovers.

``MakerspaceMembership.role`` keeps the string ``guest_admin`` and the enum keeps the
member, so a membership whose ``assigned_role`` FK is still null resolves through
``rbac._MEMBERSHIP_ROLE_ACTIONS`` exactly as before. That is the same shape migration
`0046` left ``print_manager`` in.

Reverse restores the protected default so the migration is not a one-way door -- but only
for rows this actually converted, which is why it matches on the slug it wrote.
"""

from django.db import migrations

GUEST_ADMIN = "guest_admin"


def forwards(apps, schema_editor):
    MakerspaceRole = apps.get_model("makerspaces", "MakerspaceRole")

    MakerspaceRole.objects.filter(
        legacy_role=GUEST_ADMIN, is_default=True, is_protected=True
    ).update(legacy_role=None, is_default=False, is_protected=False)


def backwards(apps, schema_editor):
    MakerspaceRole = apps.get_model("makerspaces", "MakerspaceRole")

    # Only rows that still look like the converted default are restored. A makerspace that
    # renamed or re-scoped its handover role in the meantime has made it genuinely its
    # own, and forcing it back under the protected-default constraints would be the
    # destructive direction. `makerspacerole_legacy_uniq` also forbids two rows claiming
    # one legacy value, so restoring blindly could fail on a space that meanwhile built a
    # second handover role.
    for role in MakerspaceRole.objects.filter(
        slug=GUEST_ADMIN, legacy_role__isnull=True, is_default=False
    ):
        if MakerspaceRole.objects.filter(
            makerspace_id=role.makerspace_id, legacy_role=GUEST_ADMIN
        ).exists():
            continue
        role.legacy_role = GUEST_ADMIN
        role.is_default = True
        role.is_protected = True
        role.save(update_fields=["legacy_role", "is_default", "is_protected"])


class Migration(migrations.Migration):

    dependencies = [
        ("makerspaces", "0051_backfill_a6_master_feature_switches"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
