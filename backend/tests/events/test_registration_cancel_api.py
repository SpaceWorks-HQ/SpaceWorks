"""HTTP cancellation must reach the real transactional registration/money workflow."""

from decimal import Decimal

import pytest
from django.urls import resolve, reverse
from django.utils import timezone
from drf_spectacular.generators import SchemaGenerator
from rest_framework.test import APIClient, APIRequestFactory
from rest_framework.exceptions import ValidationError

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.events import services
from apps.makerspaces import origin_scope
from apps.makerspaces.models import MakerspaceMembership, MakerspaceWaiver
from apps.payments.models import Payment
from apps.payments.reconciliation import mark_offline, waive
from tests.events.collab_helpers import (
    client_for, collaborate, make_event, make_member, make_space, make_staff,
)

pytestmark = pytest.mark.django_db


def cancel_url(space, registration, *, staff=False):
    name = "admin-event-registration-cancel" if staff else "member-event-registration-cancel"
    kwargs = {"pk": registration.pk}
    if not staff:
        kwargs["makerspace_id"] = space.pk
    return reverse(name, kwargs=kwargs)


def register(event, member, **kwargs):
    return services.register(event, member=member, actor=member, staff_registration=True, **kwargs)


def enable_charges(space):
    space.enabled_features = ["charges.enabled", "charges.events"]
    space.save(update_fields=["enabled_features"])


@pytest.mark.parametrize("staff", [False, True])
def test_cancel_releases_real_pending_charge_promotes_fifo_and_audits(staff):
    space = make_space("cancel-money")
    enable_charges(space)
    event = make_event(space, is_public=True)
    event.capacity, event.payment_amount = 1, Decimal("12.50")
    event.save(update_fields=["capacity", "payment_amount"])
    first, second, third = [make_member(space, name) for name in ("first", "second", "third")]
    confirmed, waiting, last = [register(event, member) for member in (first, second, third)]
    payment = Payment.objects.get(subject_id=confirmed.pk, subject_type="event_registration")
    assert payment.status == Payment.Status.PENDING
    actor = make_staff(space) if staff else first

    response = client_for(actor).post(cancel_url(space, confirmed, staff=staff), {}, format="json")

    assert response.status_code == 200 and response.data["status"] == "cancelled"
    confirmed.refresh_from_db()
    waiting.refresh_from_db()
    last.refresh_from_db()
    payment.refresh_from_db()
    assert (confirmed.status, waiting.status, last.status) == ("cancelled", "registered", "waitlisted")
    assert payment.status == Payment.Status.CANCELED
    assert Payment.objects.get(subject_id=waiting.pk, subject_type="event_registration").status == "pending"
    log = AuditLog.objects.get(action="event.registration_cancelled")
    assert log.actor == actor and log.makerspace == space
    assert log.meta == {"registration_id": confirmed.pk, "old_status": "registered"}
    assert AuditLog.objects.get(action="payment.canceled").actor == actor
    assert AuditLog.objects.get(action="event.registration_promoted").actor == actor
    assert first.email not in str(log.meta)


@pytest.mark.parametrize("state", ["pending_approval", "waitlisted"])
def test_member_can_cancel_unconfirmed_registration_without_presence_or_new_waiver(state):
    space = make_space("cancel-unconfirmed")
    member = make_member(space)
    event = make_event(space)
    registration = register(event, member)
    registration.status = state
    registration.save(update_fields=["status"])
    MakerspaceWaiver.objects.create(makerspace=space, version="new", body="Updated terms")
    response = client_for(member).post(cancel_url(space, registration), {}, format="json")
    assert response.status_code == 200 and response.data == {"status": "cancelled"}
    assert not Payment.objects.filter(subject_id=registration.pk).exists()


@pytest.mark.parametrize("staff", [False, True])
@pytest.mark.parametrize("state", ["cancelled", "rejected", "attended"])
def test_terminal_cancellation_conflicts_without_another_audit(staff, state):
    space = make_space("cancel-terminal")
    member = make_member(space)
    registration = register(make_event(space), member)
    registration.status = state
    registration.save(update_fields=["status"])
    actor = make_staff(space) if staff else member
    response = client_for(actor).post(cancel_url(space, registration, staff=staff), {}, format="json")
    assert response.status_code == 409
    assert not AuditLog.objects.filter(action="event.registration_cancelled").exists()


def test_member_cannot_cancel_someone_else_even_with_matching_email_or_wrong_space():
    space, other = make_space("cancel-own"), make_space("cancel-other")
    owner, intruder = make_member(space, "owner"), make_member(space, "intruder")
    make_member(other, user=owner)
    registration = register(make_event(space), owner)
    # Emails are unique per account, so "matching email" means the registration's contact
    # address names the intruder: ownership must follow the member, never the email.
    registration.email = intruder.email
    registration.save()
    assert client_for(intruder).post(cancel_url(space, registration), {}, format="json").status_code == 404
    assert client_for(owner).post(cancel_url(other, registration), {}, format="json").status_code == 404
    assert APIClient().post(cancel_url(space, registration), {}, format="json").status_code == 401
    assert not AuditLog.objects.filter(action="event.registration_cancelled").exists()


