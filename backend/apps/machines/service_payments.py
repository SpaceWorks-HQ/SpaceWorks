"""Machine-service charging boundary; payment failures never affect fulfilment."""

from decimal import Decimal, InvalidOperation

from django.db import transaction

from apps.machines.models import MakerspaceMachineTypePricing
from apps.payments.availability import online_payments_enabled
from apps.payments.models import MakerspacePaymentSettings, Payment
from apps.payments.services import create_checkout, create_payment


def effective_quantity(service_request, machine_type):
    config = machine_type.capability_config or {}
    if config.get("metering_unit") == "minutes":
        return _decimal(service_request.actual_minutes)
    quantity = service_request.actual_consumed_quantity
    if quantity is not None:
        return _decimal(quantity)
    return _decimal(service_request.actual_consumed_grams)


def create_for_completed_request(service_request, actor):
    try:
        with transaction.atomic():
            machine_type = service_request.assigned_machine.machine_type
            if not online_payments_enabled(service_request.makerspace, "machines"):
                return None
            pricing = MakerspaceMachineTypePricing.objects.filter(
                makerspace=service_request.makerspace, machine_type=machine_type, payment_enabled=True
            ).first()
            if pricing is None:
                return None
            amount = (pricing.rate_per_unit * effective_quantity(service_request, machine_type) + pricing.flat_fee).quantize(Decimal("0.01"))
            if amount <= 0:
                return None
            currency = MakerspacePaymentSettings.for_makerspace(service_request.makerspace).default_currency
            payment = create_payment(
                makerspace=service_request.makerspace,
                subject_type=Payment.SubjectType.MACHINE_SERVICE_REQUEST,
                subject_id=service_request.pk,
                member=service_request.member or service_request.requester,
                amount=amount,
                currency=currency,
                created_by=actor,
                # NO subject_label. `title` is free text a public member types, so it can
                # contain their name, email or phone -- and a snapshot outlives the
                # `machine_service` purge that exists to destroy exactly that. Leaving it
                # blank keeps the live lookup (which still shows the title while the request
                # exists) and degrades to the generic display once the request is gone.
                # The other three subjects snapshot staff-authored or literal text instead.
            )
    except Exception:
        return None
    try:
        create_checkout(payment)
    except Exception:
        pass
    return payment


def _decimal(value):
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")
    return parsed if parsed.is_finite() else Decimal("0")
