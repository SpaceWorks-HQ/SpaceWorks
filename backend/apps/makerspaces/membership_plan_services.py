"""Membership terms: creation, cancellation and the renewal/expiry sweep.

Renewal charges are raised through `apps.payments.services.create_payment` with subject
type `MEMBERSHIP_TERM` and the term pk as subject id, so the Payment table's one-row-per-
subject constraint is what guarantees "exactly one renewal charge per term". A payment
failure never rolls back a recorded debt. Optional automation tracks bounded retries,
promised grace and one successor behind the compatibility exports at the end of this file.
"""
import logging
from datetime import timedelta

from dateutil.relativedelta import relativedelta
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit import services as audit
from apps.makerspaces.guards import require_module_locked
from apps.makerspaces.models import MakerspaceMembership, MembershipPlan, MembershipTerm

logger = logging.getLogger(__name__)

# Compatibility window for plans that have not opted in to automation.
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
            ends_at=term_end(plan, _local_start(makerspace, starts_at)),
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


def _local_start(makerspace, starts_at):
    from apps.makerspaces.local_time import to_local
    return to_local(makerspace, starts_at)


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


def cancel_terms_for_membership(actor, membership):
    """Cancel every ACTIVE term of a membership that has just been revoked, with its renewal.

    Called from `revoke_membership`, which is core RBAC and runs with the module off too,
    so there is no module gate here. Without it a revoked member kept an active term and a
    PENDING renewal charge that the sweep had raised for a membership that no longer exists.
    """
    for term in MembershipTerm.objects.filter(
        membership=membership, status=MembershipTerm.Status.ACTIVE
    ):
        cancel_term(actor, term)


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



# Explicit compatibility exports for the scheduled seam.
from .membership_renewals import run_membership_renewals, _expire
from .membership_renewal_charges import raise_renewal as _raise_renewal
