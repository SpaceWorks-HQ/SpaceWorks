from django.urls import path

from apps.makerspaces.config_views import PublicConfigView
from apps.makerspaces.views import BootstrapView
from apps.makerspaces.views_membership_invitations import InvitationClaimView, InvitationDiscoveryView
from apps.makerspaces.views_memberships import (
    MemberWaiverAcceptView, MemberWaiverView, MyMembershipsView,
    PublicMembershipRequestView,
)
from apps.makerspaces.views_member_referrals import MemberReferralView
from apps.makerspaces.member_activity_views import MemberActivityView
from apps.makerspaces.profile_image_views import MemberProfileImageView
from apps.makerspaces.profile_views import (
    MemberDirectoryDetailView,
    MemberDirectoryView,
    MemberProfileView,
)
from apps.payments.views_member import MemberPaymentCheckoutView, MemberPaymentHistoryView
from apps.payments.views_member_mobile import MemberMobilePaymentIntentView

urlpatterns = [
    path("bootstrap", BootstrapView.as_view(), name="tenant-bootstrap"),
    path("config", PublicConfigView.as_view(), name="public-config"),
    path("public/<slug:makerspace_slug>/membership-requests", PublicMembershipRequestView.as_view(), name="public-membership-request"),
    path("memberships/me", MyMembershipsView.as_view(), name="my-memberships"),
    path("memberships/invitations", InvitationDiscoveryView.as_view(), name="membership-invitations"),
    path("memberships/invitations/<int:pk>/claim", InvitationClaimView.as_view(), name="membership-invitation-claim"),
    path("memberships/<int:pk>/accept-invitation", InvitationClaimView.as_view(), name="membership-invitation-claim-legacy"),
    path("member/makerspaces/<int:makerspace_id>/waiver", MemberWaiverView.as_view(), name="member-waiver"),
    path("member/makerspaces/<int:makerspace_id>/waiver/accept", MemberWaiverAcceptView.as_view(), name="member-waiver-accept"),
    path("member/makerspaces/<int:makerspace_id>/activity", MemberActivityView.as_view(), name="member-activity"),
    # The member check-in QR route is deliberately NOT here: it is an events surface and
    # must be withdrawn by an events tombstone, so it lives in `apps/events/urls_member.py`
    # and is spliced in by `config.urls.separable`. Declared here it would keep resolving,
    # and stay in the OpenAPI schema, on a deployment that ships no events app.
    path("member/makerspaces/<int:makerspace_id>/payments", MemberPaymentHistoryView.as_view(), name="member-payment-history"),
    path("member/makerspaces/<int:makerspace_id>/payments/<int:payment_id>/checkout", MemberPaymentCheckoutView.as_view(), name="member-payment-checkout"),
    path(
        'member/makerspaces/<int:makerspace_id>/payments/<int:payment_id>/mobile-intent',
        MemberMobilePaymentIntentView.as_view(),
        name='member-payment-mobile-intent',
    ),
    path("member/makerspaces/<int:makerspace_id>/referrals", MemberReferralView.as_view(), name="member-referrals"),
    path("member/makerspaces/<int:makerspace_id>/profile", MemberProfileView.as_view(), name="member-profile"),
    path("member/makerspaces/<int:makerspace_id>/profile/image", MemberProfileImageView.as_view(), name="member-profile-image"),
    path("member/makerspaces/<int:makerspace_id>/directory", MemberDirectoryView.as_view(), name="member-directory"),
    path(
        "member/makerspaces/<int:makerspace_id>/directory/<int:membership_id>",
        MemberDirectoryDetailView.as_view(),
        name="member-directory-detail",
    ),
]
