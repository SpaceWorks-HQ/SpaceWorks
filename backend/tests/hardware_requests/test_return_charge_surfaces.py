"""Self-service and counter returns share reviewed-loan charge handling."""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import Mock

import pytest
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.boxes.models import QrCode
from apps.evidence.storage import EvidenceValidationResult
from apps.hardware_requests import loan_payments
from apps.hardware_requests.models import HardwareRequest, PublicToolLoan
from apps.payments.models import MakerspacePaymentSettings, Payment
from apps.payments.reconciliation import mark_offline
from tests.return_helpers import (
    authenticated_client,
    make_issue_evidence,
    make_member,
    make_product,
    make_return_evidence,
    make_space,
    settlement_details,
)
from tests.test_public_self_checkout import eligible_member

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def quiet_external_services(monkeypatch, settings):
    settings.API_CLIENT_AUTH_REQUIRED = False
    monkeypatch.setattr(
        "apps.evidence.storage.finalize_upload",
        lambda evidence, max_bytes: EvidenceValidationResult(size=123, content_type="image/png"),
    )
    monkeypatch.setattr(loan_payments, "create_checkout", Mock())


@pytest.fixture(params=["self_checkout", "direct_handout"])
def loan_case(request):
    surface = request.param
    makerspace = make_space(f"return-charges-{surface}")
    staff = make_member(f"{surface}-staff", makerspace)
    borrower = eligible_member(makerspace, username=f"{surface}-borrower")
    makerspace.enabled_features = sorted(set(makerspace.enabled_features) | {
        "charges.enabled", "charges.loans", "payments.enabled", "payments.loans",
    })
    # No rail: debt must still be recorded and returned tools remain available.
    makerspace.enabled_modules = [key for key in makerspace.enabled_modules if key != "payments"]
    makerspace.save(update_fields=["enabled_features", "enabled_modules", "updated_at"])
    payment_settings = MakerspacePaymentSettings.for_makerspace(makerspace)
    payment_settings.loan_late_fee_per_day = Decimal("2.00")
    payment_settings.loan_late_fee_cap = Decimal("15.00")
    payment_settings.loan_grace_days = 1
    payment_settings.loan_deposit_mode = MakerspacePaymentSettings.LoanDepositMode.FIXED
    payment_settings.loan_deposit_amount = Decimal("5.00")
    payment_settings.save()
    product = make_product(makerspace, public_self_checkout_enabled=True)
    qr = QrCode.objects.create(
        makerspace=makerspace, target_type=QrCode.TargetType.PRODUCT, target_id=product.pk,
    )
    actor = borrower if surface == "self_checkout" else staff
    evidence = make_issue_evidence(makerspace, actor)
    client = authenticated_client(actor)
    if surface == "self_checkout":
        url = f"/api/v1/public/{makerspace.slug}/tools/checkout"
        body = {"payload": qr.payload, "evidence_id": evidence.pk, "remark": "Taken."}
    else:
        url = f"/api/v1/admin/makerspace/{makerspace.pk}/direct-loans"
        body = {"borrower_id": borrower.pk, "qr_payloads": [qr.payload], "evidence_id": evidence.pk}
    response = client.post(url, body, format="json")
    assert response.status_code == 201, response.data
    loan = PublicToolLoan.objects.get(makerspace=makerspace)
    return surface, makerspace, staff, actor, loan, product, qr


def return_loan(case):
    surface, makerspace, _staff, actor, loan, _product, qr = case
    evidence = make_return_evidence(makerspace, actor)
    if surface == "self_checkout":
        url = f"/api/v1/public/{makerspace.slug}/tools/return"
        body = {"payload": qr.payload, "evidence_id": evidence.pk, "remark": "All checked."}
    else:
        url = f"/api/v1/admin/direct-loans/{loan.pk}/return"
        body = {
            "qr_payload": qr.payload, "evidence_id": evidence.pk, "notes": "All checked.",
            "resolutions": [{"item_id": loan.request.items.get().pk, "returned": 1}],
        }
    response = authenticated_client(actor).post(url, body, format="json")
    assert response.status_code == 200, response.data
    loan.refresh_from_db()
    loan.request.refresh_from_db()
    assert loan.status == PublicToolLoan.Status.RETURNED
    assert loan.return_evidence_id == evidence.pk
    assert loan.request.status == HardwareRequest.Status.RETURNED
    assert loan.request.closed_by_id == actor.pk
    case[5].refresh_from_db()
    assert (case[5].available_quantity, case[5].issued_quantity) == (10, 0)
    return response


def fee_for(loan):
    return Payment.objects.filter(
        makerspace=loan.makerspace, subject_type=Payment.SubjectType.LOAN_LATE_FEE,
        subject_id=loan.request_id,
    )


def set_due(loan, due):
    loan.request.return_due_at = due
    loan.request.save(update_fields=["return_due_at"])


