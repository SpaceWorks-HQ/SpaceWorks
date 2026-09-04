"""Membership terms: creation, cancellation and the renewal/expiry sweep.

Renewal charges are raised through `apps.payments.services.create_payment` with subject
type `MEMBERSHIP_TERM` and the term pk as subject id, so the Payment table's one-row-per-
subject constraint is what guarantees "exactly one renewal charge per term". A payment
failure is logged and skipped -- it never stops the sweep and never touches the term --
mirroring `membership_payments.py`: dues are a boundary the membership must not depend on.
"""
import logging
from datetime import timedelta

from dateutil.relativedelta import relativedelta
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit import services as audit
from apps.makerspaces.guards import require_module_locked
from apps.makerspaces.models import MakerspaceMembership, MembershipPlan, MembershipTerm

logger = logging.getLogger(__name__)

# Deliberately not a plan attribute: a single window keeps the sweep one query.
RENEWAL_WINDOW = timedelta(days=7)


def term_end(plan, starts_at):
    if plan.interval == MembershipPlan.Interval.MONTHLY:
        return starts_at + relativedelta(months=1)
    if plan.interval == MembershipPlan.Interval.YEARLY:
        return starts_at + relativedelta(years=1)
    return starts_at + timedelta(days=plan.custom_days or 0)


def create_term(actor, membership, plan, starts_at=None):
    """Open a term for an active membership; a new term follows the current one."""
    with transaction.atomic():
        # Makerspace lock first, then the membership -- the order `_activate_membership`
        # mandates -- and the module gate re-checked under that lock (plan A8).
        makerspace = require_module_locked(membership.makerspace_id, "membership")
        membership = (
            MakerspaceMembership.objects.select_for_update(of=("self",))
            .select_related("user")
            .get(pk=membership.pk)
        )
        if plan.makerspace_id != makerspace.pk:
            raise ValidationError({"plan_id": "Plan must belong to this makerspace."})
        if not plan.is_active:
            raise ValidationError({"plan_id": "This plan is no longer active."})
        if membership.status != "active":
            raise ValidationError({"detail": "Only an active membership can hold a term."})
        now = timezone.now()
        if starts_at is None:
            current = (
                membership.terms.filter(status=MembershipTerm.Status.ACTIVE, ends_at__gt=now)
                .order_by("-ends_at")
                .first()
            )
            starts_at = current.ends_at if current is not None else now
        term = MembershipTerm.objects.create(
            membership=membership,
            plan=plan,
            starts_at=starts_at,
            ends_at=term_end(plan, starts_at),
            created_by=actor,
        )
        audit.record(
            actor,
            "membership.term_created",
            makerspace=makerspace,
            target=term,
            meta={"membership_id": membership.pk, "plan_id": plan.pk, "term_id": term.pk},
        )
    return term


def cancel_term(actor, term):
    with transaction.atomic():
        term = (
            MembershipTerm.objects.select_for_update(of=("self",))
            .select_related("membership__makerspace")
            .get(pk=term.pk)
        )
        if term.status != MembershipTerm.Status.ACTIVE:
            raise ValidationError({"detail": "This term is not active."})
        term.status = MembershipTerm.Status.CANCELLED
        term.save(update_fields=["status"])
        makerspace = term.membership.makerspace
        audit.record(
            actor,
            "membership.term_cancelled",
            makerspace=makerspace,
            target=term,
            meta={"membership_id": term.membership_id, "term_id": term.pk},
        )
        _cancel_pending_renewal(makerspace, term, actor)
    return term


def _cancel_pending_renewal(makerspace, term, actor):
    from apps.payments.models import Payment
    from apps.payments.reconciliation import cancel_pending

    try:
        with transaction.atomic():
            cancel_pending(
                makerspace=makerspace,
                subject_type=Payment.SubjectType.MEMBERSHIP_TERM,
                subject_id=term.pk,
                actor=actor,
            )
    except Exception:  # noqa: BLE001 - money must never block the membership workflow
        logger.exception("membership_renewal_cancel_failed", extra={"term_id": term.pk})


def run_membership_renewals(*, now=None, limit=200):
    """Expire terms past `ends_at`, then raise one renewal charge per term in the window."""
    from apps.tenant_migration.gate_runtime import fanout_tenant_write

    now = now or timezone.now()
    counts = {"expired": 0, "charged": 0, "skipped": 0, "failed": 0}
    due = MembershipTerm.objects.filter(
        status=MembershipTerm.Status.ACTIVE, ends_at__lte=now
    ).select_related("membership")[:limit]
    for term in due:
        with fanout_tenant_write(
            term.membership.makerspace_id, operation="membership_term_expiry", counts=counts
        ) as should_process:
            if not should_process:
                continue
            _expire(term)
            counts["expired"] += 1
    renewable = (
        MembershipTerm.objects.filter(
            status=MembershipTerm.Status.ACTIVE,
            ends_at__gt=now,
            ends_at__lte=now + RENEWAL_WINDOW,
            renewal_payment__isnull=True,
            membership__status="active",
        )
        .select_related("membership__user", "membership__makerspace", "plan")
        .order_by("ends_at", "pk")[:limit]
    )
    for term in renewable:
        with fanout_tenant_write(
            term.membership.makerspace_id, operation="membership_renewal", counts=counts
        ) as should_process:
            if not should_process:
                continue
            counts[_raise_renewal(term)] += 1
    return counts


def _expire(term):
    with transaction.atomic():
        term.status = MembershipTerm.Status.EXPIRED
        term.save(update_fields=["status"])
        audit.record(
            None,
            "membership.term_expired",
            makerspace=term.membership.makerspace,
            target=term,
            meta={"membership_id": term.membership_id, "term_id": term.pk},
        )


def _raise_renewal(term):
    """One charge, or a logged skip. Returns the counter to bump."""
    from apps.payments.availability import online_payments_enabled
    from apps.payments.models import Payment
    from apps.payments.services import create_checkout, create_payment

    makerspace = term.membership.makerspace
    plan = term.plan
    if plan.amount <= 0 or not online_payments_enabled(makerspace, "membership"):
        return "skipped"
    lookup = {
        "makerspace": makerspace,
        "subject_type": Payment.SubjectType.MEMBERSHIP_TERM,
        "subject_id": term.pk,
    }
    try:
        with transaction.atomic():
            try:
                payment = create_payment(
                    **lookup,
                    member=term.membership.user,
                    amount=plan.amount,
                    currency=plan.currency,
                    created_by=term.membership.user,
                    subject_label=f"Membership renewal: {plan.name}",
                )
            except IntegrityError:
                # A previous run raised the charge but lost the race to record it.
                payment = Payment.objects.get(**lookup)
            MembershipTerm.objects.filter(pk=term.pk).update(renewal_payment=payment)
            audit.record(
                None,
                "membership.renewal_raised",
                makerspace=makerspace,
                target=term,
                meta={
                    "membership_id": term.membership_id,
                    "term_id": term.pk,
                    "payment_id": payment.pk,
                },
            )
            if payment.status == Payment.Status.PENDING:
                create_checkout(payment)
    except Exception:  # noqa: BLE001 - one failing charge must not stop the sweep
        logger.exception("membership_renewal_charge_failed", extra={"term_id": term.pk})
        return "failed"
    return "charged"
