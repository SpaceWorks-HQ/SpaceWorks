"""Transactional reconciliation for every payment subject type."""

import logging

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound, PermissionDenied

from apps.accounts import rbac
from apps.audit import services as audit
from apps.payments import stripe_client
from apps.payments.models import Payment
from apps.payments.resolution import source_for_payment

logger = logging.getLogger(__name__)

SUBJECT_ACTIONS = {
    Payment.SubjectType.MACHINE_SERVICE_REQUEST: rbac.Action.MANAGE_MACHINES,
    Payment.SubjectType.BOOKING: rbac.Action.MANAGE_BOOKINGS,
    Payment.SubjectType.EVENT_REGISTRATION: rbac.Action.MANAGE_EVENTS,
    Payment.SubjectType.MAKERSPACE_MEMBERSHIP: rbac.Action.MANAGE_MAKERSPACE,
}


class PaymentConflict(APIException):
    status_code = 409

    def __init__(self, payment_ids):
        self.detail = {
            "detail": "Only pending payments can be reconciled.",
            "code": "payment_terminal",
            "payment_ids": list(payment_ids),
        }


def list_payments(*, actor, makerspace_id, status=None, subject_type=None):
    queryset = rbac.scope_by_action(
        actor,
        rbac.Action.MANAGE_MAKERSPACE,
        Payment.objects.select_related("makerspace"),
        field="makerspace_id",
    ).filter(makerspace_id=makerspace_id)
    if status:
        queryset = queryset.filter(status=status)
    if subject_type:
        queryset = queryset.filter(subject_type=subject_type)
    return queryset.order_by("-created_at", "-pk")


def mark_offline(payment, actor):
    return _compat_reconcile(
        actor=actor,
        payment=payment,
        target_status=Payment.Status.PAID_OFFLINE,
    )


def waive(payment, actor):
    return _compat_reconcile(
        actor=actor,
        payment=payment,
        target_status=Payment.Status.WAIVED,
    )


@transaction.atomic
def cancel_pending(*, makerspace, subject_type, subject_id, actor):
    """Cancel a subject's pending charge without affecting its domain workflow."""
    payment = (
        Payment.objects.select_for_update()
        .filter(
            makerspace=makerspace,
            subject_type=subject_type,
            subject_id=subject_id,
        )
        .first()
    )
    if payment is None or payment.status != Payment.Status.PENDING:
        return payment
    _expire_checkout_best_effort(payment)
    payment.status = Payment.Status.CANCELED
    payment.save(
        update_fields=[
            "status",
            "stripe_checkout_session_expired_at",
            "updated_at",
        ]
    )
    audit.record(
        actor,
        "payment.canceled",
        makerspace=makerspace,
        target=payment,
    )
    return payment


def _compat_reconcile(*, payment, actor, target_status):
    current = Payment.objects.get(pk=payment.pk)
    if current.status != Payment.Status.PENDING:
        return current
    return reconcile_payments(
        actor=actor,
        makerspace_id=current.makerspace_id,
        payment_ids=[current.pk],
        target_status=target_status,
    )[0]


@transaction.atomic
def reconcile_payments(*, actor, makerspace_id, payment_ids, target_status):
    """Lock, validate, then reconcile a batch without partial mutations."""
    if target_status not in {Payment.Status.PAID_OFFLINE, Payment.Status.WAIVED}:
        raise ValueError("Unsupported reconciliation status.")

    requested_ids = list(payment_ids)
    locked = list(
        Payment.objects.select_for_update()
        .select_related("makerspace")
        .filter(makerspace_id=makerspace_id, pk__in=requested_ids)
        .order_by("pk")
    )
    by_id = {payment.pk: payment for payment in locked}
    if len(by_id) != len(requested_ids):
        raise NotFound("Payment not found.")

    _require_subject_authority(actor, locked)
    terminal_ids = [payment.pk for payment in locked if payment.status != Payment.Status.PENDING]
    if terminal_ids:
        raise PaymentConflict(terminal_ids)

    action = (
        "payment.paid_offline"
        if target_status == Payment.Status.PAID_OFFLINE
        else "payment.waived"
    )
    for payment in locked:
        _expire_checkout_best_effort(payment)
        payment.status = target_status
        payment.save(
            update_fields=[
                "status",
                "stripe_checkout_session_expired_at",
                "updated_at",
            ]
        )
        audit.record(actor, action, makerspace=payment.makerspace, target=payment)
    return [by_id[payment_id] for payment_id in requested_ids]


