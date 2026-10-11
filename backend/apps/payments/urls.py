"""The payment LEDGER's staff surface. Mounted unconditionally.

Recording, listing and settling money owed is not an online-payment feature: a
deployment that ships no provider rail at all still has members who owe money and staff
who take it at the desk. Only the routes that actually talk to a provider live in
`apps.payments_rail.urls`, where a tombstone can withdraw them.
"""

from django.urls import path

from apps.payments.views_member import ArchivedPaymentDiscoveryView
from apps.payments.views_documents import StaffDocumentListView, StaffDocumentGrantView, DocumentDownloadView
from apps.payments.views_billing import BillingSettingsView
from apps.payments.views_refunds_offline import PaymentOfflineRefundView, PaymentDepositReleaseView, PaymentRefundAmendView
from apps.payments.views_reconciliation import (
    PaymentBulkMarkOfflineView,
    PaymentBulkWaiveView,
    PaymentListView,
    PaymentMarkOfflineView,
    PaymentSettlementAmendView,
    PaymentWaiveView,
)

urlpatterns = [
    path("admin/makerspace/<int:makerspace_id>/payment-documents", StaffDocumentListView.as_view(), name="staff-payment-documents"),
    path("admin/makerspace/<int:makerspace_id>/payment-documents/<int:document_id>/download-url", StaffDocumentGrantView.as_view(), name="staff-payment-document-url"),
    path("payment-documents/<int:document_id>/download", DocumentDownloadView.as_view(), name="payment-document-download"),
    path("admin/makerspace/<int:makerspace_id>/billing-settings", BillingSettingsView.as_view(), name="payment-billing-settings"),
    path("admin/makerspace/<int:makerspace_id>/payments/<int:payment_id>/release-deposit", PaymentDepositReleaseView.as_view(), name="payment-deposit-release"),
    path("admin/makerspace/<int:makerspace_id>/payments/<int:payment_id>/refunds/<int:refund_id>/amend", PaymentRefundAmendView.as_view(), name="payment-refund-amend"),
    path("admin/makerspace/<int:makerspace_id>/payments/<int:payment_id>/refund-offline", PaymentOfflineRefundView.as_view(), name="payment-reconciliation-refund-offline"),
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
