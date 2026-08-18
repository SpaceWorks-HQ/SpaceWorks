import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.machines import access
from apps.machines.models import (
    Machine,
    MachineOperator,
    MachineServiceRequest,
    MachineType,
)
from tests.handout_roles import make_handout_member
from tests.return_helpers import authenticated_client, make_member, make_space

pytestmark = pytest.mark.django_db


def _machine(space, slug):
    space.enabled_modules = sorted(set(space.enabled_modules or []) | {"machines"})
    space.save(update_fields=["enabled_modules"])
    machine_type = MachineType.objects.create(
        makerspace=space,
        slug=slug,
        name=f"{slug} type",
    )
    return Machine.objects.create(
        makerspace=space,
        machine_type=machine_type,
        name=f"{slug} machine",
    )


def _revoke(user, space):
    user.makerspace_memberships.filter(makerspace=space).update(status="revoked")


def test_revoked_member_with_stale_operator_cannot_read_private_machine_surfaces():
    space = make_space("p4-revoked-operator")
    operator = make_handout_member("p4-revoked-operator-user", space)
    machine = _machine(space, "p4-revoked-operator")
    MachineOperator.objects.create(
        machine=machine,
        user=operator,
        access_level=MachineOperator.AccessLevel.MANAGE,
    )
    _revoke(operator, space)
    client = authenticated_client(operator)

    responses = [
        client.get(reverse("admin-machine-detail", kwargs={"pk": machine.pk})),
        client.get(reverse("admin-machine-usage", kwargs={"pk": machine.pk})),
        client.get(reverse("admin-machine-error-logs", kwargs={"pk": machine.pk})),
    ]

    assert [response.status_code for response in responses] == [404, 404, 404]
    assert not access.scope_machines_for_actor(
        operator, Machine.objects.filter(pk=machine.pk)
    ).exists()
    assert not access.scope_manageable_machines_for_actor(
        operator, Machine.objects.filter(pk=machine.pk)
    ).exists()


def test_revoked_member_is_not_an_operator_candidate():
    space = make_space("p4-revoked-candidate")
    manager = make_member("p4-revoked-candidate-manager", space)
    active = make_handout_member("p4-active-candidate", space)
    revoked = make_handout_member("p4-revoked-candidate-user", space)
    machine = _machine(space, "p4-revoked-candidate")
    _revoke(revoked, space)

    response = authenticated_client(manager).get(
        reverse("admin-machine-operator-candidates", kwargs={"pk": machine.pk})
    )

    assert response.status_code == 200
    candidate_ids = {row["user_id"] for row in response.data}
    assert active.pk in candidate_ids
    assert revoked.pk not in candidate_ids


@pytest.mark.parametrize(
    ("membership_status", "access_status"),
    [
        ("revoked", User.AccessStatus.ACTIVE),
        ("active", User.AccessStatus.RESTRICTED),
    ],
)
def test_ineligible_member_is_not_accepted_as_service_requester(
    membership_status, access_status
):
    suffix = f"{membership_status}-{access_status}"
    space = make_space(f"p4-service-{suffix}")
    manager = make_member(f"p4-service-manager-{suffix}", space)
    requester = make_member(f"p4-service-requester-{suffix}", space)
    requester.email = f"former-{suffix}@example.test"
    requester.phone = "+1 555 0100"
    requester.access_status = access_status
    requester.save(update_fields=["email", "phone", "access_status"])
    requester.makerspace_memberships.filter(makerspace=space).update(
        status=membership_status
    )
    machine = _machine(space, f"p4-service-{suffix}")

    response = authenticated_client(manager).post(
        reverse(
            "admin-machine-service-request-list-create",
            kwargs={"makerspace_id": space.pk},
        ),
        {
            "requester_id": requester.pk,
            "machine_id": machine.pk,
            "title": "Must not copy ineligible member contact details",
        },
        format="json",
    )

    assert response.status_code == 404
    assert not MachineServiceRequest.objects.filter(requester=requester).exists()
