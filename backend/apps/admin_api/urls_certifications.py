from django.urls import path

from apps.admin_api.views_certifications import (
    CertificationGrantListCreateView,
    CertificationGrantRevokeView,
    CertificationTypeDetailView,
    CertificationTypeListCreateView,
)


urlpatterns = [
    path(
        'makerspace/<int:makerspace_id>/certification-types',
        CertificationTypeListCreateView.as_view(),
        name='admin-certification-types',
    ),
    path(
        'certification-types/<int:pk>',
        CertificationTypeDetailView.as_view(),
        name='admin-certification-type-detail',
    ),
    path(
        'certification-types/<int:pk>/grants',
        CertificationGrantListCreateView.as_view(),
        name='admin-certification-type-grants',
    ),
    path(
        'certification-grants/<int:pk>/revoke',
        CertificationGrantRevokeView.as_view(),
        name='admin-certification-grant-revoke',
    ),
]
