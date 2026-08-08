from decimal import Decimal
from uuid import uuid4

import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.machines.models import Machine, MachineServiceRequest, MachineType
from apps.machines.service_consumable_pools import create_pool
from apps.machines.service_workflow import submit
from apps.makerspaces.models import MakerspaceMembership
from tests.return_helpers import authenticated_client, make_member, make_space, make_user


pytestmark = pytest.mark.django_db


def make_machine(space, name="Service machine"):
    kind = MachineType.objects.create(
        makerspace=space, slug=f"service-api-{uuid4().hex[:8]}", name="Service API type"
    )
    return Machine.objects.create(makerspace=space, machine_type=kind, name=name)


def request_row(space, requester=None):
    requester = requester or make_member(f"service-requester-{uuid4().hex[:8]}", space)
    return submit(
        make_machine(space), requester, requester_name="Service member",
        contact_email=requester.email, contact_phone="123", title="Tune the machine",
    )


def list_url(space):
    return reverse("admin-machine-service-request-list-create", kwargs={"makerspace_id": space.pk})


def action_url(row, action):
    return reverse(f"admin-machine-service-request-{action}", kwargs={"pk": row.pk})


def test_manager_lists_scoped_queue_and_submits_for_member():
    space, other = make_space("service-api-list"), make_space("service-api-other")
    manager = make_member("service-api-manager", space, MakerspaceMembership.Role.MACHINE_MANAGER)
    member = make_member("service-api-member", space)
    own, foreign = request_row(space, member), request_row(other)
    client = authenticated_client(manager)

    listed = client.get(list_url(space))
    filtered = client.get(f"{list_url(space)}?status=pending&machine={own.bucket.machine_id}&bucket={own.bucket_id}")
    created = client.post(list_url(space), {
        "requester_id": member.pk, "machine_id": own.bucket.machine_id, "title": "Staff intake",
    }, format="json")

    assert listed.status_code == 200
    assert [row["id"] for row in listed.data] == [own.pk]
    assert [row["id"] for row in filtered.data] == [own.pk]
    assert created.status_code == 201
    assert created.data["requester"]["id"] == member.pk
    assert "object_key" not in str(created.data)
    assert client.get(reverse("admin-machine-service-request-detail", kwargs={"pk": foreign.pk})).status_code == 404


def test_manager_can_run_lifecycle_and_invalid_edge_is_conflict():
    space = make_space("service-api-lifecycle")
    manager = make_member("service-api-lifecycle-manager", space, MakerspaceMembership.Role.MACHINE_MANAGER)
    member = make_member("service-api-lifecycle-member", space)
    row = request_row(space, member)
    client = authenticated_client(manager)

    assert client.post(action_url(row, "accept"), {"estimated_minutes": 15}, format="json").status_code == 200
    assert client.post(action_url(row, "start"), {"machine_id": row.bucket.machine_id}, format="json").status_code == 200
    assert client.post(action_url(row, "complete"), {"actual_minutes": 12, "consumptions": []}, format="json").status_code == 200
    assert client.post(action_url(row, "collect"), {}, format="json").status_code == 200
    response = client.post(action_url(row, "accept"), {}, format="json")
    row.refresh_from_db()
    assert row.status == MachineServiceRequest.Status.COLLECTED
    assert (response.status_code, response.data["code"]) == (409, "service_invalid_transition")


def test_start_endpoint_reserves_requested_consumable_grams():
    space = make_space("service-api-pool-reserve")
    manager = make_member("service-api-pool-reserve-manager", space, MakerspaceMembership.Role.MACHINE_MANAGER)
    row = request_row(space)
    pool = create_pool(space, manager, material="PLA", initial_grams="50", machine=row.bucket.machine)
    client = authenticated_client(manager)

    assert client.post(action_url(row, "accept"), {}, format="json").status_code == 200
    response = client.post(action_url(row, "start"), {
        "machine_id": row.bucket.machine_id,
        "consumable_pool_id": pool.pk,
        "planned_grams": "12.50",
    }, format="json")

    row.refresh_from_db(); pool.refresh_from_db()
    assert response.status_code == 200
    assert (row.run_consumable_pool_id, row.reserved_grams, pool.remaining_grams) == (pool.pk, Decimal("12.50"), Decimal("37.50"))


def test_manager_can_reject_and_fail_a_service_request():
    space = make_space("service-api-terminal-actions")
    manager = make_member("service-api-terminal-manager", space, MakerspaceMembership.Role.MACHINE_MANAGER)
    client = authenticated_client(manager)
    rejected, failed = request_row(space), request_row(space)

    assert client.post(action_url(rejected, "reject"), {"reason": "Unsupported"}, format="json").status_code == 200
    assert client.post(action_url(failed, "accept"), {}, format="json").status_code == 200
    assert client.post(action_url(failed, "start"), {"machine_id": failed.bucket.machine_id}, format="json").status_code == 200
    response = client.post(action_url(failed, "fail"), {
        "reason": "Interrupted", "percent_complete": 25, "actual_minutes": 4, "consumptions": [],
    }, format="json")

    rejected.refresh_from_db(); failed.refresh_from_db()
    assert rejected.status == MachineServiceRequest.Status.REJECTED
    assert (response.status_code, failed.status) == (200, MachineServiceRequest.Status.FAILED)


