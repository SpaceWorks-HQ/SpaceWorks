from django.urls import path

from apps.payments.views_member import ArchivedPaymentDiscoveryView
from apps.payments.views_reconciliation import (
    PaymentBulkMarkOfflineView,
    PaymentBulkWaiveView,
    PaymentListView,
    PaymentMarkOfflineView,
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
    path("admin/makerspace/<int:makerspace_id>/payments/bulk/mark-offline", PaymentBulkMarkOfflineView.as_view(), name="payment-reconciliation-bulk-mark-offline"),
    path("admin/makerspace/<int:makerspace_id>/payments/bulk/waive", PaymentBulkWaiveView.as_view(), name="payment-reconciliation-bulk-waive"),
]