def test_member_status_and_staff_scope_are_enforced():
    space, other = make_space("cancel-permissions"), make_space("cancel-foreign")
    member = make_member(space)
    registration = register(make_event(space), member)
    foreign_staff = make_staff(other)
    assert client_for(foreign_staff).post(cancel_url(space, registration, staff=True), {}, format="json").status_code == 404
    assert client_for(member).post(cancel_url(space, registration, staff=True), {}, format="json").status_code == 403
    member.access_status = User.AccessStatus.RESTRICTED
    member.save(update_fields=["access_status"])
    assert client_for(member).post(cancel_url(space, registration), {}, format="json").status_code == 403
    member.access_status = User.AccessStatus.ACTIVE
    member.save(update_fields=["access_status"])
    MakerspaceMembership.objects.filter(user=member, makerspace=space).update(status="revoked")
    assert client_for(member).post(cancel_url(space, registration), {}, format="json").status_code == 403


def test_legacy_null_provenance_is_cancellable_only_through_the_host():
    space = make_space("cancel-legacy-provenance")
    member = make_member(space)
    registration = register(make_event(space), member)
    registration.registered_via_makerspace = None
    registration.save(update_fields=["registered_via_makerspace"])
    assert client_for(member).post(cancel_url(space, registration), {}, format="json").status_code == 200


@pytest.mark.parametrize("staff", [False, True])
def test_module_off_and_unexpected_body_refuse_without_side_effects(staff):
    space = make_space("cancel-disabled")
    member = make_member(space)
    registration = register(make_event(space), member)
    actor = make_staff(space) if staff else member
    client, url = client_for(actor), cancel_url(space, registration, staff=staff)
    assert client.post(url, {"status": "cancelled"}, format="json").status_code == 400
    space.enabled_modules = [key for key in space.enabled_modules if key != "events"]
    space.save(update_fields=["enabled_modules"])
    assert client.post(url, {}, format="json").status_code == 400
    registration.refresh_from_db()
    assert registration.status == "registered"
    assert not AuditLog.objects.filter(action="event.registration_cancelled").exists()


def test_cancellation_service_rechecks_a_disabled_module_before_mutating():
    space = make_space("cancel-locked-module")
    member = make_member(space)
    registration = register(make_event(space), member)
    space.enabled_modules = [key for key in space.enabled_modules if key != "events"]
    space.save(update_fields=["enabled_modules"])
    with pytest.raises(ValidationError):
        services.cancel_registration(registration, actor=member)
    registration.refresh_from_db()
    assert registration.status == "registered"
    assert not AuditLog.objects.filter(action="event.registration_cancelled").exists()


def test_collaborative_cancellation_survives_removed_collaboration_and_gates_host_module():
    host, partner = make_space("cancel-host"), make_space("cancel-partner")
    event = make_event(host)
    collaboration = collaborate(event, partner)
    member = make_member(partner)
    registration = register(event, member, via_makerspace=partner, collaborative=True)
    collaboration.delete()
    host.enabled_modules = [key for key in host.enabled_modules if key != "events"]
    host.save(update_fields=["enabled_modules"])
    client = client_for(member)
    assert client.post(cancel_url(partner, registration), {}, format="json").status_code == 400
    host.enabled_modules.append("events")
    host.save(update_fields=["enabled_modules"])
    assert client.post(cancel_url(partner, registration), {}, format="json").status_code == 200


@pytest.mark.parametrize("paid", [False, True])
def test_approval_event_does_not_auto_promote_and_terminal_money_is_retained(paid):
    space = make_space("cancel-approved")
    enable_charges(space)
    event = make_event(space)
    event.capacity, event.payment_amount, event.registration_requires_approval = 1, Decimal("5"), True
    event.save(update_fields=["capacity", "payment_amount", "registration_requires_approval"])
    member, waiter, staff = make_member(space), make_member(space, "waiter"), make_staff(space)
    confirmed = services.approve_registration(register(event, member), actor=staff)
    waiting = services.approve_registration(register(event, waiter), actor=staff)
    payment = Payment.objects.get(subject_id=confirmed.pk, subject_type="event_registration")
    if paid:
        mark_offline(payment, staff, settlement={
            "method": "cash", "reference": "desk", "received_at": timezone.now(),
        })
    else:
        waive(payment, staff)
    assert client_for(member).post(cancel_url(space, confirmed), {}, format="json").status_code == 200
    waiting.refresh_from_db()
    payment.refresh_from_db()
    assert waiting.status == "waitlisted"
    assert payment.status == (Payment.Status.PAID_OFFLINE if paid else Payment.Status.WAIVED)


def test_cancel_routes_have_schemas_and_correct_origin_scope():
    space = make_space("cancel-schema")
    member = make_member(space)
    registration = register(make_event(space), member)
    for staff in (False, True):
        url = cancel_url(space, registration, staff=staff)
        request = APIRequestFactory().post(url, {}, format="json")
        request.resolver_match = match = resolve(url)
        view = match.func.view_class(**match.func.view_initkwargs)
        view.kwargs = match.kwargs
        assert origin_scope._target_makerspace_id(request, view) == space.pk
    schema = SchemaGenerator().get_schema(request=None, public=True)
    for path in (
        "/api/v1/admin/event-registrations/{id}/cancel/",
        "/api/v1/member/makerspaces/{makerspace_id}/event-registrations/{id}/cancel/",
    ):
        operation = schema["paths"][path]["post"]
        assert {"200", "400", "401", "403", "404", "409"} <= set(operation["responses"])
        # The body is the field-less EmptyActionSerializer; drf-spectacular omits a
        # requestBody for a serializer with no fields, so absence is the documented shape.
        body = operation.get("requestBody")
        assert body is None or body["content"]["application/json"]["schema"]