def test_wrong_role_is_forbidden_and_disabled_module_is_rejected():
    space = make_space("service-api-permission")
    manager = make_member("service-api-permission-manager", space, MakerspaceMembership.Role.MACHINE_MANAGER)
    guest = make_member(
        "service-api-permission-guest", space,
        MakerspaceMembership.Role.GUEST_ADMIN, User.Role.GUEST_ADMIN,
    )
    row = request_row(space)
    assert authenticated_client(guest).get(list_url(space)).status_code == 403
    space.enabled_modules = [item for item in space.enabled_modules if item != "machine_service"]
    space.save(update_fields=["enabled_modules"])
    assert authenticated_client(manager).get(list_url(space)).status_code == 400
    assert authenticated_client(manager).get(
        reverse("admin-machine-service-request-detail", kwargs={"pk": row.pk})
    ).status_code == 400


# --------------------------------------------------------------------------
# Handover without machine management (collect_service_request).
# --------------------------------------------------------------------------
#
# Collecting a finished job is a front-desk act; MANAGE_MACHINES is the whole machine
# lifecycle. Requiring the latter to do the former is why a handover-only staffer could
# not hand a member their own print. These pin the split in both directions: the narrow
# action must be enough to collect and must not be enough for anything else.

def handover_member(username, space, actions=("collect_service_request",)):
    """A member holding a custom role with exactly `actions` -- no legacy role at all."""
    from apps.makerspaces.models import MakerspaceRole

    role = MakerspaceRole.objects.create(
        makerspace=space, name=f"Front Desk {username}", slug=f"front-desk-{uuid4().hex[:8]}",
        granted_actions=sorted(actions),
    )
    user = make_user(username, role=User.Role.REQUESTER, access_status=User.AccessStatus.ACTIVE)
    MakerspaceMembership.objects.create(
        user=user, makerspace=space, role=MakerspaceMembership.Role.CUSTOM, assigned_role=role,
    )
    return user


def completed_request(space):
    row = request_row(space)
    row.status = MachineServiceRequest.Status.COMPLETED
    row.save(update_fields=["status"])
    return row


def test_a_handover_role_can_collect_a_finished_job():
    space = make_space("service-collect-handover")
    desk = handover_member("service-collect-desk", space)
    row = completed_request(space)

    response = authenticated_client(desk).post(action_url(row, "collect"), {}, format="json")

    assert response.status_code == 200, response.data
    row.refresh_from_db()
    assert row.status == MachineServiceRequest.Status.COLLECTED
    assert row.collected_by_id == desk.pk


@pytest.mark.parametrize("action", ["accept", "reject", "start", "complete", "fail", "reprint"])
def test_a_handover_role_cannot_do_anything_but_collect(action):
    """The narrow action must not become a back door into the machine lifecycle."""
    space = make_space(f"service-collect-deny-{action}")
    desk = handover_member(f"service-collect-deny-{action}", space)
    row = completed_request(space)

    assert authenticated_client(desk).post(
        action_url(row, action), {}, format="json"
    ).status_code == 403


def test_a_handover_role_sees_only_jobs_awaiting_collection():
    """Reading the queue, drafts or in-progress work is machine management, not handover."""
    space = make_space("service-collect-scope")
    desk = handover_member("service-collect-scope-desk", space)
    waiting = completed_request(space)
    in_progress = request_row(space)

    response = authenticated_client(desk).get(list_url(space))

    assert response.status_code == 200
    assert [row["id"] for row in response.data] == [waiting.pk]
    # And the hidden one is not reachable directly either.
    assert authenticated_client(desk).get(
        reverse("admin-machine-service-request-detail", kwargs={"pk": in_progress.pk})
    ).status_code == 404


def test_a_handover_role_cannot_submit_a_new_job():
    space = make_space("service-collect-nosubmit")
    desk = handover_member("service-collect-nosubmit-desk", space)
    member = make_member("service-collect-nosubmit-member", space)
    machine = make_machine(space)

    assert authenticated_client(desk).post(
        list_url(space),
        {"requester_id": member.pk, "machine_id": machine.pk, "title": "New job"},
        format="json",
    ).status_code == 403


@pytest.mark.parametrize(
    "membership_role",
    [MakerspaceMembership.Role.MACHINE_MANAGER, MakerspaceMembership.Role.SPACE_MANAGER],
)
def test_machine_and_space_managers_still_collect_without_being_granted_the_action(membership_role):
    """The implication is what makes this change carry no migration for existing roles."""
    space = make_space(f"service-collect-implied-{membership_role}")
    manager = make_member(f"service-collect-implied-{membership_role}", space, membership_role)
    row = completed_request(space)

    assert authenticated_client(manager).post(
        action_url(row, "collect"), {}, format="json"
    ).status_code == 200
    # Their view is still the whole queue, not just collectable rows.
    assert authenticated_client(manager).get(list_url(space)).status_code == 200


def test_a_legacy_guest_admin_membership_gains_nothing():
    """No silent widening: the frozen fallback grant must not pick up the new action."""
    space = make_space("service-collect-legacy-guest")
    guest = make_member(
        "service-collect-legacy-guest-user", space,
        MakerspaceMembership.Role.GUEST_ADMIN, User.Role.GUEST_ADMIN,
    )
    row = completed_request(space)

    assert authenticated_client(guest).post(
        action_url(row, "collect"), {}, format="json"
    ).status_code == 403
