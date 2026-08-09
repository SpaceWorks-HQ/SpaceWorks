"""Events' staff API, relocated out of `admin_api` (plan B5/B6, phase 13).

Separate from `urls_public.py`, which carries the member-facing event list and
registration under `/api/v1/public/`; both are withdrawn by the same tombstone.

Mounted at `admin_api`'s own `/api/v1/admin/` prefix with unchanged paths and route
names, so `origin_scope_routes` (keyed by bare `url_name`), the OpenAPI snapshot and
every `reverse()` are unaffected. No `app_name`, matching `admin_api`.
"""

from django.urls import path

from apps.events.views_admin import (
    EventCancelView,
    EventCompleteView,
    EventDetailView,
    EventListCreateView,
    EventPublishView,
    EventRegistrationListView,
    EventRegistrationMarkAttendedView,
)
from apps.events.views_admin_image import EventImageView

urlpatterns = [
    path(
        'makerspaces/<int:makerspace_id>/events/',
        EventListCreateView.as_view(),
        name='admin-event-list-create',
    ),
    path(
        'events/<int:pk>/',
        EventDetailView.as_view(),
        name='admin-event-detail',
    ),
    path(
        'events/<int:pk>/publish/',
        EventPublishView.as_view(),
        name='admin-event-publish',
    ),
    path(
        'events/<int:pk>/cancel/',
        EventCancelView.as_view(),
        name='admin-event-cancel',
    ),
    path(
        'events/<int:pk>/complete/',
        EventCompleteView.as_view(),
        name='admin-event-complete',
    ),
    path(
        'events/<int:pk>/image',
        EventImageView.as_view(),
        name='admin-event-image',
    ),
    path(
        'events/<int:pk>/registrations/',
        EventRegistrationListView.as_view(),
        name='admin-event-registration-list',
    ),
    path(
        'event-registrations/<int:pk>/mark-attended/',
        EventRegistrationMarkAttendedView.as_view(),
        name='admin-event-registration-mark-attended',
    ),
]
