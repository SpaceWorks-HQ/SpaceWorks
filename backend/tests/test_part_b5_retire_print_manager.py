"""Part B5 ??? retire the default Print Manager role without breaking printing."""
from importlib import import_module
from types import SimpleNamespace

import pytest
from django.apps import apps as django_apps
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from apps.accounts import rbac
from apps.accounts.models import User
from apps.integrations.models import EmailNotificationMute
from apps.makerspaces.models import MakerspaceMembership, MakerspaceRole
from tests.return_helpers import authenticated_client, make_member, make_space, make_user


pytestmark = pytest.mark.django_db


def _default_role(makerspace, legacy_role):
    return MakerspaceRole.objects.get(makerspace=makerspace, legacy_role=legacy_role)


def test_machine_manager_implies_printing_for_actions_scopes_and_permission():
    makerspace = make_space("b5-machine-scope")
    actor = make_member(
        "b5-machine-scope-user", makerspace,
        membership_role=MakerspaceMembership.Role.MACHINE_MANAGER,
        role=User.Role.REQUESTER,
    )
    membership = MakerspaceMembership.objects.get(user=actor, makerspace=makerspace)
    membership.assigned_role = _default_role(
        makerspace, MakerspaceMembership.Role.MACHINE_MANAGER
    )
    membership.save(update_fields=["assigned_role"])

    assert rbac.actions_satisfying(rbac.Action.MANAGE_PRINTING) == frozenset({
        rbac.Action.MANAGE_PRINTING, rbac.Action.MANAGE_MACHINES,
    })
    assert rbac.can(actor, rbac.Action.MANAGE_PRINTING, makerspace.id)
    assert rbac.effective_actions(actor, makerspace.id) == {
        rbac.Action.MANAGE_MACHINES, rbac.Action.MANAGE_PRINTING,
        # Also implied by MANAGE_MACHINES, so job handover comes with the machines.
        rbac.Action.COLLECT_SERVICE_REQUEST,
    }
    assert rbac.makerspaces_for_action(actor, rbac.Action.MANAGE_PRINTING) == {makerspace.id}



def test_hidden_superadmin_membership_uses_machine_implied_printing_scope():
    makerspace = make_space("b5-hidden-machine")
    makerspace.superadmin_access_enabled = False
    makerspace.save(update_fields=["superadmin_access_enabled"])
    superadmin = make_user(
        "b5-hidden-superadmin", role=User.Role.SUPERADMIN,
        access_status=User.AccessStatus.ACTIVE,
    )
    MakerspaceMembership.objects.create(
        user=superadmin, makerspace=makerspace,
        role=MakerspaceMembership.Role.MACHINE_MANAGER,
        assigned_role=_default_role(makerspace, MakerspaceMembership.Role.MACHINE_MANAGER),
    )

    assert rbac._superadmin_hidden_to_exclude(
        superadmin, rbac.Action.MANAGE_PRINTING
    ) == set()
    assert rbac.can(superadmin, rbac.Action.MANAGE_PRINTING, makerspace.id)


def test_retirement_migration_moves_only_protected_default_memberships():
    makerspace = make_space("b5-migrate-memberships")
    machine_role = _default_role(makerspace, MakerspaceMembership.Role.MACHINE_MANAGER)
    retired_role = MakerspaceRole.objects.create(
        makerspace=makerspace, name="Print Manager", slug="print-manager",
        legacy_role=MakerspaceMembership.Role.PRINT_MANAGER,
        granted_actions=[rbac.Action.MANAGE_PRINTING], is_default=True, is_protected=True,
    )
    assigned = MakerspaceMembership.objects.create(
        user=make_user("b5-migrated-default", access_status=User.AccessStatus.ACTIVE),
        makerspace=makerspace, role=MakerspaceMembership.Role.PRINT_MANAGER,
        assigned_role=retired_role,
    )
    unassigned = MakerspaceMembership.objects.create(
        user=make_user("b5-migrated-unassigned", access_status=User.AccessStatus.ACTIVE),
        makerspace=makerspace, role=MakerspaceMembership.Role.PRINT_MANAGER,
    )
    custom_role = MakerspaceRole.objects.create(
        makerspace=makerspace, name="Printer type only", slug="printer-type-only",
        granted_actions=[rbac.Action.MANAGE_PRINTING],
    )
    custom = MakerspaceMembership.objects.create(
        user=make_user("b5-custom-printer", access_status=User.AccessStatus.ACTIVE),
        makerspace=makerspace, role=MakerspaceMembership.Role.CUSTOM, assigned_role=custom_role,
    )

    migration = import_module("apps.makerspaces.migrations.0046_retire_print_manager")
    migration.migrate_print_manager_memberships(django_apps, None)
    migration.migrate_print_manager_memberships(django_apps, None)

    assigned.refresh_from_db()
    unassigned.refresh_from_db()
    custom.refresh_from_db()
    assert assigned.assigned_role_id == machine_role.id
    assert assigned.role == MakerspaceMembership.Role.MACHINE_MANAGER
    assert unassigned.assigned_role_id is None
    assert unassigned.role == MakerspaceMembership.Role.MACHINE_MANAGER
    assert custom.assigned_role_id == custom_role.id
    assert custom.role == MakerspaceMembership.Role.CUSTOM
    assert rbac.effective_actions(custom.user, makerspace.id) == {rbac.Action.MANAGE_PRINTING}
    assert not rbac.can(custom.user, rbac.Action.MANAGE_MACHINES, makerspace.id)


def test_unassigned_legacy_print_manager_still_resolves_and_mutes_are_retargeted():
    makerspace = make_space("b5-legacy-and-mutes")
    legacy = make_member(
        "b5-legacy-printer", makerspace,
        membership_role=MakerspaceMembership.Role.PRINT_MANAGER, role=User.Role.REQUESTER,
    )
    assert rbac.can(legacy, rbac.Action.MANAGE_PRINTING, makerspace.id)

    mute = EmailNotificationMute.objects.create(
        makerspace=makerspace, target="print_manager", stream="printing",
        event="accepted", audience="staff",
    )
    migration = import_module(
        "apps.integrations.migrations.0014_retire_print_manager_notification_targets"
    )
    migration.retarget_print_manager_mutes(django_apps, None)
    mute.refresh_from_db()
    assert mute.target == "machine_manager"


