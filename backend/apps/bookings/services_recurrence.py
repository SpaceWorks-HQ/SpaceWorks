"""Bounded weekly staff bookings; each occurrence uses the ordinary locked workflow."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.bookings.exceptions import BookingConflict, BookingInvalidTransition
from apps.bookings.services_bookings import create_booking, _locked_space
from apps.makerspaces.local_time import _wall_bound, to_local
from apps.makerspaces.platform import feature_enabled


@transaction.atomic
def create_recurring_bookings(space, *, actor, starts_at, ends_at, count, interval_weeks=1, **values):
    from apps.accounts import rbac
    from rest_framework.exceptions import PermissionDenied
    from apps.makerspaces.guards import require_module_locked
    locked = _locked_space(space.pk)
    locked.makerspace = require_module_locked(locked.makerspace, 'bookings')
    if not rbac.can(actor, rbac.Action.MANAGE_BOOKINGS, locked):
        raise PermissionDenied()
    if not feature_enabled(locked.makerspace, 'bookings.recurring'):
        raise ValidationError({'feature': 'Recurring bookings are disabled.'})
    if type(count) is not int or not 2 <= count <= 52 or type(interval_weeks) is not int or not 1 <= interval_weeks <= 12:
        raise ValidationError({'count': 'Use 2–52 occurrences, spaced 1–12 weeks apart.'})
    if (count - 1) * interval_weeks > 52:
        raise ValidationError({'count': 'The last occurrence must be within 52 weeks.'})
    if timezone.is_naive(starts_at) or timezone.is_naive(ends_at):
        raise ValidationError({'starts_at': 'Datetime must include a timezone offset.'})
    try:
        ends_at + timedelta(weeks=(count - 1) * interval_weeks, days=1)
    except OverflowError:
        raise ValidationError({'ends_at': 'Series exceeds the supported calendar range.'})
    local = to_local(locked.makerspace, starts_at)
    zone = ZoneInfo(locked.makerspace.timezone)
    duration = ends_at - starts_at
    if duration <= timedelta(0):
        raise ValidationError({'ends_at': 'End must follow start.'})
    result = []
    for index in range(count):
        wall = datetime.combine(local.date() + timedelta(weeks=index * interval_weeks), local.time().replace(tzinfo=None))
        start = _wall_bound(zone, wall)
        end = start + duration
        item = {'occurrence': index + 1, 'starts_at': start, 'ends_at': end}
        if start.astimezone(zone).replace(tzinfo=None) != wall:
            result.append({**item, 'booking_id': None, 'status': 'conflict', 'detail': 'This local time does not exist after the clock change.'})
            continue
        try:
            # Each create has a savepoint, so a conflict rolls back its charge/audit only.
            booking = create_booking(locked, actor=actor, starts_at=start, ends_at=end, **values)
        except (BookingConflict, BookingInvalidTransition, ValidationError) as exc:
            result.append({**item, 'booking_id': None, 'status': 'conflict', 'detail': str(getattr(exc, 'detail', exc))})
        else:
            result.append({**item, 'booking_id': booking.pk, 'status': booking.status, 'detail': ''})
    from apps.audit import services as audit
    audit.record(actor, 'booking.recurrence_created', makerspace=locked.makerspace, target=locked,
                 meta={'requested_count': count, 'created_count': sum(row['booking_id'] is not None for row in result)})
    return result
