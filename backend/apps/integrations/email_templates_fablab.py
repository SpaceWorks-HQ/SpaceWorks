"""Runtime template contexts for the four FabLab streams.

The mirror of `email_templates.hardware_context`/`printing_context`: turn a domain object
into the exact variable names the registry declares. Values go through `bag()` rather than
being passed as model instances for the reason that helper exists — a template rendered
with a live model can walk relations (`{{ booking.space.makerspace.telegram_bot_token }}`)
and an operator-authored body must not be able to reach a credential.
"""

from django.utils import formats, timezone

from apps.integrations.email_templates_registry import bag


def _makerspace_bag(makerspace):
    return bag(
        name=makerspace.name,
        location=makerspace.location,
        map_url=makerspace.map_url,
    )


def _interval(starts_at, ends_at):
    start = timezone.localtime(starts_at)
    end = timezone.localtime(ends_at)
    return (
        f"{formats.date_format(start, 'DATETIME_FORMAT')} to "
        f"{formats.date_format(end, 'DATETIME_FORMAT')}"
    )


def _base(makerspace, event_name, **extra):
    return {
        "makerspace": _makerspace_bag(makerspace),
        "event_name": event_name,
        "now": timezone.now(),
        **extra,
    }


def events_context(event, event_name, registration=None, *, next_steps=""):
    return _base(
        event.makerspace,
        event_name,
        event=bag(
            id=event.pk,
            title=event.title,
            status=event.status,
            when=_interval(event.starts_at, event.ends_at),
            location=event.location,
        ),
        registration=(
            bag(id=registration.pk, name=registration.name, status=registration.status)
            if registration is not None
            else None
        ),
        next_steps=next_steps,
    )


def bookings_context(booking, event_name, *, next_steps=""):
    return _base(
        booking.space.makerspace,
        event_name,
        booking=bag(
            id=booking.pk,
            status=booking.status,
            name=booking.name,
            when=_interval(booking.starts_at, booking.ends_at),
            space=bag(name=booking.space.name),
        ),
        next_steps=next_steps,
    )


def maintenance_context(machine, event_name, schedule=None, log=None, *, next_steps=""):
    return _base(
        machine.makerspace,
        event_name,
        machine=bag(id=machine.pk, name=machine.name),
        schedule=(
            bag(
                id=schedule.pk,
                description=schedule.description,
                next_due=schedule.next_due,
                is_active=schedule.is_active,
            )
            if schedule is not None
            else None
        ),
        log=(
            bag(
                id=log.pk,
                summary=log.summary,
                performed_at=log.performed_at,
                parts_note=log.parts_note,
            )
            if log is not None
            else None
        ),
        next_steps=next_steps,
    )


def membership_context(makerspace, event_name, *, user=None, request=None):
    return _base(
        makerspace,
        event_name,
        member=(
            bag(
                name=(getattr(user, "display_name", "") or user.username),
                username=user.username,
                email=user.email,
            )
            if user is not None
            else None
        ),
        request=(
            bag(
                id=request.pk,
                applicant=(
                    request.user.username if request.user_id else "An applicant"
                ),
            )
            if request is not None
            else None
        ),
    )
