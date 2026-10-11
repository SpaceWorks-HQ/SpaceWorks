"""Run this same HTTP workflow normally and with TOMBSTONED_APPS=payments_rail."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.events.models import Event, EventRegistration
from apps.makerspaces.models import MakerspaceMembership
from apps.payments.models import Payment, ManualSettlement
from tests.events.collab_helpers import make_staff, client_for
from tests.events.ticketing_helpers import event_space, account, public_url
from tests.return_helpers import settlement_payload

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("kind", ["free", "invite", "paid"])
def test_events_only_create_publish_detail_register_offline_settle_checkin(kind):
    space = event_space()
    assert "membership" not in space.enabled_modules and "payments" not in space.enabled_modules
    staff, attendee = make_staff(space), account()
    staff_client = client_for(staff)
    start = timezone.now() + timedelta(hours=1)
    created = staff_client.post(reverse("admin-event-list-create", args=[space.pk]), {
        "title": "Workshop", "description": "", "starts_at": start.isoformat(),
        "ends_at": (start + timedelta(hours=2)).isoformat(), "location": "Lab", "is_public": True,
        "registration_audience": "invite" if kind == "invite" else "accounts",
    }, format="json")
    assert created.status_code == 201, created.data
    event = Event.objects.get(pk=created.data["id"])
    assert staff_client.post(reverse("admin-event-publish", args=[event.pk]), {}, format="json").status_code == 200
    body = {}
    if kind == "invite":
        invitation = staff_client.post(reverse("admin-event-invites", args=[event.pk]), {"email": attendee.email}, format="json")
        assert invitation.status_code == 201
        body["invite_code"] = invitation.data["code"]
    if kind in {"free", "invite", "paid"}:
        ticket = staff_client.post(reverse("admin-event-tickets", args=[event.pk]), {"name": "Public", "amount": "25.00" if kind == "paid" else "0.00", "audience": "public", "capacity": 5}, format="json")
        assert ticket.status_code == 201, ticket.data
        body["ticket_type_id"] = ticket.data["id"]
    detail = APIClient().get(public_url(event, "public-event-detail"))
    assert detail.status_code == 200
    registered = client_for(attendee).post(public_url(event), body, format="json")
    assert registered.status_code == 201, registered.data
    registration = EventRegistration.objects.get(event=event, member=attendee)
    assert not MakerspaceMembership.objects.filter(makerspace=space, user=attendee).exists()
    if kind == "paid":
        payment = Payment.objects.get(subject_id=registration.pk, subject_type="event_registration")
        assert payment.amount == Decimal("25") and payment.provider == "unclaimed" and payment.status == "pending"
        settled = staff_client.post(reverse("payment-reconciliation-mark-offline", args=[space.pk, payment.pk]), settlement_payload(), format="json")
        assert settled.status_code == 200, settled.data
        payment.refresh_from_db()
        assert payment.status == "paid_offline"
        assert ManualSettlement.objects.get(payment=payment).recorded_by == staff
    else:
        assert not Payment.objects.filter(subject_id=registration.pk, subject_type="event_registration").exists()
    qr = client_for(attendee).get(reverse("member-event-checkin-qr", args=[space.pk, registration.pk]))
    assert qr.status_code == 200
    resolved = staff_client.post(reverse("admin-event-check-in-resolve", args=[event.pk]), {"checkin_token": str(registration.checkin_token)}, format="json")
    assert resolved.status_code == 200, resolved.data
    attended = staff_client.post(reverse("admin-event-registration-mark-attended", args=[registration.pk]), {"source": "qr"}, format="json")
    assert attended.status_code == 200, attended.data
    registration.refresh_from_db()
    assert registration.status == "attended"
    assert AuditLog.objects.filter(actor=staff, action="event.registration_attended").exists()
