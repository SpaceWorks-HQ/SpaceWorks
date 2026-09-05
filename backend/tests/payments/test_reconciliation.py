from decimal import Decimal
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts import rbac
from apps.audit.models import AuditLog
from apps.bookings.models import BookableSpace, Booking
from apps.events.models import Event, EventRegistration
from apps.makerspaces.models import MakerspaceMembership, MakerspaceRole
from apps.payments.models import Payment
from tests.return_helpers import (
    authenticated_client,
    make_member,
    make_space,
    make_user,
)

pytestmark = pytest.mark.django_db


def payment(space, actor, subject_type, subject_id, *, status=Payment.Status.PENDING):
    now = timezone.now()
    if subject_type == Payment.SubjectType.BOOKING:
        bookable = BookableSpace.objects.create(
            makerspace=space,
            name=f"Payment space {subject_id}",
            created_by=actor,
        )
        subject_id = Booking.objects.create(
            space=bookable,
            member=actor,
            name=actor.username,
            email=actor.email or f"{actor.username}@example.com",
            phone="1",
            starts_at=now + timedelta(days=1),
            ends_at=now + timedelta(days=1, hours=1),
        ).pk
    elif subject_type == Payment.SubjectType.EVENT_REGISTRATION:
        event = Event.objects.create(
            makerspace=space,
            title=f"Payment event {subject_id}",
            starts_at=now + timedelta(days=1),
            ends_at=now + timedelta(days=1, hours=1),
            created_by=actor,
        )
        subject_id = EventRegistration.objects.create(
            event=event,
            member=actor,
            name=actor.username,
            email=actor.email or f"{actor.username}@example.com",
            phone="1",
        ).pk
    elif subject_type == Payment.SubjectType.MAKERSPACE_MEMBERSHIP:
        subject_id = MakerspaceMembership.objects.get(
            makerspace=space,
            user=actor,
        ).pk
    return Payment.objects.create(
        makerspace=space,
        subject_type=subject_type,
        subject_id=subject_id,
        member=actor,
        amount=Decimal("12.50"),
        currency="usd",
        status=status,
        created_by=actor,
    )


def custom_actor(username, space, actions):
    actor = make_user(username, access_status="active")
    role = MakerspaceRole.objects.create(
        makerspace=space,
        name=f"{username} role",
        slug=f"{username}-role",
        granted_actions=actions,
    )
    MakerspaceMembership.objects.create(
        user=actor,
        makerspace=space,
        role=MakerspaceMembership.Role.CUSTOM,
        assigned_role=role,
    )
    return actor


def list_url(space, query=""):
    return f"/api/v1/admin/makerspace/{space.id}/payments{query}"


def action_url(space, row, action):
    return f"{list_url(space)}/{row.id}/{action}"


def test_list_is_manager_only_filtered_and_tenant_scoped():
    space = make_space("payments-list")
    other = make_space("payments-list-other")
    manager = make_member("payments-list-manager", space)
    booking = payment(space, manager, Payment.SubjectType.BOOKING, 1)
    payment(space, manager, Payment.SubjectType.EVENT_REGISTRATION, 2)
    payment(other, make_member("payments-list-other-manager", other), Payment.SubjectType.BOOKING, 3)

    response = authenticated_client(manager).get(
        list_url(space, "?status=pending&subject_type=booking")
    )

    assert response.status_code == 200
    assert [row["id"] for row in response.data] == [booking.id]
    assert authenticated_client(manager).get(list_url(other)).status_code == 404
    audit_only = custom_actor("payments-list-audit", space, [rbac.Action.VIEW_AUDIT])
    assert authenticated_client(audit_only).get(list_url(space)).status_code == 404


def test_subject_specific_authority_and_makerspace_mismatch():
    space = make_space("payments-subject-auth")
    other = make_space("payments-subject-auth-other")
    creator = make_member("payments-subject-creator", space)
    booking = payment(space, creator, Payment.SubjectType.BOOKING, 10)
    event = payment(space, creator, Payment.SubjectType.EVENT_REGISTRATION, 11)
    booking_manager = custom_actor(
        "payments-booking-manager", space, [rbac.Action.MANAGE_BOOKINGS]
    )

    assert authenticated_client(booking_manager).post(
        action_url(space, booking, "mark-offline")
    ).status_code == 200
    assert authenticated_client(booking_manager).post(
        action_url(space, event, "waive")
    ).status_code == 403
    assert authenticated_client(booking_manager).post(
        action_url(other, event, "waive")
    ).status_code == 404


def test_bulk_is_all_or_nothing_preserves_input_order_and_audits_each_change():
    space = make_space("payments-bulk")
    manager = make_member("payments-bulk-manager", space)
    first = payment(space, manager, Payment.SubjectType.BOOKING, 20)
    terminal = payment(
        space, manager, Payment.SubjectType.EVENT_REGISTRATION, 21,
        status=Payment.Status.WAIVED,
    )
    pending = payment(space, manager, Payment.SubjectType.MAKERSPACE_MEMBERSHIP, 22)
    bulk_url = f"{list_url(space)}/bulk/mark-offline"

    conflict = authenticated_client(manager).post(
        bulk_url, {"ids": [first.id, terminal.id]}, format="json"
    )
    assert conflict.status_code == 409
    first.refresh_from_db()
    assert first.status == Payment.Status.PENDING
    assert AuditLog.objects.filter(target_id=str(first.id)).count() == 0

    response = authenticated_client(manager).post(
        bulk_url, {"ids": [pending.id, first.id]}, format="json"
    )
    assert response.status_code == 200
    assert [row["id"] for row in response.data] == [pending.id, first.id]
    assert AuditLog.objects.filter(
        action="payment.paid_offline", target_id__in=[str(first.id), str(pending.id)]
    ).count() == 2


def test_bulk_rejects_duplicate_or_missing_ids_before_mutation():
    space = make_space("payments-bulk-validation")
    manager = make_member("payments-bulk-validation-manager", space)
    row = payment(space, manager, Payment.SubjectType.BOOKING, 30)
    url = f"{list_url(space)}/bulk/waive"

    assert authenticated_client(manager).post(url, {"ids": []}, format="json").status_code == 400
    assert authenticated_client(manager).post(
        url, {"ids": [row.id, row.id]}, format="json"
    ).status_code == 400
    assert authenticated_client(manager).post(
        url, {"ids": [row.id, 999999]}, format="json"
    ).status_code == 404
    row.refresh_from_db()
    assert row.status == Payment.Status.PENDING


def test_checkout_expiry_failure_is_best_effort(monkeypatch):
    space = make_space("payments-expiry")
    manager = make_member("payments-expiry-manager", space)
    row = payment(space, manager, Payment.SubjectType.BOOKING, 40)
    Payment.objects.filter(pk=row.pk).update(stripe_checkout_session_id="cs_live")
    monkeypatch.setattr(
        "apps.payments.reconciliation_rail.stripe_client.expire_checkout_session",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("Stripe down")),
    )

    response = authenticated_client(manager).post(action_url(space, row, "waive"))

    assert response.status_code == 200
    row.refresh_from_db()
    assert row.status == Payment.Status.WAIVED
    assert row.stripe_checkout_session_expired_at is None
    assert AuditLog.objects.filter(action="payment.waived", target_id=str(row.id)).count() == 1
