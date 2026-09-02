from django.urls import path

from apps.events.views_checkin_station import (
    EventStationRosterView,
    EventStationSessionView,
    EventStationSyncView,
)


urlpatterns = [
    path(
        "event-checkin-stations/<uuid:public_token>/session/",
        EventStationSessionView.as_view(),
        name="event-check-in-station-session",
    ),
    path(
        "event-checkin-stations/<uuid:public_token>/roster/",
        EventStationRosterView.as_view(),
        name="event-check-in-station-roster",
    ),
    path(
        "event-checkin-stations/<uuid:public_token>/sync/",
        EventStationSyncView.as_view(),
        name="event-check-in-station-sync",
    ),
]
