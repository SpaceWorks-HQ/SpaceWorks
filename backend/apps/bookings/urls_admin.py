"""Bookings' staff API, relocated out of `admin_api` (plan B5/B6, phase 14).

Separate from `urls_public.py`, which carries the member-facing space list,
availability and self-booking under `/api/v1/public/`; both are withdrawn by the same
tombstone.

Mounted at `admin_api`'s own `/api/v1/admin/` prefix with unchanged paths and route
names, so `origin_scope_routes` (keyed by bare `url_name`), the OpenAPI snapshot and
every `reverse()` are unaffected. No `app_name`, matching `admin_api`.

Ordering within the file is the original ordering: `spaces/<pk>/image/presign/` and
`spaces/<pk>/image/finalize/` must stay ahead of `spaces/<pk>/image/`, which would
otherwise never be the winning match for the more specific paths.
"""

from django.urls import path

from apps.bookings.views_admin_bookings import (
    BookingApproveView,
    BookingCancelView,
    BookingCompleteView,
    BookingNoShowView,
    BookingRejectView,
    SpaceBookingListView,
)
from apps.bookings.views_admin_rules import BookableSpaceBookingRulesView
from apps.bookings.views_admin_spaces import (
    BookableSpaceDeactivateView,
    BookableSpaceDetailView,
    BookableSpaceImageDeleteView,
    BookableSpaceImageFinalizeView,
    BookableSpaceImagePresignView,
    BookableSpaceListCreateView,
)

urlpatterns = [
    path(
        'makerspaces/<int:makerspace_id>/spaces/',
        BookableSpaceListCreateView.as_view(),
        name='admin-bookable-space-list-create',
    ),
    path(
        'spaces/<int:pk>/',
        BookableSpaceDetailView.as_view(),
        name='admin-bookable-space-detail',
    ),
    path(
        'spaces/<int:pk>/deactivate/',
        BookableSpaceDeactivateView.as_view(),
        name='admin-bookable-space-deactivate',
    ),
    path(
        'spaces/<int:pk>/image/presign/',
        BookableSpaceImagePresignView.as_view(),
        name='admin-bookable-space-image-presign',
    ),
    path(
        'spaces/<int:pk>/image/finalize/',
        BookableSpaceImageFinalizeView.as_view(),
        name='admin-bookable-space-image-finalize',
    ),
    path(
        'spaces/<int:pk>/image/',
        BookableSpaceImageDeleteView.as_view(),
        name='admin-bookable-space-image-delete',
    ),
    path(
        'spaces/<int:pk>/bookings/',
        SpaceBookingListView.as_view(),
        name='admin-space-booking-list',
    ),
    path(
        'spaces/<int:pk>/booking-rules/',
        BookableSpaceBookingRulesView.as_view(),
        name='admin-bookable-space-booking-rules',
    ),
    path(
        'bookings/<int:pk>/approve/',
        BookingApproveView.as_view(),
        name='admin-booking-approve',
    ),
    path(
        'bookings/<int:pk>/reject/',
        BookingRejectView.as_view(),
        name='admin-booking-reject',
    ),
    path(
        'bookings/<int:pk>/cancel/',
        BookingCancelView.as_view(),
        name='admin-booking-cancel',
    ),
    path(
        'bookings/<int:pk>/complete/',
        BookingCompleteView.as_view(),
        name='admin-booking-complete',
    ),
    path(
        'bookings/<int:pk>/no-show/',
        BookingNoShowView.as_view(),
        name='admin-booking-no-show',
    ),
]
