"""Identity-aware organization totals that cannot be derived from public rows."""

from django.contrib.auth import get_user_model
from django.db.models import Count, Sum

from apps.hardware_requests.display import label_from_candidates
from apps.hardware_requests.models import HardwareRequest, HardwareRequestItem
from apps.makerspaces.anonymous_requesters import anonymous_requester_ids
from apps.makerspaces.models import MakerspaceMembership, MembershipRequest
from apps.operations.report_scope import ReportScope, scope_queryset


def globally_ranked_borrowers(scope: ReportScope, *, date_range, limit):
    items = scope_queryset(
        HardwareRequestItem.objects.filter(
            issued_quantity__gt=0,
            product__is_archived=False,
        ),
        scope,
        makerspace_field="request__makerspace_id",
    )
    items = _range(items, "request__issued_at", date_range)
    # Same reason as the per-space ranking: the shared account-less principal is not a
    # person and must not occupy a rank. Excluded before the slice so it cannot displace
    # a real borrower from the top `limit`.
    items = items.exclude(request__requester_id__in=anonymous_requester_ids())
    ranked = list(
        items.values("request__requester_id")
        .annotate(
            requests=Count("request_id", distinct=True),
            items_borrowed=Sum("issued_quantity"),
        )
        .order_by("-requests", "-items_borrowed", "request__requester_id")[:limit]
    )
    labels = _requester_labels(
        scope,
        {row["request__requester_id"] for row in ranked},
        date_range,
    )
    return [
        {
            "holder": labels.get(row["request__requester_id"], "Member"),
            "requests": row["requests"],
            "items_borrowed": row["items_borrowed"] or 0,
        }
        for row in ranked
    ]


def distinct_member_activity(scope: ReportScope, *, date_range):
    memberships = scope_queryset(
        MakerspaceMembership.objects.all(), scope, makerspace_field="makerspace_id"
    )
    requests = scope_queryset(
        MembershipRequest.objects.all(), scope, makerspace_field="makerspace_id"
    )
    return [{
        "new_members": _distinct_users(_range(memberships, "activated_at", date_range)),
        "active_members": _distinct_users(memberships.filter(status="active")),
        "revoked_members": _distinct_users(_range(memberships, "revoked_at", date_range)),
        "pending_requests": _distinct_people(requests.filter(
            kind=MembershipRequest.Kind.REQUEST,
            state=MembershipRequest.State.REQUESTED,
        )),
        "open_invites": _distinct_people(requests.filter(
            kind=MembershipRequest.Kind.INVITE,
            state=MembershipRequest.State.INVITED,
        )),
        "referred_joins": _distinct_people(_range(requests.filter(
            auto_activate_on_claim=True,
            state=MembershipRequest.State.ACTIVE,
        ), "decided_at", date_range)),
        "verified_members": _distinct_users(memberships.filter(verified_at__isnull=False)),
    }]


def _requester_labels(scope, requester_ids, date_range):
    if not requester_ids:
        return {}
    requests = scope_queryset(
        HardwareRequest.objects.filter(
            requester_id__in=requester_ids,
            items__issued_quantity__gt=0,
            items__product__is_archived=False,
        ).select_related("requester"),
        scope,
        makerspace_field="makerspace_id",
    )
    requests = _range(requests, "issued_at", date_range).order_by(
        "requester_id", "-issued_at", "-id"
    )
    labels = {}
    for request in requests.iterator(chunk_size=200):
        labels.setdefault(
            request.requester_id,
            label_from_candidates(
                request.requester_username,
                request.requester.external_checkin_user_id,
                request.requester.username,
            ),
        )
    return labels


def _distinct_users(queryset):
    return queryset.values("user_id").distinct().count()


def _normalized_email(value):
    return value.strip().lower() if value else ""


def _distinct_people(queryset):
    """Count a person once across the organization, reconciling user and email identities.

    Stage 4 [P2]: keying a row as ("user", id) when it has a user and ("email", addr)
    otherwise double-counts anyone invited to one owned makerspace BEFORE they had an
    account and to another AFTER signing up -- the pre-signup row is email-keyed, the
    post-signup row is user-keyed, and the same human counts twice. That is precisely
    the error a distinct-person metric exists to avoid.

    Reconciliation costs ONE extra query, not one per row: the account emails of every
    user referenced in this queryset are fetched in a single pass, and an email that
    belongs to a known account collapses onto that account's key.
    """
    rows = list(queryset.values_list("pk", "user_id", "invite_email"))
    user_ids = {user_id for _pk, user_id, _email in rows if user_id is not None}
    email_to_user = {}
    if user_ids:
        for user_id, email in (
            get_user_model()
            .objects.filter(pk__in=user_ids)
            .values_list("pk", "email")
        ):
            normalized = _normalized_email(email)
            if normalized:
                email_to_user[normalized] = user_id

    people = set()
    for pk, user_id, invite_email in rows:
        if user_id is not None:
            people.add(("user", user_id))
            continue
        normalized = _normalized_email(invite_email)
        if not normalized:
            people.add(("request", pk))
        elif normalized in email_to_user:
            # Same human as an account-backed row above; collapse onto the account.
            people.add(("user", email_to_user[normalized]))
        else:
            people.add(("email", normalized))
    return len(people)


def _range(queryset, field, date_range):
    if not date_range:
        return queryset
    start, end = date_range
    if start is not None:
        queryset = queryset.filter(**{f"{field}__gte": start})
    if end is not None:
        queryset = queryset.filter(**{f"{field}__lt": end})
    return queryset
