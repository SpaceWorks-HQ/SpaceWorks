"""Locked, idempotent renewal automation; lapse never revokes membership authority."""
import logging
from datetime import timedelta

from django.db import transaction
from django.db.models import Exists, F, OuterRef, Q
from django.utils import timezone

from apps.accounts import rbac
from apps.audit import services as audit
from apps.makerspaces.local_time import to_local
from apps.makerspaces.models import MakerspaceMembership, MembershipTerm
from apps.makerspaces.platform import feature_enabled, module_enabled
from apps.makerspaces.membership_renewal_charges import raise_renewal, attempt_checkout

logger = logging.getLogger(__name__)


def renewal_terms(makerspace_id=None):
    """The internal tenant boundary for both discovery and locked renewal reads."""
    return rbac.scope_for_scheduled_work(
        MembershipTerm.objects.all(), makerspace_id=makerspace_id,
        field="membership__makerspace_id",
    )


def automatic(term):
    return (term.plan.auto_renew and term.plan.is_active and
            term.membership.renewal_cancelled_at is None and
            term.membership.status == "active" and
            feature_enabled(term.membership.makerspace, "membership.auto_renew"))


def grace_end(term):
    if term.grace_until:
        return term.grace_until
    if not automatic(term):
        return term.ends_at
    return to_local(term.membership.makerspace, term.ends_at) + timedelta(days=term.plan.renewal_grace_days)


def current_terms(membership, *, now=None):
    """Actual coverage, including snapshotted grace; a future prepaid term isn't current."""
    now = now or timezone.now()
    terms = MembershipTerm.objects.filter(membership=membership, status="active", starts_at__lte=now)
    terms = rbac.scope_by_makerspace(membership.user, terms, "membership__makerspace_id")
    return [term for term in terms.select_related("plan", "membership__makerspace")
            if grace_end(term) > now]


def _expire(term):
    if term.status != MembershipTerm.Status.ACTIVE:
        return
    term.status = MembershipTerm.Status.EXPIRED
    term.save(update_fields=["status"])
    audit.record(None, "membership.term_expired", makerspace=term.membership.makerspace,
                 target=term, meta={"membership_id": term.membership_id, "term_id": term.pk})


def _open_next(term):
    from apps.makerspaces.membership_plan_services import create_term
    rows = renewal_terms(term.membership.makerspace_id)
    if rows.filter(renewed_from=term).exists():
        return False
    # Staff may already have opened the successor. Never duplicate it or change plan.
    if rows.filter(membership=term.membership, status="active", starts_at__gte=term.ends_at).exists():
        return False
    next_term = create_term(None, term.membership, term.plan, starts_at=term.ends_at)
    next_term.renewed_from = term
    next_term.save(update_fields=["renewed_from"])
    from apps.makerspaces.membership_renewal_notifications import notify_term
    transaction.on_commit(lambda: notify_term(next_term, "renewed"))
    audit.record(None, "membership.renewed", makerspace=term.membership.makerspace,
                 target=term, meta={"membership_id": term.membership_id, "term_id": next_term.pk})
    return True


def _process(term_id, now, counts):
    from apps.makerspaces.guards import require_module_locked
    from apps.payments.availability import charge_tracking_enabled
    from apps.payments.models import Payment

    with transaction.atomic():
        seed = renewal_terms().get(pk=term_id)
        require_module_locked(seed.membership.makerspace_id, "membership")
        membership = rbac.scope_for_scheduled_work(
            MakerspaceMembership.objects.all(), makerspace_id=seed.membership.makerspace_id,
        ).select_for_update().get(pk=seed.membership_id)
        term = renewal_terms(membership.makerspace_id).select_for_update().get(pk=term_id)
        term.membership = membership
        auto = automatic(term)
        if membership.status != "active" or term.status == "cancelled":
            return
        local_today = to_local(membership.makerspace, now).date()
        days_left = (to_local(membership.makerspace, term.ends_at).date() - local_today).days
        window = term.plan.renewal_open_days if auto else 7
        if auto and term.grace_until is None:
            term.grace_until = grace_end(term)
            term.save(update_fields=["grace_until"])
            audit.record(None, "membership.grace_promised", makerspace=membership.makerspace,
                         target=term)
        if membership.renewal_cancelled_at is None and term.plan.is_active and days_left <= window:
            paid = term.renewal_payment and term.renewal_payment.status in (
                Payment.Status.PAID_ONLINE, Payment.Status.PAID_OFFLINE, Payment.Status.WAIVED,
            )
            if auto and (paid or term.plan.amount <= 0 or not charge_tracking_enabled(membership.makerspace, "membership")):
                if _open_next(term):
                    counts["opened"] += 1
            elif (term.status == "active" and now < grace_end(term) and
                  term.renewal_payment_id is None and
                  (not auto or term.renewal_attempts <= term.plan.renewal_retries) and
                  (term.renewal_retry_at is None or term.renewal_retry_at <= now)):
                result = raise_renewal(term)
                counts[result] += 1
                if result == "failed" and auto:
                    _retry_state(term, now)
                elif result == "charged":
                    if auto:
                        # Commit the initial attempt identity too; a worker death
                        # between commit and the callback is recoverable by F1.
                        term.renewal_retry_at = now
                        term.save(update_fields=["renewal_retry_at"])
                    transaction.on_commit(lambda: attempt_checkout(term.pk, now))
            elif auto and now < grace_end(term) and term.renewal_retry_at and term.renewal_retry_at <= now:
                transaction.on_commit(lambda: attempt_checkout(term.pk, now))
        if term.status == "active" and now >= grace_end(term):
            _expire(term)
            counts["expired"] += 1


