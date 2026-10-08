from django.urls import path

from apps.makerspaces.station_views_admin import (
    KioskStationDetailView,
    KioskStationListCreateView,
    KioskStationRevealView,
    KioskStationRotateView,
)
from apps.makerspaces.station_views_public import (
    KioskOperatorLeaseView,
    KioskStationSessionView,
)


urlpatterns = [
    path(
        "admin/makerspace/<int:makerspace_id>/kiosk-stations/",
        KioskStationListCreateView.as_view(),
        name="admin-kiosk-station-list-create",
    ),
    path(
        "admin/kiosk-stations/<int:pk>/",
        KioskStationDetailView.as_view(),
        name="admin-kiosk-station-detail",
    ),
    path(
        "admin/kiosk-stations/<int:pk>/rotate/",
        KioskStationRotateView.as_view(),
        name="admin-kiosk-station-rotate",
    ),
    path(
        "admin/kiosk-stations/<int:pk>/reveal/",
        KioskStationRevealView.as_view(),
        name="admin-kiosk-station-reveal",
    ),
    path(
        "kiosk-stations/<uuid:public_token>/session/",
        KioskStationSessionView.as_view(),
        name="kiosk-station-session",
    ),
    path(
        "kiosk-stations/<uuid:public_token>/operator-lease/",
        KioskOperatorLeaseView.as_view(),
        name="kiosk-station-operator-lease",
    ),
]
