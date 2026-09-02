from django.urls import path

from apps.events.views_checkin import EventCheckInResolveView
from apps.events.views_checkin_offline import EventOfflineRosterView, EventOfflineSyncView
from apps.events.views_checkin_station_admin import (
    EventStationRevealView,
    EventStationRotateView,
    EventStationStatusView,
)


urlpatterns = [
    path(
        "events/<int:pk>/check-in/resolve/",
        EventCheckInResolveView.as_view(),
        name="admin-event-check-in-resolve",
    ),
    path(
        "events/<int:pk>/check-in/offline-roster/",
        EventOfflineRosterView.as_view(),
        name="admin-event-check-in-offline-roster",
    ),
    path(
        "events/<int:pk>/check-in/offline-sync/",
        EventOfflineSyncView.as_view(),
        name="admin-event-check-in-offline-sync",
    ),
    path(
        "events/<int:pk>/check-in/station/",
        EventStationStatusView.as_view(),
        name="admin-event-check-in-station",
    ),
    path(
        "events/<int:pk>/check-in/station/rotate/",
        EventStationRotateView.as_view(),
        name="admin-event-check-in-station-rotate",
    ),
    path(
        "events/<int:pk>/check-in/station/reveal/",
        EventStationRevealView.as_view(),
        name="admin-event-check-in-station-reveal",
    ),
]
