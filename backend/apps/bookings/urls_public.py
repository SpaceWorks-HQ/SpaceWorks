from django.urls import path

from apps.bookings.views_public import (
    PublicBookableSpaceListView,
    PublicBookingSubmissionView,
    PublicSpaceAvailabilityView,
)
from apps.bookings.views_member import MemberBookingCancelView, MemberBookingListView, MemberBookingRescheduleView


from .views_feed import BookingFeedSettingsView, PublicBookingFeedView

urlpatterns = [
    path('<slug:makerspace_slug>/my-bookings/calendar/', BookingFeedSettingsView.as_view(), name='member-booking-feed-settings'),
    path('<slug:makerspace_slug>/bookings/calendar/<str:raw_token>.ics', PublicBookingFeedView.as_view(), name='public-booking-feed'),
    path('<slug:makerspace_slug>/my-bookings/<uuid:public_token>/reschedule/', MemberBookingRescheduleView.as_view(), name='member-booking-reschedule'),
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
