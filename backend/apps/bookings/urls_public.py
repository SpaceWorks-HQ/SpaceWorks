from django.urls import path

from apps.bookings.views_public import (
    PublicBookableSpaceListView,
    PublicBookingSubmissionView,
    PublicSpaceAvailabilityView,
)
from apps.bookings.views_member import MemberBookingCancelView, MemberBookingListView


urlpatterns = [
    path('<slug:makerspace_slug>/my-bookings/', MemberBookingListView.as_view(), name='member-booking-list'),
    path('<slug:makerspace_slug>/my-bookings/<uuid:public_token>/cancel/', MemberBookingCancelView.as_view(), name='member-booking-cancel'),
    path(
        '<slug:makerspace_slug>/spaces/',
        PublicBookableSpaceListView.as_view(),
        name='public-bookable-space-list',
    ),
    path(
        '<slug:makerspace_slug>/spaces/<uuid:public_token>/availability/',
        PublicSpaceAvailabilityView.as_view(),
        name='public-space-availability',
    ),
    path(
        '<slug:makerspace_slug>/spaces/<uuid:public_token>/book/',
        PublicBookingSubmissionView.as_view(),
        name='public-booking-submit',
    ),
]
