from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from django.db import IntegrityError, close_old_connections, transaction
from django.urls import resolve, reverse
from django.utils import timezone
from drf_spectacular.generators import SchemaGenerator
from rest_framework.test import APIRequestFactory

from apps.audit.models import AuditLog
from apps.events import services
from apps.events.exceptions import (
    CapacityConflict,
    EventInvalidTransition,
    RegistrationClosed,
    RegistrationRejected,
)
from apps.events.models import Event, EventRegistration
from apps.events.serializers_admin import EventWriteSerializer
from apps.makerspaces import origin_scope
from tests.events.test_admin_api import (
    client_for,
    grant,
    make_space,
    make_user,
)
from tests.events.test_services import make_event, make_registration, register
from tests.member_submission import active_member_client


pytestmark = pytest.mark.django_db


def test_cutoff_defaults_and_validation_preserve_existing_behavior():
    event = make_event(make_space("cutoff-default"))
    assert event.registration_requires_approval is False
    assert event.registration_cutoff_at is None
    assert event.registration_cutoff_lead_minutes is None
    assert register(event, "default@example.test").status == "registered"

    event.registration_cutoff_lead_minutes = 30
    serializer = EventWriteSerializer(
        event,
        data={"registration_cutoff_at": event.starts_at.isoformat()},
        partial=True,
    )
    assert not serializer.is_valid()
    assert set(serializer.errors) == {
        "registration_cutoff_at", "registration_cutoff_lead_minutes"
    }


def test_cutoff_constraints_reject_two_modes_and_after_start():
    space = make_space("cutoff-constraints")
    start = timezone.now() + timedelta(hours=2)
    with pytest.raises(IntegrityError), transaction.atomic():
        Event.objects.create(
            makerspace=space, title="Both", starts_at=start,
            ends_at=start + timedelta(hours=1), registration_cutoff_at=start,
            registration_cutoff_lead_minutes=0,
        )
    with pytest.raises(IntegrityError), transaction.atomic():
        Event.objects.create(
            makerspace=space, title="Late", starts_at=start,
            ends_at=start + timedelta(hours=1),
            registration_cutoff_at=start + timedelta(seconds=1),
        )


def test_pending_member_is_active_for_uniqueness_but_rejected_is_terminal():
    space = make_space("approval-uniqueness")
    member = make_user("approval-unique-member")
    event = make_event(space, registration_requires_approval=True)
    first = make_registration(
        event, "first-identity@example.test", "pending_approval"
    )
    first.member = member
    first.save(update_fields=["member"])
    with pytest.raises(IntegrityError), transaction.atomic():
        EventRegistration.objects.create(
            event=event, member=member, name="Same member",
            email="second-identity@example.test", phone="1",
            status=EventRegistration.Status.PENDING_APPROVAL,
        )


def test_approval_policy_changes_only_while_draft():
    actor = make_user("approval-policy-actor")
    published = make_event(make_space("approval-policy-published"))
    with pytest.raises(EventInvalidTransition):
        services.update_event(
            published, actor=actor, registration_requires_approval=True
        )
    draft = make_event(
        make_space("approval-policy-draft"), status=Event.Status.DRAFT
    )
    updated = services.update_event(
        draft, actor=actor, registration_requires_approval=True
    )
    assert updated.registration_requires_approval is True


def test_registration_cutoff_is_closed_at_equality(monkeypatch):
    fixed = timezone.now() + timedelta(minutes=30)
    event = make_event(
        make_space("cutoff-equality"),
        starts_at=fixed + timedelta(hours=1),
        ends_at=fixed + timedelta(hours=2),
        registration_cutoff_at=fixed,
    )
    monkeypatch.setattr("apps.events.services_registration.timezone.now", lambda: fixed)
    with pytest.raises(RegistrationClosed):
        register(event, "equal@example.test")

    event.registration_cutoff_at = fixed + timedelta(seconds=1)
    event.save(update_fields=["registration_cutoff_at"])
    assert register(event, "before@example.test").status == "registered"


def test_pending_approval_consumes_no_capacity_and_charges_only_on_confirmation(
    monkeypatch,
):
    event = make_event(
        make_space("approval-payment"),
        capacity=1,
        registration_requires_approval=True,
    )
    payment_calls = []
    monkeypatch.setattr(
        "apps.events.service_payments.create_for_registered_registration",
        lambda registration, actor: payment_calls.append(registration.pk),
    )
    monkeypatch.setattr(
        "apps.events.services_registration_state.create_for_registered_registration",
        lambda registration, actor: payment_calls.append(registration.pk),
    )

    first = register(event, "first@example.test")
    second = register(event, "second@example.test")
    assert first.status == second.status == EventRegistration.Status.PENDING_APPROVAL
    assert payment_calls == []

    first = services.approve_registration(first, actor=None)
    second = services.approve_registration(second, actor=None)
    assert (first.status, second.status) == ("registered", "waitlisted")
    assert payment_calls == [first.pk]
    with pytest.raises(EventInvalidTransition):
        services.approve_registration(first, actor=None)
    assert payment_calls == [first.pk]

    second = services.reject_registration(second, actor=None)
    assert second.status == EventRegistration.Status.REJECTED
    assert payment_calls == [first.pk]
    assert set(AuditLog.objects.values_list("action", flat=True)) >= {
        "event.registration_approval_requested",
        "event.registration_approved",
        "event.registration_rejected",
    }


