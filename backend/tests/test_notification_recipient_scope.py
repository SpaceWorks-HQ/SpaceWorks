"""Object scoping on recipient rules (Notifications v2, N4).

Composition is `role_scope AND (rule_scope OR all)` — it can only ever NARROW. The two
halves fail in opposite directions on purpose and this file pins both: an unscoped *rule*
matches everything (an operator who did not narrow it), while an unscoped machine-managing
*role* reaches nothing (access fails closed). Getting either backwards is either a silent
mute or an alert about hardware the recipient would 403 on.
"""

import pytest
from django.contrib.auth import get_user_model

from apps.accounts.models import User
from apps.accounts.rbac import Action
from apps.integrations.destinations import NotificationScope
from apps.integrations.models_recipients import (
    NotificationRecipient,
    NotificationRecipientKind,
)
from apps.integrations.staff_notifications import staff_emails_for_feature
from apps.machines.models import Machine, MachineType
from apps.machines.role_scope import grant_builtin_type_scope  # noqa: F401  (import guard)
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole
from apps.makerspaces.roles import ensure_default_roles

pytestmark = pytest.mark.django_db


def make_space(slug):
    space = Makerspace.objects.create(name=slug, slug=slug)
    ensure_default_roles(space)
    return space


def make_machine(space, name):
    machine_type = MachineType.objects.create(
        makerspace=space, name=f"{name}-type", slug=f"{space.slug}-{name}-type"
    )
    return Machine.objects.create(makerspace=space, machine_type=machine_type, name=name)


def make_role(space, slug, actions):
    return MakerspaceRole.objects.create(
        makerspace=space, name=slug.title(), slug=slug, granted_actions=sorted(actions)
    )


def make_member(username, space, role):
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
    return user


def select_role(space, role, event="logged", feature="maintenance"):
    return NotificationRecipient.objects.create(
        makerspace=space,
        feature=feature,
        event=event,
        kind=NotificationRecipientKind.ROLE,
        role=role,
    )


def emails(space, machine, event="logged"):
    return staff_emails_for_feature(
        space, "maintenance", event=event, scope=NotificationScope(machine=machine)
    )


# --- rule scope: no links means everything -------------------------------------------


def test_an_unnarrowed_rule_matches_every_subject():
    space = make_space("rulescope-open")
    laser = make_machine(space, "laser")
    printer = make_machine(space, "printer")
    role = make_role(space, "machine-team", [Action.MANAGE_MACHINES])
    role.machine_type_scopes.create(machine_type=laser.machine_type)
    role.machine_type_scopes.create(machine_type=printer.machine_type)
    member = make_member("rulescope-open-member", space, role)
    select_role(space, role)

    assert emails(space, laser) == [member.email]
    assert emails(space, printer) == [member.email]


def test_a_narrowed_rule_only_matches_what_it_names():
    space = make_space("rulescope-narrow")
    laser = make_machine(space, "laser")
    printer = make_machine(space, "printer")
    role = make_role(space, "machine-team", [Action.MANAGE_MACHINES])
    role.machine_type_scopes.create(machine_type=laser.machine_type)
    role.machine_type_scopes.create(machine_type=printer.machine_type)
    member = make_member("rulescope-narrow-member", space, role)
    rule = select_role(space, role)
    rule.machine_scopes.create(machine=laser)

    assert emails(space, laser) == [member.email]
    assert emails(space, printer) == []


def test_rule_narrowing_is_a_union_of_machine_type_and_machine():
    space = make_space("rulescope-union")
    laser = make_machine(space, "laser")
    printer_a = make_machine(space, "printer-a")
    printer_b = make_machine(space, "printer-b")
    role = make_role(space, "machine-team", [Action.MANAGE_MAKERSPACE, Action.MANAGE_MACHINES])
    member = make_member("rulescope-union-member", space, role)
    rule = select_role(space, role)
    rule.machine_type_scopes.create(machine_type=printer_a.machine_type)
    rule.machine_scopes.create(machine=laser)

    assert emails(space, laser) == [member.email]
    assert emails(space, printer_a) == [member.email]
    assert emails(space, printer_b) == []


def test_a_narrowed_rule_matches_nothing_when_the_alert_names_no_subject():
    space = make_space("rulescope-no-subject")
    laser = make_machine(space, "laser")
    role = make_role(space, "machine-team", [Action.MANAGE_MAKERSPACE])
    make_member("rulescope-no-subject-member", space, role)
    rule = select_role(space, role)
    rule.machine_scopes.create(machine=laser)

    assert staff_emails_for_feature(space, "maintenance", event="logged") == []


# --- role scope is the floor, and it can only narrow ---------------------------------


