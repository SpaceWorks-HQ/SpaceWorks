from django.urls import path
from .views_machine_type_policy import MachineTypePolicyView
from .views_certification_members import CertificationMembersView

from apps.admin_api.views_certifications import (
    CertificationGrantListCreateView,
    CertificationGrantRevokeView,
    CertificationGrantRenewView,
    CertificationTypeDetailView,
    CertificationTypeListCreateView,
)


urlpatterns = [
    path("certification-types/<int:pk>/members", CertificationMembersView.as_view(), name="admin-certification-members"),
    path("certification-grants/<int:pk>/renew", CertificationGrantRenewView.as_view(), name="admin-certification-grant-renew"),
    path("makerspace/<int:makerspace_id>/machine-types/<int:machine_type_id>/policy", MachineTypePolicyView.as_view(), name="admin-machine-type-policy"),
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
