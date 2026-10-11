"""Integration contract with w7-events: account registration, no community module."""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.events.models import Event, EventCheckInEvent, EventRegistration
from apps.makerspaces.models import MakerspaceMembership
from apps.makerspaces.module_profiles import EVENTS_ONLY, profile_modules
from apps.payments.models import ManualSettlement, Payment
from apps.separability import registry
from tests.modules.family_helpers import account, assert_family_bootstrap, client, family_space
from tests.return_helpers import settlement_payload

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("rail_tombstoned", [False, True])
@pytest.mark.parametrize("amount", ["0.00", "25.00"])
def test_events_only_create_publish_account_register_offline_settle_checkin(
    amount, rail_tombstoned, settings, monkeypatch,
):
    # Match the runtime manifest at startup. Also run this file in a real
    # TOMBSTONED_APPS=payments_rail process to exercise URL withdrawal on integration.
    settings.TOMBSTONED_APPS = frozenset({"payments_rail"}) if rail_tombstoned else frozenset()
    monkeypatch.setitem(registry._runtime_apps._entries, "payments_rail", not rail_tombstoned)
    suffix = f"{rail_tombstoned}-{amount.replace('.', '-')}"
    modules = set(profile_modules(EVENTS_ONLY)) - {"payments", "membership"}
    space = family_space(f"family-events-{suffix}", *modules)
    space.enabled_features.append("events.account_registration")
    space.save(update_fields=["enabled_features"])
    staff, attendee = account(f"event-staff-{suffix}", staff=True), account(f"event-attendee-{suffix}")
    admin = client(staff)
    start = timezone.now() + timedelta(days=1)
    response = admin.post(reverse("admin-event-list-create", args=[space.pk]), {
        "title": "Open workshop", "starts_at": start.isoformat(),
        "ends_at": (start + timedelta(hours=2)).isoformat(), "is_public": True,
        "registration_audience": "accounts", "payment_amount": amount,
    }, format="json")
    assert response.status_code == 201, response.data
    event = Event.objects.get(pk=response.data["id"])
    assert event.registration_audience == "accounts"  # supplied by w7-events
    published = admin.post(reverse("admin-event-publish", args=[event.pk]), {}, format="json")
    assert published.status_code == 200, published.data
    result = client(attendee).post(reverse("public-event-register", args=[space.slug, event.public_token]), {}, format="json")
    assert result.status_code == 201, result.data
    registration = EventRegistration.objects.get(event=event, member=attendee)
    assert not MakerspaceMembership.objects.filter(user=attendee).exists()
    charges = Payment.objects.filter(makerspace=space, subject_type=Payment.SubjectType.EVENT_REGISTRATION,
                                     subject_id=registration.pk)
    if amount == "0.00":
        assert not charges.exists()
    else:
        charge = charges.get()
        assert charge.provider == "unclaimed" and charge.status == Payment.Status.PENDING
        settled = admin.post(reverse("payment-reconciliation-mark-offline", args=[space.pk, charge.pk]),
                             settlement_payload(), format="json")
        assert settled.status_code == 200, settled.data
        charge.refresh_from_db()
        assert charge.status == Payment.Status.PAID_OFFLINE
        assert ManualSettlement.objects.get(payment=charge).recorded_by == staff
    resolved = admin.post(reverse("admin-event-check-in-resolve", args=[event.pk]),
                          {"checkin_token": str(registration.checkin_token)}, format="json")
    assert resolved.status_code == 200 and resolved.data["confirmable"] is True
    attended = admin.post(reverse("admin-event-registration-mark-attended", args=[registration.pk]), {}, format="json")
    assert attended.status_code == 200, attended.data
    assert EventCheckInEvent.objects.get(registration=registration).actor == staff
    assert_family_bootstrap(space, "events")
    assert "payments" not in space.enabled_modules
