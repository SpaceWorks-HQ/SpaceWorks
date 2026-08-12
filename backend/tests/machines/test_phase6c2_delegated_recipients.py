"""Delegated maintenance recipient rules remain bounded by machine-role scope."""

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.rbac import Action
from apps.integrations.models_recipients import (
    NotificationRecipient,
    NotificationRecipientKind,
)
from apps.inventory.models import Category
from apps.machines.models import Machine, MachineType
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole
from apps.admin_api import views_recipient_rules
from apps.makerspaces.roles import ensure_default_roles

pytestmark = pytest.mark.django_db

SWITCH = "notifications.delegated_recipients"


def make_space(slug, *, delegated=False):
    space = Makerspace.objects.create(name=slug, slug=slug)
    ensure_default_roles(space)
    space.enabled_modules = sorted(
        set(space.enabled_modules) | {"machines", "maintenance", "notifications"}
    )
    if delegated:
        space.enabled_features = [*space.enabled_features, SWITCH]
    space.save(update_fields=["enabled_modules", "enabled_features"])
    return space


def make_type(space, slug):
    return MachineType.objects.create(makerspace=space, name=slug.title(), slug=slug)


def make_actor(space, machine_type, username="delegated-maintainer"):
    role = MakerspaceRole.objects.create(
        makerspace=space,
        name="Laser Maintainers",
        slug=f"laser-maintainers-{space.pk}",
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


def make_manager(space, username="delegated-space-manager"):
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


def scoped_rule(kind, machine_type, **target):
    return {
        "kind": kind,
        **target,
        "scope": {"machine_type_ids": [machine_type.pk]},
    }


def test_switch_off_keeps_the_delegated_surface_invisible():
    space = make_space("delegated-off")
    laser_type = make_type(space, "delegated-off-laser")
    actor, _ = make_actor(space, laser_type)
    client = client_for(actor)

    assert client.get(url(space)).status_code in (403, 404)
    response = client.put(
        url(space),
        {
            "feature": "maintenance",
            "event": "logged",
            "rules": [scoped_rule("members", laser_type)],
        },
        format="json",
    )
    assert response.status_code in (403, 404)
    assert NotificationRecipient.objects.filter(makerspace=space).exists() is False


def test_switch_on_allows_only_own_scoped_maintenance_rules():
    space = make_space("delegated-on", delegated=True)
    laser_type = make_type(space, "delegated-on-laser")
    printer_type = make_type(space, "delegated-on-printer")
    actor, role = make_actor(space, laser_type)
    client = client_for(actor)

    initial = client.get(url(space))
    assert initial.status_code == 200
    assert initial.data["delegated"] is True
    assert [item["key"] for item in initial.data["features"]] == ["maintenance"]
    assert initial.data["scope_options"]["machine_types"] == [
        {"id": laser_type.pk, "name": laser_type.name}
    ]
    assert printer_type.pk not in {
        row["id"] for row in initial.data["scope_options"]["machine_types"]
    }

    saved = client.put(
        url(space),
        {
            "feature": "maintenance",
            "event": "logged",
            "rules": [scoped_rule("role", laser_type, role_id=role.pk)],
        },
        format="json",
    )
    assert saved.status_code == 200
    assert saved.data["rules"][0]["role_id"] == role.pk
    assert saved.data["rules"][0]["scope"]["machine_type_ids"] == [laser_type.pk]

    refused = client.put(
        url(space),
        {"feature": "bookings", "event": "created", "rules": []},
        format="json",
    )
    assert refused.status_code == 403


def test_space_manager_authority_is_unchanged_when_the_switch_is_off():
    space = make_space("delegated-manager-off")
    manager = make_manager(space)
    client = client_for(manager)

    payload = client.get(url(space))
    assert payload.status_code == 200
    assert payload.data["delegated"] is False
    assert "bookings" in {feature["key"] for feature in payload.data["features"]}
    saved = client.put(
        url(space),
        {"feature": "bookings", "event": "created", "rules": []},
        format="json",
    )
    assert saved.status_code == 200


def test_unreachable_and_foreign_targets_are_atomic_400s():
    space = make_space("delegated-targets", delegated=True)
    other = make_space("delegated-targets-other", delegated=True)
    laser_type = make_type(space, "delegated-targets-laser")
    printer_type = make_type(space, "delegated-targets-printer")
    foreign_type = make_type(other, "delegated-targets-foreign")
    laser = Machine.objects.create(
        makerspace=space, machine_type=laser_type, name="Laser"
    )
    printer = Machine.objects.create(
        makerspace=space, machine_type=printer_type, name="Printer"
    )
    foreign_machine = Machine.objects.create(
        makerspace=other, machine_type=foreign_type, name="Foreign"
    )
    category = Category.objects.create(makerspace=space, name="Parts", slug="parts")
    foreign_category = Category.objects.create(
        makerspace=other, name="Foreign", slug="foreign"
    )
    actor, role = make_actor(space, laser_type)
    original = NotificationRecipient.objects.create(
        makerspace=space,
        feature="maintenance",
        event="logged",
        kind=NotificationRecipientKind.ROLE,
        role=role,
    )
    original.machine_scopes.create(machine=laser)
    client = client_for(actor)

    invalid_scopes = [
        {"machine_type_ids": [printer_type.pk]},
        {"machine_type_ids": [foreign_type.pk]},
        {"machine_ids": [printer.pk]},
        {"machine_ids": [foreign_machine.pk]},
        {"category_ids": [category.pk]},
        {"category_ids": [foreign_category.pk]},
    ]
    for scope in invalid_scopes:
        response = client.put(
            url(space),
            {
                "feature": "maintenance",
                "event": "logged",
                "rules": [{"kind": "members", "scope": scope}],
            },
            format="json",
        )
        assert response.status_code == 400
        assert NotificationRecipient.objects.filter(pk=original.pk).exists() is True
        assert NotificationRecipient.objects.filter(makerspace=space).count() == 1


def test_delegated_rules_require_scope_and_full_multi_type_coverage():
    space = make_space("delegated-required-scope", delegated=True)
    laser_type = make_type(space, "delegated-required-laser")
    printer_type = make_type(space, "delegated-required-printer")
    actor, _ = make_actor(space, laser_type)
    client = client_for(actor)

    unscoped = client.put(
        url(space),
        {
            "feature": "maintenance",
            "event": "logged",
            "rules": [{"kind": "members"}],
        },
        format="json",
    )
    assert unscoped.status_code == 400

    partial = client.put(
        url(space),
        {
            "feature": "maintenance",
            "event": "logged",
            "rules": [
                {
                    "kind": "members",
                    "scope": {
                        "machine_type_ids": [laser_type.pk, printer_type.pk]
                    },
                }
            ],
        },
        format="json",
    )
    assert partial.status_code == 400
    assert NotificationRecipient.objects.filter(makerspace=space).exists() is False


def test_the_partition_is_resolved_inside_the_write_transaction():
    """Resolving it in the view was a read-then-write race.

    Two concurrent PUTs would both materialize the existing rows; the second commits, and
    the first then deletes a set that no longer describes the table — leaving a union of
    both submissions or tripping the recipient uniqueness constraint. Asserted as an
    observable (`in_atomic_block` while the predicate runs) rather than by reading the
    source, since only the former fails if the resolution moves back out.
    """
    from django.db import transaction

    space = make_space("delegated-lock", delegated=True)
    lasers = make_type(space, "lock-laser")
    actor, role = make_actor(space, lasers, username="lock-maintainer")
    # An existing row gives `keep_row` something to be called about.
    scoped = NotificationRecipient.objects.create(
        makerspace=space, feature="maintenance", event="logged",
        kind="role", role_id=role.pk,
    )
    scoped.machine_type_scopes.create(machine_type=lasers)

    # Patched on the VIEW module, not on `recipient_rule_common`: the view `from`-imports
    # the name, so it holds its own binding and patching the source module would leave the
    # spy uncalled and this test vacuously green.
    seen = []
    original = views_recipient_rules.row_fully_reachable

    # `**kwargs` so the spy tracks `row_fully_reachable`'s signature: it gained a
    # `manageable_identity` keyword, and a fixed (row, reach) spy raises TypeError rather
    # than reporting what this test is actually about.
    def spy(row, reach, **kwargs):
        seen.append(transaction.get_connection().in_atomic_block)
        return original(row, reach, **kwargs)

    views_recipient_rules.row_fully_reachable = spy
    try:
        response = client_for(actor).put(
            url(space),
            {
                "feature": "maintenance",
                "event": "logged",
                "rules": [scoped_rule("role", lasers, role_id=role.pk)],
            },
            format="json",
        )
    finally:
        views_recipient_rules.row_fully_reachable = original

    assert response.status_code == 200
    assert seen, "the partition predicate was never consulted"
    assert all(seen), "the partition was resolved outside the write transaction"


def test_a_delegated_actor_may_only_name_identities_the_picker_offers():
    """Accepting identities the editor never presents is the inverse of a 403-on-click.

    The console offers a delegated actor their own role and the teammates holding it, so the
    API must refuse anything else — otherwise a narrow grant can point another team's
    maintenance alerts at an arbitrary colleague, or at a role it does not hold.
    """
    space = make_space("delegated-identities", delegated=True)
    lasers = make_type(space, "identities-laser")
    actor, own_role = make_actor(space, lasers, username="identities-maintainer")
    manager = make_manager(space, username="identities-manager")
    other_role = MakerspaceRole.objects.get(makerspace=space, slug="space_manager")
    client = client_for(actor)

    foreign_role = client.put(
        url(space),
        {
            "feature": "maintenance",
            "event": "logged",
            "rules": [scoped_rule("role", lasers, role_id=other_role.pk)],
        },
        format="json",
    )
    foreign_user = client.put(
        url(space),
        {
            "feature": "maintenance",
            "event": "logged",
            "rules": [scoped_rule("user", lasers, user_id=manager.pk)],
        },
        format="json",
    )
    own = client.put(
        url(space),
        {
            "feature": "maintenance",
            "event": "logged",
            "rules": [scoped_rule("role", lasers, role_id=own_role.pk)],
        },
        format="json",
    )

    assert foreign_role.status_code == 400
    assert foreign_user.status_code == 400
    assert own.status_code == 200
    # Only the permitted write landed.
    assert list(
        NotificationRecipient.objects.filter(makerspace=space).values_list(
            "role_id", "user_id"
        )
    ) == [(own_role.pk, None)]


def test_delegated_put_preserves_unowned_rows_and_replaces_its_partition():
    space = make_space("delegated-partition", delegated=True)
    laser_type = make_type(space, "delegated-partition-laser")
    printer_type = make_type(space, "delegated-partition-printer")
    actor, role = make_actor(space, laser_type)
    manager = make_manager(space, "delegated-partition-manager")
    spacewide = NotificationRecipient.objects.create(
        makerspace=space,
        feature="maintenance",
        event="logged",
        kind=NotificationRecipientKind.MEMBERS,
    )
    other_team = NotificationRecipient.objects.create(
        makerspace=space,
        feature="maintenance",
        event="logged",
        kind=NotificationRecipientKind.USER,
        user=manager,
    )
    other_team.machine_type_scopes.create(machine_type=laser_type)
    other_team.machine_type_scopes.create(machine_type=printer_type)
    owned = NotificationRecipient.objects.create(
        makerspace=space,
        feature="maintenance",
        event="logged",
        kind=NotificationRecipientKind.ROLE,
        role=role,
    )
    owned.machine_type_scopes.create(machine_type=laser_type)

    response = client_for(actor).put(
        url(space),
        {
            "feature": "maintenance",
            "event": "logged",
            "rules": [scoped_rule("requester", laser_type)],
        },
        format="json",
    )

    assert response.status_code == 200
    assert NotificationRecipient.objects.filter(pk=spacewide.pk).exists() is True
    assert NotificationRecipient.objects.filter(pk=other_team.pk).exists() is True
    assert NotificationRecipient.objects.filter(pk=owned.pk).exists() is False
    assert NotificationRecipient.objects.filter(
        makerspace=space, kind=NotificationRecipientKind.REQUESTER
    ).exists() is True


def test_hidden_policies_are_redacted_without_identity_leakage():
    space = make_space("delegated-redaction", delegated=True)
    laser_type = make_type(space, "delegated-redaction-laser")
    actor, _ = make_actor(space, laser_type, "delegated-redaction-actor")
    manager = make_manager(space, "secret-space-manager")
    manager_role = MakerspaceRole.objects.get(makerspace=space, slug="space_manager")
    hidden = NotificationRecipient.objects.create(
        makerspace=space,
        feature="maintenance",
        event="logged",
        kind=NotificationRecipientKind.ROLE,
        role=manager_role,
        created_by=manager,
    )
    assert hidden.machine_type_scopes.exists() is False

    response = client_for(actor).get(url(space))

    assert response.status_code == 200
    assert response.data["rules"] == []
    assert response.data["managed_policy_markers"] == [
        {"feature": "maintenance", "event": "logged", "count": 1}
    ]
    assert manager_role.pk not in {role["id"] for role in response.data["roles"]}
    assert manager.pk not in {member["id"] for member in response.data["members"]}
    body = str(response.data)
    assert manager.username not in body
    assert manager.email not in body
    assert manager_role.name not in body
