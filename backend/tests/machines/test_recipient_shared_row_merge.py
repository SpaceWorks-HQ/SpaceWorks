"""A delegate edits their own links inside a SHARED requester/members recipient row.

`uniq_notification_recipient_special` allows one such row per (makerspace, feature, event),
so two teams wanting "notify the requester for MY machines" are describing one row. These
tests pin the merge that lets each of them own part of it, the refusal that protects a
space-wide policy from being narrowed, and the redacted projection that makes a delegate's
save read back as something other than absent.

Everything drives the real HTTP path: `create_for_registered_registration`-style silent
swallowing is not a risk here, but a test that constructs rows directly would prove nothing
about the view, the lock or the serializer.
"""

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.rbac import Action
from apps.integrations.models_recipients import (
    NotificationRecipient,
    NotificationRecipientKind,
)
from apps.machines.models import MachineType
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole
from apps.makerspaces.roles import ensure_default_roles

pytestmark = pytest.mark.django_db

SWITCH = "notifications.delegated_recipients"


def make_space(slug):
    space = Makerspace.objects.create(name=slug, slug=slug)
    ensure_default_roles(space)
    space.enabled_modules = sorted(
        set(space.enabled_modules) | {"machines", "maintenance", "notifications"}
    )
    space.enabled_features = [*space.enabled_features, SWITCH]
    space.save(update_fields=["enabled_modules", "enabled_features"])
    return space


def make_type(space, slug):
    return MachineType.objects.create(makerspace=space, name=slug.title(), slug=slug)


def make_delegate(space, machine_type, username):
    role = MakerspaceRole.objects.create(
        makerspace=space,
        name=f"{username} role",
        slug=f"{username}-role",
        granted_actions=[Action.MANAGE_MACHINES],
    )
    role.machine_type_scopes.create(machine_type=machine_type)
    user = get_user_model().objects.create_user(
        username=username,
        email=f"{username}@e.com",
        role=User.Role.REQUESTER,
        access_status=User.AccessStatus.ACTIVE,
    )
    MakerspaceMembership.objects.create(
        user=user,
        makerspace=space,
        role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=role,
    )
    return user, role


def make_manager(space, username):
    user = get_user_model().objects.create_user(
        username=username,
        email=f"{username}@e.com",
        role=User.Role.SPACE_MANAGER,
        access_status=User.AccessStatus.ACTIVE,
    )
    MakerspaceMembership.objects.create(
        user=user,
        makerspace=space,
        role=MakerspaceMembership.Role.SPACE_MANAGER,
        assigned_role=MakerspaceRole.objects.get(makerspace=space, slug="space_manager"),
    )
    return user


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def url(space):
    return f"/api/v1/admin/makerspace/{space.pk}/notification-recipient-rules"


def put(user, space, rules):
    return client_for(user).put(
        url(space),
        {"feature": "maintenance", "event": "logged", "rules": rules},
        format="json",
    )


def requester_rule(*machine_types):
    return {
        "kind": "requester",
        "scope": {"machine_type_ids": [t.pk for t in machine_types]},
    }


def shared_row(space, *machine_types, kind=NotificationRecipientKind.REQUESTER):
    row = NotificationRecipient.objects.create(
        makerspace=space, feature="maintenance", event="logged", kind=kind
    )
    for machine_type in machine_types:
        row.machine_type_scopes.create(machine_type=machine_type)
    return row


def linked_type_ids(row):
    return set(row.machine_type_scopes.values_list("machine_type_id", flat=True))


def test_merge_replaces_only_the_delegates_links_in_a_shared_row():
    space = make_space("merge-partition")
    laser = make_type(space, "merge-partition-laser")
    printer = make_type(space, "merge-partition-printer")
    actor, _ = make_delegate(space, laser, "merge-partition-laser-tech")
    row = shared_row(space, laser, printer)

    response = put(actor, space, [requester_rule(laser)])

    assert response.status_code == 200
    row.refresh_from_db()
    # One row still, because the constraint allows exactly one -- the delegate's submission
    # was expressed by editing this row rather than by inserting a colliding second.
    assert (
        NotificationRecipient.objects.filter(
            makerspace=space, kind=NotificationRecipientKind.REQUESTER
        ).count()
        == 1
    )
    assert linked_type_ids(row) == {laser.pk, printer.pk}


