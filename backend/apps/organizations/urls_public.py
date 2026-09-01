from django.urls import path

from apps.organizations.views_public import (
    PublicOrganizationDetailView,
    PublicOrganizationEventListView,
)


urlpatterns = [
    path("<slug:slug>/", PublicOrganizationDetailView.as_view(), name="public-organization-detail"),
    path(
        "<slug:slug>/events/",
        PublicOrganizationEventListView.as_view(),
        name="public-organization-events",
    ),
]
