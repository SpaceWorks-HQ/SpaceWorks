"""Realistic phase 1-9 graph shared by backup and tenant-move tests."""

from datetime import date, time, timedelta
import hashlib
import json

from django.utils import timezone

from apps.audit import services as audit
from apps.evidence.models import (
    EvidenceObjectRetentionState,
    EvidencePhoto,
    EvidenceRetentionPolicy,
)
from apps.events.models import (
    EventAttendanceCertificate,
    EventCheckInEvent,
    EventCheckInStationCredential,
    EventFeedbackResponse,
    EventFeedbackSurvey,
    EventOrganizer,
    EventSeries,
    EventSeriesOrganizer,
    MemberCalendarFeed,
)
from apps.operations.models import ReportMetricRollup, ReportRollupCursor
from apps.organizations.models import (
    Organization,
    OrganizationInvitation,
    OrganizationMakerspace,
    OrganizationMembership,
)
from apps.payments.models import Payment


QUESTION = {
    "id": "rating",
    "label": "Rating",
    "type": "number",
    "options": [],
    "required": True,
}


def create_programme_graph(space, user, _request):
    """Extend ``portable_import_case`` with every phase 3-9 entity."""
    event = space.events.get()
    registration = event.registrations.get()
    now = timezone.now()
    series = EventSeries.objects.create(
        makerspace=space,
        title="Monthly safety lab",
        description="Materialised training series",
        recurrence_timezone="UTC",
        dtstart_local_date=date.today() + timedelta(days=1),
        dtstart_local_time=time(10, 30),
        recurrence_rule="FREQ=MONTHLY;COUNT=3",
        duration_minutes=90,
        capacity=12,
        payment_amount="25.00",
        registration_requires_approval=True,
        registration_cutoff_lead_minutes=60,
        is_public=True,
        created_by=user,
    )
    event.series = series
    event.series_occurrence_key = "20260903T103000"
    event.series_revision = 1
    event.series_override_fields = ["location"]
    event.badge_template = {"label": "Safety graduate"}
    event.save()
    registration.status = registration.Status.ATTENDED
    registration.custom_answers = {"experience": "beginner"}
    registration.calendar_sequence = 2
    registration.save()

    check_in = EventCheckInEvent.objects.create(
        makerspace=space,
        event=event,
        registration=registration,
        source=EventCheckInEvent.Source.OFFLINE_SYNC,
        actor=user,
        session_id="55b66883-4e1e-44c3-8cec-5ef91e65d725",
    )
    survey = EventFeedbackSurvey.objects.create(
        event=event,
        title="How was the lab?",
        thank_you_text="Thank you",
        questions=[QUESTION],
        is_open=True,
        certificate_enabled=True,
        answered_question_ids=["rating"],
        opened_at=now,
    )
    response = EventFeedbackResponse.objects.create(
        survey=survey,
        registration=registration,
        answers_snapshot=json.dumps({"rating": 5}, sort_keys=True),
        certificate_requested=True,
    )
    certificate = EventAttendanceCertificate.objects.create(
        response=response,
        registration=registration,
        revision=1,
        recipient_name="Archive Member",
        event_title=event.title,
        event_starts_at=event.starts_at,
        event_ends_at=event.ends_at,
        issuer_name=space.name,
        object_key=f"event-certificates/{space.pk}/certificate.pdf",
    )
    payment = Payment.objects.create(
        makerspace=space,
        subject_type=Payment.SubjectType.EVENT_REGISTRATION,
        subject_id=registration.pk,
        member=user,
        via_makerspace=space,
        subject_label=event.title,
        amount="25.00",
        currency="usd",
        status=Payment.Status.PAID_OFFLINE,
        created_by=user,
    )
    photo = EvidencePhoto.objects.create(
        makerspace=space,
        evidence_type=EvidencePhoto.EvidenceType.ISSUE,
        object_key=f"evidence/{space.pk}/expired.jpg",
        uploaded_by=user,
    )
    EvidenceRetentionPolicy.objects.create(makerspace=space, object_retention_days=30)
    expired = EvidenceObjectRetentionState.objects.create(
        evidence=photo,
        status=EvidenceObjectRetentionState.Status.EXPIRED,
        object_expired_at=now - timedelta(minutes=5),
        expired_size_bytes=321,
    )
    rollup = ReportMetricRollup.objects.create(
        makerspace=space,
        source_module="events",
        report_key="event_attendance",
        metric_key="attended",
        bucket_start=now.replace(hour=0, minute=0, second=0, microsecond=0),
        grain=ReportMetricRollup.Grain.DAY,
        dimension_key="status=attended",
        dimensions={"status": "attended"},
        value="1.000000",
        sample_count=1,
        source_cutoff=now,
        checksum="a" * 64,
    )
    ReportRollupCursor.objects.create(
        makerspace=space, source_module="events", rolled_through=now
    )

    organization = Organization.objects.create(
        name="Archive Guild", slug=f"archive-guild-{space.pk}",
        public_profile_enabled=True, created_by=user,
    )
    OrganizationMakerspace.objects.create(
        organization=organization, makerspace=space,
        relationship=OrganizationMakerspace.Relationship.OWNER, created_by=user,
    )
    OrganizationMembership.objects.create(
        organization=organization, user=user,
        granted_actions=["events.manage"], governance_actions=["organizations.manage"],
        created_by=user,
    )
    OrganizationInvitation.objects.create(
        organization=organization,
        token_digest=hashlib.sha256(
            f"one-time-invitation:{space.pk}".encode()
        ).hexdigest(),
        granted_actions=["events.manage"],
        expires_at=now + timedelta(days=1), created_by=user,
    )
    series_organizer = EventSeriesOrganizer.objects.create(
        series=series, organization=organization, created_by=user
    )
    EventOrganizer.objects.create(
        event=event, organization=organization, created_by=user,
        source_series_organizer=series_organizer,
    )
    membership = space.memberships.get(user=user)
    MemberCalendarFeed.objects.create(
        membership=membership, token_digest=hashlib.sha256(b"calendar-token").digest(),
        token_hint="deadbeef",
    )
    EventCheckInStationCredential.objects.create(
        event=event, pin_digest="pbkdf2$fixture", pin_ciphertext=b"ciphertext", version=3
    )
    audit_row = audit.record(
        user, "events.programme_fixture_created", makerspace=space,
        target=check_in,
    )
    return {
        "series": series, "event": event, "registration": registration,
        "check_in": check_in, "survey": survey, "response": response,
        "certificate": certificate, "payment": payment, "photo": photo,
        "expired": expired, "rollup": rollup, "organization": organization,
        "audit": audit_row,
    }
