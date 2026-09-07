"""The member's own view of what they owe. Mounted unconditionally.

Seeing a charge, its amount and its receipt is ledger business, so it survives a rail
tombstone -- withdrawing it would leave members with debts they cannot even read. Paying
one online lives in `apps.payments_rail.urls_member`.
"""

from django.urls import path

from apps.payments.views_member import MemberPaymentHistoryView


urlpatterns = [
    path(
        "makerspaces/<int:makerspace_id>/payments",
        MemberPaymentHistoryView.as_view(),
        name="member-payment-history",
    ),
]
