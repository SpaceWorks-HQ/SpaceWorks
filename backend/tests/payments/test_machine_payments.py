from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import InternalError, transaction

from apps.machines.models import Machine, MachineServiceRequest, MachineType, MakerspaceMachineTypePricing
from apps.machines.service_workflow import accept, complete, start, submit
from apps.payments.models import Payment
from apps.payments.services import apply_webhook_event, mark_offline, waive
from tests.payments.test_models import configured_settings
from tests.return_helpers import make_member, make_space


pytestmark = pytest.mark.django_db


def service_request(space, actor, *, config=None):
    machine_type = MachineType.objects.create(makerspace=space, slug=f"charge-{space.pk}-{MachineType.objects.count()}", name="Chargeable", capability_config=config or {})
    machine = Machine.objects.create(makerspace=space, machine_type=machine_type, name="Chargeable machine")
    return submit(machine, actor, member=actor, actor=actor, requester_name=actor.username, contact_email=actor.email, contact_phone="", title="Paid service")


def payment_for(row, actor, *, amount="5.00"):
    return Payment.objects.create(makerspace=row.makerspace, subject_type=Payment.SubjectType.MACHINE_SERVICE_REQUEST, subject_id=row.pk, member=row.requester, amount=Decimal(amount), currency="usd", created_by=actor)


def test_payment_subject_is_unique_and_must_share_makerspace():
    space, other = make_space("c3-payment-subject"), make_space("c3-payment-other")
    actor = make_member("c3-payment-subject-user", space)
    row = service_request(space, actor)
    payment_for(row, actor)
    with pytest.raises(ValidationError):
        payment_for(row, actor)
    with pytest.raises(ValidationError):
        Payment.objects.create(makerspace=other, subject_type=Payment.SubjectType.MACHINE_SERVICE_REQUEST, subject_id=row.pk, member=actor, amount=Decimal("1"), currency="usd", created_by=actor)


def test_terminal_payment_is_immutable_and_reconciliation_is_audited():
    space = make_space("c3-payment-transition")
    actor = make_member("c3-payment-transition-user", space)
    payment = payment_for(service_request(space, actor), actor)
    assert mark_offline(payment, actor).status == Payment.Status.PAID_OFFLINE
    payment.amount = Decimal("9.00")
    with pytest.raises(ValidationError):
        payment.save()
    assert waive(payment, actor).status == Payment.Status.PAID_OFFLINE


def test_payment_delete_is_immutable_outside_purge():
    space = make_space("c3-payment-delete")
    actor = make_member("c3-payment-delete-user", space)
    paid = payment_for(service_request(space, actor), actor)
    pending = payment_for(service_request(space, actor), actor)
    mark_offline(paid, actor)

    for payment in (paid, pending):
        with pytest.raises(InternalError):
            with transaction.atomic():
                Payment.objects.filter(pk=payment.pk).delete()


def test_verified_webhook_is_idempotent_and_marks_matching_checkout_paid():
    space = make_space("c3-payment-webhook")
    space.enabled_features = ["payments.enabled", "payments.machines"]
    space.save(update_fields=["enabled_features", "updated_at"])
    configured_settings(space)
    actor = make_member("c3-payment-webhook-user", space)
    payment = payment_for(service_request(space, actor), actor)
    Payment.objects.filter(pk=payment.pk).update(stripe_checkout_session_id="cs_c3")
    event = {"id": "evt_c3", "type": "checkout.session.completed", "data": {"object": {"id": "cs_c3", "payment_status": "paid", "payment_intent": "pi_c3"}}}
    assert apply_webhook_event(space, event).status == Payment.Status.PAID_ONLINE
    assert apply_webhook_event(space, event) is None


def test_async_checkout_webhook_settles_matching_pending_payment():
    space = make_space("c3-payment-async-webhook")
    actor = make_member("c3-payment-async-webhook-user", space)
    payment = payment_for(service_request(space, actor), actor)
    Payment.objects.filter(pk=payment.pk).update(stripe_checkout_session_id="cs_c3_async")
    unpaid_completion = {"id": "evt_c3_unpaid", "type": "checkout.session.completed", "data": {"object": {"id": "cs_c3_async", "payment_status": "unpaid"}}}
    async_success = {"id": "evt_c3_async", "type": "checkout.session.async_payment_succeeded", "data": {"object": {"id": "cs_c3_async", "payment_intent": "pi_c3_async"}}}

    assert apply_webhook_event(space, unpaid_completion) is None
    payment.refresh_from_db()
    assert payment.status == Payment.Status.PENDING
    assert apply_webhook_event(space, async_success).status == Payment.Status.PAID_ONLINE
    assert apply_webhook_event(space, async_success) is None
    payment.refresh_from_db()
    assert payment.stripe_payment_intent_id == "pi_c3_async"


