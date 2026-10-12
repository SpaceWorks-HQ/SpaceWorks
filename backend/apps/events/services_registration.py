"""Registration mutation boundary, kept separate from event lifecycle services."""

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.encryption.write_fence import assert_mapped_write_allowed
from apps.events.capacity import (
    effective_registration_cutoff,
    fresh_registration_status,
    registration_is_open,
)
from apps.events.exceptions import (
    DuplicateRegistration,
    EventInvalidTransition,
    RegistrationClosed,
    RegistrationRejected,
)
from apps.events.models import EventRegistration
from apps.forms_schema.validation import validate_answers
from apps.makerspaces.guards import require_module_locked
from apps.events.services_calendar import calendar_registration_changed


@transaction.atomic
def register(
    event, *, member=None, name=None, email=None, phone=None,
    custom_answers=None, actor=None, staff_registration=False,
    via_makerspace=None, collaborative=False,
    invite_code=None, ticket_type_id=None, promo_code=None,
):
    """Register someone for an event.

    `staff_registration` and `collaborative` each relax exactly one condition: the
    `is_public` requirement. That flag answers "does this event appear in the public
    catalogue", while staff at the door and members of accepted collaborators are not
    the public. Every other rule (published, not ended, capacity, duplicates, the
    custom form, the write fence, and payment) is identical, because this is the same
    service and the state machine has one home.

    `collaborative=True` is a trusted internal capability restricted to the enforcing
    member view. That view proves an accepted EventCollaborator exists; this service
    deliberately does not re-derive the actor's makerspace membership.
    """
    from apps.events.services import _audit, _locked_event, _refresh, _validate

    assert_mapped_write_allowed(event.makerspace_id)
    if member is not None:
        name = member.display_name or member.get_full_name() or member.username
        # Account first, caller's value as the fallback -- the same rule as `phone` just
        # below, and for the same reason: a walk-in record may carry neither, and the
        # registration model requires both.
        email = member.email or email
        # The account wins, but a caller-supplied number is kept as the fallback: a
        # registration needs a contact number (`EventRegistration.phone` is non-blank),
        # and an account without one would otherwise be a dead end nobody at the desk
        # could resolve. The public path passes none, so it is unchanged.
        phone = member.phone or phone
    name = (name or "").strip()
    normalized_email = (email or "").strip().lower()
    phone = (phone or "").strip()
    generation = event_hash = None
    if settings.PII_ENCRYPTION_ENABLED:
        from apps.encryption.blind_index import active_generation, event_email_hash

        generation = active_generation()
        event_hash = event_email_hash(
            normalized_email, generation=generation.generation,
            makerspace_id=event.makerspace_id, event_id=event.pk,
        )
    locked = _locked_event(event.pk)
    # register() previously lacked this locked module check. Keep event-then-makerspace
    # ordering: publish() takes the event lock first, so taking the makerspace first
    # here would create a deadlock pair with it.
    locked.makerspace = require_module_locked(locked.makerspace, "events")
    now = timezone.now()
    if not locked.is_public and not staff_registration and not collaborative:
        raise EventInvalidTransition("This event is not open for registration.")
    if not registration_is_open(locked, now):
        cutoff = effective_registration_cutoff(locked)
        if (
            locked.status == locked.Status.PUBLISHED
            and now < locked.ends_at
            and cutoff is not None
            and now >= cutoff
        ):
            raise RegistrationClosed("Registration for this event is closed.")
        raise EventInvalidTransition("This event is not open for registration.")
    from .registration_access import require_registration_access
    from .ticketing import select_ticket
    require_registration_access(locked, member, staff=staff_registration, collaborative=collaborative, via=via_makerspace)
    custom_answers = validate_answers(locked.custom_form, custom_answers)
    existing = _existing_registration(
        locked, member, normalized_email, generation, event_hash
    )
    # A contact fallback is not proof of ownership. In particular an account with
    # no email must not claim another attendee's cancelled row by naming its email.
    if member is not None and existing and existing.member_id != member.pk:
        raise ValidationError({"email": "This contact cannot be used for this registration."})
    if existing and existing.status != EventRegistration.Status.CANCELLED:
        if existing.status == EventRegistration.Status.REJECTED:
            raise RegistrationRejected("This registration application was rejected.")
        raise DuplicateRegistration("A registration already exists for this email.", fresh_status=existing.status)
    ticket = select_ticket(locked, ticket_type_id, member)
    status = fresh_registration_status(locked, ticket)
    if existing and existing.status == EventRegistration.Status.CANCELLED:
        # The unique payment subject preserves historical money. Reusing a cancelled
        # paid row would find its terminal charge and silently provide a free place.
        from apps.payments.models import Payment

        if locked.payment_amount > 0 or (ticket and ticket.amount > 0) or (existing.quoted_amount and existing.quoted_amount > 0) or Payment.objects.filter(
            makerspace=locked.makerspace,
            subject_type=Payment.SubjectType.EVENT_REGISTRATION,
            subject_id=existing.pk,
        ).exists():
            raise EventInvalidTransition(
                "A cancelled paid registration cannot be registered again. Contact staff."
            )
        quote = _quote(locked, member, ticket, invite_code, promo_code)
        for field, value in quote.items():
            setattr(existing, field, value)
        existing.member = member or existing.member
        existing.registered_via_makerspace = via_makerspace or locked.makerspace
        # Written together, but they diverge later: a purge clears the provenance above and
        # leaves this one, so a charge raised after that purge still reaches the member.
        existing.payment_via_makerspace = via_makerspace or locked.makerspace
        existing.name, existing.email, existing.phone = name, normalized_email, phone
        existing.custom_answers, existing.status, existing.created_at = custom_answers, status, timezone.now()
        _validate(existing)
        existing.save(update_fields=[
            "member", "registered_via_makerspace", "payment_via_makerspace", "name",
            "email", "phone", "custom_answers", "status", "created_at", *quote,
        ])
        calendar_registration_changed(existing)
        return _record_registration(locked, actor, existing, status)
    quote = _quote(locked, member, ticket, invite_code, promo_code)
    registration = EventRegistration(
        **quote,
        event=locked, member=member, name=name, email=normalized_email,
        phone=phone, custom_answers=custom_answers, status=status,
        registered_via_makerspace=via_makerspace or locked.makerspace,
        payment_via_makerspace=via_makerspace or locked.makerspace,
    )
    _validate(registration)
    registration.save()
    return _record_registration(locked, actor, registration, status)


