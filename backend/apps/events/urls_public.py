from django.urls import path

from apps.events.views_public import (
    PublicEventListView,
    PublicEventRegistrationView,
)
from apps.events.views_feedback_public import PublicEventFeedbackView


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
]
