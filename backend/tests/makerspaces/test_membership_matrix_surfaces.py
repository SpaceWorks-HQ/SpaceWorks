"""M14–M17: verification, witnessed/stale waivers and revocation at public surfaces."""
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.bookings.models import BookableSpace
from apps.events.models import Event, EventRegistration
from apps.inventory.models import InventoryProduct
from apps.makerspaces import membership_services, waiver_services
from apps.makerspaces.models import MakerspaceMembership
from apps.presence import services as presence
from apps.presence.guard import MemberPresenceRequired
from tests.makerspaces.test_membership_j1 import manager, member_role, space, user
from tests.return_helpers import authenticated_client
from tests.test_machine_service_member_n6 import machine
from tests.test_public_self_checkout import make_product, make_qr, checkout_url, checkout_payload

pytestmark = pytest.mark.django_db


@pytest.fixture
def member_state(settings):
    settings.API_CLIENT_AUTH_REQUIRED = False
    makerspace = space("matrix-public-surfaces")
    boss = manager(makerspace, "matrix-public-surfaces-manager")
    person = user("matrix-public-surfaces-member")
    person.phone = "1234567890"; person.save(update_fields=["phone"])
    row = MakerspaceMembership.objects.create(
        makerspace=makerspace, user=person, assigned_role=member_role(makerspace), role="custom",
    )
    waiver_services.publish_waiver(boss, makerspace, "Be careful", "v1")
    waiver_services.accept_waiver(row)
    presence.start_session(person, makerspace, 60)
    return makerspace, boss, person, row


def surface(makerspace, kind, person=None):
    now = timezone.now()
    if kind == "request":
        product = InventoryProduct.objects.create(makerspace=makerspace, name="Scope", total_quantity=2, available_quantity=2, is_public=True)
        return reverse("hardware_requests:request-submit", args=[makerspace.slug]), {"requested_for": "Bench", "items": [{"product_id": product.pk, "quantity": 1}]}
    if kind == "checkout":
        product = make_product(makerspace, public_self_checkout_enabled=True)
        qr = make_qr(makerspace, product)
        return checkout_url(makerspace), checkout_payload(makerspace, person, qr.payload)
    if kind == "booking":
        bookable = BookableSpace.objects.create(makerspace=makerspace, name="Room", is_public=True)
        return reverse("public-booking-submit", args=[makerspace.slug, bookable.public_token]), {"starts_at": (now + timedelta(days=1)).isoformat(), "ends_at": (now + timedelta(days=1, hours=1)).isoformat()}
    if kind == "event":
        event = Event.objects.create(makerspace=makerspace, title="Workshop", is_public=True, status=Event.Status.PUBLISHED, starts_at=now + timedelta(days=1), ends_at=now + timedelta(days=1, hours=2))
        return reverse("public-event-register", args=[makerspace.slug, event.public_token]), {}
    target = machine(makerspace)
    return f"/api/v1/public/{makerspace.slug}/machine-service-requests", {"machine_id": target.pk, "title": "Tune optics"}


@pytest.mark.parametrize("kind", ["request", "checkout", "booking", "event", "machine"])
def test_revoked_members_are_refused_before_other_prerequisites(member_state, kind):
    makerspace, _, person, row = member_state
    url, body = surface(makerspace, kind, person)
    # Keep current evidence/presence: only the active-membership guard may cause refusal.
    MakerspaceMembership.objects.filter(pk=row.pk).update(status="revoked")
    response = authenticated_client(person).post(url, body, format="json")
    assert response.status_code == 403, response.data
    assert response.data["code"] == "membership_required"


def test_presence_start_refuses_a_revoked_member():
    makerspace = space("presence-revoked")
    person = user("presence-revoked-member")
    MakerspaceMembership.objects.create(makerspace=makerspace, user=person, status="revoked", assigned_role=member_role(makerspace), role="custom")
    with pytest.raises(MemberPresenceRequired):
        presence.start_session(person, makerspace, 60)


def test_event_registration_rechecks_superseded_waiver_and_accepts_witnessed_current_version(member_state):
    makerspace, boss, person, row = member_state
    membership_services.verify_member(boss, row)
    url, _ = surface(makerspace, "event")
    client = authenticated_client(person)
    waiver_services.publish_waiver(boss, makerspace, "Updated liability terms", "v2")
    refused = client.post(url, {}, format="json")
    assert refused.status_code == 403 and refused.data["code"] == "waiver_acceptance_required"
    assert not EventRegistration.objects.filter(member=person).exists()
    waiver_services.witness_waiver_acceptance(boss, row.pk)
    assert client.post(url, {}, format="json").status_code == 201
    # Verification is a badge: removing it does not invalidate the witnessed waiver.
    membership_services.unverify_member(boss, row)
    assert client.post(url, {}, format="json").status_code == 201
