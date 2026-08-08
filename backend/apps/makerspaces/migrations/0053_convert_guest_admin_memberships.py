"""Move every remaining ``role="guest_admin"`` membership onto a real custom role.

Migration `0052` converted the seeded Guest Admin *role* row into an ordinary custom role
but deliberately left the membership's ``role`` string alone, so a membership whose
``assigned_role`` FK was still null kept resolving through the frozen
``rbac._MEMBERSHIP_ROLE_ACTIONS["guest_admin"]`` fallback. That fallback is what this
migration exists to make unnecessary: once no row holds the string, the enum member and the
fallback entry can both go, which is the point of the final removal.

Two shapes of membership, handled differently because only one of them is missing anything:

* **FK already set** (the common case -- `0039` backfilled it). Authority already resolves
  from ``assigned_role.granted_actions``; the ``role`` string is a stale mirror. Flipping it
  to ``custom`` changes nothing about what the person can do.
* **FK null.** Authority is coming from the frozen fallback, so the membership needs a role
  row that grants *exactly* those six actions -- no more, no less. Widening here would be a
  silent permission grant, and narrowing would lock a working front-desk staffer out.

For the null case the makerspace's existing handover role is reused **only when its actions
still equal the frozen six**. That is the untouched-`0052`-row case, and reusing it keeps a
space from ending up with two near-identical handover roles. If an operator has since
widened or narrowed that role -- which `0052` made legal -- reusing it would hand the
membership authority it never had, so a dedicated role is created instead.

The created role is named "Front Desk" because that is the job, not the legacy label; both
``name`` and ``slug`` are case-insensitively unique per makerspace, so both are suffixed
until they land.
"""

from django.db import migrations

GUEST_ADMIN = "guest_admin"
CUSTOM = "custom"

# Frozen copy of `rbac._GUEST_ADMIN_ACTIONS`. A migration must not import runtime code --
# that set is deleted in the same batch, and even if it were not, a historical migration
# has to keep meaning what it meant when it was written.
HANDOUT_ACTIONS = sorted(
    [
        "view_inventory",
        "assign_box",
        "issue_request",
        "issue_direct_loan",
        "return_request",
        "upload_evidence",
    ]
)

FRONT_DESK_NAME = "Front Desk"
FRONT_DESK_SLUG = "front-desk"


def _unique_name_and_slug(MakerspaceRole, makerspace_id):
    """Pick a (name, slug) pair free of both case-insensitive uniques in this makerspace."""
    existing_names = {
        value.casefold()
        for value in MakerspaceRole.objects.filter(
            makerspace_id=makerspace_id
        ).values_list("name", flat=True)
    }
    existing_slugs = {
        value.casefold()
        for value in MakerspaceRole.objects.filter(
            makerspace_id=makerspace_id
        ).values_list("slug", flat=True)
    }
    suffix = 1
    while True:
        name = FRONT_DESK_NAME if suffix == 1 else f"{FRONT_DESK_NAME} {suffix}"
        slug = FRONT_DESK_SLUG if suffix == 1 else f"{FRONT_DESK_SLUG}-{suffix}"
        if name.casefold() not in existing_names and slug.casefold() not in existing_slugs:
            return name, slug
        suffix += 1


def _handover_role_for(MakerspaceRole, makerspace_id, cache):
    """Reuse the space's untouched handover role, else make a dedicated one."""
    if makerspace_id in cache:
        return cache[makerspace_id]

    reusable = None
    for role in MakerspaceRole.objects.filter(
        makerspace_id=makerspace_id, slug=GUEST_ADMIN
    ):
        actions = role.granted_actions if isinstance(role.granted_actions, list) else []
        if sorted(str(action) for action in actions) == HANDOUT_ACTIONS:
            reusable = role
            break

    if reusable is None:
        name, slug = _unique_name_and_slug(MakerspaceRole, makerspace_id)
        reusable = MakerspaceRole.objects.create(
            makerspace_id=makerspace_id,
            name=name,
            slug=slug,
            granted_actions=list(HANDOUT_ACTIONS),
            legacy_role=None,
            is_default=False,
            is_protected=False,
        )

    cache[makerspace_id] = reusable
    return reusable


def forwards(apps, schema_editor):
    MakerspaceMembership = apps.get_model("makerspaces", "MakerspaceMembership")
    MakerspaceRole = apps.get_model("makerspaces", "MakerspaceRole")

    role_cache = {}
    for membership in MakerspaceMembership.objects.filter(role=GUEST_ADMIN).iterator():
        if membership.assigned_role_id is None:
            role = _handover_role_for(
                MakerspaceRole, membership.makerspace_id, role_cache
            )
            membership.assigned_role_id = role.pk
            membership.role = CUSTOM
            membership.save(update_fields=["assigned_role", "role"])
        else:
            membership.role = CUSTOM
            membership.save(update_fields=["role"])


def backwards(apps, schema_editor):
    """Restore the legacy string on memberships that still look like what we wrote.

    Same caution as `0052`: only rows matching the shape this migration produced are
    touched. A membership reassigned to some other role since is genuinely custom now, and
    forcing the legacy string back onto it would be the destructive direction.

    Roles created here are dropped only if nothing else came to depend on them -- the
    membership FK is PROTECT, so a role still held by an untouched membership must survive.
    """
    MakerspaceMembership = apps.get_model("makerspaces", "MakerspaceMembership")
    MakerspaceRole = apps.get_model("makerspaces", "MakerspaceRole")

    created_slugs_q = MakerspaceRole.objects.filter(
        slug__startswith=FRONT_DESK_SLUG, legacy_role__isnull=True, is_default=False
    )
    created_ids = set(created_slugs_q.values_list("pk", flat=True))

    reverted = MakerspaceMembership.objects.filter(
        role=CUSTOM, assigned_role__slug__in=[GUEST_ADMIN, *created_slugs_q.values_list("slug", flat=True)]
    )
    for membership in reverted.select_related("assigned_role").iterator():
        role = membership.assigned_role
        actions = role.granted_actions if isinstance(role.granted_actions, list) else []
        if sorted(str(action) for action in actions) != HANDOUT_ACTIONS:
            continue
        membership.role = GUEST_ADMIN
        if role.pk in created_ids:
            # This role only ever existed to carry the reverse of the null-FK case, so the
            # reverse restores the null too.
            membership.assigned_role_id = None
            membership.save(update_fields=["assigned_role", "role"])
        else:
            membership.save(update_fields=["role"])

    for role in MakerspaceRole.objects.filter(pk__in=created_ids):
        if not MakerspaceMembership.objects.filter(assigned_role_id=role.pk).exists():
            role.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("makerspaces", "0052_retire_builtin_guest_admin_role"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