def _retry_state(term, now):
    from apps.makerspaces.membership_renewal_notifications import notify_term
    term.renewal_attempts += 1
    term.renewal_retry_at = (now + timedelta(days=1) if term.renewal_attempts <= term.plan.renewal_retries else None)
    term.save(update_fields=["renewal_attempts", "renewal_retry_at"])
    audit.record(None, "membership.renewal_retry", makerspace=term.membership.makerspace,
                 target=term, meta={"attempt": term.renewal_attempts})
    transaction.on_commit(lambda: notify_term(term, "renewal_failed"))


def _run_one(term_id, now, counts):
    try:
        _process(term_id, now, counts)
    except Exception:
        counts["failed"] += 1
        logger.warning("membership_renewal_failed", extra={"term_id": term_id})


def run_membership_renewals(*, now=None, limit=200, makerspace_id=None):
    from apps.tenant_migration.gate_runtime import _boundary_shared_locks, fanout_tenant_write
    now = now or timezone.now()
    counts = {key: 0 for key in ("expired", "charged", "skipped", "failed", "opened")}
    # Read via RBAC's internal tenant boundary, including expired-in-grace candidates.
    rows = rbac.scope_for_scheduled_work(
        MembershipTerm.objects.filter(membership__status="active").filter(
            Q(status="active") | Q(status="expired", next_term__isnull=True,
                                   plan__auto_renew=True, membership__renewal_cancelled_at__isnull=True,
                                   renewal_payment__status__in=("paid_online", "paid_offline", "waived")),
        ), makerspace_id=makerspace_id, field="membership__makerspace_id",
    ).filter(Q(ends_at__lte=now + timedelta(days=8)) |
             Q(plan__auto_renew=True, ends_at__lte=now + timedelta(days=1) + F("plan__renewal_open_days") * timedelta(days=1)))
    successors = renewal_terms(makerspace_id).filter(membership_id=OuterRef("membership_id"),
        status="active", starts_at__gte=OuterRef("ends_at")).exclude(pk=OuterRef("pk"))
    rows = rows.annotate(staff_successor=Exists(successors)).filter(
        # A paid predecessor with a successor needs only its eventual expiry.
        # Keeping it in the bounded queue throughout grace starves other members.
        Q(staff_successor=False, next_term__isnull=True)
        | Q(status="active", grace_until__lte=now)
        | Q(status="active", grace_until__isnull=True, ends_at__lte=now),
    ).select_related("membership__makerspace").order_by("ends_at", "pk")
    # Completed predecessors wait for expiry; prepaid successors wait for their window.
    for term in rows[:limit]:
        space = term.membership.makerspace
        if not module_enabled(space, "membership"):
            counts["skipped"] += 1
            continue
        # F1 already owns a dedicated boundary; reacquiring behind a queued writer
        # would deadlock that writer against the outer boundary.
        if space.pk in _boundary_shared_locks.get():
            _run_one(term.pk, now, counts)
            continue
        with fanout_tenant_write(space.pk, operation="membership_renewal", counts=counts) as permitted:
            if not permitted:
                continue
            _run_one(term.pk, now, counts)
    return counts
