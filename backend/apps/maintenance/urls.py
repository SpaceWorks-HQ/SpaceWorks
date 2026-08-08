"""Maintenance's staff API, relocated out of `admin_api` (plan B5/B6, phase 11).

Same contract as the warranty move in phase 10: mounted at `admin_api`'s own
`/api/v1/admin/` prefix with unchanged paths and unchanged route names, so the OpenAPI
snapshot, `makerspaces.origin_scope_routes` (keyed by bare `url_name`) and every
`reverse()` are unaffected. No `app_name`, for the same reason -- these names are
unnamespaced today and a namespace would break callers silently.
"""

from django.urls import path

from apps.maintenance.views import (
    MaintenanceLogDocumentDetailView,
    MaintenanceLogDocumentFinalizeView,
    MaintenanceLogDocumentPresignView,
    MaintenanceLogDocumentUrlView,
    MaintenanceLogListCreateView,
    MaintenanceScheduleDeactivateView,
    MaintenanceScheduleDetailView,
    MaintenanceScheduleListCreateView,
)

urlpatterns = [
    # Schedules and logs hang off a machine; the per-row routes are flat because a
    # schedule or log id already identifies its machine.
    path(
        "makerspaces/<int:makerspace_id>/machines/<int:machine_id>/maintenance/schedules/",
        MaintenanceScheduleListCreateView.as_view(),
        name="admin-maintenance-schedule-list-create",
    ),
    path(
        "maintenance/schedules/<int:pk>/",
        MaintenanceScheduleDetailView.as_view(),
        name="admin-maintenance-schedule-detail",
    ),
    path(
        "maintenance/schedules/<int:pk>/deactivate/",
        MaintenanceScheduleDeactivateView.as_view(),
        name="admin-maintenance-schedule-deactivate",
    ),
    path(
        "makerspaces/<int:makerspace_id>/machines/<int:machine_id>/maintenance/logs/",
        MaintenanceLogListCreateView.as_view(),
        name="admin-maintenance-log-list-create",
    ),
    path(
        "maintenance/logs/<int:pk>/documents/presign/",
        MaintenanceLogDocumentPresignView.as_view(),
        name="admin-maintenance-log-document-presign",
    ),
    path(
        "maintenance/logs/<int:pk>/documents/",
        MaintenanceLogDocumentFinalizeView.as_view(),
        name="admin-maintenance-log-document-finalize",
    ),
    path(
        "maintenance/log-documents/<int:pk>/url/",
        MaintenanceLogDocumentUrlView.as_view(),
        name="admin-maintenance-log-document-url",
    ),
    path(
        "maintenance/log-documents/<int:pk>/",
        MaintenanceLogDocumentDetailView.as_view(),
        name="admin-maintenance-log-document-detail",
    ),
]
