"""Registration mutation boundary, kept separate from event lifecycle services."""

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.encryption.write_fence import assert_mapped_write_allowed
from apps.events.capacity import fresh_registration_status
from apps.events.exceptions import DuplicateRegistration, EventInvalidTransition
from apps.events.models import EventCollaborator, EventRegistration
from apps.forms_schema.validation import validate_answers
from apps.makerspaces.guards import require_module_locked
from apps.makerspaces.platform import module_enabled


def collaborator_makerspace_ids(event):
    """Return eligible accepted collaborator makerspace IDs for an event."""
    collaborators = (
        EventCollaborator.objects.filter(
            event=event,
            status=EventCollaborator.Status.ACCEPTED,
            makerspace__archived_at__isnull=True,
        )
        # Model validation prevents this relation; excluding it here is the
        # service-level defense because clean() is not invoked by every write path.
        .exclude(makerspace_id=event.makerspace_id)
        .select_related("makerspace")
    )
    return {
        collaborator.makerspace_id
        for collaborator in collaborators
        if module_enabled(collaborator.makerspace, "events")
    }


@transaction.atomic
def register(
    event, *, member=None, name=None, email=None, phone=None,
    custom_answers=None, actor=None, staff_registration=False,
    via_makerspace=None, collaborative=False,
):
    """Register someone for an event.

    `staff_registration` and `collaborative` each relax exactly one condition: the
    `is_public` requirement. That flag answers "does this event appear in the public
    catalogue", while staff at the door and members of accepted collaborators are not
    the public. Every other rule (published, not ended, capacity, duplicates, the
    custom form, the write fence, and payment) is identical, because this is the same
    service and the state machine has one home.
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
    require_module_locked(locked.makerspace, "events")
    if (
        (not locked.is_public and not staff_registration and not collaborative)
        or locked.status != locked.Status.PUBLISHED
        or locked.ends_at < timezone.now()
    ):
        raise EventInvalidTransition("This event is not open for registration.")
    custom_answers = validate_answers(locked.custom_form, custom_answers)
    status = fresh_registration_status(locked)
    existing = _existing_registration(
        locked, member, normalized_email, generation, event_hash
    )
    if existing and existing.status == EventRegistration.Status.CANCELLED:
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
            "email", "phone", "custom_answers", "status", "created_at",
        ])
        return _record_registration(locked, actor, existing, status)
    if existing:
        raise DuplicateRegistration("A registration already exists for this email.", fresh_status=status)
    registration = EventRegistration(
        event=locked, member=member, name=name, email=normalized_email,
        phone=phone, custom_answers=custom_answers, status=status,
        registered_via_makerspace=via_makerspace or locked.makerspace,
        payment_via_makerspace=via_makerspace or locked.makerspace,
    )
    _validate(registration)
    registration.save()
    return _record_registration(locked, actor, registration, status)


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

    services._audit(event, actor, "event.registration_created", registration, {"registration_id": registration.pk, "status": status})
    services.notify_event_lifecycle(event, "registration_created", registration.pk)
    if status == EventRegistration.Status.REGISTERED:
        from apps.events.service_payments import create_for_registered_registration

        create_for_registered_registration(registration, actor)
    return services._refresh(registration)