def test_a_rule_naming_a_machine_outside_the_roles_scope_yields_nobody():
    """The composition's whole point: never alert about hardware they would 403 on."""
    space = make_space("rolescope-floor")
    laser = make_machine(space, "laser")
    printer = make_machine(space, "printer")
    role = make_role(space, "laser-team", [Action.MANAGE_MACHINES])
    role.machine_type_scopes.create(machine_type=laser.machine_type)
    make_member("rolescope-floor-member", space, role)
    rule = select_role(space, role)
    # The operator narrowed the rule to the printer, which this role cannot reach.
    rule.machine_scopes.create(machine=printer)

    assert emails(space, printer) == []
    assert emails(space, laser) == []


def test_the_role_floor_applies_even_with_no_rule_narrowing():
    space = make_space("rolescope-floor-open-rule")
    laser = make_machine(space, "laser")
    printer = make_machine(space, "printer")
    role = make_role(space, "laser-team", [Action.MANAGE_MACHINES])
    role.machine_type_scopes.create(machine_type=laser.machine_type)
    member = make_member("rolescope-floor-open-member", space, role)
    select_role(space, role)

    assert emails(space, laser) == [member.email]
    assert emails(space, printer) == []


def test_a_space_manager_role_is_exempt_from_the_floor():
    space = make_space("rolescope-exempt")
    printer = make_machine(space, "printer")
    role = MakerspaceRole.objects.get(makerspace=space, slug="space_manager")
    member = make_member("rolescope-exempt-member", space, role)
    select_role(space, role)

    # A space manager covers every machine, including types created later — making them
    # enumerate types to administer their own lab is the worse failure.
    assert emails(space, printer) == [member.email]


def test_a_legacy_membership_with_no_assigned_role_is_not_stripped():
    space = make_space("rolescope-legacy")
    printer = make_machine(space, "printer")
    role = make_role(space, "machine-team", [Action.MANAGE_MACHINES])
    role.machine_type_scopes.create(machine_type=printer.machine_type)
    legacy = get_user_model().objects.create_user(
        username="rolescope-legacy-member",
        email="rolescope-legacy-member@e.com",
        role=User.Role.REQUESTER,
        access_status=User.AccessStatus.ACTIVE,
    )
    membership = MakerspaceMembership.objects.create(
        user=legacy,
        makerspace=space,
        role=MakerspaceMembership.Role.MACHINE_MANAGER,
        assigned_role=role,
    )
    # A null assigned_role resolves through the frozen legacy fallback, which is not a
    # role row and has nothing to link — scoping it would silently strip the membership.
    MakerspaceMembership.objects.filter(pk=membership.pk).update(assigned_role=None)
    select_role(space, role)

    # The rule names the role, and this membership no longer holds it, so it is not
    # selected at all — the floor is not what excluded them.
    assert emails(space, printer) == []


# --- the floor applies to ROLE rows only ---------------------------------------------


def test_the_member_body_is_not_filtered_by_machine_authority():
    """A plain member holds no machine grant; the fail-closed floor would mute them all."""
    space = make_space("rolescope-members")
    printer = make_machine(space, "printer")
    member_role = MakerspaceRole.objects.get(makerspace=space, slug="member")
    member = make_member("rolescope-members-member", space, member_role)
    NotificationRecipient.objects.create(
        makerspace=space,
        feature="maintenance",
        event="logged",
        kind=NotificationRecipientKind.MEMBERS,
    )

    assert emails(space, printer) == [member.email]


def test_a_named_individual_is_not_filtered_by_machine_authority():
    space = make_space("rolescope-named")
    printer = make_machine(space, "printer")
    member_role = MakerspaceRole.objects.get(makerspace=space, slug="member")
    named = make_member("rolescope-named-member", space, member_role)
    NotificationRecipient.objects.create(
        makerspace=space,
        feature="maintenance",
        event="logged",
        kind=NotificationRecipientKind.USER,
        user=named,
    )

    # Selected as a PERSON, not as an authority: an operator naming the workshop lead
    # meant them, and a machine-authority floor would make the kind unusable here.
    assert emails(space, printer) == [named.email]


def test_a_named_individual_is_still_narrowed_by_the_rule():
    space = make_space("rolescope-named-narrow")
    laser = make_machine(space, "laser")
    printer = make_machine(space, "printer")
    member_role = MakerspaceRole.objects.get(makerspace=space, slug="member")
    named = make_member("rolescope-named-narrow-member", space, member_role)
    rule = NotificationRecipient.objects.create(
        makerspace=space,
        feature="maintenance",
        event="logged",
        kind=NotificationRecipientKind.USER,
        user=named,
    )
    rule.machine_scopes.create(machine=laser)

    assert emails(space, laser) == [named.email]
    assert emails(space, printer) == []


# --- features with no subject are unaffected -----------------------------------------


def test_scoping_does_not_disturb_a_feature_that_names_no_machine():
    space = make_space("rolescope-events")
    role = make_role(space, "events-team", [Action.MANAGE_EVENTS])
    member = make_member("rolescope-events-member", space, role)
    select_role(space, role, event="published", feature="events")

    # Events carry no machine, so neither half of the composition applies and the
    # selection resolves exactly as it did before N4.
    assert staff_emails_for_feature(space, "events", event="published") == [member.email]
