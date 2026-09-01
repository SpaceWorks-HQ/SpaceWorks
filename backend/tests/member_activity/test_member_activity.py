from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.bookings.models import BookableSpace, Booking
from apps.events.models import Event, EventRegistration
from apps.hardware_requests.models import HardwareRequest, PublicToolLoan
from apps.machines.models import Machine, MachineServiceRequest, MachineType, ServiceBucket, ServiceQueue
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole
from apps.presence import services as presence_services


pytestmark = pytest.mark.django_db


def member(space, username):
    user = User.objects.create_user(
        username=username, display_name=f"{username} display",
        email=f"{username}@example.test", phone="9999999999",
    )
    MakerspaceMembership.objects.create(
        makerspace=space, user=user,
        assigned_role=MakerspaceRole.objects.get(makerspace=space, slug="member"),
        role="custom",
    )
    return user


def client(user):
    result = APIClient()
    result.force_authenticate(user)
    return result


def activity_url(space):
    return f"/api/v1/member/makerspaces/{space.id}/activity"


def make_loan(space, user, label="Own loan"):
    request = HardwareRequest.objects.create(
        makerspace=space, requester=user, requester_username=user.username,
        requester_name=user.display_name,
    )
    return PublicToolLoan.objects.create(
        makerspace=space, request=request, requester=user, target_type="product",
        target_id=1, target_label=label, due_at=timezone.now() - timedelta(hours=1),
    )


def test_activity_is_member_owned_and_has_safe_projections_without_presence():
    space = Makerspace.objects.create(name="Activity", slug="activity")
    user, other = member(space, "activity-owner"), member(space, "activity-other")
    make_loan(space, user)
    make_loan(space, other, "Other loan")
    printer_type = MachineType.objects.get(makerspace__isnull=True, slug="3d_printer")
    print_queue = ServiceQueue.objects.create(makerspace=space, machine_type=printer_type, name="Public")
    MachineServiceRequest.objects.create(makerspace=space, queue=print_queue, requester=user, member=user, title="Own print")
    MachineServiceRequest.objects.create(makerspace=space, queue=print_queue, requester=other, member=other, title="Other print", contact_email=user.email)
    bookable = BookableSpace.objects.create(makerspace=space, name="Bench")
    Booking.objects.create(
        space=bookable, member=user, name=user.display_name, email=user.email, phone=user.phone,
        starts_at=timezone.now() + timedelta(days=1), ends_at=timezone.now() + timedelta(days=1, hours=1),
    )
    Booking.objects.create(
        space=bookable, member=other, name=other.display_name, email=user.email, phone=other.phone,
        starts_at=timezone.now() + timedelta(days=2), ends_at=timezone.now() + timedelta(days=2, hours=1),
    )
    event = Event.objects.create(
        makerspace=space, title="Workshop", starts_at=timezone.now() + timedelta(days=1),
        ends_at=timezone.now() + timedelta(days=1, hours=1), status=Event.Status.PUBLISHED,
    )
    EventRegistration.objects.create(event=event, member=user, name=user.display_name, email=user.email, phone=user.phone, status="waitlisted")
    EventRegistration.objects.create(event=event, member=other, name=other.display_name, email=other.email, phone=other.phone, status="waitlisted")
    machine_type = MachineType.objects.create(makerspace=space, slug="activity-type", name="Activity type")
    machine = Machine.objects.create(makerspace=space, machine_type=machine_type, name="Laser")
    service_bucket = ServiceBucket.objects.create(machine=machine, name="Service")
    MachineServiceRequest.objects.create(bucket=service_bucket, requester=user, member=user, title="Own service")
    MachineServiceRequest.objects.create(bucket=service_bucket, requester=other, member=other, title="Other service", contact_email=user.email)
    presence_services.start_session(user, space, 60)

    response = client(user).get(activity_url(space))

    assert response.status_code == 200
    assert response.data["active_hardware_loans"] == [{
        "label": "Own loan", "checked_out_at": response.data["active_hardware_loans"][0]["checked_out_at"],
        "due_at": response.data["active_hardware_loans"][0]["due_at"], "overdue": True,
    }]
    assert [item["title"] for item in response.data["print_requests"]] == ["Own print"]
    assert [item["space_name"] for item in response.data["bookings"]["upcoming"]] == ["Bench"]
    assert [item["event_title"] for item in response.data["event_registrations"]] == ["Workshop"]
    assert response.data["event_registrations"][0]["waitlist_position"] == 1
    assert {item["title"] for item in response.data["machine_service_requests"]} == {"Own service", "Own print"}
    assert response.data["machine_service_requests"][0]["queue_position"] == 1
    assert response.data["currently_checked_in"] is True
    assert response.data["accountability"] == {
        "membership_active": True, "waiver_acceptance_required": False, "restriction_code": None,
    }
    serialized = str(response.data)
    for sentinel in (user.email, user.phone, other.email, other.phone, "contact_email", "object_key", "custom_answers"):
        assert sentinel not in serialized


def test_activity_requires_active_exact_membership_but_not_presence():
    space, other_space = Makerspace.objects.create(name="One", slug="one"), Makerspace.objects.create(name="Two", slug="two")
    user = member(space, "exact-member")
    assert client(user).get(activity_url(space)).status_code == 200
    response = client(user).get(activity_url(other_space))
    assert response.status_code == 403 and response.data["code"] == "membership_required"
    user.makerspace_memberships.get(makerspace=space).delete()
    response = client(user).get(activity_url(space))
    assert response.status_code == 403 and response.data["code"] == "membership_required"


def test_disabled_capabilities_are_omitted():
    space = Makerspace.objects.create(
        name="Disabled", slug="disabled",
        # `membership` is required because the activity endpoint is itself a member
        # surface (plan A7); the point of this test is the other modules being off.
        enabled_modules=["public_inventory", "request_workflow", "membership"],
    )
    user = member(space, "disabled-member")
    response = client(user).get(activity_url(space))
    assert response.status_code == 200
    assert {"print_requests", "bookings", "event_registrations", "machine_service_requests"}.isdisjoint(response.data)


def test_activity_query_count_does_not_grow_with_member_rows():
    space = Makerspace.objects.create(name="Query", slug="query")
    user = member(space, "query-member")
    printer_type = MachineType.objects.get(makerspace__isnull=True, slug="3d_printer")
    queue = ServiceQueue.objects.create(makerspace=space, machine_type=printer_type, name="Queue")
    MachineServiceRequest.objects.create(makerspace=space, queue=queue, requester=user, member=user, title="Print 0")
    api = client(user)
    with CaptureQueriesContext(connection) as baseline:
        assert api.get(activity_url(space)).status_code == 200
    for number in range(1, 12):
        MachineServiceRequest.objects.create(makerspace=space, queue=queue, requester=user, member=user, title=f"Print {number}")
    with CaptureQueriesContext(connection) as expanded:
        assert api.get(activity_url(space)).status_code == 200
    assert len(expanded) <= len(baseline) + 2