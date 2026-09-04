"""Loan deposits and late fees: the payments boundary for reviewed hardware loans.

Mirrors `apps/makerspaces/membership_payments.py`. Every entry point swallows payment
failures, because a provider outage must never stop a handover or a return. The
workflow module calls in at three points, and only the workflow module may:

* `require_deposit_settled` -- the issue gate, run BEFORE the QR/evidence Hard Rules.
  It only ever refuses when `loan_deposit_blocks_issue` is on and the deposit is unpaid;
  it raises the deposit itself so the member has something to pay.
* `raise_deposit` -- after the issue transition commits (non-blocking mode).
* `on_request_closed` -- after a return closes the loan: raise the late fee (computed
  once, never mutated) and cancel a deposit that was never collected.

Amounts are `Decimal` major units, like every Payment row. Never floats.
"""

import logging
import math
from datetime import timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.hardware_requests import notifications
from apps.hardware_requests.models import HardwareRequest
from apps.hardware_requests.workflow_errors import DepositRequired
from apps.payments.availability import online_payments_enabled
from apps.payments.models import MakerspacePaymentSettings, Payment
from apps.payments.reconciliation import cancel_pending
from apps.payments.services import create_checkout, create_payment

logger = logging.getLogger(__name__)

CLOSED_STATUSES = frozenset(
    {HardwareRequest.Status.RETURNED, HardwareRequest.Status.CLOSED_WITH_ISSUE}
)
ZERO = Decimal("0.00")


def loans_enabled(makerspace):
    return online_payments_enabled(makerspace, "loans")


def deposit_amount(request, settings_row):
    mode = settings_row.loan_deposit_mode
    if mode == MakerspacePaymentSettings.LoanDepositMode.FIXED:
        return Decimal(settings_row.loan_deposit_amount or 0)
    if mode == MakerspacePaymentSettings.LoanDepositMode.PER_PRODUCT:
        total = ZERO
        for item in request.items.select_related("product"):
            per_unit = item.product.deposit_amount
            if per_unit and item.accepted_quantity > 0:
                total += Decimal(per_unit) * item.accepted_quantity
        return total
    return ZERO


def require_deposit_settled(request, actor):
    """Refuse an issue only while a blocking deposit is unpaid. Failing open on any
    payment-system error is deliberate: a Stripe outage is not a reason to keep tools
    on the shelf, and the deposit is still raised post-commit by `raise_deposit`."""
    try:
        if request.status != HardwareRequest.Status.ACCEPTED:
            return None
        settings_row = MakerspacePaymentSettings.for_makerspace(request.makerspace)
        if not settings_row.loan_deposit_blocks_issue or not loans_enabled(request.makerspace):
            return None
        amount = deposit_amount(request, settings_row)
        if amount <= 0:
            return None
        payment = _deposit(request, actor, amount, settings_row.default_currency)
    except Exception:
        logger.exception("loan_deposit_gate_failed", extra={"request_id": request.pk})
        return None
    if payment.status == Payment.Status.PENDING:
        raise DepositRequired(payment)
    return payment


def raise_deposit(request_id, actor):
    """Post-commit: raise (or find) the deposit for a loan that was just issued."""
    try:
        request = HardwareRequest.objects.select_related("makerspace").get(pk=request_id)
        if request.status != HardwareRequest.Status.ISSUED:
            return None
        settings_row = MakerspacePaymentSettings.for_makerspace(request.makerspace)
        if not loans_enabled(request.makerspace):
            return None
        amount = deposit_amount(request, settings_row)
        if amount <= 0:
            return None
        return _deposit(request, actor, amount, settings_row.default_currency)
    except Exception:
        logger.exception("loan_deposit_raise_failed", extra={"request_id": request_id})
        return None


def on_request_closed(request_id, actor, now=None):
    """Post-commit: late fee first, then release an uncollected deposit."""
    try:
        request = HardwareRequest.objects.select_related("makerspace").get(pk=request_id)
        if request.status not in CLOSED_STATUSES:
            return None
        fee = raise_late_fee(request, actor, now or timezone.now())
        # A deposit nobody paid secures nothing once the loan is over, whether or not a
        # fee was raised -- the fee is its own charge. A PAID deposit stays on the
        # ledger for staff to refund (or keep against the fee) through the refund path.
        cancel_pending(
            makerspace=request.makerspace,
            subject_type=Payment.SubjectType.LOAN_DEPOSIT,
            subject_id=request.pk,
            actor=actor,
        )
        return fee
    except Exception:
        logger.exception("loan_close_payments_failed", extra={"request_id": request_id})
        return None


def raise_late_fee(request, actor, now):
    settings_row = MakerspacePaymentSettings.for_makerspace(request.makerspace)
    per_day = Decimal(settings_row.loan_late_fee_per_day or 0)
    if per_day <= 0 or request.return_due_at is None or not loans_enabled(request.makerspace):
        return None
    deadline = request.return_due_at + timedelta(days=settings_row.loan_grace_days or 0)
    if now <= deadline:
        return None
    existing = _existing(request, Payment.SubjectType.LOAN_LATE_FEE)
    if existing is not None:
        # Computed once at close, never recomputed: a fee that grew after the fact
        # would be a charge the member never saw raised.
        return existing
    days_late = math.ceil((now - deadline).total_seconds() / 86400)
    fee = per_day * days_late
    cap = Decimal(settings_row.loan_late_fee_cap or 0)
    if cap > 0:
        fee = min(fee, cap)
    if fee <= 0:
        return None
    payment, created = _get_or_create(
        request, Payment.SubjectType.LOAN_LATE_FEE, fee, settings_row.default_currency,
        actor, f"Late return fee - request #{request.pk}",
    )
    if created:
        audit.record(
            actor, "loan.late_fee_raised", makerspace=request.makerspace, target=request,
            meta={"request_id": request.pk, "payment_id": payment.pk},
        )
        notifications.notify_loan_charge(request, "late_fee_raised", payment)
    if payment.status == Payment.Status.PENDING:
        _schedule_checkout(payment)
    return payment


def _deposit(request, actor, amount, currency):
    payment, created = _get_or_create(
        request, Payment.SubjectType.LOAN_DEPOSIT, amount, currency,
        actor, f"Loan deposit - request #{request.pk}",
    )
    if created:
        audit.record(
            actor, "loan.deposit_raised", makerspace=request.makerspace, target=request,
            meta={"request_id": request.pk, "payment_id": payment.pk},
        )
        notifications.notify_loan_charge(request, "deposit_raised", payment)
    if payment.status == Payment.Status.PENDING:
        _schedule_checkout(payment)
    return payment


def _existing(request, subject_type):
    return Payment.objects.filter(
        makerspace=request.makerspace, subject_type=subject_type, subject_id=request.pk
    ).first()


def _get_or_create(request, subject_type, amount, currency, actor, label):
    existing = _existing(request, subject_type)
    if existing is not None:
        return existing, False
    try:
        with transaction.atomic():
            return create_payment(
                makerspace=request.makerspace,
                subject_type=subject_type,
                subject_id=request.pk,
                member=request.requester,
                amount=amount.quantize(Decimal("0.01")),
                currency=currency,
                created_by=actor or request.requester,
                subject_label=label,
            ), True
    except IntegrityError:
        return _existing(request, subject_type), False


def _schedule_checkout(payment):
    def create_safely():
        try:
            create_checkout(payment)
        except Exception:
            logger.exception("loan_checkout_schedule_failed", extra={"payment_id": payment.pk})

    transaction.on_commit(create_safely)
