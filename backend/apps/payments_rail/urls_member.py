"""Member surfaces that raise a provider object. Withdrawn by a rail tombstone.

Both mint something at Stripe or Razorpay, so on a deployment shipping no rail they
would exist only to 503. The member's payment HISTORY is not here: that is ledger
business and stays reachable.
"""

from django.urls import path

from apps.payments_rail.views_member_checkout import MemberPaymentCheckoutView
from apps.payments_rail.views_member_mobile import MemberMobilePaymentIntentView


urlpatterns = [
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
