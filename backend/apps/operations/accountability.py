from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.accounts.models import User
from apps.hardware_requests.display import requester_label
from apps.hardware_requests.models import (
    HardwareRequest,
    PublicProblemReport,
    PublicToolLoan,
    RequesterAccountability,
)
from apps.makerspaces.anonymous_requesters import anonymous_requester_ids


def _anonymous_accountability(makerspace_id, principals):
    """Damage and loss recorded against account-less requests, as one total.

    Not a ranking row and deliberately not shaped like one: there is no person to name,
    contact or restrict here, only a count of what strangers did not bring back.
    """
    totals = RequesterAccountability.objects.filter(
        makerspace_id=makerspace_id, requester_id__in=principals
    ).aggregate(
        damaged=Count("id", filter=Q(issue_type=RequesterAccountability.IssueType.DAMAGED)),
        missing=Count("id", filter=Q(issue_type=RequesterAccountability.IssueType.MISSING)),
        total_issues=Count("id"),
        total_quantity=Coalesce(Sum("quantity"), 0),
    )
    return {key: value or 0 for key, value in totals.items()}


def accountability_data(makerspace_id, *, limit=200):
    principals = anonymous_requester_ids([makerspace_id])
    repeat_offenders, repeat_truncated = _repeat_offenders(makerspace_id, limit, principals)
    overdue, overdue_truncated = _overdue_loans(makerspace_id, limit)
    problem_reports, problems_truncated = _problem_reports(makerspace_id, limit)
    return {
        "repeat_offenders": repeat_offenders,
        # The damage and loss that the excluded principal was carrying, kept as a total
        # rather than dropped: an accountability panel that silently lost every
        # account-less incident would be worse than one that named a fictional person.
        "anonymous_accountability": _anonymous_accountability(makerspace_id, principals),
        "overdue": overdue,
        "restrictions": _restricted_requesters(makerspace_id),
        "problem_reports": problem_reports,
        "truncated": {
            "repeat_offenders": repeat_truncated,
            "overdue": overdue_truncated,
            "problem_reports": problems_truncated,
        },
    }


def _problem_reports(makerspace_id, limit):
    rows = list(
        PublicProblemReport.objects.filter(
            makerspace_id=makerspace_id, resolved_at__isnull=True
        )
        .select_related("requester", "loan", "request").prefetch_related("request__items__product")
        .order_by("created_at")[: limit + 1]
    )
    return [
        {
            "id": report.id,
            "requester_username": report.requester.username,
            "label": report.loan.target_label,
            "note": report.note,
            "created_at": report.created_at.isoformat(),
            "items": [
                {
                    "id": item.id,
                    "product_name": item.product.name,
                    "issued_quantity": item.issued_quantity,
                    "tracking_mode": item.product.tracking_mode,
                }
                for item in report.request.items.all()
            ],
        }
        for report in rows[:limit]
    ], len(rows) > limit


def _repeat_offenders(makerspace_id, limit, principals):
    rows = list(
        # Excluded BEFORE the limit, not after: filtering a materialized page would let
        # the principal push a real repeat offender off the end of the list.
        RequesterAccountability.objects.filter(makerspace_id=makerspace_id)
        .exclude(requester_id__in=principals)
        .values(
            "requester_id",
            "requester__username",
            "requester__access_status",
            "requester__restriction_reason",
        )
        .annotate(
            damaged=Count("id", filter=Q(issue_type=RequesterAccountability.IssueType.DAMAGED)),
            missing=Count("id", filter=Q(issue_type=RequesterAccountability.IssueType.MISSING)),
            total_issues=Count("id"),
            total_quantity=Coalesce(Sum("quantity"), 0),
        )
        .order_by("-total_issues", "-total_quantity")[: limit + 1]
    )
    return [
        {
            "requester_id": row["requester_id"],
            "username": row["requester__username"],
            "access_status": row["requester__access_status"],
            "restriction_reason": row["requester__restriction_reason"],
            "damaged": row["damaged"],
            "missing": row["missing"],
            "total_issues": row["total_issues"],
            "total_quantity": row["total_quantity"],
        }
        for row in rows[:limit]
    ], len(rows) > limit


def _overdue_loans(makerspace_id, limit):
    now = timezone.now()
    # Bound each source at the DB (limit + 1, oldest first) before materializing so a
    # makerspace with thousands of overdue loans can't load them all into memory.
    rows = _overdue_requests(makerspace_id, now, limit) + _overdue_direct_loans(makerspace_id, now, limit)
    rows.sort(key=lambda row: row["due_at"])
    truncated = len(rows) > limit
    return [
        {
            **row,
            "due_at": row["due_at"].isoformat(),
            "days_overdue": (now - row["due_at"]).days,
        }
        for row in rows[:limit]
    ], truncated


def _overdue_requests(makerspace_id, now, limit):
    queryset = (
        HardwareRequest.objects.filter(
            makerspace_id=makerspace_id,
            status__in=[
                HardwareRequest.Status.ISSUED,
                HardwareRequest.Status.PARTIALLY_RETURNED,
            ],
            return_due_at__lt=now,
            public_tool_loan__isnull=True,
        )
        .select_related("requester")
        .prefetch_related("items__product")
        .order_by("return_due_at")[: limit + 1]
    )
    return [
        {
            "type": "request",
            "reference_id": request.id,
            # `requester_label` prefers the request's own contact snapshot, so an
            # account-less overdue loan shows the email the borrower actually gave
            # instead of the principal's internal `member_<uuid>` username.
            "requester_username": requester_label(request),
            "label": _request_label(request),
            "due_at": request.return_due_at,
        }
        for request in queryset
    ]


def _overdue_direct_loans(makerspace_id, now, limit):
    queryset = PublicToolLoan.objects.filter(
        makerspace_id=makerspace_id,
        status=PublicToolLoan.Status.CHECKED_OUT,
        due_at__lt=now,
    ).select_related("requester").order_by("due_at")[: limit + 1]
    return [
        {
            "type": "direct",
            "reference_id": loan.id,
            "requester_username": loan.requester.username,
            "label": loan.target_label,
            "due_at": loan.due_at,
        }
        for loan in queryset
    ]


def _request_label(request):
    names = [item.product.name for item in request.items.all()]
    label = ", ".join(names[:5])
    if len(names) > 5:
        label = f"{label}, ..."
    return label


def _restricted_requesters(makerspace_id):
    # The principal can never legitimately appear here -- restrict/restore both refuse it
    # via `refuse_anonymous_requester_access_mutation` -- but it is excluded anyway, so a
    # row created before that guard, or by a direct DB edit, cannot render as a person.
    principals = anonymous_requester_ids([makerspace_id])
    return [
        {
            "requester_id": user.id,
            "username": user.username,
            "access_status": user.access_status,
            "restriction_reason": user.restriction_reason,
        }
        for user in User.objects.exclude(pk__in=principals).filter(
            accountability_records__makerspace_id=makerspace_id,
            access_status__in=[
                User.AccessStatus.RESTRICTED,
                User.AccessStatus.SUSPENDED,
            ],
        )
        .distinct()
        .order_by("username")
    ]
