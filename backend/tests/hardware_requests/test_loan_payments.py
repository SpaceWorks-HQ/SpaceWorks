"""`payments.loans`: deposits raised by the workflow at issue, late fees at close."""

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.boxes.models import BoxScan
from apps.evidence.storage import EvidenceValidationResult
from apps.hardware_requests import loan_payments, workflow
from apps.hardware_requests.models import HardwareRequest
from apps.payments.models import MakerspacePaymentSettings, Payment
from apps.payments.subjects import resolve_subject_labels, subject_label
from tests.payments.test_models import configured_settings
from tests.return_helpers import (
    authenticated_client,
    make_accepted_request,
    make_box,
    make_issue_evidence,
    make_issued_request,
    make_member,
    make_product,
    make_return_evidence,
    make_space,
    return_payload,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def quiet_storage_and_stripe(monkeypatch):
    monkeypatch.setattr(
        "apps.evidence.storage.finalize_upload",
        lambda evidence, max_bytes: EvidenceValidationResult(size=123, content_type="image/png"),
    )
    # Checkout creation is post-commit and best-effort; keep the test off the network.
    monkeypatch.setattr("apps.payments.services_checkout.create_checkout_url", lambda *args, **kwargs: "")


def loan_space(slug, *, feature_on=True, **overrides):
    makerspace = make_space(slug)
    staff = make_member(f"{slug}-staff", makerspace)
    makerspace.enabled_features = ["payments.enabled"] + (["payments.loans"] if feature_on else [])
    makerspace.save(update_fields=["enabled_features", "updated_at"])
    settings_row = configured_settings(makerspace)
    for name, value in overrides.items():
        setattr(settings_row, name, value)
    settings_row.save()
    return makerspace, staff


def accepted_loan(makerspace, staff, product=None, quantity=1):
    product = product or make_product(makerspace)
    request = make_accepted_request(makerspace, product, quantity)
    product.available_quantity -= quantity
    product.reserved_quantity += quantity
    product.save(update_fields=["available_quantity", "reserved_quantity", "updated_at"])
    box = make_box(makerspace)
    request.assigned_box = box
    request.save(update_fields=["assigned_box", "updated_at"])
    BoxScan.objects.create(
        makerspace=makerspace, box=box, request=request, actor=staff, context=BoxScan.Context.ISSUE
    )
    return request


def issue(staff, request, django_capture_on_commit_callbacks, evidence_id=None):
    evidence_id = evidence_id or make_issue_evidence(request.makerspace, staff).pk
    with django_capture_on_commit_callbacks(execute=True):
        return workflow.issue_request(staff, request, evidence_id, "Handed out.")


def close(staff, request, django_capture_on_commit_callbacks):
    payload = return_payload(request, make_return_evidence(request.makerspace, staff))
    with django_capture_on_commit_callbacks(execute=True):
        return workflow.return_items(
            staff, request, payload["evidence_id"], payload["remark"],
            payload["box_code"], payload["resolutions"],
        )


def loan_payment(request, subject_type):
    return Payment.objects.filter(
        makerspace=request.makerspace, subject_type=subject_type, subject_id=request.pk
    ).first()


def test_feature_off_raises_nothing(django_capture_on_commit_callbacks):
    makerspace, staff = loan_space(
        "loans-off", feature_on=False,
        loan_deposit_mode=MakerspacePaymentSettings.LoanDepositMode.FIXED,
        loan_deposit_amount=Decimal("5.00"),
    )
    request = accepted_loan(makerspace, staff)

    issued = issue(staff, request, django_capture_on_commit_callbacks)

    assert issued.status == HardwareRequest.Status.ISSUED
    assert not Payment.objects.filter(makerspace=makerspace).exists()
    assert not AuditLog.objects.filter(action__startswith="loan.").exists()


def test_deposit_is_raised_on_issue_with_a_receipt_label(django_capture_on_commit_callbacks):
    makerspace, staff = loan_space(
        "loans-deposit",
        loan_deposit_mode=MakerspacePaymentSettings.LoanDepositMode.FIXED,
        loan_deposit_amount=Decimal("5.00"),
    )
    request = accepted_loan(makerspace, staff)

    issue(staff, request, django_capture_on_commit_callbacks)

    deposit = loan_payment(request, Payment.SubjectType.LOAN_DEPOSIT)
    assert (deposit.status, deposit.amount, deposit.currency) == (Payment.Status.PENDING, Decimal("5.00"), "usd")
    assert deposit.member_id == request.requester_id
    assert subject_label(deposit, resolve_subject_labels([deposit])) == f"Loan deposit - request #{request.pk}"
    entry = AuditLog.objects.get(action="loan.deposit_raised")
    assert entry.meta == {"request_id": request.pk, "payment_id": deposit.pk}

    listed = authenticated_client(staff).get(f"/api/v1/admin/makerspace/{makerspace.pk}/payments")
    assert listed.status_code == 200
    row = next(item for item in listed.data if item["id"] == deposit.pk)
    assert row["subject_type"] == "loan_deposit"
    assert row["subject_label"] == f"Loan deposit - request #{request.pk}"
    assert Decimal(row["refunded_amount"]) == Decimal("0.00") and row["refunds"] == []


def test_per_product_deposit_sums_accepted_units(django_capture_on_commit_callbacks):
    makerspace, staff = loan_space(
        "loans-per-product",
        loan_deposit_mode=MakerspacePaymentSettings.LoanDepositMode.PER_PRODUCT,
    )
    product = make_product(makerspace, deposit_amount=Decimal("2.50"))
    request = accepted_loan(makerspace, staff, product=product, quantity=2)

    issue(staff, request, django_capture_on_commit_callbacks)

    assert loan_payment(request, Payment.SubjectType.LOAN_DEPOSIT).amount == Decimal("5.00")


def test_blocking_deposit_refuses_issue_before_evidence_is_checked(django_capture_on_commit_callbacks):
    makerspace, staff = loan_space(
        "loans-blocking",
        loan_deposit_mode=MakerspacePaymentSettings.LoanDepositMode.FIXED,
        loan_deposit_amount=Decimal("5.00"),
        loan_deposit_blocks_issue=True,
    )
    request = accepted_loan(makerspace, staff)

    # Evidence id 999999 does not exist: if evidence were validated first this would be
    # a 400 validation error. The payment gate answers first, with a typed conflict.
    response = authenticated_client(staff).post(
        f"/api/v1/admin/requests/{request.pk}/issue",
        {"evidence_id": 999999, "remark": "x"},
        format="json",
    )
    assert response.status_code == 409
    assert response.data["code"] == "deposit_required"
    deposit = loan_payment(request, Payment.SubjectType.LOAN_DEPOSIT)
    assert deposit.status == Payment.Status.PENDING
    request.refresh_from_db()
    assert request.status == HardwareRequest.Status.ACCEPTED

    # A second attempt does not raise a second deposit; settling it opens the gate.
    with pytest.raises(workflow.DepositRequired):
        workflow.issue_request(staff, request, 999999, "x")
    assert Payment.objects.filter(subject_id=request.pk).count() == 1
    Payment.objects.filter(pk=deposit.pk).update(status=Payment.Status.PAID_OFFLINE)

    issued = issue(staff, request, django_capture_on_commit_callbacks)
    assert issued.status == HardwareRequest.Status.ISSUED
    assert Payment.objects.filter(subject_id=request.pk).count() == 1


def test_late_fee_is_capped_computed_once_and_respects_grace(django_capture_on_commit_callbacks):
    makerspace, staff = loan_space(
        "loans-late-fee",
        loan_late_fee_per_day=Decimal("2.00"),
        loan_late_fee_cap=Decimal("15.00"),
        loan_grace_days=1,
    )
    product = make_product(makerspace)
    request = make_issued_request(makerspace, staff, [(product, 1)])
    request.return_due_at = timezone.now() - timedelta(days=10)
    request.save(update_fields=["return_due_at"])

    closed = close(staff, request, django_capture_on_commit_callbacks)

    assert closed.status == HardwareRequest.Status.RETURNED
    fee = loan_payment(request, Payment.SubjectType.LOAN_LATE_FEE)
    assert fee.amount == Decimal("15.00")  # 9 days late x 2.00 = 18.00, capped
    assert fee.status == Payment.Status.PENDING
    assert AuditLog.objects.get(action="loan.late_fee_raised").meta == {
        "request_id": request.pk, "payment_id": fee.pk,
    }

    loan_payments.on_request_closed(request.pk, staff, now=timezone.now() + timedelta(days=30))
    fee.refresh_from_db()
    assert fee.amount == Decimal("15.00")
    assert Payment.objects.filter(subject_id=request.pk, subject_type="loan_late_fee").count() == 1

    on_time = make_issued_request(makerspace, staff, [(product, 1)])
    on_time.return_due_at = timezone.now() - timedelta(hours=12)  # inside the grace day
    on_time.save(update_fields=["return_due_at"])
    close(staff, on_time, django_capture_on_commit_callbacks)
    assert loan_payment(on_time, Payment.SubjectType.LOAN_LATE_FEE) is None


def test_an_uncollected_deposit_is_cancelled_when_the_loan_closes(django_capture_on_commit_callbacks):
    makerspace, staff = loan_space(
        "loans-release",
        loan_deposit_mode=MakerspacePaymentSettings.LoanDepositMode.FIXED,
        loan_deposit_amount=Decimal("5.00"),
    )
    request = make_issued_request(makerspace, staff, [(make_product(makerspace), 1)])
    deposit = loan_payments.raise_deposit(request.pk, staff)
    assert deposit.status == Payment.Status.PENDING

    close(staff, request, django_capture_on_commit_callbacks)

    deposit.refresh_from_db()
    assert deposit.status == Payment.Status.CANCELED
    assert AuditLog.objects.filter(action="payment.canceled").count() == 1


def test_a_deposit_can_be_waived_by_handover_staff(django_capture_on_commit_callbacks):
    makerspace, staff = loan_space(
        "loans-waive",
        loan_deposit_mode=MakerspacePaymentSettings.LoanDepositMode.FIXED,
        loan_deposit_amount=Decimal("5.00"),
    )
    request = accepted_loan(makerspace, staff)
    issue(staff, request, django_capture_on_commit_callbacks)
    deposit = loan_payment(request, Payment.SubjectType.LOAN_DEPOSIT)

    response = authenticated_client(staff).post(
        f"/api/v1/admin/makerspace/{makerspace.pk}/payments/{deposit.pk}/waive"
    )

    assert response.status_code == 200
    assert response.data["status"] == Payment.Status.WAIVED
    assert AuditLog.objects.filter(action="payment.waived").count() == 1


def test_payment_failures_never_block_issue_or_return(monkeypatch, django_capture_on_commit_callbacks):
    makerspace, staff = loan_space(
        "loans-never-block",
        loan_deposit_mode=MakerspacePaymentSettings.LoanDepositMode.FIXED,
        loan_deposit_amount=Decimal("5.00"),
        loan_deposit_blocks_issue=True,
        loan_late_fee_per_day=Decimal("1.00"),
    )
    monkeypatch.setattr(
        loan_payments, "create_payment",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("provider exploded")),
    )
    request = accepted_loan(makerspace, staff)

    issued = issue(staff, request, django_capture_on_commit_callbacks)
    assert issued.status == HardwareRequest.Status.ISSUED

    issued.return_due_at = timezone.now() - timedelta(days=3)
    issued.save(update_fields=["return_due_at"])
    closed = close(staff, issued, django_capture_on_commit_callbacks)
    assert closed.status == HardwareRequest.Status.RETURNED
    assert not Payment.objects.filter(makerspace=makerspace).exists()
