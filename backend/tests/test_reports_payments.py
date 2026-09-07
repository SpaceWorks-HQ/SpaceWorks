from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounts import rbac
from apps.bookings.models import BookableSpace, Booking
from apps.events.models import Event, EventRegistration
from apps.hardware_requests.models import HardwareRequest
from apps.makerspaces.models import (
    MakerspaceMembership,
    MakerspaceRole,
    MembershipPlan,
    MembershipTerm,
)
from apps.operations.reports_payments import build_payment_reconciliation
from apps.payments.models import Payment
from tests.return_helpers import authenticated_client, make_member, make_space, make_user

pytestmark = pytest.mark.django_db


def add_payment(space, actor, subject_type, subject_id, amount, currency="usd", status="pending", created_at=None):
    now = timezone.now()
    if subject_type == Payment.SubjectType.BOOKING:
        bookable = BookableSpace.objects.create(
            makerspace=space, name=f"Payment report space {subject_id}", created_by=actor
        )
        subject_id = Booking.objects.create(
            space=bookable, member=actor, name=actor.username,
            email=actor.email or f"{actor.username}@example.test", phone="1",
            starts_at=now + timedelta(days=1), ends_at=now + timedelta(days=1, hours=1),
        ).pk
    elif subject_type == Payment.SubjectType.EVENT_REGISTRATION:
        event = Event.objects.create(
            makerspace=space, title=f"Payment report event {subject_id}",
            starts_at=now + timedelta(days=1), ends_at=now + timedelta(days=1, hours=1),
            created_by=actor,
        )
        subject_id = EventRegistration.objects.create(
            event=event, member=actor, name=actor.username,
            email=actor.email or f"{actor.username}@example.test", phone="1",
        ).pk
    elif subject_type == Payment.SubjectType.MAKERSPACE_MEMBERSHIP:
        subject_id = MakerspaceMembership.objects.get(
            makerspace=space, user=actor
        ).pk
    elif subject_type == Payment.SubjectType.MEMBERSHIP_TERM:
        plan = MembershipPlan.objects.create(
            makerspace=space, name=f"Payment report plan {subject_id}", interval="monthly",
        )
        subject_id = MembershipTerm.objects.create(
            membership=MakerspaceMembership.objects.get(makerspace=space, user=actor),
            plan=plan, starts_at=now - timedelta(days=30), ends_at=now + timedelta(days=1),
        ).pk
    elif subject_type in Payment.LOAN_SUBJECT_TYPES:
        subject_id = HardwareRequest.objects.create(
            makerspace=space, requester=actor, requester_username=actor.username,
        ).pk
    row = Payment.objects.create(
        makerspace=space, subject_type=subject_type, subject_id=subject_id,
        member=actor, amount=Decimal(amount), currency=currency, status=status,
        created_by=actor,
    )
    if created_at:
        Payment.objects.filter(pk=row.pk).update(created_at=created_at)
    return row


def test_report_groups_real_rows_by_tenant_currency_subject_and_status():
    space = make_space("payment-report-groups")
    other = make_space("payment-report-groups-other")
    manager = make_member("payment-report-manager", space)
    other_manager = make_member("payment-report-other-manager", other)
    add_payment(space, manager, Payment.SubjectType.BOOKING, 1, "10.00")
    add_payment(space, manager, Payment.SubjectType.BOOKING, 2, "5.00")
    add_payment(space, manager, Payment.SubjectType.BOOKING, 3, "7.00", "eur")
    add_payment(space, manager, Payment.SubjectType.EVENT_REGISTRATION, 4, "9.00", status="waived")
    add_payment(other, other_manager, Payment.SubjectType.BOOKING, 5, "99.00")

    result = build_payment_reconciliation(space.id)

    assert "makerspace_id" not in result.field_order
    assert len(result.records) == 3
    usd_pending = next(row for row in result.records if row["currency"] == "usd" and row["status"] == "pending")
    assert usd_pending["payment_count"] == 2
    assert usd_pending["amount_total"] == Decimal("15.00")
    assert usd_pending["outstanding_amount"] == Decimal("15.00")
    waived = next(row for row in result.records if row["status"] == "waived")
    assert waived["outstanding_amount"] == Decimal("0.00")


def test_report_date_range_keeps_pending_and_filters_non_pending_created_at():
    space = make_space("payment-report-dates")
    manager = make_member("payment-report-dates-manager", space)
    now = timezone.now()
    old = now - timedelta(days=60)
    add_payment(space, manager, Payment.SubjectType.BOOKING, 10, "4.00", created_at=old)
    add_payment(space, manager, Payment.SubjectType.EVENT_REGISTRATION, 11, "5.00", status="paid_online", created_at=old)
    add_payment(space, manager, Payment.SubjectType.MAKERSPACE_MEMBERSHIP, 12, "6.00", status="paid_offline", created_at=now)

    result = build_payment_reconciliation(
        space.id, date_range=(now - timedelta(days=1), now + timedelta(days=1))
    )

    assert {(row["subject_type"], row["status"]) for row in result.records} == {
        (Payment.SubjectType.BOOKING, Payment.Status.PENDING),
        (Payment.SubjectType.MAKERSPACE_MEMBERSHIP, Payment.Status.PAID_OFFLINE),
    }


def test_report_filters_all_subject_types_and_aggregate_includes_makerspace_id():
    space = make_space("payment-report-filters")
    manager = make_member("payment-report-filters-manager", space)
    for index, subject_type in enumerate(Payment.SubjectType.values, start=20):
        if subject_type == Payment.SubjectType.MACHINE_SERVICE_REQUEST:
            assert build_payment_reconciliation(
                space.id, subject_type=subject_type
            ).records == []
            continue
        add_payment(space, manager, subject_type, index, "1.00")
        result = build_payment_reconciliation(space.id, subject_type=subject_type)
        assert {row["subject_type"] for row in result.records} == {subject_type}

    aggregate = build_payment_reconciliation(None)
    assert aggregate.field_order[0] == "makerspace_id"
    assert all(row["makerspace_id"] == space.id for row in aggregate.records)


def test_private_report_requires_manage_makerspace_not_view_audit():
    space = make_space("payment-report-rbac")
    manager = make_member("payment-report-rbac-manager", space)
    add_payment(space, manager, Payment.SubjectType.BOOKING, 40, "11.00")
    audit_actor = make_user("payment-report-auditor", access_status="active")
    role = MakerspaceRole.objects.create(
        makerspace=space, name="Audit only", slug="audit-only",
        granted_actions=[rbac.Action.VIEW_AUDIT],
    )
    MakerspaceMembership.objects.create(
        makerspace=space, user=audit_actor, role="custom", assigned_role=role
    )
    url = f"/api/v1/admin/makerspace/{space.id}/analytics/payment-reconciliation"

    assert authenticated_client(audit_actor).get(url).status_code == 404
    response = authenticated_client(manager).get(url + "?subject_type=booking")
    assert response.status_code == 200
    assert response.data["typed_rows"][0]["amount_total"] == "11.00"
