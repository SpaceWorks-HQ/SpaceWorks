import pytest
from django.test import RequestFactory

from apps.accounts import rbac
from apps.accounts.org_payload import organization_makerspace_entries
from apps.accounts.serializers import user_payload
from apps.accounts.services_social_identity import SocialResolutionError
from apps.accounts.services_social_login import assert_staff_authority
from apps.machines import access as machine_access
from apps.machines.models import Machine, MachineType
from apps.makerspaces.models import Makerspace
from apps.organizations.admin import OrganizationMembershipForm
from tests.organizations.test_org_authority import (
    grant,
    link,
    make_makerspace,
    make_organization,
    make_user,
)


pytestmark = pytest.mark.django_db


def _org_actor(slug, actions):
    actor = make_user(f"{slug}-actor")
    makerspace = make_makerspace(f"{slug}-space")
    organization = make_organization(f"{slug}-org")
    link(organization, makerspace, "manager")
    membership = grant(organization, actor, actions)
    return actor, makerspace, organization, membership


def test_raw_manage_machines_grant_is_rejected_before_implication_everywhere():
    actor, makerspace, _organization, membership = _org_actor(
        "raw-machine", [rbac.Action.MANAGE_MACHINES]
    )

    assert rbac.actions_for_organization_membership(membership) == set()
    assert rbac.effective_actions(actor, makerspace.id) == set()
    assert not rbac.has_any_org_authority(actor)
    for action in (
        rbac.Action.MANAGE_MACHINES,
        rbac.Action.MANAGE_PRINTING,
        rbac.Action.COLLECT_SERVICE_REQUEST,
    ):
        assert not rbac.can(actor, action, makerspace.id)
        assert rbac.makerspaces_for_action(actor, action) == set()
        assert not rbac.scope_by_action(
            actor, action, Makerspace.objects.all(), field="id"
        ).exists()
    assert organization_makerspace_entries(actor) == {}
    assert user_payload(actor)["makerspaces"] == []
    with pytest.raises(SocialResolutionError):
        assert_staff_authority(actor, RequestFactory().get("/"))


def test_org_manage_printing_is_not_machine_or_type_manager_authority():
    actor, makerspace, _organization, _membership = _org_actor(
        "org-printing", [rbac.Action.MANAGE_PRINTING]
    )
    machine_type = MachineType.objects.create(
        slug="org-printing-type",
        name="Organization printing type",
        is_builtin=True,
        managing_action=rbac.Action.MANAGE_PRINTING,
    )
    machine = Machine.objects.create(
        makerspace=makerspace,
        machine_type=machine_type,
        name="Organization printer",
    )

    assert rbac.can(actor, rbac.Action.MANAGE_PRINTING, makerspace.id)
    assert not machine_access.can_create_machine(actor, makerspace.id, machine_type)
    assert not machine_access.can_manage_machine(actor, machine)
    assert not machine_access.scope_manageable_machines_for_actor(
        actor, Machine.objects.all()
    ).exists()


def test_admin_form_remains_a_second_layer_against_manage_machines():
    actor = make_user("machine-form-actor")
    organization = make_organization("machine-form-org")
    form = OrganizationMembershipForm(
        data={
            "organization": organization.pk,
            "user": actor.pk,
            "status": "active",
            "granted_actions": [rbac.Action.MANAGE_MACHINES],
        }
    )

    assert not form.is_valid()
    assert "granted_actions" in form.errors
