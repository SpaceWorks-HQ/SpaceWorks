from django.urls import path

from apps.organizations.views_admin import (
    OrganizationDetailView,
    OrganizationInvitationListCreateView,
    OrganizationInvitationRevokeView,
    OrganizationListView,
    OrganizationMembershipListView,
)


urlpatterns = [
    path("organizations/", OrganizationListView.as_view(), name="admin-organization-list"),
    path("organizations/<int:pk>/", OrganizationDetailView.as_view(), name="admin-organization-detail"),
    path(
        "organizations/<int:pk>/memberships/",
        OrganizationMembershipListView.as_view(),
        name="admin-organization-memberships",
    ),
    path(
        "organizations/<int:pk>/invitations/",
        OrganizationInvitationListCreateView.as_view(),
        name="admin-organization-invitations",
    ),
    path(
        "organization-invitations/<int:pk>/",
        OrganizationInvitationRevokeView.as_view(),
        name="admin-organization-invitation-revoke",
    ),
]