def _require_subject_authority(actor, payments):
    for subject_type, action in SUBJECT_ACTIONS.items():
        ids = [payment.pk for payment in payments if payment.subject_type == subject_type]
        if not ids:
            continue
        visible = set(
            rbac.scope_by_action(
                actor,
                action,
                Payment.objects.filter(pk__in=ids),
                field="makerspace_id",
            ).values_list("pk", flat=True)
        )
        if visible != set(ids):
            raise PermissionDenied("Payment action is not permitted.")
        if subject_type == Payment.SubjectType.MACHINE_SERVICE_REQUEST:
            _require_machine_scope(actor, payments)
    if any(payment.subject_type not in SUBJECT_ACTIONS for payment in payments):
        raise PermissionDenied("Payment subject type is not supported.")


def _require_machine_scope(actor, payments):
    """MANAGE_MACHINES is scoped per role, so reconciling a charge follows the job.

    Imported locally: `apps.machines` reaches into `apps.payments` for service pricing, so
    a module-level edge back would close the cycle.
    """
    from apps.machines.models import MachineServiceRequest
    from apps.machines.role_scope import EXEMPT, manage_scopes_for, scoped_service_requests

    machine_payments = [
        payment
        for payment in payments
        if payment.subject_type == Payment.SubjectType.MACHINE_SERVICE_REQUEST
    ]
    subject_ids = {payment.subject_id for payment in machine_payments}
    if not subject_ids:
        return
    requests = MachineServiceRequest.objects.filter(pk__in=subject_ids)
    live_ids = set(requests.values_list("pk", flat=True))
    covered = set(
        scoped_service_requests(
            actor,
            requests,
            set(requests.values_list("makerspace_id", flat=True)),
        ).values_list("pk", flat=True)
    )
    if covered != live_ids:
        raise PermissionDenied("Payment action is not permitted.")

    # A charge whose service request was purged names no machine, type or team, so there is
    # nothing left for machine scoping to answer. Comparing against `subject_ids` here made
    # the set unequal for every actor, so a pending charge could never be waived or marked
    # paid in cash -- stranding it forever, which is the exact failure that preserving the
    # payment exists to prevent. Failing OPEN to every `MANAGE_MACHINES` holder would
    # silently widen a scoped role, and scoping is documented as failing closed. So the
    # orphan is actionable only by the actor machine scoping already exempts -- a space
    # manager, a superadmin, or the null-`assigned_role` legacy fallback -- all of whom are
    # unscoped everywhere else in this mechanism.
    orphaned = subject_ids - live_ids
    if not orphaned:
        return
    orphan_makerspace_ids = {
        payment.makerspace_id
        for payment in machine_payments
        if payment.subject_id in orphaned
    }
    scopes = manage_scopes_for(actor, orphan_makerspace_ids)
    if any(scopes.get(ms_id) is not EXEMPT for ms_id in orphan_makerspace_ids):
        raise PermissionDenied("Payment action is not permitted.")


def _expire_checkout_best_effort(payment):
    """Close a live hosted page when staff settle a charge another way.

    Without this a member can still pay a link for a charge already marked offline or
    waived, and the webhook then records `payment.paid_after_terminal` -- visible, but
    the member is out of pocket. Best-effort by contract: the reconciliation that called
    this must succeed regardless of what the vendor says.
    """
    order_id = payment.external_order_id or payment.stripe_checkout_session_id
    if not order_id or payment.stripe_checkout_session_expired_at:
        return
    try:
        source = source_for_payment(payment)
        if source is None:
            raise stripe_client.PaymentsUnavailable(
                "The payment's provider credentials are no longer configured."
            )
        if payment.provider != payment.Provider.STRIPE:
            from apps.payments.providers import get_provider

            get_provider(payment.provider).expire_checkout(source, order_id)
            payment.stripe_checkout_session_expired_at = timezone.now()
        elif stripe_client.expire_checkout_session(source, order_id):
            payment.stripe_checkout_session_expired_at = timezone.now()
    except Exception:
        logger.exception(
            "payment_checkout_expiry_failed", extra={"payment_id": payment.pk}
        )
