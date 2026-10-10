"""Local-day aging, default terms, domain dates and policy/portable guards."""

from datetime import datetime, timedelta, timezone as utc
from decimal import Decimal

import pytest
from django.db import DatabaseError, transaction
from django.urls import reverse
from django.utils import timezone

from apps.bookings.service_payments import create_for_confirmed_booking
from apps.events.service_payments import create_for_registered_registration
from apps.makerspaces.models import MakerspaceMembership
from apps.payments.due_dates import due_state, filter_due
from apps.payments.models import MakerspaceBillingSettings, Payment, Refund
from apps.payments.reconciliation import list_payments
from apps.payments.services import create_payment
from apps.tenant_migration.money_digest import money_fingerprint
from apps.tenant_migration.tenant_dump_catalog import FIELD_POLICIES, validate_catalog
from apps.tenant_migration.tenant_dump_types import AuthorityDisposition
from apps.data_export.models import EXPORTED_MODEL_FIELDS
from apps.tenant_migration.target_projection import TARGET_FIELD_PROJECTION
from tests.payments.test_new_subjects import subjects
from tests.return_helpers import authenticated_client, make_member, make_space

pytestmark = pytest.mark.django_db


def new_charge(space, member, *, due_at=None):
    membership = MakerspaceMembership.objects.get(makerspace=space, user=member)
    return create_payment(makerspace=space, member=member, created_by=member, amount=Decimal("10.00"),
                          currency="usd", subject_type="makerspace_membership", subject_id=membership.pk, due_at=due_at)


def test_default_terms_snapshotted_on_raise_and_future_policy_never_rewrites_debt(monkeypatch):
    space = make_space("p5-terms")
    space.timezone = "Asia/Kolkata"
    space.save(update_fields=["timezone"])
    now = datetime(2026, 10, 10, 20, tzinfo=utc.utc)
    monkeypatch.setattr("apps.payments.due_dates.timezone.now", lambda: now)
    first = new_charge(space, make_member("p5-first", space))
    assert first.due_at == now
    MakerspaceBillingSettings.objects.create(makerspace=space, payment_terms_days=3)
    second = new_charge(space, make_member("p5-second", space))
    assert second.due_at == datetime(2026, 10, 13, 18, 30, tzinfo=utc.utc)
    first.refresh_from_db()
    assert first.due_at == now
    fingerprint = money_fingerprint(space.pk)
    with pytest.raises(DatabaseError, match="due date is immutable"), transaction.atomic():
        Payment.objects.filter(pk=first.pk).update(due_at=now + timedelta(days=1))
    assert money_fingerprint(space.pk) == fingerprint


def test_aging_and_query_filter_agree_across_local_midnight():
    space = make_space("p5-local-aging")
    space.timezone = "America/Los_Angeles"
    space.save(update_fields=["timezone"])
    due = datetime(2026, 10, 11, 1, tzinfo=utc.utc)  # Oct 10 locally
    payment = new_charge(space, make_member("p5-aging", space), due_at=due)
    before = datetime(2026, 10, 11, 6, 59, tzinfo=utc.utc)
    after = datetime(2026, 10, 11, 7, tzinfo=utc.utc)
    assert due_state(payment, now=before) == "due_today"
    assert due_state(payment, now=after) == "overdue"
    assert not filter_due(Payment.objects.all(), space, "overdue", now=before).exists()
    assert filter_due(Payment.objects.all(), space, "overdue", now=after).get() == payment
    payment.status = "paid_offline"
    assert due_state(payment, now=after) == ""


def test_domain_booking_and_event_start_override_default_terms():
    space = make_space("p5-domain-dates")
    staff = make_member("p5-domain-staff", space)
    MakerspaceBillingSettings.objects.create(makerspace=space, payment_terms_days=30)
    rows = subjects(space, staff)
    booking = rows["booking"]
    booking.space.payment_amount = Decimal("8.00")
    booking.space.save(update_fields=["payment_amount"])
    event_registration = rows["event_registration"]
    event_registration.event.payment_amount = Decimal("9.00")
    event_registration.event.save(update_fields=["payment_amount"])
    assert create_for_confirmed_booking(booking, staff).due_at == booking.starts_at
    assert create_for_registered_registration(event_registration, staff).due_at == event_registration.event.starts_at


def test_membership_dues_use_existing_term_start_and_renewal_uses_next_start():
    from apps.makerspaces.models import MembershipTerm
    from apps.makerspaces.membership_payments import create_for_active_membership
    from apps.makerspaces.membership_plan_services import _raise_renewal
    from tests.makerspaces.test_membership_plans import plan
    space = make_space("p5-term-dates")
    space.membership_dues_amount = Decimal("10.00")
    space.save(update_fields=["membership_dues_amount"])
    staff = make_member("p5-term-staff", space)
    membership = MakerspaceMembership.objects.get(makerspace=space, user=staff)
    now = timezone.now()
    term = MembershipTerm.objects.create(membership=membership, plan=plan(space),
                                         starts_at=now, ends_at=now + timedelta(days=30))
    assert create_for_active_membership(membership, staff).due_at == term.starts_at
    assert _raise_renewal(term) == "charged"
    assert Payment.objects.get(subject_type="membership_term", subject_id=term.pk).due_at == term.ends_at


def test_staff_and_member_lists_sort_by_due_and_refuse_foreign_policy_access():
    space = make_space("p5-sort")
    staff = make_member("p5-sort-staff", space)
    late = new_charge(space, staff, due_at=timezone.now() + timedelta(days=5))
    early = new_charge(space, make_member("p5-sort-early", space), due_at=timezone.now() - timedelta(days=1))
    assert [row.pk for row in list_payments(actor=staff, makerspace_id=space.pk)] == [early.pk, late.pk]
    response = authenticated_client(staff).get(reverse("payment-reconciliation-list", args=[space.pk]), {"due_state": "overdue"})
    assert response.status_code == 200 and [row["id"] for row in response.data["results"]] == [early.pk]
    assert response.data["results"][0]["due_state"] == "overdue"
    history_url = reverse("member-payment-history", args=[space.pk])
    own = authenticated_client(early.member).get(history_url, {"due_state": "overdue"})
    assert own.status_code == 200 and [row["id"] for row in own.data] == [early.pk]
    assert authenticated_client(staff).get(history_url, {"due_state": "overdue"}).data == []
    assert authenticated_client(staff).get(history_url, {"due_state": "invalid"}).status_code == 400
    foreign = make_member("p5-foreign", make_space("p5-foreign-space"))
    policy_url = reverse("payment-billing-settings", args=[space.pk])
    assert authenticated_client(foreign).patch(policy_url, {"payment_terms_days": 7}, format="json").status_code == 404
    client = authenticated_client(staff)
    assert client.patch(policy_url, {"reminder_days_after": [1, 1]}, format="json").status_code == 400
    assert client.patch(policy_url, {"payment_terms_days": 7}, format="json").status_code == 200


def test_billing_and_amendment_catalogs_have_exact_field_coverage():
    from apps.tenant_migration.projection_guards import validate_unique_constraint_risks
    validate_unique_constraint_risks()
    validate_catalog()  # coordinator first recomputes the merged catalog digest
    for model in (MakerspaceBillingSettings, Payment, Refund):
        declared = set(EXPORTED_MODEL_FIELDS[model._meta.label].split())
        assert declared == {field.name for field in model._meta.fields}
    assert FIELD_POLICIES[("payments.Payment", "due_at")].dispositions == (AuthorityDisposition.PRESERVE,)
    assert TARGET_FIELD_PROJECTION[("payments.MakerspaceBillingSettings", "max_reminders")].value == 0
