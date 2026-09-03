import hmac
import json

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from apps.audit import services as audit
from apps.events import services as event_services
from apps.events.exceptions import (
    EventInvalidTransition,
    FeedbackConflict,
    FeedbackIneligible,
)
from apps.events.feedback_validation import (
    validate_feedback_answers,
    validate_feedback_schema,
)
from apps.events.models import (
    Event,
    EventFeedbackResponse,
    EventFeedbackSurvey,
    EventRegistration,
)
from apps.events.services_certificates import create_pending
from apps.makerspaces.guards import require_module_locked
from apps.presence.guard import require_active_member


def _locked_event(event):
    locked = event_services._locked_event(event.pk)
    require_module_locked(locked.makerspace, "events")
    return locked


def _locked_survey(event, *, required=True):
    survey = EventFeedbackSurvey.objects.select_for_update().filter(event=event).first()
    if survey is None and required:
        raise EventInvalidTransition("This event has no feedback survey.")
    return survey


def _canonical_questions(questions):
    try:
        return validate_feedback_schema(questions)
    except DjangoValidationError as exc:
        raise serializers.ValidationError({"questions": exc.messages}) from exc


def _submission_ready(event, survey):
    return (
        survey.is_open
        and timezone.now() >= event.ends_at
        and event.status in (Event.Status.PUBLISHED, Event.Status.COMPLETED)
    )


def _snapshot(schema, answers):
    value = validate_feedback_answers(schema, answers)
    return value, json.dumps(value, sort_keys=True, separators=(",", ":"))


def _merge_answered_ids(survey, snapshot):
    answered = {item["id"] for item in snapshot["answers"]}
    merged = sorted(set(survey.answered_question_ids) | answered)
    if merged != survey.answered_question_ids:
        survey.answered_question_ids = merged
        survey.save(update_fields=["answered_question_ids", "updated_at"])


@transaction.atomic
def configure_survey(
    event,
    *,
    actor,
    title,
    thank_you_text="",
    questions=None,
    certificate_enabled=False,
):
    locked_event = _locked_event(event)
    survey = _locked_survey(locked_event, required=False)
    created = survey is None
    if created:
        survey = EventFeedbackSurvey(event=locked_event)
    survey.title = title
    survey.thank_you_text = thank_you_text
    survey.questions = _canonical_questions(questions)
    survey.certificate_enabled = certificate_enabled
    survey.save()
    audit.record(
        actor,
        "event.feedback_survey_configured",
        makerspace=locked_event.makerspace,
        target=survey,
        meta={"created": created, "question_count": len(survey.questions)},
    )
    return survey


@transaction.atomic
def open_survey(event, *, actor):
    locked_event = _locked_event(event)
    survey = _locked_survey(locked_event)
    if survey.is_open:
        raise EventInvalidTransition("The survey is already open.")
    if timezone.now() < locked_event.ends_at:
        raise EventInvalidTransition("Feedback cannot open before the event ends.")
    if locked_event.status not in (Event.Status.PUBLISHED, Event.Status.COMPLETED):
        raise EventInvalidTransition("This event cannot accept feedback.")
    if not survey.questions:
        raise EventInvalidTransition("The survey needs at least one question.")
    survey.is_open = True
    survey.opened_at = timezone.now()
    survey.closed_at = None
    survey.save(update_fields=["is_open", "opened_at", "closed_at", "updated_at"])
    audit.record(
        actor,
        "event.feedback_survey_opened",
        makerspace=locked_event.makerspace,
        target=survey,
        meta={},
    )
    return survey


@transaction.atomic
def close_survey(event, *, actor):
    locked_event = _locked_event(event)
    survey = _locked_survey(locked_event)
    if not survey.is_open:
        raise EventInvalidTransition("The survey is already closed.")
    survey.is_open = False
    survey.closed_at = timezone.now()
    survey.save(update_fields=["is_open", "closed_at", "updated_at"])
    audit.record(
        actor,
        "event.feedback_survey_closed",
        makerspace=locked_event.makerspace,
        target=survey,
        meta={},
    )
    return survey


@transaction.atomic
def submit_anonymous_feedback(event, answers):
    locked_event = _locked_event(event)
    survey = _locked_survey(locked_event)
    if survey.certificate_enabled or not _submission_ready(locked_event, survey):
        raise FeedbackIneligible()
    snapshot, encoded = _snapshot(survey.questions, answers)
    response = EventFeedbackResponse.objects.create(
        survey=survey,
        registration=None,
        answers_snapshot=encoded,
        certificate_requested=False,
    )
    _merge_answered_ids(survey, snapshot)
    # Deliberately no response target/id and no request principal. AuditLog is
    # append-only, so even an encrypted or hashed identity would break anonymity.
    audit.record(
        None,
        "event.feedback_submitted",
        makerspace=locked_event.makerspace,
        target=survey,
        meta={"mode": "anonymous"},
    )
    return response, None


@transaction.atomic
def submit_identified_feedback(
    event,
    *,
    actor,
    email,
    answers,
    registration=None,
):
    locked_event = _locked_event(event)
    survey = _locked_survey(locked_event)
    if not survey.certificate_enabled or not _submission_ready(locked_event, survey):
        raise FeedbackIneligible()
    registration_id = registration.pk if registration is not None else None
    # No `select_related("registered_via_makerspace")` here: that FK is NULLABLE, so it
    # joins LEFT OUTER, and Postgres refuses `FOR UPDATE` against the nullable side of an
    # outer join outright. The attribute below loads lazily instead, which costs one extra
    # query only when the registration actually travelled via another makerspace.
    eligible = EventRegistration.objects.select_for_update().filter(
        event=locked_event,
        member=actor,
        status=EventRegistration.Status.ATTENDED,
    )
    if registration_id is not None:
        eligible = eligible.filter(pk=registration_id)
    locked_registration = eligible.first()
    normalized = (email or "").strip().lower()
    if locked_registration is None:
        raise FeedbackIneligible()
    via_space = (
        locked_registration.registered_via_makerspace
        or locked_event.makerspace
    )
    require_active_member(actor, via_space)
    if not hmac.compare_digest(normalized, locked_registration.email):
        raise FeedbackIneligible()
    snapshot, encoded = _snapshot(survey.questions, answers)
    existing = EventFeedbackResponse.objects.select_for_update().filter(
        survey=survey,
        registration=locked_registration,
    ).first()
    if existing is not None:
        if not hmac.compare_digest(existing.answers_snapshot, encoded):
            raise FeedbackConflict()
        return existing, existing.certificates.order_by("-revision").first()
    response = EventFeedbackResponse.objects.create(
        survey=survey,
        registration=locked_registration,
        answers_snapshot=encoded,
        certificate_requested=True,
    )
    certificate = create_pending(response)
    _merge_answered_ids(survey, snapshot)
    audit.record(
        actor,
        "event.feedback_submitted",
        makerspace=locked_event.makerspace,
        target=response,
        meta={"mode": "certificate"},
    )
    audit.record(
        actor,
        "event.certificate_requested",
        makerspace=locked_event.makerspace,
        target=certificate,
        meta={"revision": certificate.revision},
    )
    return response, certificate
