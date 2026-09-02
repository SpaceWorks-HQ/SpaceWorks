from datetime import timedelta

import pytest
from django.db import connection
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.encryption.crypto import is_envelope
from apps.events import services
from apps.events.exceptions import EventInvalidTransition, FeedbackConflict, FeedbackIneligible
from apps.events.feedback_validation import validate_feedback_schema
from apps.events.models import (
    Event,
    EventAttendanceCertificate,
    EventCheckInEvent,
    EventFeedbackResponse,
    EventRegistration,
)
from apps.events.services_certificates import create_pending
from apps.events.services_certificates import download_url
from apps.events.services_feedback import (
    configure_survey,
    open_survey,
    submit_anonymous_feedback,
    submit_identified_feedback,
)
from apps.makerspaces.models import Makerspace
from tests.encryption.conftest import enabled_encryption
from tests.member_submission import active_member_client


pytestmark = pytest.mark.django_db

QUESTION = {
    "id": "rating",
    "label": "Rating",
    "type": "number",
    "options": [],
    "required": True,
}


def ended_event(slug="postevent", **values):
    space = Makerspace.objects.create(name=slug, slug=slug)
    defaults = {
        "makerspace": space,
        "title": "Safety workshop",
        "starts_at": timezone.now() - timedelta(hours=2),
        "ends_at": timezone.now() - timedelta(hours=1),
        "status": Event.Status.PUBLISHED,
        "is_public": True,
    }
    defaults.update(values)
    return Event.objects.create(**defaults)


def opened_survey(event, *, certificate=False):
    survey = configure_survey(
        event,
        actor=None,
        title="How was it?",
        thank_you_text="Thank you",
        questions=[QUESTION],
        certificate_enabled=certificate,
    )
    return open_survey(event, actor=None)


def registration(event, member, status):
    return EventRegistration.objects.create(
        event=event,
        member=member,
        name=member.display_name,
        email=member.email,
        phone=member.phone,
        status=status,
    )


def test_feedback_schema_uses_all_seven_canonical_question_types():
    types = (
        "short_text", "paragraph", "dropdown", "multi_choice",
        "single_choice", "yes_no", "number",
    )
    schema = [
        {
            "id": f"q{index}",
            "label": value,
            "type": value,
            "options": ["A"] if value in {"dropdown", "multi_choice", "single_choice"} else [],
            "required": False,
        }
        for index, value in enumerate(types)
    ]
    assert [item["type"] for item in validate_feedback_schema(schema)] == list(types)


def test_anonymous_feedback_is_repeatable_encrypted_and_unidentifiable_in_audit():
    event = ended_event()
    opened_survey(event)
    actor, _client = active_member_client(event.makerspace, "anonymous-browser")

    with enabled_encryption():
        first, certificate = submit_anonymous_feedback(event, {"rating": 5})
        second, _ = submit_anonymous_feedback(event, {"rating": 4})
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT answers_snapshot FROM events_eventfeedbackresponse WHERE id = %s",
                [first.pk],
            )
            raw = cursor.fetchone()[0]

    assert certificate is None
    assert first.pk != second.pk
    assert first.registration_id is None
    assert is_envelope(raw)
    audits = AuditLog.objects.filter(action="event.feedback_submitted")
    assert audits.count() == 2
    assert all(row.actor_id is None and row.meta == {"mode": "anonymous"} for row in audits)
    assert actor.pk not in [row.actor_id for row in audits]


@pytest.mark.parametrize(
    "registration_status",
    [
        EventRegistration.Status.PENDING_APPROVAL,
        EventRegistration.Status.REGISTERED,
        EventRegistration.Status.WAITLISTED,
        EventRegistration.Status.REJECTED,
        EventRegistration.Status.CANCELLED,
    ],
)
def test_certificate_feedback_rejects_every_non_attended_status(registration_status):
    event = ended_event(f"no-show-{registration_status}")
    opened_survey(event, certificate=True)
    member, _client = active_member_client(event.makerspace, f"member-{registration_status}")
    row = registration(event, member, registration_status)

    with pytest.raises(FeedbackIneligible):
        submit_identified_feedback(
            event,
            actor=member,
            registration=row,
            email=member.email,
            answers={"rating": 5},
        )

    assert not EventAttendanceCertificate.objects.exists()


