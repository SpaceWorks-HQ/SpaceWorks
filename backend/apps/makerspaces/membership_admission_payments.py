"""First-term debt and settlement-driven admission; the payment rail stays optional."""
import logging

from django.db import transaction
from django.utils import timezone

from apps.audit import services as audit
from apps.accounts import rbac
from apps.makerspaces.membership_admission_settings import AdmissionError, ensure_join_allowed
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MembershipRequest
from apps.payments.availability import charge_tracking_enabled, online_payments_enabled
from apps.payments.models import Payment

logger = logging.getLogger(__name__)
SETTLED = ("paid_online", "paid_offline", "waived")


def charge_admission(row, actor, policy):
    if row.admission_payment_id:
        return Payment.objects.select_for_update().get(pk=row.admission_payment_id, makerspace=row.makerspace, member=row.user)
    plan = row.selected_plan
    if plan and (plan.makerspace_id != row.makerspace_id or not plan.is_active):
        raise AdmissionError("membership_plan_unavailable", "The admission plan is no longer available.")
    row.first_term_amount = plan.amount if plan else 0
    row.joining_fee = policy.joining_fee if not row.rejoining or policy.rejoin_dues_rule == "each_join" else 0
    row.charge_currency = plan.currency if plan else policy.joining_fee_currency
    if plan and row.joining_fee > 0 and plan.currency != policy.joining_fee_currency:
        raise AdmissionError("membership_currency_mismatch", "The joining fee and plan must use the same currency.")
    row.save(update_fields=["first_term_amount", "joining_fee", "charge_currency"])
    amount = row.first_term_amount + row.joining_fee
    if amount <= 0:
        return None
    if not charge_tracking_enabled(row.makerspace, "membership"):
        if policy.payment_timing == "before_activation":
            raise AdmissionError("membership_charge_tracking_required", "Membership charge tracking is required before activation.")
        return None
    from apps.payments.services import create_payment
    payment = create_payment(
        makerspace=row.makerspace, subject_type=Payment.SubjectType.MEMBERSHIP_REQUEST,
        subject_id=row.pk, member=row.user, amount=amount, currency=row.charge_currency,
        created_by=actor, subject_label=f"Membership admission{': ' + plan.name if plan else ''}",
    )
    row.admission_payment = payment
    row.save(update_fields=["admission_payment"])
    if online_payments_enabled(row.makerspace, "membership"):
        from apps.makerspaces.membership_payments import _schedule_checkout
        _schedule_checkout(payment)
    return payment


def activate_admission(actor, row):
    from apps.makerspaces.membership_activation import _activate_membership
    from apps.makerspaces.membership_plan_services import create_term

    if row.user is None or not row.user.is_active or row.user.access_status != "active":
        raise AdmissionError("membership_applicant_unavailable", "The applicant account is no longer eligible.")
    if row.assigned_role is None or row.assigned_role.granted_actions:
        raise AdmissionError("membership_role_unavailable", "Community admission requires a member role.")
    membership = _activate_membership(
        actor, row.makerspace, row.user, row.assigned_role,
        request=row, source="approval", skip_dues=True,
    )
    if row.selected_plan_id:
        create_term(actor, membership, row.selected_plan)
    if row.user.is_walk_in and membership.can_refer:
        membership.can_refer = False
        membership.save(update_fields=["can_refer"])
    return membership


def resume_after_payment(payment_id):
    from apps.tenant_migration.gate_runtime import tenant_write

    payment = Payment.objects.filter(pk=payment_id, subject_type=Payment.SubjectType.MEMBERSHIP_REQUEST).first()
    if payment is None:
        return None
    with tenant_write(payment.makerspace_id):
        makerspace = Makerspace.objects.select_for_update().get(pk=payment.makerspace_id)
        row = MembershipRequest.objects.select_for_update().filter(
            pk=payment.subject_id, makerspace=makerspace, admission_payment=payment, admission_managed=True,
        ).first()
        payment = Payment.objects.select_for_update().get(pk=payment.pk)
        if row is None or row.state != "awaiting_payment" or payment.status not in SETTLED:
            return None
        from apps.makerspaces.guards import require_module
        require_module(makerspace, "membership")
        policy = ensure_join_allowed(makerspace)
        if row.expires_at and row.expires_at <= timezone.now():
            close_admission(None, row, "expired")
            audit.record(None, "membership.payment_after_expiry", makerspace=makerspace, target=row,
                         meta={"payment_id": payment.pk})
            return row
        from apps.makerspaces.membership_admission import advance
        return advance(None, row, policy)


