"""The sixth charge seam: record once, then attach a best-effort online rail."""
import logging

from django.db import IntegrityError, transaction

from apps.accounts import rbac
from apps.audit import services as audit
from apps.makerspaces.models import MembershipTerm

logger = logging.getLogger(__name__)


def raise_renewal(term):
    from apps.payments.availability import charge_tracking_enabled
    from apps.payments.models import Payment
    from apps.payments.services import create_payment

    space, plan = term.membership.makerspace, term.plan
    if plan.amount <= 0 or not charge_tracking_enabled(space, "membership"):
        return "skipped"
    lookup = dict(makerspace=space, subject_type=Payment.SubjectType.MEMBERSHIP_TERM,
                  subject_id=term.pk)
    try:
        with transaction.atomic():
            # A savepoint contains a uniqueness race; the outer transaction stays usable.
            try:
                with transaction.atomic():
                    payment = create_payment(
                        **lookup, member=term.membership.user, amount=plan.amount,
                        currency=plan.currency, created_by=term.membership.user,
                        subject_label=f"Membership renewal: {plan.name}", due_at=term.ends_at,
                    )
            except IntegrityError:
                payment = rbac.scope_for_scheduled_work(
                    Payment.objects.all(), makerspace_id=space.pk,
                ).get(**lookup)
            rbac.scope_for_scheduled_work(
                MembershipTerm.objects.all(), makerspace_id=space.pk, field="membership__makerspace_id",
            ).filter(pk=term.pk).update(renewal_payment=payment)
            term.renewal_payment = payment
            audit.record(None, "membership.renewal_raised", makerspace=space, target=term,
                         meta={"membership_id": term.membership_id, "term_id": term.pk,
                               "payment_id": payment.pk})
        return "charged"
    except Exception:
        logger.warning("membership_renewal_charge_failed", extra={"term_id": term.pk})
        return "failed"


def attempt_checkout(term_id, now):
    """Claim an attempt after the charge commits; observe the real provider outcome.

    Provider credentials/Payment have their own lock order. Release membership row
    locks before contacting the rail, and retain the surrounding tenant boundary.
    A crashed worker leaves a dated retry claim rather than duplicating the debt.
    """
    from datetime import timedelta
    from apps.makerspaces.guards import require_module_locked
    from apps.makerspaces.membership_renewals import automatic, grace_end, renewal_terms
    from apps.payments.availability import online_payments_enabled
    from apps.payments.models import Payment
    from apps.payments.services import create_checkout_url
    from apps.makerspaces.models import MakerspaceMembership

    with transaction.atomic():
        seed = renewal_terms().get(pk=term_id)
        space = require_module_locked(seed.membership.makerspace_id, "membership")
        member = rbac.scope_for_scheduled_work(
            MakerspaceMembership.objects.all(), makerspace_id=space.pk,
        ).select_for_update().get(pk=seed.membership_id)
        term = renewal_terms(space.pk).select_for_update().get(pk=term_id)
        term.membership = member
        auto = automatic(term)
        payment = term.renewal_payment
        if (member.status != "active" or member.renewal_cancelled_at or
            term.status != "active" or now >= grace_end(term) or not payment or
            payment.status != Payment.Status.PENDING or
            (auto and (term.renewal_retry_at is None or term.renewal_attempts > term.plan.renewal_retries or
                       (term.renewal_retry_at and term.renewal_retry_at > now)))):
            return
        if not online_payments_enabled(space, "membership"):
            # Cash-only debt is complete work, rather than a failing checkout job.
            term.renewal_retry_at = None
            term.save(update_fields=["renewal_retry_at"])
            return
        term.renewal_attempts += 1
        term.renewal_retry_at = now + timedelta(days=1) if auto and term.renewal_attempts <= term.plan.renewal_retries else None
        term.save(update_fields=["renewal_attempts", "renewal_retry_at"])
        attempt = term.renewal_attempts
        audit.record(None, "membership.renewal_checkout_attempted", makerspace=space,
                     target=term, meta={"attempt": attempt})
    failed = False
    try:
        create_checkout_url(payment.pk, actor=member.user)
    except Exception:
        failed = True
        logger.warning("membership_renewal_checkout_failed", extra={"term_id": term.pk})
    with transaction.atomic():
        require_module_locked(space.pk, "membership")
        rbac.scope_for_scheduled_work(
            MakerspaceMembership.objects.all(), makerspace_id=space.pk,
        ).select_for_update().get(pk=member.pk)
        term = renewal_terms(space.pk).select_for_update().get(pk=term_id)
        if term.renewal_attempts != attempt:
            return
        if not failed:
            term.renewal_retry_at = None
            term.save(update_fields=["renewal_retry_at"])
        else:
            from apps.makerspaces.membership_renewal_notifications import notify_term
            audit.record(None, "membership.renewal_retry", makerspace=space,
                         target=term, meta={"attempt": attempt})
            transaction.on_commit(lambda: notify_term(term, "renewal_failed"))
