from django.urls import path

from apps.evidence.views import EvidenceDetailView, EvidenceUploadUrlView
from apps.evidence.views_retention import (
    EvidenceRetentionPolicyView,
    EvidenceRetentionPreviewView,
)

app_name = "evidence_admin"

urlpatterns = [
    path(
        "makerspaces/<int:makerspace_id>/evidence-retention",
        EvidenceRetentionPolicyView.as_view(),
        name="evidence-retention-policy",
    ),
    path(
        "makerspaces/<int:makerspace_id>/evidence-retention/preview",
        EvidenceRetentionPreviewView.as_view(),
        name="evidence-retention-preview",
    ),
    path(
        "makerspaces/<int:makerspace_id>/uploads/evidence-url",
        EvidenceUploadUrlView.as_view(),
        name="evidence-upload-url",
    ),
    path("evidence/<int:pk>", EvidenceDetailView.as_view(), name="evidence-detail"),
]
