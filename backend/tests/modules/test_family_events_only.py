"""Events-only HTTP flows, loans off, with the online rail present or tombstoned.

Also run in a TOMBSTONED_APPS=payments_rail process to verify URL withdrawal.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.events.models import Event, EventCheckInEvent, EventRegistration
from apps.makerspaces.models import MakerspaceMembership
from apps.makerspaces.module_profiles import EVENTS_ONLY, profile_modules
from apps.payments.models import ManualSettlement, Payment
from apps.separability import registry
from tests.events.collab_helpers import make_staff
from tests.events.ticketing_helpers import public_url
from tests.modules.family_helpers import account, assert_family_bootstrap, client, family_space
from tests.return_helpers import settlement_payload

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("rail_tombstoned", [False, True])
@pytest.mark.parametrize("kind", ["free", "invite", "paid"])
def test_events_only_create_publish_detail_register_offline_settle_checkin(
    kind, rail_tombstoned, settings, monkeypatch,
):
    settings.TOMBSTONED_APPS = frozenset({"payments_rail"}) if rail_tombstoned else frozenset()
    monkeypatch.setitem(registry._runtime_apps._entries, "payments_rail", not rail_tombstoned)
    suffix = f"{rail_tombstoned}-{kind}"
    modules = set(profile_modules(EVENTS_ONLY)) - {"payments", "membership"}
    space = family_space(f"family-events-{suffix}", *modules)
    space.enabled_features.extend([
        "events.account_registration", "events.invites", "events.ticket_types",
    ])
    space.save(update_fields=["enabled_features"])
    assert_family_bootstrap(space, "events")
    assert "membership" not in space.enabled_modules and "payments" not in space.enabled_modules
    staff, attendee = make_staff(space), account(f"event-attendee-{suffix}")
    staff_client = client(staff)
    start = timezone.now() + timedelta(hours=1)
    created = staff_client.post(reverse("admin-event-list-create", args=[space.pk]), {
        "title": "Workshop", "description": "", "starts_at": start.isoformat(),
        "ends_at": (start + timedelta(hours=2)).isoformat(), "location": "Lab", "is_public": True,
        "registration_audience": "invite" if kind == "invite" else "accounts",
    }, format="json")
    assert created.status_code == 201, created.data
    event = Event.objects.get(pk=created.data["id"])
    assert event.registration_audience == ("invite" if kind == "invite" else "accounts")
    published = staff_client.post(reverse("admin-event-publish", args=[event.pk]), {}, format="json")
    assert published.status_code == 200, published.data
    body = {}
    if kind == "invite":
        invitation = staff_client.post(reverse("admin-event-invites", args=[event.pk]), {"email": attendee.email}, format="json")
        assert invitation.status_code == 201, invitation.data
        body["invite_code"] = invitation.data["code"]
    ticket = staff_client.post(reverse("admin-event-tickets", args=[event.pk]), {"name": "Public", "amount": "25.00" if kind == "paid" else "0.00", "audience": "public", "capacity": 5}, format="json")
    assert ticket.status_code == 201, ticket.data
    body["ticket_type_id"] = ticket.data["id"]
    detail = client().get(public_url(event, "public-event-detail"))
    assert detail.status_code == 200, detail.data
    registered = client(attendee).post(public_url(event), body, format="json")
    assert registered.status_code == 201, registered.data
    registration = EventRegistration.objects.get(event=event, member=attendee)
    assert not MakerspaceMembership.objects.filter(user=attendee).exists()
    charges = Payment.objects.filter(
        makerspace=space, subject_id=registration.pk,
        subject_type=Payment.SubjectType.EVENT_REGISTRATION,
    )
    if kind == "paid":
        payment = charges.get()
        assert payment.amount == Decimal("25") and payment.provider == "unclaimed" and payment.status == Payment.Status.PENDING
        settled = staff_client.post(reverse("payment-reconciliation-mark-offline", args=[space.pk, payment.pk]), settlement_payload(), format="json")
        assert settled.status_code == 200, settled.data
        payment.refresh_from_db()
        assert payment.status == Payment.Status.PAID_OFFLINE
        assert ManualSettlement.objects.get(payment=payment).recorded_by == staff
    else:
        assert not charges.exists()
    qr = client(attendee).get(reverse("member-event-checkin-qr", args=[space.pk, registration.pk]))
    assert qr.status_code == 200, qr.data
    resolved = staff_client.post(reverse("admin-event-check-in-resolve", args=[event.pk]), {"checkin_token": str(registration.checkin_token)}, format="json")
    assert resolved.status_code == 200, resolved.data
    assert resolved.data["confirmable"] is True
    attended = staff_client.post(reverse("admin-event-registration-mark-attended", args=[registration.pk]), {"source": "qr"}, format="json")
    assert attended.status_code == 200, attended.data
    registration.refresh_from_db()
    assert registration.status == EventRegistration.Status.ATTENDED
    assert EventCheckInEvent.objects.get(registration=registration).actor == staff
    assert AuditLog.objects.filter(actor=staff, action="event.registration_attended").exists()
    assert_family_bootstrap(space, "events")
    assert "payments" not in space.enabled_modules