def test_omitting_the_kind_strips_only_the_delegates_links():
    space = make_space("merge-retract")
    laser = make_type(space, "merge-retract-laser")
    printer = make_type(space, "merge-retract-printer")
    actor, _ = make_delegate(space, laser, "merge-retract-laser-tech")
    row = shared_row(space, laser, printer)

    response = put(actor, space, [])

    assert response.status_code == 200
    row.refresh_from_db()
    # The other team's printer link survives; only the laser coverage this actor owns went.
    assert linked_type_ids(row) == {printer.pk}


def test_a_space_wide_row_is_refused_rather_than_narrowed():
    space = make_space("merge-spacewide")
    laser = make_type(space, "merge-spacewide-laser")
    actor, _ = make_delegate(space, laser, "merge-spacewide-laser-tech")
    # No scope links at all: `rule_covers` reads that as EVERY subject, so adding this
    # delegate's links would silently shrink a space-wide policy to one team's machines.
    row = shared_row(space)

    response = put(actor, space, [requester_rule(laser)])

    assert response.status_code == 400
    assert "space-wide" in response.json()["detail"]
    row.refresh_from_db()
    assert linked_type_ids(row) == set()


def test_a_space_wide_row_is_untouched_when_the_kind_is_omitted():
    space = make_space("merge-spacewide-omit")
    laser = make_type(space, "merge-spacewide-omit-laser")
    actor, _ = make_delegate(space, laser, "merge-spacewide-omit-tech")
    row = shared_row(space)

    response = put(actor, space, [])

    assert response.status_code == 200
    assert NotificationRecipient.objects.filter(pk=row.pk).exists() is True
    assert linked_type_ids(row) == set()


def test_a_partially_owned_row_is_projected_to_the_delegates_own_links():
    space = make_space("merge-projection")
    laser = make_type(space, "merge-projection-laser")
    printer = make_type(space, "merge-projection-printer")
    actor, _ = make_delegate(space, laser, "merge-projection-laser-tech")
    shared_row(space, laser, printer)

    body = client_for(actor).get(url(space)).json()

    projected = [rule for rule in body["rules"] if rule["kind"] == "requester"]
    assert len(projected) == 1
    # Only the delegate's half is shown -- the printer link is not disclosed ...
    assert projected[0]["scope"]["machine_type_ids"] == [laser.pk]
    # ... the real primary key is withheld, since PUT is not id-addressed and nothing reads
    # it, so returning it would disclose a row this actor does not own ...
    assert projected[0]["id"] is None
    # ... and the row is STILL counted as a hidden policy, because both facts are true at
    # once: they own part of it, and part of it is outside their reach.
    assert body["managed_policy_markers"] == [
        {"feature": "maintenance", "event": "logged", "count": 1}
    ]


def test_putting_the_projection_back_is_a_no_op():
    """The round-trip an untouched form performs must not add or drop coverage.

    This is what forces the projection and the merge to share one link-ownership
    predicate: if "which links do I show you" and "which links do I strip" disagree, an
    operator who opens the editor and saves without typing changes the policy.
    """
    space = make_space("merge-roundtrip")
    laser = make_type(space, "merge-roundtrip-laser")
    printer = make_type(space, "merge-roundtrip-printer")
    actor, _ = make_delegate(space, laser, "merge-roundtrip-laser-tech")
    row = shared_row(space, laser, printer)
    before = linked_type_ids(row)

    body = client_for(actor).get(url(space)).json()
    response = put(
        actor,
        space,
        [
            {"kind": rule["kind"], "scope": rule["scope"]}
            for rule in body["rules"]
            if rule["kind"] == "requester"
        ],
    )

    assert response.status_code == 200
    row.refresh_from_db()
    assert linked_type_ids(row) == before


