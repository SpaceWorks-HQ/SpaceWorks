"""The member's own view of what they owe. Mounted unconditionally.

Seeing a charge, its amount and its receipt is ledger business, so it survives a rail
tombstone -- withdrawing it would leave members with debts they cannot even read. Paying
one online lives in `apps.payments_rail.urls_member`.
"""

from django.urls import path

from apps.payments.views_member import MemberPaymentHistoryView
from apps.payments.views_documents import MemberDocumentListView, MemberDocumentGrantView


urlpatterns = [
    path("makerspaces/<int:makerspace_id>/payment-documents", MemberDocumentListView.as_view(), name="member-payment-documents"),
    path("makerspaces/<int:makerspace_id>/payment-documents/<int:document_id>/download-url", MemberDocumentGrantView.as_view(), name="member-payment-document-url"),
    path(
        "makerspaces/<int:makerspace_id>/payments",
        MemberPaymentHistoryView.as_view(),
        name="member-payment-history",
    ),
]
