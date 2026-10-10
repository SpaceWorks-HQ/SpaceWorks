"""Booking window policy, evaluated while holding the bookable-space row lock."""

from datetime import timedelta

from rest_framework import serializers

from apps.bookings.models import Booking
from apps.makerspaces.local_time import next_open_interval


def occupied_window(space, starts_at, ends_at):
    return (
        starts_at - timedelta(minutes=space.buffer_before_minutes),
        ends_at + timedelta(minutes=space.buffer_after_minutes),
    )


def enforce_opening_hours(space, starts_at, ends_at):
    """Require the entire occupied window to be covered by contiguous open intervals.

    F4 owns the local calendar and DST semantics. Walking its daily intervals also
    permits an overnight reservation when adjacent days are continuously open.
    Empty schedules retain the existing 24/7 behaviour.
    """
    cursor, end = occupied_window(space, starts_at, ends_at)
    while cursor < end:
        interval = next_open_interval(space.makerspace, cursor)
        if interval is None or interval[0] > cursor:
            raise serializers.ValidationError({
                'starts_at': 'Booking and cleanup buffers must fit within opening hours.',
            })
        cursor = interval[1]


def confirmed_overlap(space, starts_at, ends_at, *, exclude=None):
    # Both reservations carry the same space's before/after buffers. The summed
    # gap compares their occupied windows without backend-specific SQL arithmetic.
    gap = timedelta(minutes=space.buffer_before_minutes + space.buffer_after_minutes)
    queryset = Booking.objects.filter(
        space=space, status=Booking.Status.CONFIRMED,
        starts_at__lt=ends_at + gap, ends_at__gt=starts_at - gap,
    )
    if exclude is not None:
        queryset = queryset.exclude(pk=exclude)
    return queryset.exists()


def published_open_intervals(makerspace, starts_at, ends_at):
    intervals = []
    cursor = starts_at
    while cursor < ends_at:
        interval = next_open_interval(makerspace, cursor)
        if interval is None or interval[0] >= ends_at:
            break
        start, end = max(interval[0], starts_at), min(interval[1], ends_at)
        if intervals and start == intervals[-1]['ends_at']:
            intervals[-1]['ends_at'] = end
        else:
            intervals.append({'starts_at': start, 'ends_at': end})
        cursor = interval[1]
    return intervals


def validate_buffer_change(space, *, now):
    """A policy edit cannot make existing live reservations occupy the same time."""
    rows = Booking.objects.filter(
        space=space, status=Booking.Status.CONFIRMED,
        ends_at__gt=now - timedelta(minutes=space.buffer_after_minutes),
    ).order_by('starts_at', 'pk')
    previous_end = None
    for booking in rows.iterator():
        start, end = occupied_window(space, booking.starts_at, booking.ends_at)
        if previous_end is not None and start < previous_end:
            raise serializers.ValidationError({
                'buffer_after_minutes': 'These buffers overlap existing confirmed bookings.',
            })
        previous_end = end


def cancellation_cutoff(booking):
    return booking.starts_at - timedelta(hours=booking.space.cancellation_cutoff_hours)


def member_can_cancel(booking, *, now):
    return booking.status in (Booking.Status.PENDING, Booking.Status.CONFIRMED) and now < cancellation_cutoff(booking)
