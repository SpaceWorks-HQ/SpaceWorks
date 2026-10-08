from django.urls import path

from apps.devices.views_enrollment import (
    DeviceEnrollmentChallengeView,
    DeviceEnrollmentCompleteView,
)
from apps.devices.views_heartbeat import DeviceHeartbeatView
from apps.devices.views_identity import (
    DeviceDetailView,
    DeviceEnrollmentCreateView,
    DeviceListCreateView,
    DeviceRevokeView,
)

app_name = "devices"

# Object routes use `pk`: the origin-scope resolver reads only kwargs["pk"].
urlpatterns = [
    path(
        "admin/makerspace/<int:makerspace_id>/devices",
        DeviceListCreateView.as_view(),
        name="admin-device-list",
    ),
    path("admin/devices/<uuid:pk>", DeviceDetailView.as_view(), name="admin-device-detail"),
    path(
        "admin/devices/<uuid:pk>/enrollments",
        DeviceEnrollmentCreateView.as_view(),
        name="admin-device-enrollment-create",
    ),
    path("admin/devices/<uuid:pk>/revoke", DeviceRevokeView.as_view(), name="admin-device-revoke"),
    # Everything under device/ is covered by route_registry.DEVICE_ROUTES.
    path(
        "device/enrollments/<uuid:pk>/challenge",
        DeviceEnrollmentChallengeView.as_view(),
        name="device-enrollment-challenge",
    ),
    path(
        "device/enrollments/<uuid:pk>/complete",
        DeviceEnrollmentCompleteView.as_view(),
        name="device-enrollment-complete",
    ),
    path("device/heartbeat", DeviceHeartbeatView.as_view(), name="device-heartbeat"),
]