def test_two_delegates_each_hold_their_own_partition_of_one_row():
    space = make_space("merge-two-teams")
    laser = make_type(space, "merge-two-teams-laser")
    printer = make_type(space, "merge-two-teams-printer")
    laser_tech, _ = make_delegate(space, laser, "merge-two-teams-laser-tech")
    printer_tech, _ = make_delegate(space, printer, "merge-two-teams-printer-tech")

    assert put(laser_tech, space, [requester_rule(laser)]).status_code == 200
    # The second team's submission is the one that used to trip the unique constraint and
    # surface as "a Space Manager-managed policy already uses one of these recipients".
    assert put(printer_tech, space, [requester_rule(printer)]).status_code == 200

    row = NotificationRecipient.objects.get(
        makerspace=space, kind=NotificationRecipientKind.REQUESTER
    )
    assert linked_type_ids(row) == {laser.pk, printer.pk}


def test_delegate_may_delete_a_manager_special_row_inside_their_reach():
    """Accepted contract, pinned deliberately: for these kinds SCOPE IS OWNERSHIP.

    `created_by` is never consulted and the schema carries no per-link provenance, so a
    row lying entirely inside the delegate's reach is theirs to replace -- exactly as a
    `role` row naming their own role already is. Recorded as a test rather than left
    implicit so that changing it is a decision, not an accident.
    """
    space = make_space("merge-ownership")
    laser = make_type(space, "merge-ownership-laser")
    actor, _ = make_delegate(space, laser, "merge-ownership-laser-tech")
    manager = make_manager(space, "merge-ownership-manager")
    row = shared_row(space, laser)
    row.created_by = manager
    row.save(update_fields=["created_by"])

    response = put(actor, space, [])

    assert response.status_code == 200
    assert NotificationRecipient.objects.filter(pk=row.pk).exists() is False


def test_stripping_the_last_link_deletes_the_row():
    """The fail-safe, driven directly because no API path can reach it.

    A shared row only ever reaches the merge because it was NOT fully reachable, and every
    reason for that leaves a link `owns_link` does not claim -- so the strip cannot empty
    it. The guard exists for the day that stops being true, because a row left with zero
    links covers EVERYTHING: a narrow team rule would silently become a space-wide policy.

    It is driven through `rows_for`, which is how the service loads these rows, so the row
    arrives carrying the same `prefetch_related` cache. That is the point of the test: the
    first version counted links with `row.machine_type_scopes.count()`, which answers from
    that stale cache and reported one remaining link for a row that had none, so the guard
    never fired.
    """
    from apps.admin_api.recipient_rule_common import reach_for, rows_for
    from apps.admin_api.recipient_rule_merge import _replace_owned_links

    space = make_space("merge-failsafe")
    laser = make_type(space, "merge-failsafe-laser")
    actor, _ = make_delegate(space, laser, "merge-failsafe-laser-tech")
    row = shared_row(space, laser)

    prefetched = rows_for(space, feature="maintenance", event="logged").get(pk=row.pk)
    _replace_owned_links(prefetched, None, reach_for(actor, space.pk))

    assert NotificationRecipient.objects.filter(pk=row.pk).exists() is False


def test_space_manager_replacement_is_unchanged():
    space = make_space("merge-manager-path")
    laser = make_type(space, "merge-manager-path-laser")
    printer = make_type(space, "merge-manager-path-printer")
    manager = make_manager(space, "merge-manager-path-manager")
    shared_row(space, laser, printer)

    response = put(manager, space, [requester_rule(printer)])

    assert response.status_code == 200
    # A Space Manager owns every row, so this is a full replace: the old row went and the
    # submitted one took its place, carrying only what was submitted.
    row = NotificationRecipient.objects.get(
        makerspace=space, kind=NotificationRecipientKind.REQUESTER
    )
    assert linked_type_ids(row) == {printer.pk}
