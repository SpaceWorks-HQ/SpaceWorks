"""Staff surfaces that talk to a payment provider. Withdrawn by a rail tombstone.

A refund is provider I/O: without the rail there is no vendor to send money back
through, so the route would answer only to fail.
"""

from django.urls import path

from apps.payments.views_refunds import PaymentRefundView

urlpatterns = [
    path(
        "admin/makerspace/<int:makerspace_id>/payments/<int:payment_id>/refund",
        PaymentRefundView.as_view(),
        name="payment-reconciliation-refund",
    ),
]
