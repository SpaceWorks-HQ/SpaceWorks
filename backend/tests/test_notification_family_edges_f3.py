"""Existing domain edges emit once after commit; timers are left to F1."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from apps.integrations import notify
from apps.integrations.destinations import NotificationScope
from apps.integrations.email_templates_registry_helpers import bag
from apps.integrations.models import NotificationPreference
from apps.integrations.notifications_research import notify_family
from apps.integrations.staff_notifications import staff_emails_for_feature, staff_user_ids_for_feature
from apps.machines.models import Machine
from apps.machines.service_consumable_pools import correct_pool, create_pool
from apps.makerspaces import membership_services
from apps.makerspaces.models import MakerspaceRole, MembershipRequest, MembershipTerm, MakerspaceMembership
from apps.payments.models import Payment, Refund
from apps.payments.reconciliation import mark_offline, waive
from apps.payments.services import create_payment
from apps.payments.services_refunds import settle_refund
from apps.payments.services_webhooks import apply_webhook_event, apply_razorpay_webhook_event
from apps.procurement.models import ToBuyItem
from tests.machines.certification_helpers import _certification, _machine_type, _manager, _member
from tests.module_helpers import disable_module
from tests.return_helpers import authenticated_client, make_user, settlement_details
from tests.test_notification_families_f3 import family_world, capture_delivery

pytestmark = pytest.mark.django_db


def captured_events(monkeypatch):
    events = []
    monkeypatch.setattr(notify, "_run_guarded", lambda ms, feature, event, build, sync, occurred_at=None, event_key=None:
                        events.append((feature, event)))
    return events


def payment_term(space, member):
    from tests.makerspaces.test_membership_plans import plan
    now = timezone.now()
    return MembershipTerm.objects.create(
        membership=MakerspaceMembership.objects.get(makerspace=space, user=member),
        plan=plan(space), starts_at=now, ends_at=now + timedelta(days=30),
    )


def test_charge_creation_and_offline_settlement_emit_only_after_commit(monkeypatch, django_capture_on_commit_callbacks):
    space, manager, member, _row = family_world("f3-charge-edge")
    events = captured_events(monkeypatch)
    with django_capture_on_commit_callbacks(execute=True):
        with transaction.atomic():
            payment = create_payment(makerspace=space, member=member, created_by=manager,
                                     subject_type="membership_term", subject_id=payment_term(space, member).pk,
                                     amount=Decimal("20.00"), currency="usd")
            assert events == []
    assert events == [("payments", "charge_raised")]
    with django_capture_on_commit_callbacks(execute=True):
        mark_offline(payment, manager, settlement_details())
        mark_offline(payment, manager, settlement_details())
        assert len(events) == 1
    assert events == [("payments", "charge_raised"), ("payments", "payment_received")]


@pytest.mark.parametrize("provider", ["stripe", "razorpay"])
def test_online_settlement_is_idempotent_at_payment_edge(monkeypatch, django_capture_on_commit_callbacks, provider):
    from apps.payments.providers.base import WebhookEvent
    space, _manager, _member, payment = family_world(f"f3-online-{provider}")
    Payment.objects.filter(pk=payment.pk).update(
        provider=provider, stripe_payment_intent_id="pi_f3", external_order_id="order_f3",
    )
    events = captured_events(monkeypatch)
    if provider == "stripe":
        apply = lambda: apply_webhook_event(space, {
            "id": "evt_f3", "type": "payment_intent.succeeded", "data": {"object": {"id": "pi_f3"}},
        })
    else:
        apply = lambda: apply_razorpay_webhook_event(space, WebhookEvent(
            event_id="evt_f3", is_paid=True, order_id="order_f3", payment_id="pay_f3",
        ))
    with django_capture_on_commit_callbacks(execute=True):
        assert apply() is not None
        assert apply() is None
        assert events == []
    assert events == [("payments", "payment_received")]


def test_waiver_does_not_emit_payment_received(monkeypatch, django_capture_on_commit_callbacks):
    _space, manager, _member, payment = family_world("f3-waive")
    events = captured_events(monkeypatch)
    with django_capture_on_commit_callbacks(execute=True):
        waive(payment, manager)
    assert events == []


@pytest.mark.parametrize("provider", ["stripe", "razorpay"])
def test_late_online_receipt_emits_once_when_waiver_becomes_real_payment(monkeypatch, django_capture_on_commit_callbacks, provider):
    from apps.payments.providers.base import WebhookEvent
    space, manager, member, _pending = family_world(f"f3-late-{provider}")
    payment = Payment.objects.create(
        makerspace=space, member=member, created_by=manager,
        subject_type="membership_term", subject_id=payment_term(space, member).pk,
        amount="20.00", currency="usd", status="waived", provider=provider,
        stripe_payment_intent_id="pi_f3_late", external_order_id="order_f3_late",
    )
    events = captured_events(monkeypatch)
    with django_capture_on_commit_callbacks(execute=True):
        for event_id in ("evt_f3_late_1", "evt_f3_late_2"):
            if provider == "stripe":
                apply_webhook_event(space, {
                    "id": event_id, "type": "payment_intent.succeeded",
                    "data": {"object": {"id": "pi_f3_late"}},
                })
            else:
                apply_razorpay_webhook_event(space, WebhookEvent(
                    event_id=event_id, is_paid=True, order_id="order_f3_late", payment_id="pay_f3_late",
                ))
        assert events == []
    payment.refresh_from_db()
    assert payment.status == "paid_online"
    assert events == [("payments", "payment_received")]


def test_successful_refund_emits_once_and_pending_or_failed_do_not(monkeypatch, django_capture_on_commit_callbacks):
    space, manager, _member, payment = family_world("f3-refund")
    # Terminal row at creation avoids bypassing the immutable payment trigger.
    paid = Payment.objects.create(makerspace=space, member=manager, created_by=manager, subject_type="membership_term",
                                  subject_id=payment_term(space, manager).pk, amount="20.00", currency="usd", status="paid_online")
    refund = Refund.objects.create(payment=paid, amount="5.00", currency="usd", provider="stripe", created_by=manager)
    events = captured_events(monkeypatch)
    with django_capture_on_commit_callbacks(execute=True):
        settle_refund(refund, external_refund_id="re_f3", status="pending", actor=manager)
        settle_refund(refund, external_refund_id="re_f3", status="succeeded", actor=manager)
        settle_refund(refund, external_refund_id="re_f3", status="succeeded", actor=manager)
    assert events == [("payments", "refund_issued")]
    failed = Refund.objects.create(payment=paid, amount="1.00", currency="usd", provider="stripe", created_by=manager)
    with django_capture_on_commit_callbacks(execute=True):
        settle_refund(failed, external_refund_id="re_failed", status="failed", actor=manager)
    assert events == [("payments", "refund_issued")]


def test_offline_refund_emits_after_receipt_transaction(monkeypatch, django_capture_on_commit_callbacks):
    from apps.payments.services_refunds_offline import record_offline_refund
    space, manager, member, _payment = family_world("f3-manual-refund")
    paid = Payment.objects.create(makerspace=space, member=member, created_by=manager, subject_type="membership_term",
                                  subject_id=payment_term(space, member).pk, amount="10.00", currency="usd", status="paid_offline")
    events = captured_events(monkeypatch)
    with django_capture_on_commit_callbacks(execute=True):
        refund = record_offline_refund(paid, actor=manager, amount="5.00", reason="Deposit release",
                                       receipt={"method": "cash", "reference": "refund-1",
                                                "refunded_at": timezone.now()})
        assert refund.status == "succeeded" and events == []
    assert events == [("payments", "refund_issued")]


def test_membership_decisions_extend_existing_events_and_preserve_welcome(monkeypatch, django_capture_on_commit_callbacks):
    space, manager, _member, _payment = family_world("f3-member-edge")
    member = make_user("f3-applicant", access_status="active")
    request = MembershipRequest.objects.create(makerspace=space, user=member, invite_email=member.email,
                                               kind="request", state="requested")
    role = MakerspaceRole.objects.get(makerspace=space, slug="member")
    events = captured_events(monkeypatch)
    welcome = []
    monkeypatch.setattr("apps.makerspaces.membership_notifications.send_makerspace_email",
                        lambda *args, **kwargs: welcome.append((args, kwargs)))
    with django_capture_on_commit_callbacks(execute=True):
        membership_services.approve_request(manager, request, role)
        assert events == []
    assert ("members", "approved") in events and ("members", "member_joined") in events
    assert len(welcome) == 1 and welcome[0][0][3] == [member.email]
    assert welcome[0][1]["event"] == "approved"
    declined_member = make_user("f3-declined", access_status="active")
    declined = MembershipRequest.objects.create(makerspace=space, user=declined_member,
                                                invite_email=declined_member.email, kind="request", state="requested")
    with django_capture_on_commit_callbacks(execute=True):
        membership_services.revoke_request(manager, declined)
        membership_services.revoke_request(manager, declined)
    assert events.count(("members", "declined")) == 1


def test_low_stock_emits_once_per_existing_restock_edge(monkeypatch, django_capture_on_commit_callbacks):
    space, manager, _member, _payment = family_world("f3-stock-edge")
    pool = create_pool(space, manager, material="PLA", color="Blue", initial_grams="100", low_threshold_grams="50")
    events = captured_events(monkeypatch)
    with django_capture_on_commit_callbacks(execute=True):
        correct_pool(pool, manager, quantity_delta="-50", reason="Usage")
        correct_pool(pool, manager, quantity_delta="-1", reason="More usage")
        assert events == []
    assert events == [("stock", "low_stock")]
    item = ToBuyItem.objects.get(source_pool=pool)
    with django_capture_on_commit_callbacks(execute=True):
        response = authenticated_client(manager).patch(f"/api/v1/procurement/to-buy/{item.pk}",
                                                       {"status": "received"}, format="json")
        assert response.status_code == 200, response.data
    assert events == [("stock", "low_stock"), ("stock", "procurement_received")]
    with django_capture_on_commit_callbacks(execute=True):
        response = authenticated_client(manager).patch(f"/api/v1/procurement/to-buy/{item.pk}",
                                                       {"status": "received"}, format="json")
        assert response.status_code == 200, response.data
    assert events.count(("stock", "procurement_received")) == 1


def test_certification_http_edges_emit_granted_and_revoked(monkeypatch, django_capture_on_commit_callbacks):
    space, _staff, _member_user, _payment = family_world("f3-cert-edge")
    machine_type = _machine_type(space)
    manager, _role = _manager(space, "f3-cert-manager", machine_type)
    _member_user, membership = _member(space, "f3-cert-owner")
    certification = _certification(space, machine_type)
    events = captured_events(monkeypatch)
    client = authenticated_client(manager)
    with django_capture_on_commit_callbacks(execute=True):
        granted = client.post(reverse("admin-certification-type-grants", args=[certification.pk]),
                              {"membership_id": membership.pk}, format="json")
        assert granted.status_code == 201, granted.data
        assert events == []
    with django_capture_on_commit_callbacks(execute=True):
        revoked = client.post(reverse("admin-certification-grant-revoke", args=[granted.data["id"]]),
                              {}, format="json")
        assert revoked.status_code == 200, revoked.data
    assert events == [("certifications", "granted"), ("certifications", "revoked")]


def test_type_only_notification_scope_excludes_other_machine_types():
    space, _manager_user, _member, _payment = family_world("f3-type-scope")
    laser, printer = _machine_type(space, "Laser"), _machine_type(space, "Printer")
    manager, _role = _manager(space, "f3-laser-only", laser)
    _manager(space, "f3-printer-only", printer)
    scope = NotificationScope(machine_type=laser)
    emails = staff_emails_for_feature(space, "certifications", event="granted", scope=scope)
    ids = staff_user_ids_for_feature(space, "certifications", event="granted", scope=scope)
    assert manager.email in emails and manager.pk in ids
    assert "f3-printer-only@e.com" not in emails


@pytest.mark.parametrize("feature,event", [
    ("members", "declined"),
    ("stock", "low_stock"), ("certifications", "granted"),
])
def test_each_family_module_off_suppresses_delivery(monkeypatch, django_capture_on_commit_callbacks, feature, event):
    from apps.integrations.recipients_selection import FEATURE_MODULES
    space, _manager, member, _payment = family_world(f"f3-gate-{feature}")
    NotificationPreference.objects.create(makerspace=space, feature=feature, channel="email", enabled=True)
    emails, channels = capture_delivery(monkeypatch)
    with django_capture_on_commit_callbacks(execute=True):
        notify_family(space, feature, event, bag(id=12, name="Test", status="pending", expires_at=""),
                      data={}, member_id=member.pk)
        disable_module(space, FEATURE_MODULES[feature])
    assert emails == [] and channels == []


def test_existing_maintenance_log_edge_and_module_gate(monkeypatch, django_capture_on_commit_callbacks):
    from apps.maintenance.services_workflows import log_maintenance
    space, manager, _member, _payment = family_world("f3-maintenance")
    machine_type = _machine_type(space)
    machine = Machine.objects.create(makerspace=space, machine_type=machine_type, name="Laser")
    events = captured_events(monkeypatch)
    with django_capture_on_commit_callbacks(execute=True):
        log_maintenance(machine, actor=manager, summary="Cleaned optics")
    assert events == [("maintenance", "logged")]
    monkeypatch.undo()
    emails, channels = capture_delivery(monkeypatch)
    NotificationPreference.objects.create(makerspace=space, feature="maintenance", channel="email", enabled=True)
    with django_capture_on_commit_callbacks(execute=True):
        log_maintenance(machine, actor=manager, summary="Replaced optics")
        disable_module(space, "maintenance")
    assert emails == [] and channels == []
