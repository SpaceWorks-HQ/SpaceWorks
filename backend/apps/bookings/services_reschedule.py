"""Move an owned reservation while holding the same space lock as creation."""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.bookings.exceptions import BookingConflict, BookingInvalidTransition
from apps.bookings.models import Booking
from apps.bookings.services_schedule import confirmed_overlap, member_can_cancel


@transaction.atomic
def reschedule_booking(booking, *, actor, starts_at, ends_at):
    from apps.bookings.services_bookings import _audit, _locked_booking, _refresh, _validate, _require_certification
    from apps.bookings.services_rules import enforce_booking_rules
    from apps.makerspaces.guards import require_module_locked
    from apps.presence.guard import require_active_account

    space, locked = _locked_booking(booking)
    require_module_locked(space.makerspace, 'bookings')
    require_active_account(actor, space.makerspace)
    from apps.accounts import rbac
    if rbac.personal_notification_membership_refused(actor, space.makerspace_id):
        raise BookingInvalidTransition('Revoked members may not reschedule bookings.')
    locked.space = space
    if locked.member_id != actor.pk:
        raise BookingInvalidTransition('Only the booking owner may reschedule it.')
    if not member_can_cancel(locked, now=timezone.now()):
        raise BookingInvalidTransition('The booking reschedule cutoff has passed.')
    if not space.is_active:
        raise BookingInvalidTransition('Inactive spaces cannot accept bookings.')
    _require_certification(space, actor, actor, '')
    old_start, old_end = locked.starts_at, locked.ends_at
    locked.starts_at, locked.ends_at = starts_at, ends_at
    _validate(locked)
    now = timezone.now()
    enforce_booking_rules(space, starts_at, ends_at, now)
    if starts_at <= now or starts_at <= now + timedelta(hours=space.cancellation_cutoff_hours):
        raise ValidationError({'starts_at': 'New time must be after the reschedule cutoff.'})
    if confirmed_overlap(space, starts_at, ends_at, exclude=locked.pk):
        raise BookingConflict('This space is already booked for that time.')
    locked.calendar_sequence += 1
    locked.calendar_updated_at = now
    locked.save(update_fields=['starts_at', 'ends_at', 'calendar_sequence', 'calendar_updated_at'])
    _audit(space, actor, 'booking.rescheduled', locked, {
        'old_starts_at': old_start.isoformat(), 'old_ends_at': old_end.isoformat(),
        'starts_at': starts_at.isoformat(), 'ends_at': ends_at.isoformat(),
    })
    from apps.bookings.notifications import notify_booking_status
    notify_booking_status(locked, 'confirmed' if locked.status == Booking.Status.CONFIRMED else 'created')
    # Keep the subject id, pending approval and flat per-booking charge unchanged.
    return _refresh(locked)