def _quote(event, member, ticket, invite_code, promo_code):
    from decimal import Decimal
    from .invites import redeem_invite
    from .promos import redeem_promo

    invite = redeem_invite(event, invite_code, member) if event.registration_audience == "invite" else None
    amount = Decimal(ticket.amount if ticket else event.payment_amount)
    promo, discount = redeem_promo(event, promo_code, amount) if promo_code else (None, Decimal("0"))
    return {"registration_audience": event.registration_audience, "ticket_type": ticket, "invite": invite, "promo_code": promo,
            "quoted_amount": amount - discount, "discount_amount": discount}


def _existing_registration(event, member, normalized_email, generation, event_hash):
    if member is not None:
        existing = EventRegistration.objects.select_for_update().filter(
            event=event, member=member
        ).first()
        if existing:
            return existing
    if not settings.PII_ENCRYPTION_ENABLED:
        return EventRegistration.objects.select_for_update().filter(event=event, email=normalized_email).first()
    candidates = EventRegistration.objects.select_for_update().filter(
        event=event, email_hash_generation=generation, email_exact_hash=event_hash
    )
    existing = next((row for row in candidates if row.email.strip().lower() == normalized_email), None)
    if settings.PII_ENCRYPTION_DUAL_READ:
        from apps.encryption.search import legacy_plaintext_candidates

        legacy = legacy_plaintext_candidates(
            EventRegistration.objects.filter(event=event), field_name="email", term=normalized_email, exact=True
        )
        if legacy:
            return EventRegistration.objects.select_for_update().filter(pk__in=legacy).first() or existing
    return existing


def _record_registration(event, actor, registration, status):
    from apps.events import services

    services._audit(
        event,
        actor,
        "event.registration_created",
        registration,
        {"registration_id": registration.pk, "status": status},
    )
    if registration.invite_id:
        services._audit(event, actor, "event.invite_redeemed", registration, {"invite_id": registration.invite_id})
    if registration.promo_code_id:
        services._audit(event, actor, "event.promo_redeemed", registration, {"promo_id": registration.promo_code_id, "discount_amount": str(registration.discount_amount)})
    lifecycle_event = "registration_created"
    if status == EventRegistration.Status.PENDING_APPROVAL:
        services._audit(
            event,
            actor,
            "event.registration_approval_requested",
            registration,
            {"registration_id": registration.pk},
        )
        lifecycle_event = "registration_pending_approval"
    elif status == EventRegistration.Status.WAITLISTED:
        lifecycle_event = "registration_waitlisted"
    services.notify_event_lifecycle(event, lifecycle_event, registration.pk)
    if status == EventRegistration.Status.REGISTERED:
        from apps.events.service_payments import create_for_registered_registration

        create_for_registered_registration(registration, actor)
    return services._refresh(registration)
