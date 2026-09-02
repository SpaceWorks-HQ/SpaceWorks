from django.urls import path

from apps.events.views_public import (
    PublicEventListView,
    PublicEventRegistrationView,
)
from apps.events.views_feedback_public import PublicEventFeedbackView
from apps.events.views_calendar import (
    PublicEventCalendarView,
    PublicMemberEventCalendarFeedView,
)


urlpatterns = [
    path(
        '<slug:makerspace_slug>/events/',
        PublicEventListView.as_view(),
        name='public-event-list',
    ),
    path(
        '<slug:makerspace_slug>/events/<uuid:public_token>/register/',
        PublicEventRegistrationView.as_view(),
        name='public-event-register',
    ),
    path(
        '<slug:makerspace_slug>/events/<uuid:public_token>/feedback/',
        PublicEventFeedbackView.as_view(),
        name='public-event-feedback',
    ),
    path(
        '<slug:makerspace_slug>/events/<uuid:public_token>/calendar.ics',
        PublicEventCalendarView.as_view(),
        name='public-event-calendar',
    ),
    path(
        '<slug:makerspace_slug>/event-calendar/<str:raw_token>.ics',
        PublicMemberEventCalendarFeedView.as_view(),
        name='public-event-calendar-feed',
    ),
]
