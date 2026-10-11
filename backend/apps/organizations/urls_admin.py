from django.urls import path
from apps.organizations.views_console import OrganizationLinksView, OrganizationLinkDeleteView

from apps.organizations.views_admin import (
    OrganizationDetailView,
    OrganizationInvitationListCreateView,
    OrganizationInvitationRevokeView,
    OrganizationListView,
    OrganizationMembershipListView,
)


urlpatterns = [
    path("organizations/<int:pk>/makerspaces/", OrganizationLinksView.as_view(), name="admin-organization-links"),
    path("organizations/<int:pk>/makerspaces/<int:makerspace_id>/", OrganizationLinkDeleteView.as_view(), name="admin-organization-link-delete"),
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