def test_completion_creates_payment_and_checkout_failure_never_blocks(monkeypatch):
    space = make_space("c3-payment-complete")
    space.enabled_features = ["payments.enabled", "payments.machines"]
    space.save(update_fields=["enabled_features", "updated_at"])
    configured_settings(space)
    actor = make_member("c3-payment-complete-user", space)
    row = service_request(space, actor, config={"metering_unit": "minutes", "requires_booking": False})
    MakerspaceMachineTypePricing.objects.create(
        makerspace=space, machine_type=row.assigned_machine.machine_type,
        rate_per_unit="1.00", flat_fee="2.00", payment_enabled=True,
    )
    monkeypatch.setattr("apps.machines.service_payments.create_checkout", lambda payment: (_ for _ in ()).throw(RuntimeError("stripe unavailable")))
    accept(row, actor)
    start(row, actor, machine_id=row.assigned_machine_id)
    assert complete(row, actor, actual_minutes=1, consumptions=[]).status == MachineServiceRequest.Status.COMPLETED
    payment = Payment.objects.get(subject_id=row.pk)
    assert (payment.amount, payment.currency) == (Decimal("3.00"), "usd")


def test_reconciliation_expires_an_open_checkout_session(monkeypatch):
    space = make_space("c3-payment-expire")
    actor = make_member("c3-payment-expire-user", space)
    payment = payment_for(service_request(space, actor), actor)
    configured_settings(space)
    Payment.objects.filter(pk=payment.pk).update(stripe_checkout_session_id="cs_expire")
    expired = []
    def expire(source, session_id):
        expired.append((source, session_id))
    monkeypatch.setattr("apps.payments.services.stripe_client.expire_checkout_session", expire)
    mark_offline(payment, actor)
    assert expired[0][0].provider == Payment.StripeProvider.RAW
    assert expired[0][0].connected_account_id is None
    assert expired[0][1] == "cs_expire"


def test_terminal_payment_webhook_is_audited_as_an_anomaly(monkeypatch):
    from apps.audit.models import AuditLog
    from apps.payments.models import ProcessedStripeEvent
    space = make_space("c3-payment-terminal-webhook")
    actor = make_member("c3-payment-terminal-webhook-user", space)
    payment = payment_for(service_request(space, actor), actor)
    Payment.objects.filter(pk=payment.pk).update(stripe_checkout_session_id="cs_terminal")
    monkeypatch.setattr("apps.payments.services.stripe_client.expire_checkout_session", lambda *_: None)
    mark_offline(payment, actor)
    event = {"id": "evt_terminal", "type": "checkout.session.completed", "data": {"object": {"id": "cs_terminal", "payment_status": "paid"}}}
    result = apply_webhook_event(space, event)
    assert result.status == Payment.Status.PAID_OFFLINE
    assert ProcessedStripeEvent.objects.filter(makerspace=space, stripe_event_id="evt_terminal").exists()
    assert AuditLog.objects.filter(action="payment.paid_after_terminal", target_id=str(payment.pk)).exists()


def test_member_can_generate_a_missing_checkout_url(monkeypatch):
    from rest_framework.test import APIClient
    space = make_space("c3-payment-regenerate")
    configured_settings(space)
    actor = make_member("c3-payment-regenerate-user", space)
    payment = payment_for(service_request(space, actor), actor)
    monkeypatch.setattr("apps.payments.services.member_area_url", lambda _: "https://space.example/member")
    monkeypatch.setattr("apps.payments.services.stripe_client.create_checkout_session", lambda *_args, **_kwargs: {"id": "cs_regenerated", "url": "https://checkout.stripe.test/cs_regenerated"})
    client = APIClient()
    client.force_authenticate(actor)
    response = client.post(f"/api/v1/member/makerspaces/{space.pk}/payments/{payment.pk}/checkout")
    assert response.status_code == 200
    assert response.data["checkout_url"] == "https://checkout.stripe.test/cs_regenerated"
    payment.refresh_from_db()
    assert payment.stripe_checkout_session_id == "cs_regenerated"
