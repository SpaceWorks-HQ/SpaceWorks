"""Ledger settlement must not implicitly acquire admission's makerspace lock."""

from threading import Event, Thread
from types import SimpleNamespace

import pytest
from django.db import close_old_connections, transaction

from apps.makerspaces.models import Makerspace
from apps.payments import reconciliation
from apps.payments import services_checkout
from apps.payments.models import Payment
from tests.payments.test_admission_settlement import admission_charge
from tests.return_helpers import settlement_details

pytestmark = pytest.mark.django_db(transaction=True)


def test_checkout_reexport_preserves_scheduled_checkout_patch(monkeypatch):
    calls = []
    payment = SimpleNamespace(pk=123, created_by=None)
    monkeypatch.setattr(transaction, "on_commit", lambda callback: callback())
    monkeypatch.setattr(
        services_checkout, "create_checkout_url",
        lambda payment_id, **kwargs: calls.append((payment_id, kwargs["actor"])),
    )
    services_checkout.create_checkout(payment)
    assert calls == [(123, None)]


def test_offline_settlement_leaves_joined_makerspace_unlocked(monkeypatch):
    space, manager, request, payment = admission_charge()
    payment_locked = Event()
    release_payment = Event()
    results = {}

    def pause_after_payment_lock(_payment):
        payment_locked.set()
        assert release_payment.wait(10)

    monkeypatch.setattr(reconciliation, "_expire_checkout_best_effort", pause_after_payment_lock)
    # This test exercises transaction lock ownership; domain activation has its own
    # integration tests and must not acquire a second lock after this worker commits.
    monkeypatch.setattr(
        "apps.makerspaces.membership_admission_payments.resume_after_payment", lambda _id: None,
    )

    def settle():
        close_old_connections()
        try:
            row = reconciliation.reconcile_payments(
                actor=manager, makerspace_id=space.pk, payment_ids=[payment.pk],
                target_status=Payment.Status.PAID_OFFLINE, settlement=settlement_details(),
            )[0]
            results["status"] = row.status
        except Exception as exc:
            results["error"] = exc
        finally:
            close_old_connections()

    worker = Thread(target=settle)
    worker.start()
    try:
        assert payment_locked.wait(10)
        with transaction.atomic():
            # A generic FOR UPDATE on the payment's select_related join would lock
            # Makerspace too. NOWAIT proves that the admission lock remains available.
            Makerspace.objects.select_for_update(nowait=True).get(pk=space.pk)
    finally:
        release_payment.set()
        worker.join(10)
    assert not worker.is_alive()
    assert "error" not in results
    assert results["status"] == Payment.Status.PAID_OFFLINE
