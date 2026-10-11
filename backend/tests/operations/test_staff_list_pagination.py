from decimal import Decimal
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.audit import services as audit
from apps.bookings.models import BookableSpace, Booking
from apps.events.models import Event
from apps.hardware_requests.models import HardwareRequest
from apps.makerspaces.models import MembershipRequest
from apps.payments.models import Payment
from tests.module_helpers import disable_module
from tests.return_helpers import authenticated_client, make_member, make_product, make_space

pytestmark = pytest.mark.django_db


def test_inventory_sorts_the_whole_scoped_queryset_before_paging():
    space, foreign = make_space("list-pages"), make_space("list-pages-foreign")
    actor = make_member("list-pages-manager", space)
    for index in range(26):
        make_product(space, f"Tool {index:02d}")
    make_product(foreign, "Tool 99")
    client = authenticated_client(actor)
    url = f"/api/v1/admin/makerspace/{space.pk}/inventory"
    first = client.get(url, {"ordering": "-name"})
    second = client.get(url, {"ordering": "-name", "page": 2})
    assert first.status_code == second.status_code == 200
    assert first.data["count"] == 26 and len(first.data["results"]) == 24
    assert first.data["results"][0]["name"] == "Tool 25"
    assert [row["name"] for row in second.data["results"]] == ["Tool 01", "Tool 00"]
    tool = first.data["results"][0]
    selected = client.get(url, {"id": tool["id"]})
    assert selected.data["count"] == 1 and selected.data["results"][0]["id"] == tool["id"]
    foreign_id = make_product(foreign, "Foreign selected tool").pk
    assert client.get(url, {"id": foreign_id}).data["results"] == []
    assert client.get(url, {"id": "9" * 100}).status_code == 400
    assert client.get(url, {"ordering": "makerspace__name"}).status_code == 400


def test_payment_list_is_bounded_and_orders_before_paging():
    space = make_space("payment-pages")
    actor = make_member("payment-pages-manager", space)
    for index in range(26):
        borrower = make_member(f"payment-pages-borrower-{index}", space)
        membership = borrower.makerspace_memberships.get(makerspace=space)
        Payment.objects.create(makerspace=space, subject_type="makerspace_membership", subject_id=membership.pk, member=borrower, created_by=actor, amount=Decimal(index + 1), currency="usd")
    client = authenticated_client(actor)
    url = f"/api/v1/admin/makerspace/{space.pk}/payments"
    first = client.get(url, {"ordering": "-amount"})
    second = client.get(url, {"ordering": "-amount", "page": 2})
    assert first.status_code == second.status_code == 200
    assert first.data["count"] == 26 and len(first.data["results"]) == 24
    assert Decimal(first.data["results"][0]["amount"]) == Decimal(26)
    assert [Decimal(row["amount"]) for row in second.data["results"]] == [Decimal(2), Decimal(1)]
    assert client.get(url, {"ordering": "member__email"}).status_code == 400


def test_request_queue_sorts_ties_stably_and_refuses_other_tenants():
    space, foreign = make_space("queue-pages"), make_space("queue-pages-other")
    actor = make_member("queue-pages-manager", space)
    requests = [HardwareRequest.objects.create(makerspace=space, requester=actor,
                                               requested_for="drill", status="pending_approval") for _ in range(26)]
    HardwareRequest.objects.create(makerspace=foreign, requested_for="drill", status="pending_approval")
    client = authenticated_client(actor)
    url = f"/api/v1/admin/makerspace/{space.pk}/pending-requests"
    first = client.get(url, {"ordering": "status", "search": "drill"})
    second = client.get(url, {"ordering": "status", "search": "drill", "page": 2})
    assert first.status_code == second.status_code == 200
    assert first.data["count"] == 26
    assert [row["id"] for row in first.data["results"] + second.data["results"]] == [row.pk for row in requests]
    selected = client.get(url, {"id": requests[-1].pk})
    assert selected.data["count"] == 1 and selected.data["results"][0]["id"] == requests[-1].pk
    accepted = HardwareRequest.objects.create(makerspace=space, requester=actor, status="accepted")
    assert client.get(url, {"id": accepted.pk}).data["results"] == []
    assert client.get(f"/api/v1/admin/makerspace/{foreign.pk}/pending-requests").status_code == 404
    assert client.get(url, {"ordering": "requester_contact_email"}).status_code == 400


def test_member_roster_filters_and_sorts_before_paginating():
    space, foreign = make_space("member-pages"), make_space("member-pages-other")
    actor = make_member("member-pages-manager", space)
    members = [make_member(f"roster-{index:02d}", space) for index in range(26)]
    make_member("roster-99", foreign)
    client = authenticated_client(actor)
    path = "/api/v1/admin/memberships"
    filters = {"makerspace_id": space.pk, "q": "roster-", "status": "active", "ordering": "-user__username"}
    first, second = client.get(path, filters), client.get(path, {**filters, "page": 2})
    assert first.status_code == second.status_code == 200
    assert first.data["count"] == 26
    rows = first.data["results"] + second.data["results"]
    assert [row["user"]["username"] for row in rows] == [member.username for member in reversed(members)]
    selected = client.get(path, {"makerspace_id": space.pk, "id": rows[-1]["id"]})
    assert selected.data["count"] == 1 and selected.data["results"][0]["id"] == rows[-1]["id"]
    foreign_member = foreign.memberships.get(user__username="roster-99")
    assert client.get(path, {"makerspace_id": space.pk, "id": foreign_member.pk}).data["results"] == []
    assert client.get(path, {"makerspace_id": foreign.pk}).status_code == 404
    assert client.get(path, {"makerspace_id": space.pk, "status": "typo"}).status_code == 400


