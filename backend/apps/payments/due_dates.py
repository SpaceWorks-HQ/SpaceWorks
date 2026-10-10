"""A charge's due date is history; overdue is a view of today's local day."""

from datetime import timedelta

from django.db.models import F, Q
from django.utils import timezone

from apps.accounts import rbac
from apps.makerspaces.local_time import local_day_bounds, to_local
from apps.payments.models_billing import MakerspaceBillingSettings


def default_due_at(makerspace, *, actor, now=None):
    now = now or timezone.now()
    policies = MakerspaceBillingSettings.objects.all()
    # Internal charge seams also serve account-only borrowers. Scheduled-work scope
    # admits a live tenant; explicit actor scope retains a hidden tenant's own staff.
    policies = (rbac.scope_by_makerspace(actor, policies) |
                rbac.scope_for_scheduled_work(policies, makerspace_id=makerspace.pk))
    days = (policies.filter(makerspace=makerspace)
            .values_list("payment_terms_days", flat=True).first()) or 0
    if days == 0:
        return now
    day = to_local(makerspace, now).date() + timedelta(days=days)
    return local_day_bounds(makerspace, day)[0]


def due_state(payment, *, now=None):
    if payment.status != "pending" or payment.due_at is None:
        return ""
    today = to_local(payment.makerspace, now or timezone.now()).date()
    due = to_local(payment.makerspace, payment.due_at).date()
    return "overdue" if due < today else "due_today" if due == today else "upcoming"


def filter_due(queryset, makerspace, state, *, now=None):
    if not state:
        return queryset
    today = to_local(makerspace, now or timezone.now()).date()
    start, end = local_day_bounds(makerspace, today)
    conditions = {
        "overdue": Q(due_at__lt=start),
        "due_today": Q(due_at__gte=start, due_at__lt=end),
        "upcoming": Q(due_at__gte=end),
    }
    return queryset.filter(conditions[state], status="pending")


def order_by_due(queryset):
    return queryset.order_by(F("due_at").asc(nulls_last=True), "pk")
