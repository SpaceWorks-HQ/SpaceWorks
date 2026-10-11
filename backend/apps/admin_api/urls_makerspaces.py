from django.urls import path

from apps.admin_api import views
from apps.admin_api.views_hosting import MakerspaceProvisionSubdomainView
from apps.admin_api.views_subdomain_requests import SubdomainRequestListCreateView
from apps.admin_api.views_makerspace_profile import MakerspaceProfileView
from apps.admin_api.views_space_packs import SpacePackView, SpacePackProfileListView


urlpatterns = [
    path("makerspace/<int:makerspace_id>/space-pack", SpacePackView.as_view(), name="admin-space-pack"),
    path("space-pack-profiles", SpacePackProfileListView.as_view(), name="admin-space-pack-profiles"),
    path("makerspace/<int:makerspace_id>/profile", MakerspaceProfileView.as_view(), name="admin-makerspace-profile"),
    path("makerspaces", views.MakerspaceListCreateView.as_view(), name="admin-makerspaces"),
    path("makerspaces/<int:pk>", views.MakerspaceDetailView.as_view(), name="admin-makerspace"),
    path(
        "makerspace/<int:makerspace_id>/archive-requests",
        views.MakerspaceArchiveRequestListCreateView.as_view(),
        name="admin-makerspace-archive-requests",
    ),
    path(
        "makerspace/<int:makerspace_id>/archive-requests/<int:pk>/withdraw",
        views.MakerspaceArchiveRequestWithdrawView.as_view(),
        name="admin-makerspace-archive-request-withdraw",
    ),
    path(
        "makerspace/<int:makerspace_id>/provision-subdomain",
        MakerspaceProvisionSubdomainView.as_view(),
        name="admin-makerspace-provision-subdomain",
    ),
    path(
        "makerspace/<int:makerspace_id>/subdomain-request",
        SubdomainRequestListCreateView.as_view(),
        name="admin-makerspace-subdomain-request",
    ),
    path(
        "makerspace/<int:makerspace_id>/verify-domain",
        views.MakerspaceVerifyDomainView.as_view(),
        name="makerspace-verify-domain",
    ),
    path(
        "makerspace/<int:makerspace_id>/return-policy",
        views.ReturnPolicyView.as_view(),
        name="admin-return-policy",
    ),
    path(
        "makerspace/<int:makerspace_id>/logo",
        views.MakerspaceLogoImageView.as_view(),
        name="admin-makerspace-logo",
    ),
    path(
        "makerspace/<int:makerspace_id>/cover",
        views.MakerspaceCoverImageView.as_view(),
        name="admin-makerspace-cover",
    ),
]
