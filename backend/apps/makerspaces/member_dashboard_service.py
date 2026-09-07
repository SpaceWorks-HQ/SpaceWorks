"""The member dashboard's history, money and notices (owner decision D8).

`member_activity_service` answers "what is happening right now" -- active loans, today's
bookings, presence. This answers the three things a member actually opens a dashboard
for: what have I borrowed and given back, what do I owe, and what needs my attention.

Gated by the `membership` module through the one endpoint that serves it, so a space
that does not run memberships is unchanged. **Payment visibility is deliberately NOT
behind that gate** and lives in `apps.payments`: an account-only borrower with a loan
deposit must be able to see and settle a debt whether or not they hold a membership.
What is here is the dashboard's *summary* of dues, for a member who by definition has
one.

The notices feed is DERIVED from the member's own rows, not read from
`notifications.Notification`. That table is makerspace-wide: it has no recipient column
and one shared `read_at`, so serving it to members would hand them staff alerts and let
one member's read mark speak for everyone. A derived feed cannot leak, needs no
migration, and says only things that are true of the member reading it.
"""

from datetime import timedelta

from django.db.models import Sum
from django.utils import timezone

from apps.hardware_requests.models import HardwareRequest
from apps.hardware_requests.self_checkout_models import PublicToolLoan

HISTORY_LIMIT = 20


def loan_history(makerspace_id, member):
    """Returned self-checkout loans, newest first, with what came back."""
    rows = (
        PublicToolLoan.objects.filter(
            makerspace_id=makerspace_id,
            requester=member,
            status=PublicToolLoan.Status.RETURNED,
        )
        .only("target_label", "checked_out_at", "due_at", "returned_at")
        .order_by("-returned_at")[:HISTORY_LIMIT]
    )
    return [
        {
            "label": row.target_label,
            "checked_out_at": row.checked_out_at,
            "returned_at": row.returned_at,
            "due_at": row.due_at,
            # Whether it came back late is the member's own record, and it is the one
            # fact a borrower is most likely to want to check.
            "returned_late": bool(
                row.due_at and row.returned_at and row.returned_at > row.due_at
            ),
        }
        for row in rows
    ]


def request_history(makerspace_id, member):
    """The member's own reviewed hardware requests, whatever became of them.

    `member_activity` only ever showed ACTIVE self-checkout loans, so a member could not
    see a request they submitted last week, whether it was accepted, or what they
    returned. Scoped by `requester`, so it is their own history and nobody else's.
    """
    rows = (
        HardwareRequest.objects.filter(makerspace_id=makerspace_id, requester=member)
        .only("status", "created_at")
        .prefetch_related("items")
        .order_by("-created_at")[:HISTORY_LIMIT]
    )
    history = []
    for row in rows:
        items = list(row.items.all())
        history.append(
            {
                "status": row.status,
                "created_at": row.created_at,
                "item_count": len(items),
                "returned_quantity": sum(item.returned_quantity for item in items),
                # Surfaced because it is what an accountability restriction is based on:
                # a member should see the same damage/loss record staff are acting on.
                "damaged_quantity": sum(item.damaged_quantity for item in items),
                "missing_quantity": sum(item.missing_quantity for item in items),
            }
        )
    return history


def membership_dues(membership):
    """What this membership costs and what of it is outstanding.

    Read through the payments app rather than recomputed here: the ledger is the single
    authority on what is owed, and a second sum would eventually disagree with it.

    `outstanding_by_currency` is `None` when the ledger could not be read at all, which
    is deliberately distinct from `{}` for "nothing outstanding": a member must never be
    told they owe nothing on the strength of a query that failed.
    """
    makerspace = membership.makerspace
    totals = {}
    try:
        from apps.payments.models import Payment

        # Grouped BY CURRENCY and never added across them, the same rule the staff
        # dashboard and the reconciliation report follow: one combined figure mixing
        # INR and USD is not money.
        rows = (
            Payment.objects.filter(
                makerspace=makerspace,
                member=membership.user,
                status=Payment.Status.PENDING,
            )
            .values("currency")
            .annotate(total=Sum("amount"))
            .order_by("currency")
        )
        totals = {row["currency"]: str(row["total"]) for row in rows}
    except Exception:
        # A payments failure must not blank a member's loans and bookings: money is one
        # section of this dashboard, not a precondition for rendering it. But it must not
        # read as "you owe nothing" either -- that is a false statement about someone's
        # money, and the reader cannot tell it from a real zero. `None` means "could not
        # be read" and renders as unavailable; `{}` means "nothing is outstanding".
        totals = None
    return {
        "dues_amount": str(makerspace.membership_dues_amount or 0),
        "outstanding_by_currency": totals,
    }


def notices(membership, activity):
    """Things that need this member's attention, derived from their own rows.

    Ordered most-urgent first. Every entry is a fact about the reader, which is what
    makes serving it safe without a recipient-scoped notification table.
    """
    now = timezone.now()
    feed = []
    accountability = activity.get("accountability") or {}
    if accountability.get("restriction_code"):
        feed.append({
            "level": "critical",
            "event": "access_restricted",
            "title": "Your borrowing is restricted",
            "body": "Speak to staff to resolve an outstanding accountability issue.",
        })
    if accountability.get("waiver_acceptance_required"):
        feed.append({
            "level": "warning",
            "event": "waiver_required",
            "title": "A waiver needs your acceptance",
            "body": "You cannot borrow or check in until the current waiver is accepted.",
        })
    if not accountability.get("membership_active", True):
        feed.append({
            "level": "warning",
            "event": "membership_inactive",
            "title": "Your membership is not active",
            "body": "Renew to keep borrowing and booking.",
        })
    overdue = [
        loan for loan in activity.get("active_hardware_loans") or [] if loan.get("overdue")
    ]
    if overdue:
        feed.append({
            "level": "critical",
            "event": "loan_overdue",
            "title": f"{len(overdue)} item(s) are overdue",
            "body": "Return them as soon as you can; a late fee may apply.",
        })
    due_soon = [
        loan
        for loan in activity.get("active_hardware_loans") or []
        if loan.get("due_at") and not loan.get("overdue")
        # The whole timedelta, not `.days`: that floors, so everything under 48 hours
        # reported as 1 and a loan due in two days was announced as due within one.
        and loan["due_at"] - now <= timedelta(days=1)
    ]
    if due_soon:
        feed.append({
            "level": "info",
            "event": "loan_due_soon",
            "title": f"{len(due_soon)} item(s) are due within a day",
            "body": "",
        })
    dues = activity.get("membership_dues") or {}
    if dues.get("outstanding_by_currency"):
        owed = ", ".join(
            f"{amount} {currency.upper()}"
            for currency, amount in sorted(dues["outstanding_by_currency"].items())
        )
        feed.append({
            "level": "warning",
            "event": "payment_due",
            "title": f"You have {owed} outstanding",
            "body": "Pay online where available, or settle it at the space.",
        })
    return feed