def close_admission(actor, row, state="canceled"):
    """Caller holds makerspace/request locks; a settled charge is never altered."""
    from apps.makerspaces.membership_admission import OPEN_STATES, transition
    from apps.payments.reconciliation import cancel_pending
    if row.state not in OPEN_STATES:
        raise AdmissionError("membership_request_terminal", "This application is no longer open.")
    transition(actor, row, state)
    if row.admission_payment_id:
        cancel_pending(makerspace=row.makerspace, subject_type=Payment.SubjectType.MEMBERSHIP_REQUEST,
                       subject_id=row.pk, actor=actor)
    return row


def cancel_for_admitted_member(actor, membership):
    """Revocation cancels unpaid admission dues, preserving received money."""
    from apps.payments.reconciliation import cancel_pending

    rows = rbac.scope_by_action(actor, rbac.Action.MANAGE_MEMBERS, MembershipRequest.objects.all()).filter(
        makerspace=membership.makerspace, user=membership.user, state="active",
        admission_managed=True, admission_payment__status=Payment.Status.PENDING,
    ).order_by("pk")
    for row in rows:
        cancel_pending(makerspace=membership.makerspace,
                       subject_type=Payment.SubjectType.MEMBERSHIP_REQUEST,
                       subject_id=row.pk, actor=actor)


def sweep_admissions(*, now=None, limit=200):
    from apps.makerspaces.membership_admission import OPEN_STATES
    from apps.tenant_migration.gate_runtime import fanout_tenant_write
    now = now or timezone.now()
    counts = {"expired": 0, "activated": 0, "failed": 0, "skipped": 0}
    scoped = rbac.scope_for_scheduled_work(MembershipRequest.objects.all()).filter(
        admission_managed=True, makerspace__enabled_modules__contains=["membership"],
    )
    rows = scoped.filter(state__in=OPEN_STATES).filter(
        expires_at__lte=now,
    ).order_by("expires_at", "pk")[:limit]
    for row in rows:
        with fanout_tenant_write(row.makerspace_id, operation="membership_admission_expiry", counts=counts) as allowed:
            if not allowed:
                continue
            try:
                with transaction.atomic():
                    makerspace = Makerspace.objects.select_for_update().get(pk=row.makerspace_id)
                    from apps.makerspaces.platform import module_enabled
                    if not module_enabled(makerspace, "membership"):
                        counts["skipped"] += 1
                        continue
                    row = MembershipRequest.objects.select_for_update().get(pk=row.pk)
                    if row.state in OPEN_STATES and row.expires_at <= now:
                        close_admission(None, row, "expired")
                        counts["expired"] += 1
            except Exception:
                counts["failed"] += 1
                logger.warning("membership_admission_expiry_failed", extra={"request_id": row.pk})
    settled = scoped.filter(
        state="awaiting_payment", admission_payment__status__in=SETTLED,
        expires_at__gt=now,
    ).order_by("pk")[:limit]
    for row in settled:
        with fanout_tenant_write(row.makerspace_id, operation="membership_admission_settlement", counts=counts) as allowed:
            if not allowed:
                continue
            try:
                result = resume_after_payment(row.admission_payment_id)
                counts["activated" if isinstance(result, MakerspaceMembership) else "skipped"] += 1
            except Exception:
                counts["failed"] += 1
                logger.warning("membership_admission_activation_failed", extra={"request_id": row.pk})
    return counts