def test_membership_request_list_scopes_filters_and_orders_server_side():
    space, foreign = make_space("join-pages"), make_space("join-pages-other")
    actor = make_member("join-pages-manager", space)
    requests = [MembershipRequest.objects.create(makerspace=space, kind="invite", state="invited",
                                                 invite_email=f"person-{index}@example.test") for index in range(26)]
    MembershipRequest.objects.create(makerspace=space, kind="invite", state="revoked", invite_email="revoked@example.test")
    MembershipRequest.objects.create(makerspace=foreign, kind="invite", state="invited", invite_email="other@example.test")
    client = authenticated_client(actor)
    path = "/api/v1/admin/membership-requests"
    filters = {"makerspace_id": space.pk, "state": "invited", "ordering": "created_at"}
    first, second = client.get(path, filters), client.get(path, {**filters, "page": 2})
    assert first.status_code == second.status_code == 200
    assert first.data["count"] == 26
    assert [row["id"] for row in first.data["results"] + second.data["results"]] == [row.pk for row in requests]
    assert client.get(path, {"makerspace_id": foreign.pk}).status_code == 404
    assert client.get(path, {"makerspace_id": space.pk, "state": "typo"}).status_code == 400


def test_bookable_spaces_and_booking_id_filter_work_beyond_page_one():
    space, foreign = make_space("booking-pages"), make_space("booking-pages-other")
    actor = make_member("booking-pages-manager", space)
    rooms = [BookableSpace.objects.create(makerspace=space, name=f"Room {index:02d}") for index in range(26)]
    foreign_room = BookableSpace.objects.create(makerspace=foreign, name="Room 99")
    client = authenticated_client(actor)
    path = f"/api/v1/admin/makerspaces/{space.pk}/spaces/"
    first, second = client.get(path, {"ordering": "-name"}), client.get(path, {"ordering": "-name", "page": 2})
    assert first.status_code == second.status_code == 200
    assert first.data["count"] == 26
    assert [row["id"] for row in first.data["results"] + second.data["results"]] == [room.pk for room in reversed(rooms)]
    now = timezone.now()
    bookings = [Booking.objects.create(space=rooms[0], name=actor.username, email=actor.email,
                                        phone="555-0100", starts_at=now + timedelta(hours=index),
                                        ends_at=now + timedelta(hours=index + 1)) for index in range(26)]
    foreign_booking = Booking.objects.create(space=foreign_room, name=actor.username, email=actor.email,
                                            phone="555-0100", starts_at=now, ends_at=now + timedelta(hours=1))
    path = f"/api/v1/admin/spaces/{rooms[0].pk}/bookings/"
    assert len(client.get(path).data["results"]) == 24
    selected = client.get(path, {"booking_id": bookings[-1].pk})
    assert selected.status_code == 200 and selected.data["count"] == 1
    assert selected.data["results"][0]["id"] == bookings[-1].pk
    assert client.get(path, {"booking_id": foreign_booking.pk}).data["results"] == []
    assert client.get(f"/api/v1/admin/spaces/{foreign_room.pk}/bookings/").status_code == 404
    assert client.get(path, {"booking_id": "9" * 100}).status_code == 400
    disable_module(space, "bookings")
    assert client.get(path).status_code == 400


def test_event_list_filters_sorts_and_paginates_within_its_tenant():
    space, foreign = make_space("event-pages"), make_space("event-pages-other")
    actor = make_member("event-pages-manager", space)
    now = timezone.now()
    events = [Event.objects.create(makerspace=space, title=f"Laser event {index:02d}", status="draft",
                                    starts_at=now, ends_at=now + timedelta(hours=1)) for index in range(26)]
    Event.objects.create(makerspace=foreign, title="Laser foreign", starts_at=now, ends_at=now + timedelta(hours=1))
    Event.objects.create(makerspace=space, title="Laser published", status="published", starts_at=now, ends_at=now + timedelta(hours=1))
    client = authenticated_client(actor)
    path = f"/api/v1/admin/makerspaces/{space.pk}/events/"
    filters = {"q": "Laser", "status": "draft", "ordering": "-title"}
    first, second = client.get(path, filters), client.get(path, {**filters, "page": 2})
    assert first.status_code == second.status_code == 200
    assert first.data["count"] == 26
    assert [row["id"] for row in first.data["results"] + second.data["results"]] == [row.pk for row in reversed(events)]
    assert client.get(path, {"status": "typo"}).status_code == 400
    disable_module(space, "events")
    assert client.get(path).status_code == 400


def test_audit_ordering_remains_stable_and_tenant_scoped_across_pages():
    space, foreign = make_space("audit-pages"), make_space("audit-pages-other")
    actor = make_member("audit-pages-manager", space)
    logs = [audit.record(actor, "inventory.created", makerspace=space) for _ in range(26)]
    audit.record(actor, "inventory.created", makerspace=foreign)
    client = authenticated_client(actor)
    path = "/api/v1/admin/audit-logs"
    filters = {"makerspace": space.pk, "action": "inventory.created", "ordering": "action"}
    first, second = client.get(path, filters), client.get(path, {**filters, "page": 2})
    assert first.status_code == second.status_code == 200
    assert first.data["count"] == 26
    assert [row["id"] for row in first.data["results"] + second.data["results"]] == [row.pk for row in logs]
    assert client.get(path, {"makerspace": foreign.pk}).data["results"] == []
    assert client.get(path, {"ordering": "meta"}).status_code == 400
