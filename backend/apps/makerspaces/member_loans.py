"""Active reviewed and direct loans with policy-bound renewal eligibility."""

from rest_framework.exceptions import ValidationError

from apps.accounts import rbac
from apps.hardware_requests.models import HardwareRequest, PublicToolLoan
from apps.hardware_requests.renewal_workflow import ACTIVE_LOAN_STATUSES, check_renewal
from apps.makerspaces.models_loan_policy import MakerspaceLoanPolicy
from apps.makerspaces.platform import feature_enabled


def member_loans(makerspace, member, now, *, limit=50):
    rows = rbac.scope_by_borrower(member, HardwareRequest.objects.all(), makerspace=makerspace).filter(
        status__in=ACTIVE_LOAN_STATUSES,
    ).select_related("requester", "makerspace").prefetch_related("items__product__category").order_by("return_due_at", "issued_at")[:limit]
    rows = list(rows)
    linked = rbac.scope_by_borrower(member, PublicToolLoan.objects.all(), makerspace=makerspace).filter(
        request_id__in=[row.pk for row in rows], status=PublicToolLoan.Status.CHECKED_OUT,
    )
    labels = {loan.request_id: loan.target_label for loan in linked}
    policy = MakerspaceLoanPolicy.for_makerspace(makerspace)
    enabled = feature_enabled(makerspace, "loans.renewals")
    result = []
    for row in rows:
        can_renew, reason = False, "renewals_off"
        if enabled:
            try:
                check_renewal(row, policy, actor=member)
                can_renew, reason = True, None
            except ValidationError as exc:
                reason = str(exc.detail["code"])
        result.append({
            "request_id": row.pk, "label": labels.get(row.pk) or ", ".join(item.product.name for item in row.items.all()),
            "checked_out_at": row.issued_at or row.created_at, "due_at": row.return_due_at,
            "overdue": bool(row.return_due_at and row.return_due_at < now),
            "renewal_count": row.renewal_count, "can_renew": can_renew, "renewal_refusal": reason,
        })
    return result