def test_only_attended_registration_gets_certificate_and_exact_retry_is_idempotent():
    event = ended_event("attended-certificate")
    opened_survey(event, certificate=True)
    member, _client = active_member_client(event.makerspace, "attended-member")
    row = registration(event, member, EventRegistration.Status.ATTENDED)

    response, certificate = submit_identified_feedback(
        event, actor=member, registration=row, email=member.email,
        answers={"rating": 5},
    )
    retried_response, retried_certificate = submit_identified_feedback(
        event, actor=member, registration=row, email=member.email,
        answers={"rating": 5},
    )

    assert response.pk == retried_response.pk
    assert certificate.pk == retried_certificate.pk
    assert certificate.status == EventAttendanceCertificate.Status.PENDING
    with pytest.raises(FeedbackConflict):
        submit_identified_feedback(
            event, actor=member, registration=row, email=member.email,
            answers={"rating": 3},
        )


def test_attended_visitor_uses_durable_registration_makerspace_membership():
    event = ended_event("visitor-certificate")
    opened_survey(event, certificate=True)
    source = Makerspace.objects.create(name="Visitor source", slug="visitor-source")
    member, _client = active_member_client(source, "visiting-attendee")
    row = registration(event, member, EventRegistration.Status.ATTENDED)
    row.registered_via_makerspace = source
    row.save(update_fields=["registered_via_makerspace"])

    response, certificate = submit_identified_feedback(
        event,
        actor=member,
        registration=row,
        email=member.email,
        answers={"rating": 5},
    )

    assert response.registration_id == row.pk
    assert certificate.registration_id == row.pk


def test_mark_attended_writes_history_and_correction_revokes_certificate():
    event = ended_event("attendance-history")
    opened_survey(event, certificate=True)
    member, _client = active_member_client(event.makerspace, "history-member")
    actor = User.objects.create_user(username="attendance-staff")
    row = registration(event, member, EventRegistration.Status.REGISTERED)

    attended = services.mark_attended(row, actor=actor)
    response = EventFeedbackResponse.objects.create(
        survey=event.feedback_survey,
        registration=attended,
        answers_snapshot='{"version":1,"answers":[]}',
        certificate_requested=True,
    )
    certificate = create_pending(response)
    certificate.status = EventAttendanceCertificate.Status.RENDERING
    certificate.save(update_fields=["status"])
    certificate.status = EventAttendanceCertificate.Status.ACTIVE
    certificate.size_bytes = 10
    certificate.sha256 = "a" * 64
    certificate.rendered_at = timezone.now()
    certificate.save(update_fields=["status", "size_bytes", "sha256", "rendered_at"])

    corrected, revoked = services.correct_attendance(attended, actor=actor)

    history = EventCheckInEvent.objects.get(registration=row)
    assert history.source == EventCheckInEvent.Source.ONLINE
    assert history.attended_at <= timezone.now()
    assert corrected.status == EventRegistration.Status.REGISTERED
    assert [item.pk for item in revoked] == [certificate.pk]
    certificate.refresh_from_db()
    assert certificate.status == EventAttendanceCertificate.Status.REVOKED
    assert certificate.revocation_reason == "attendance_corrected"


def test_pending_certificate_cannot_render_after_attendance_is_corrected():
    event = ended_event("pending-attendance-correction")
    opened_survey(event, certificate=True)
    member, _client = active_member_client(event.makerspace, "pending-history-member")
    actor = User.objects.create_user(username="pending-attendance-staff")
    row = registration(event, member, EventRegistration.Status.ATTENDED)
    response, certificate = submit_identified_feedback(
        event,
        actor=member,
        registration=row,
        email=member.email,
        answers={"rating": 5},
    )
    services.correct_attendance(row, actor=actor)

    with pytest.raises(EventInvalidTransition, match="Attendance is required"):
        download_url(certificate)

    assert response.registration_id == row.pk
