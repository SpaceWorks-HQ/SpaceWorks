from importlib import import_module

import pytest
from django.apps import apps
from django.db import connection

from apps.accounts import rbac
from apps.makerspaces.models import MakerspaceMembership, MakerspaceRole
from apps.makerspaces.roles import ensure_default_roles
from tests.return_helpers import make_member, make_space

pytestmark = pytest.mark.django_db
NEW = {rbac.Action.MANAGE_MEMBERS, rbac.Action.VIEW_FINANCE, rbac.Action.RECORD_PAYMENT}


def test_backfill_is_additive_idempotent_and_covers_custom_admin_roles():
    space = make_space("f6-backfill")
    manager_role = MakerspaceRole.objects.get(makerspace=space, slug="space_manager")
    manager_role.granted_actions = [rbac.Action.MANAGE_MAKERSPACE, rbac.Action.VIEW_AUDIT]
    manager_role.save(update_fields=["granted_actions"])
    custom = MakerspaceRole.objects.create(
        makerspace=space, name="Admin", slug="admin", granted_actions=["manage_makerspace"],
    )
    inventory = MakerspaceRole.objects.get(makerspace=space, slug="inventory_manager")
    before = list(inventory.granted_actions)
    migration = import_module("apps.makerspaces.migrations.0078_member_finance_actions")
    assert ("makerspaces", "0077_makerspace_location_profile") in migration.Migration.dependencies
    assert ("organizations", "0003_organization_presentation_and_governance") in migration.Migration.dependencies
    for _ in range(2):
        migration.forwards(apps, connection.schema_editor())
    manager_role.refresh_from_db()
    custom.refresh_from_db()
    inventory.refresh_from_db()
    assert set(manager_role.granted_actions) == NEW | {"manage_makerspace", "view_audit"}
    assert set(custom.granted_actions) == NEW | {"manage_makerspace"}
    assert inventory.granted_actions == before


def test_new_and_legacy_space_manager_keep_all_three_actions():
    space = make_space("f6-defaults")
    ensure_default_roles(space)
    assert MakerspaceRole.objects.filter(makerspace=space, is_protected=True).count() == 4
    assert NEW <= set(MakerspaceRole.objects.get(makerspace=space, slug="space_manager").granted_actions)
    actor = make_member("f6-legacy", space)
    membership = actor.makerspace_memberships.get(makerspace=space)
    MakerspaceMembership.objects.filter(pk=membership.pk).update(assigned_role=None)
    membership.refresh_from_db()
    assert NEW <= rbac.actions_for_membership(membership)
    assert rbac.Action.MANAGE_MEMBER_CARDS in rbac.expand_implied_actions({"manage_members"})
    assert "manage_members" not in rbac.expand_implied_actions({"manage_makerspace"})


def test_role_editor_catalog_exposes_plain_descriptions_for_new_actions():
    from tests.return_helpers import authenticated_client
    space = make_space("f6-catalog")
    manager = make_member("f6-catalog-manager", space)
    response = authenticated_client(manager).get(f"/api/v1/admin/makerspaces/{space.pk}/roles/capabilities")
    assert response.status_code == 200
    catalog = {row["value"]: row for row in response.data}
    for action in NEW:
        assert catalog[action]["grantable"] is True
        assert catalog[action]["description"]


def test_organization_admin_backfill_preserves_actions_without_widening_reach():
    from apps.organizations.models import Organization, OrganizationMakerspace, OrganizationMembership
    from tests.return_helpers import make_user

    space = make_space("f6-org-owned")
    other = make_space("f6-org-unlinked")
    hidden = make_space("f6-org-hidden")
    type(space).objects.filter(pk=hidden.pk).update(superadmin_access_enabled=False)
    organization = Organization.objects.create(name="Parent", slug="f6-parent")
    for linked in [space, hidden]:
        OrganizationMakerspace.objects.create(organization=organization, makerspace=linked, relationship="owner")
    actor = make_user("f6-org-admin", access_status="active")
    grant = OrganizationMembership.objects.create(
        organization=organization, user=actor, granted_actions=["manage_makerspace"],
    )
    migration = import_module("apps.makerspaces.migrations.0078_member_finance_actions")
    migration.forwards(apps, connection.schema_editor())
    grant.refresh_from_db()
    assert NEW <= set(grant.granted_actions)
    for action in NEW:
        assert rbac.can(actor, action, space.pk)
        assert not rbac.can(actor, action, other.pk)
        assert not rbac.can(actor, action, hidden.pk)
