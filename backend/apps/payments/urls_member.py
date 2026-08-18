"""Payments' member-facing surface, mounted under ``/api/v1/member/``.

These routes live with the payments app so ``config.urls.separable`` can withdraw
them when payments is tombstoned. Keeping them in the makerspaces urlconf would leave
checkout creation reachable after the rest of the payment surface disappeared.
"""

from django.urls import path

from apps.payments.views_member import MemberPaymentCheckoutView, MemberPaymentHistoryView
from apps.payments.views_member_mobile import MemberMobilePaymentIntentView


urlpatterns = [
    path(
        "makerspaces/<int:makerspace_id>/payments",
        MemberPaymentHistoryView.as_view(),
        name="member-payment-history",
    ),
    path(
        "makerspaces/<int:makerspace_id>/payments/<int:payment_id>/checkout",
        MemberPaymentCheckoutView.as_view(),
        name="member-payment-checkout",
    ),
    path(
        "makerspaces/<int:makerspace_id>/payments/<int:payment_id>/mobile-intent",
        MemberMobilePaymentIntentView.as_view(),
        name="member-payment-mobile-intent",
    ),
]