@pytest.mark.parametrize("overdue, amount", [
    (timedelta(days=-1), None),
    (timedelta(hours=12), None),
    (timedelta(days=3, hours=2), Decimal("6.00")),
    (timedelta(days=10), Decimal("15.00")),
])
def test_return_fee_respects_grace_rounding_cap_and_no_rail(
    loan_case, overdue, amount, monkeypatch, django_capture_on_commit_callbacks,
):
    loan = loan_case[4]
    closed_at = timezone.now()
    set_due(loan, closed_at - overdue)
    monkeypatch.setattr(timezone, "now", lambda: closed_at)
    with django_capture_on_commit_callbacks(execute=True):
        return_loan(loan_case)
        assert not fee_for(loan).exists()  # Charge handling waits for commit.
    if amount is None:
        assert not fee_for(loan).exists()
        return
    fee = fee_for(loan).get()
    assert (fee.amount, fee.status, fee.provider) == (amount, Payment.Status.PENDING, "unclaimed")
    assert fee.member_id == loan.requester_id
    assert fee.makerspace_id == loan.makerspace_id
    assert AuditLog.objects.filter(action="loan.late_fee_raised", actor=loan_case[3]).count() == 1
    assert not fee.checkout_url
    loan_payments.create_checkout.assert_not_called()
    loan_payments.on_request_closed(loan.request_id, loan_case[3], now=closed_at + timedelta(days=30))
    assert fee_for(loan).count() == 1
    assert fee_for(loan).get().amount == amount


@pytest.mark.parametrize("paid", [False, True])
def test_return_cancels_only_uncollected_deposit(
    loan_case, paid, django_capture_on_commit_callbacks,
):
    _surface, _makerspace, staff, _actor, loan, _product, _qr = loan_case
    deposit = loan_payments.raise_deposit(loan.request_id, staff)
    if paid:
        mark_offline(deposit, staff, settlement=settlement_details())
    with django_capture_on_commit_callbacks(execute=True):
        return_loan(loan_case)
    deposit.refresh_from_db()
    assert deposit.status == (Payment.Status.PAID_OFFLINE if paid else Payment.Status.CANCELED)
    assert AuditLog.objects.filter(action="payment.canceled", target_id=str(deposit.pk)).count() == (
        0 if paid else 1
    )


@pytest.mark.parametrize("disabled", ["charges.enabled", "charges.loans"])
def test_return_respects_charge_switches(loan_case, disabled, django_capture_on_commit_callbacks):
    makerspace, loan = loan_case[1], loan_case[4]
    makerspace.enabled_features.remove(disabled)
    makerspace.save(update_fields=["enabled_features", "updated_at"])
    set_due(loan, timezone.now() - timedelta(days=10))
    with django_capture_on_commit_callbacks(execute=True):
        return_loan(loan_case)
    assert not fee_for(loan).exists()


def test_checkout_failure_preserves_fee_and_return(
    loan_case, monkeypatch, django_capture_on_commit_callbacks,
):
    makerspace, loan = loan_case[1], loan_case[4]
    makerspace.enabled_modules.append("payments")
    makerspace.save(update_fields=["enabled_modules", "updated_at"])
    payment_settings = MakerspacePaymentSettings.for_makerspace(makerspace)
    payment_settings.set_stripe_secret_key("sk_test_secret")
    payment_settings.set_stripe_webhook_secret("whsec_test_secret")
    payment_settings.save()
    set_due(loan, timezone.now() - timedelta(days=10))

    def unavailable(payment):
        # The ledger row exists before any provider I/O.
        assert fee_for(loan).get().pk == payment.pk
        raise RuntimeError("provider unavailable")

    checkout = Mock(side_effect=unavailable)
    monkeypatch.setattr(loan_payments, "create_checkout", checkout)
    with django_capture_on_commit_callbacks(execute=True):
        return_loan(loan_case)
    checkout.assert_called_once()
    assert fee_for(loan).get().amount == Decimal("15.00")


def test_charge_recording_failure_does_not_block_return(
    loan_case, monkeypatch, django_capture_on_commit_callbacks,
):
    set_due(loan_case[4], timezone.now() - timedelta(days=10))
    monkeypatch.setattr(loan_payments, "create_payment", Mock(side_effect=RuntimeError("ledger unavailable")))
    with django_capture_on_commit_callbacks(execute=True):
        return_loan(loan_case)
    assert not fee_for(loan_case[4]).exists()


def test_return_rollback_does_not_charge(loan_case, django_capture_on_commit_callbacks):
    from django.db import transaction

    set_due(loan_case[4], timezone.now() - timedelta(days=10))
    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        with pytest.raises(RuntimeError, match="rollback"):
            with transaction.atomic():
                return_loan(loan_case)
                raise RuntimeError("rollback")
    assert callbacks == []
    assert not fee_for(loan_case[4]).exists()
    loan_case[4].refresh_from_db()
    assert loan_case[4].status == PublicToolLoan.Status.CHECKED_OUT
