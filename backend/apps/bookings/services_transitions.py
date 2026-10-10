"""Audited booking lifecycle transitions behind the stable service barrel."""

from django.db import transaction
from django.utils import timezone

from apps.bookings import notifications
from apps.bookings.exceptions import BookingInvalidTransition
from apps.bookings.models import Booking


def _transition(booking, actor, new_status, action, event, *, require_ended=False, member_cancel=False):
    from apps.bookings.services_bookings import _audit, _locked_booking, _refresh

    space, locked = _locked_booking(booking)
    cancelling = new_status == Booking.Status.CANCELLED
    allowed = (Booking.Status.PENDING, Booking.Status.CONFIRMED) if cancelling else (Booking.Status.CONFIRMED,)
    if locked.status not in allowed:
        raise BookingInvalidTransition(
            f'Cannot transition booking from {locked.status} to {new_status}.'
        )
    if member_cancel:
        from apps.bookings.services_schedule import member_can_cancel
        from apps.makerspaces.guards import require_module_locked

        locked.space = space
        require_module_locked(space.makerspace, 'bookings')
        if locked.member_id != getattr(actor, 'pk', None):
            raise BookingInvalidTransition('Only the booking member may cancel it.')
        if not member_can_cancel(locked, now=timezone.now()):
            raise BookingInvalidTransition('The booking cancellation cutoff has passed.')
    if require_ended and locked.ends_at > timezone.now():
        raise BookingInvalidTransition('Booking has not ended yet.')
    old_status = locked.status
    locked.status = new_status
    locked.save(update_fields=['status'])
    _audit(
        space,
        actor,
        action,
        locked,
        {
            'booking_id': locked.pk,
            'old_status': old_status,
            'new_status': new_status,
        },
    )
    notifications.notify_booking_status(locked, event)
    return _refresh(locked)


@transaction.atomic
def cancel_booking(booking, *, actor, member_cancel=False):
    cancelled = _transition(
        booking, actor, Booking.Status.CANCELLED, 'booking.cancelled', 'cancelled',
        member_cancel=member_cancel,
    )
    from apps.bookings.service_payments import cancel_for_booking

    cancel_for_booking(cancelled, actor)
    return cancelled


@transaction.atomic
def complete_booking(booking, *, actor):
    return _transition(
        booking,
        actor,
        Booking.Status.COMPLETED,
        'booking.completed',
        'completed',
        require_ended=True,
    )


@transaction.atomic
def mark_no_show(booking, *, actor):
    return _transition(
        booking,
        actor,
        Booking.Status.NO_SHOW,
        'booking.no_show_marked',
        'no_show',
        require_ended=True,
    )
