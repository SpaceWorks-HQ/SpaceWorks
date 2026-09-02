from django.db.models import Count, F, IntegerField, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce

from apps.makerspaces.models import Makerspace, MakerspaceMembership, MembershipRequest
from apps.operations.report_registry import ReportResult
from apps.operations.report_scope import scoped_ids


FIELDS = (
    "makerspace_name", "membership_policy", "referrals_enabled", "new_members",
    "active_members", "revoked_members", "pending_requests", "open_invites",
    "referred_joins", "verified_members",
)


def build_member_activity(makerspace_id, *, limit=None, date_range=None):
    """Report membership snapshots; range metrics use the current lifecycle timestamps."""
    aggregate = makerspace_id is None
    memberships = MakerspaceMembership.objects.filter(makerspace_id=OuterRef("pk"))
    requests = MembershipRequest.objects.filter(makerspace_id=OuterRef("pk"))
    queryset = Makerspace.objects.filter(id__in=scoped_ids(makerspace_id, "membership")).annotate(
        makerspace_id=F("id"),
        makerspace_name=F("name"),
        new_members=_count(memberships.filter(_in_range("activated_at", date_range))),
        active_members=_count(memberships.filter(status="active")),
        revoked_members=_count(memberships.filter(_in_range("revoked_at", date_range))),
        pending_requests=_count(requests.filter(
            kind=MembershipRequest.Kind.REQUEST,
            state=MembershipRequest.State.REQUESTED,
        )),
        open_invites=_count(requests.filter(
            kind=MembershipRequest.Kind.INVITE,
            state=MembershipRequest.State.INVITED,
        )),
        referred_joins=_count(requests.filter(
            auto_activate_on_claim=True,
            state=MembershipRequest.State.ACTIVE,
        ).filter(_in_range("decided_at", date_range))),
        verified_members=_count(memberships.filter(verified_at__isnull=False)),
    )
    fields = (("makerspace_id",) + FIELDS) if aggregate else FIELDS
    rows = queryset.values(*fields).order_by("id")
    if limit is not None:
        rows = rows[:limit]
    return ReportResult(fields, list(rows))


def _count(queryset):
    grouped = queryset.values("makerspace_id").annotate(count=Count("pk")).values("count")[:1]
    return Coalesce(Subquery(grouped, output_field=IntegerField()), Value(0))


def _in_range(field, date_range):
    query = Q()
    if date_range:
        start, end = date_range
        if start is not None:
            query &= Q(**{f"{field}__gte": start})
        if end is not None:
            query &= Q(**{f"{field}__lt": end})
    return query
