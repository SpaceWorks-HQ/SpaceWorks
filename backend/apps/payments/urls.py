"""The payment LEDGER's staff surface. Mounted unconditionally.

Recording, listing and settling money owed is not an online-payment feature: a
deployment that ships no provider rail at all still has members who owe money and staff
who take it at the desk. Only the routes that actually talk to a provider live in
`apps.payments_rail.urls`, where a tombstone can withdraw them.
"""

from django.urls import path

from apps.payments.views_member import ArchivedPaymentDiscoveryView
from apps.payments.views_reconciliation import (
    PaymentBulkMarkOfflineView,
    PaymentBulkWaiveView,
    PaymentListView,
    PaymentMarkOfflineView,
    PaymentSettlementAmendView,
    PaymentWaiveView,
)

urlpatterns = [
    path(
        "member/archived-payments",
        ArchivedPaymentDiscoveryView.as_view(),
        name="member-archived-payments",
    ),
    path("admin/makerspace/<int:makerspace_id>/payments", PaymentListView.as_view(), name="payment-reconciliation-list"),
    path("admin/makerspace/<int:makerspace_id>/payments/<int:payment_id>/mark-offline", PaymentMarkOfflineView.as_view(), name="payment-reconciliation-mark-offline"),
    path("admin/makerspace/<int:makerspace_id>/payments/<int:payment_id>/waive", PaymentWaiveView.as_view(), name="payment-reconciliation-waive"),
    path(
        "admin/makerspace/<int:makerspace_id>/payments/<int:payment_id>/amend-settlement",
        PaymentSettlementAmendView.as_view(),
        name="payment-settlement-amend",
    ),
    path("admin/makerspace/<int:makerspace_id>/payments/bulk/mark-offline", PaymentBulkMarkOfflineView.as_view(), name="payment-reconciliation-bulk-mark-offline"),
    path("admin/makerspace/<int:makerspace_id>/payments/bulk/waive", PaymentBulkWaiveView.as_view(), name="payment-reconciliation-bulk-waive"),
]
