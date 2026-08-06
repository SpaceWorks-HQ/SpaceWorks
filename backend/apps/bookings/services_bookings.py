'''Audited mutation boundary for bookings and their lifecycle.'''

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from apps.audit import services as audit
from apps.bookings import notifications
from apps.bookings.exceptions import BookingConflict, BookingInvalidTransition
from apps.bookings.models import BookableSpace, Booking
from apps.forms_schema.validation import validate_answers
from apps.makerspaces import limits
from apps.makerspaces.guards import require_module_locked


def _locked_space(space_id):
    return (
        BookableSpace.objects.select_for_update()
        .select_related('makerspace')
        .get(pk=space_id)
    )


def _validate(booking):
    try:
        booking.full_clean(validate_unique=False, validate_constraints=False)
    except DjangoValidationError as exc:
        detail = exc.message_dict if hasattr(exc, 'message_dict') else exc.messages
        raise serializers.ValidationError(detail) from exc
    if booking.ends_at <= booking.starts_at:
        raise serializers.ValidationError(
            {'ends_at': 'End time must be after start time.'}
        )


def _audit(space, actor, action, target, meta=None):
    return audit.record(
        actor,
        action,
        makerspace=space.makerspace,
        target=target,
        meta=meta or {},
    )


def _refresh(instance):
    instance.refresh_from_db()
    return instance


@transaction.atomic
def create_booking(
    space, *, starts_at, ends_at, member=None, name=None, email=None, phone=None,
    custom_answers=None, note='', actor=None,
):
    from apps.bookings.services_rules import enforce_booking_rules
    from apps.encryption.write_fence import assert_mapped_write_allowed

    assert_mapped_write_allowed(space.makerspace_id)
    locked_space = _locked_space(space.pk)
    if not locked_space.is_active:
        raise BookingInvalidTransition('Inactive spaces cannot accept bookings.')

    now = timezone.now()
    status = (
        Booking.Status.CONFIRMED
        if locked_space.approval_mode == BookableSpace.ApprovalMode.INSTANT
        else Booking.Status.PENDING
    )
    if member is not None:
        name = member.display_name or member.get_full_name() or member.username
        email = member.email
        phone = member.phone
    booking = Booking(
        space=locked_space,
        member=member,
        name=(name or '').strip(),
        email=(email or '').strip().lower(),
        phone=(phone or '').strip(),
        starts_at=starts_at,
        ends_at=ends_at,
        note=note,
        status=status,
    )
    _validate(booking)
    enforce_booking_rules(locked_space, starts_at, ends_at, now)
    if ends_at <= now:
        raise serializers.ValidationError(
            {'ends_at': 'End time must be in the future.'}
        )
    booking.custom_answers = validate_answers(
        locked_space.custom_form, custom_answers
    )
    require_module_locked(locked_space.makerspace, 'bookings')
    limits.check_quota(locked_space.makerspace, 'bookings', adding=1)
    if status == Booking.Status.CONFIRMED and _confirmed_overlap(
        locked_space, starts_at, ends_at
    ):
        raise BookingConflict('This space is already booked for that time.')

    booking.save()
    _audit(
        locked_space,
        actor,
        'booking.created',
        booking,
        {'booking_id': booking.pk, 'status': status},
    )
    notifications.notify_booking_status(booking, 'created')
    if status == Booking.Status.CONFIRMED:
        from apps.bookings.service_payments import create_for_confirmed_booking

        create_for_confirmed_booking(booking, actor)
    return _refresh(booking)


def _confirmed_overlap(space, starts_at, ends_at, *, exclude=None):
    queryset = Booking.objects.filter(
        space=space,
        status=Booking.Status.CONFIRMED,
        starts_at__lt=ends_at,
        ends_at__gt=starts_at,
    )
    if exclude is not None:
        queryset = queryset.exclude(pk=exclude)
    return queryset.exists()


def _locked_booking(booking):
    space = _locked_space(booking.space_id)
    locked = Booking.objects.select_for_update().get(pk=booking.pk)
    if locked.space_id != space.pk:
        raise BookingInvalidTransition('Booking no longer belongs to this space.')
    return space, locked


@transaction.atomic
def approve_booking(booking, *, actor):
    space, locked = _locked_booking(booking)
    if locked.status != Booking.Status.PENDING:
        raise BookingInvalidTransition(
            f'Cannot transition booking from {locked.status} to confirmed.'
        )
    if not space.is_active:
        raise BookingInvalidTransition('Inactive spaces cannot approve bookings.')
    if locked.ends_at <= timezone.now():
        raise BookingInvalidTransition('Ended bookings cannot be approved.')
    if _confirmed_overlap(
        space, locked.starts_at, locked.ends_at, exclude=locked.pk
    ):
        raise BookingConflict('This space is already booked for that time.')
    locked.status = Booking.Status.CONFIRMED
    locked.save(update_fields=['status'])
    _audit(
        space,
        actor,
        'booking.approved',
        locked,
        {
            'booking_id': locked.pk,
            'old_status': Booking.Status.PENDING,
            'new_status': Booking.Status.CONFIRMED,
        },
    )
    notifications.notify_booking_status(locked, 'confirmed')
    from apps.bookings.service_payments import create_for_confirmed_booking

    create_for_confirmed_booking(locked, actor)
    return _refresh(locked)


@transaction.atomic
def reject_booking(booking, *, actor):
    space, locked = _locked_booking(booking)
    if locked.status != Booking.Status.PENDING:
        raise BookingInvalidTransition(
            f'Cannot transition booking from {locked.status} to rejected.'
        )
    locked.status = Booking.Status.REJECTED
    locked.save(update_fields=['status'])
    _audit(
        space,
        actor,
        'booking.rejected',
        locked,
        {
            'booking_id': locked.pk,
            'old_status': Booking.Status.PENDING,
            'new_status': Booking.Status.REJECTED,
        },
    )
    notifications.notify_booking_status(locked, 'rejected')
    return _refresh(locked)


def _transition(booking, actor, new_status, action, event, *, require_ended=False):
    space, locked = _locked_booking(booking)
    if locked.status != Booking.Status.CONFIRMED:
        raise BookingInvalidTransition(
            f'Cannot transition booking from {locked.status} to {new_status}.'
        )
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
def cancel_booking(booking, *, actor):
    cancelled = _transition(
        booking, actor, Booking.Status.CANCELLED, 'booking.cancelled', 'cancelled'
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