def test_rejected_registration_is_terminal_and_not_refunded():
    event = make_event(
        make_space("approval-rejected"), registration_requires_approval=True
    )
    registration = services.reject_registration(
        register(event, "rejected@example.test"), actor=None
    )
    with pytest.raises(RegistrationRejected):
        register(event, "rejected@example.test")
    with pytest.raises(EventInvalidTransition):
        services.cancel_registration(registration)


def test_approval_events_never_auto_promote_and_manual_promotion_rechecks_capacity(
    monkeypatch,
):
    event = make_event(
        make_space("approval-promotion"),
        capacity=1,
        registration_requires_approval=True,
    )
    confirmed = make_registration(event, "held@example.test")
    oldest = make_registration(event, "old@example.test", "waitlisted")
    selected = make_registration(event, "selected@example.test", "waitlisted")
    payment_calls = []
    monkeypatch.setattr(
        "apps.events.services_registration_state.create_for_registered_registration",
        lambda registration, actor: payment_calls.append(registration.pk),
    )
    services.cancel_registration(confirmed)
    oldest.refresh_from_db()
    assert oldest.status == EventRegistration.Status.WAITLISTED

    promoted = services.promote_registration(selected, actor=None)
    assert promoted.status == EventRegistration.Status.REGISTERED
    assert payment_calls == [selected.pk]
    with pytest.raises(CapacityConflict):
        services.promote_registration(oldest, actor=None)
    log = AuditLog.objects.get(action="event.registration_promoted")
    assert log.meta["promotion_mode"] == "manual"


@pytest.mark.django_db(transaction=True)
def test_two_approvals_for_last_place_serialize():
    event = make_event(
        make_space("approval-concurrency"),
        capacity=1,
        registration_requires_approval=True,
    )
    registrations = [
        make_registration(event, f"pending-{index}@example.test", "pending_approval")
        for index in range(2)
    ]
    barrier = Barrier(2)

    def approve(registration_id):
        close_old_connections()
        barrier.wait()
        try:
            row = EventRegistration.objects.get(pk=registration_id)
            return services.approve_registration(row, actor=None).status
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(approve, [row.pk for row in registrations]))
    assert sorted(statuses) == ["registered", "waitlisted"]


def test_approval_endpoints_are_scoped_and_documented():
    space = make_space("approval-api")
    manager = make_user("approval-api-manager")
    grant(manager, space)
    event = make_event(space, registration_requires_approval=True)
    registration = make_registration(event, "api@example.test", "pending_approval")
    client = client_for(manager)
    response = client.post(
        reverse("admin-event-registration-approve", kwargs={"pk": registration.pk}),
        {},
        format="json",
    )
    assert response.status_code == 200
    assert response.data["status"] == EventRegistration.Status.REGISTERED

    outsider = client_for(make_user("approval-api-outsider"))
    assert outsider.post(
        reverse("admin-event-registration-reject", kwargs={"pk": registration.pk}),
        {}, format="json",
    ).status_code == 404

    factory = APIRequestFactory()
    for name in (
        "admin-event-registration-approve",
        "admin-event-registration-reject",
        "admin-event-registration-promote",
    ):
        url = reverse(name, kwargs={"pk": registration.pk})
        match = resolve(url)
        request = factory.post(url)
        request.resolver_match = match
        view = match.func.view_class(**match.func.view_initkwargs)
        view.kwargs = match.kwargs
        assert origin_scope._target_makerspace_id(request, view) == space.pk

    schema = SchemaGenerator().get_schema(request=None, public=True)
    for action in ("approve", "reject", "promote"):
        path = f"/api/v1/admin/event-registrations/{{id}}/{action}/"
        assert "post" in schema["paths"][path]


def test_public_cutoff_and_pending_status_are_typed():
    space = make_space("approval-public")
    event = make_event(
        space,
        registration_requires_approval=True,
        registration_cutoff_at=timezone.now() - timedelta(seconds=1),
    )
    _member, client = active_member_client(space, "approval-public-member")
    url = reverse(
        "public-event-register",
        kwargs={"makerspace_slug": space.slug, "public_token": event.public_token},
    )
    closed = client.post(url, {}, format="json")
    assert closed.status_code == 409
    assert closed.data["code"] == "registration_closed"

    event.registration_cutoff_at = None
    event.save(update_fields=["registration_cutoff_at"])
    pending = client.post(url, {}, format="json")
    assert pending.status_code == 201
    assert pending.data == {"status": EventRegistration.Status.PENDING_APPROVAL}
