from django.urls import path

from apps.admin_api import (
    api_client_scope_views,
    api_client_settings_views,
    api_client_views,
)


makerspace_urlpatterns = [
    path(
        "makerspace/<int:makerspace_id>/api-clients",
        api_client_views.ApiClientListCreateView.as_view(),
        name="admin-api-clients",
    ),
    path(
        "makerspace/<int:makerspace_id>/api-client-scopes",
        api_client_scope_views.ApiClientScopeCatalogView.as_view(),
        name="admin-api-client-scopes",
    ),
    path(
        "makerspace/<int:makerspace_id>/api-settings",
        api_client_settings_views.ApiIntegrationSettingsView.as_view(),
        name="admin-api-settings",
    ),
]


client_urlpatterns = [
    path(
        "api-clients/<int:pk>",
        api_client_views.ApiClientDetailView.as_view(),
        name="admin-api-client",
    ),
    path(
        "api-clients/<int:pk>/rotate-secret",
        api_client_views.ApiClientRotateSecretView.as_view(),
        name="admin-api-client-rotate-secret",
    ),
    path(
        "api-key-requests",
        api_client_views.ApiKeyRequestListCreateView.as_view(),
        name="admin-api-key-requests",
    ),
]
