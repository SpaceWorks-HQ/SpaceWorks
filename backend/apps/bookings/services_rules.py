from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from apps.audit import services as audit
from apps.bookings.exceptions import BookingInvalidTransition
from apps.bookings.models import BookableSpace
from apps.bookings.services_bookings import _locked_space


RULE_FIELDS = frozenset({
    'min_booking_duration_minutes',
    'max_booking_duration_minutes',
    'booking_lead_time_minutes',
    'max_booking_advance_days',
    'approval_mode',
    'buffer_before_minutes',
    'buffer_after_minutes',
    'cancellation_cutoff_hours',
})

# Upper bounds keep any accepted rule value evaluable without overflowing
# ``timedelta``/``datetime`` addition when enforce_booking_rules adds the lead
# window or the advance window to ``now`` (the DB/serializer alone would allow
# up to 2**31-1, which overflows). Generous operator maxima, not tight limits.
MAX_DURATION_MINUTES = 60 * 24 * 30  # 30 days
MAX_LEAD_MINUTES = 60 * 24 * 365  # 1 year
MAX_ADVANCE_DAYS = 3650  # 10 years


def enforce_booking_rules(space, starts_at, ends_at, now):
    from apps.bookings.services_schedule import enforce_opening_hours

    duration = ends_at - starts_at
    if duration < timedelta(minutes=space.min_booking_duration_minutes):
        raise serializers.ValidationError({
            'ends_at': (
                f'Booking must be at least '
                f'{space.min_booking_duration_minutes} minutes long.'
            )
        })
    if duration > timedelta(minutes=space.max_booking_duration_minutes):
        raise serializers.ValidationError({
            'ends_at': (
                f'Booking cannot exceed '
                f'{space.max_booking_duration_minutes} minutes.'
            )
        })
    if starts_at < now + timedelta(minutes=space.booking_lead_time_minutes):
        raise serializers.ValidationError({
            'starts_at': (
                f'Booking must start at least '
                f'{space.booking_lead_time_minutes} minutes from now.'
            )
        })
    if starts_at > now + timedelta(days=space.max_booking_advance_days):
        raise serializers.ValidationError({
            'starts_at': (
                f'Booking cannot start more than '
                f'{space.max_booking_advance_days} days from now.'
            )
        })
    # Calendar traversal must be bounded by the cheap duration/advance checks.
    enforce_opening_hours(space, starts_at, ends_at)


@transaction.atomic
def update_booking_rules(space, *, actor, **changes):
    unknown = set(changes) - RULE_FIELDS
    if unknown:
        raise serializers.ValidationError({
            field: 'This field cannot be updated.'
            for field in sorted(unknown)
        })

    locked = _locked_space(space.pk)
    if not locked.is_active:
        raise BookingInvalidTransition('Inactive spaces cannot be updated.')

    for field, value in changes.items():
        setattr(locked, field, value)

    for field, maximum in (
        ('buffer_before_minutes', 1440), ('buffer_after_minutes', 1440),
        ('cancellation_cutoff_hours', 8760),
    ):
        value = getattr(locked, field)
        if type(value) is not int or not 0 <= value <= maximum:
            raise serializers.ValidationError({field: f'Must be between 0 and {maximum}.'})

    if locked.min_booking_duration_minutes < 1:
        raise serializers.ValidationError({
            'min_booking_duration_minutes': 'Must be at least 1 minute.'
        })
    if locked.max_booking_duration_minutes < 1:
        raise serializers.ValidationError({
            'max_booking_duration_minutes': 'Must be at least 1 minute.'
        })
    if (
        locked.max_booking_duration_minutes
        < locked.min_booking_duration_minutes
    ):
        raise serializers.ValidationError({
            'max_booking_duration_minutes': (
                'Maximum duration cannot be below the minimum.'
            )
        })
    if locked.min_booking_duration_minutes > MAX_DURATION_MINUTES:
        raise serializers.ValidationError({
            'min_booking_duration_minutes': (
                f'Cannot exceed {MAX_DURATION_MINUTES} minutes.'
            )
        })
    if locked.max_booking_duration_minutes > MAX_DURATION_MINUTES:
        raise serializers.ValidationError({
            'max_booking_duration_minutes': (
                f'Cannot exceed {MAX_DURATION_MINUTES} minutes.'
            )
        })
    if locked.booking_lead_time_minutes < 0:
        raise serializers.ValidationError({
            'booking_lead_time_minutes': 'Cannot be negative.'
        })
    if locked.booking_lead_time_minutes > MAX_LEAD_MINUTES:
        raise serializers.ValidationError({
            'booking_lead_time_minutes': (
                f'Cannot exceed {MAX_LEAD_MINUTES} minutes.'
            )
        })
    if locked.max_booking_advance_days < 1:
        raise serializers.ValidationError({
            'max_booking_advance_days': 'Must be at least 1 day.'
        })
    if locked.max_booking_advance_days > MAX_ADVANCE_DAYS:
        raise serializers.ValidationError({
            'max_booking_advance_days': (
                f'Cannot exceed {MAX_ADVANCE_DAYS} days.'
            )
        })
    if locked.approval_mode not in BookableSpace.ApprovalMode.values:
        raise serializers.ValidationError({
            'approval_mode': 'Invalid approval mode.'
        })

    if {'buffer_before_minutes', 'buffer_after_minutes'} & set(changes):
        from apps.bookings.services_schedule import validate_buffer_change

        validate_buffer_change(locked, now=timezone.now())

    if changes:
        locked.save(update_fields=[*sorted(changes), 'updated_at'])
    audit.record(
        actor,
        'booking.space_rules_updated',
        makerspace=locked.makerspace,
        target=locked,
        meta={'changed_fields': sorted(changes)},
    )
    locked.refresh_from_db()
    return locked
