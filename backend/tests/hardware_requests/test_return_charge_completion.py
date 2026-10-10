"""Charge timing at the shared request-close seam."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.evidence.storage import EvidenceValidationResult
from apps.hardware_requests import loan_payments, workflow
from apps.hardware_requests.models import HardwareRequest
from apps.payments.models import Payment
from tests.hardware_requests.test_loan_payments import loan_payment, loan_space
from tests.return_helpers import make_issued_request, make_product, make_return_evidence, return_payload

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def quiet_external_services(monkeypatch):
    monkeypatch.setattr(
        "apps.evidence.storage.finalize_upload",
        lambda evidence, max_bytes: EvidenceValidationResult(size=123, content_type="image/png"),
    )
    monkeypatch.setattr(loan_payments, "create_checkout", lambda payment: None)


def test_partial_return_waits_until_all_units_are_resolved(django_capture_on_commit_callbacks):
    makerspace, staff = loan_space(
        "charge-partial", loan_late_fee_per_day=Decimal("2.00"),
        loan_deposit_mode="fixed", loan_deposit_amount=Decimal("5.00"),
    )
    request = make_issued_request(makerspace, staff, [(make_product(makerspace), 2)])
    request.return_due_at = timezone.now() - timedelta(days=3)
    request.save(update_fields=["return_due_at"])
    deposit = loan_payments.raise_deposit(request.pk, staff)

    for expected in [HardwareRequest.Status.PARTIALLY_RETURNED, HardwareRequest.Status.RETURNED]:
        payload = return_payload(request, make_return_evidence(makerspace, staff))
        payload["resolutions"][0]["returned"] = 1
        with django_capture_on_commit_callbacks(execute=True):
            request = workflow.return_items(
                staff, request, payload["evidence_id"], payload["remark"],
                payload["box_code"], payload["resolutions"],
            )
        assert request.status == expected
        deposit.refresh_from_db()
        fee = loan_payment(request, Payment.SubjectType.LOAN_LATE_FEE)
        if expected == HardwareRequest.Status.PARTIALLY_RETURNED:
            assert fee is None
            assert deposit.status == Payment.Status.PENDING
        else:
            assert fee is not None
            assert deposit.status == Payment.Status.CANCELED


def test_delayed_close_callback_uses_recorded_return_time():
    makerspace, staff = loan_space("charge-delayed", loan_late_fee_per_day=Decimal("2.00"))
    request = make_issued_request(makerspace, staff, [(make_product(makerspace), 1)])
    request.status = HardwareRequest.Status.RETURNED
    request.closed_at = timezone.now() - timedelta(days=10)
    request.return_due_at = request.closed_at - timedelta(hours=25)
    request.save(update_fields=["status", "closed_at", "return_due_at"])

    loan_payments.on_request_closed(request.pk, staff)

    assert loan_payment(request, Payment.SubjectType.LOAN_LATE_FEE).amount == Decimal("4.00")
