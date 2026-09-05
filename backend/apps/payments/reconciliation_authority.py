"""Who may reconcile a payment: subject-type authority and machine scoping.

Split out of `reconciliation.py` at the 300-line ceiling. Import through the
`reconciliation` barrel -- `views_refunds` already imports `_require_subject_authority`
from there, so the name must keep resolving at its old path.
"""

from rest_framework.exceptions import PermissionDenied

from apps.accounts import rbac
from apps.payments.models import Payment

SUBJECT_ACTIONS = {
    Payment.SubjectType.MACHINE_SERVICE_REQUEST: rbac.Action.MANAGE_MACHINES,
    Payment.SubjectType.BOOKING: rbac.Action.MANAGE_BOOKINGS,
    Payment.SubjectType.EVENT_REGISTRATION: rbac.Action.MANAGE_EVENTS,
    Payment.SubjectType.MAKERSPACE_MEMBERSHIP: rbac.Action.MANAGE_MAKERSPACE,
    # Loan charges follow the handover job: whoever may issue settles the deposit,
    # whoever may take a return settles the late fee.
    Payment.SubjectType.LOAN_DEPOSIT: rbac.Action.ISSUE_REQUEST,
    Payment.SubjectType.LOAN_LATE_FEE: rbac.Action.RETURN_REQUEST,
}


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
