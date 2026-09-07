from django.urls import path

from apps.admin_api.views_invitation_requests import (
    InvitationRequestDeclineView,
    InvitationRequestInviteView,
    InvitationRequestListView,
)
from apps.admin_api.views_membership_plans import (
    MembershipPlanDetailView,
    MembershipPlanListCreateView,
    MembershipTermCancelView,
    MembershipTermListCreateView,
)


urlpatterns = [
    path(
        "makerspaces/<int:makerspace_id>/membership-plans",
        MembershipPlanListCreateView.as_view(),
        name="admin-membership-plans",
    ),
    path(
        "membership-plans/<int:pk>",
        MembershipPlanDetailView.as_view(),
        name="admin-membership-plan-detail",
    ),
    path(
        "memberships/<int:pk>/terms",
        MembershipTermListCreateView.as_view(),
        name="admin-membership-terms",
    ),
    path(
        "membership-terms/<int:pk>/cancel",
        MembershipTermCancelView.as_view(),
        name="admin-membership-term-cancel",
    ),
    path(
        "makerspaces/<int:makerspace_id>/invitation-requests",
        InvitationRequestListView.as_view(),
        name="admin-invitation-requests",
    ),
    path(
        "invitation-requests/<int:pk>/invite",
        InvitationRequestInviteView.as_view(),
        name="admin-invitation-request-invite",
    ),
    path(
        "invitation-requests/<int:pk>/decline",
        InvitationRequestDeclineView.as_view(),
        name="admin-invitation-request-decline",
    ),
]
