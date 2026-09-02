"""End-to-end portable tenant move for the complete events programme graph."""

import hashlib
import json

import pytest

from apps.backup import storage as backup_storage
from apps.audit.models import AuditLog
from apps.evidence.models import EvidenceObjectRetentionState, EvidencePhoto, EvidenceRetentionPolicy
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
from apps.makerspaces.models import Makerspace
from apps.operations.models import ReportMetricRollup, ReportRollupCursor
from apps.organizations.models import OrganizationMakerspace
from apps.payments.models import Payment
from apps.tenant_migration.materialization import materialize_tenant
from apps.tenant_migration.object_export import capture_tenant_objects
from tests.data_export.portable_helpers import make_space, make_user
from tests.encryption.conftest import enabled_encryption
from tests.tenant_migration.materialization_helpers import portable_import_case
from tests.tenant_migration.object_helpers import memory_objects
from tests.tenant_migration.programme_graph import QUESTION, create_programme_graph


pytestmark = pytest.mark.django_db(transaction=True)
CERTIFICATE_BYTES = b"%PDF-1.7\nprogramme certificate\n%%EOF\n"


def test_complete_programme_graph_round_trips_with_target_pii_and_expiry(
    memory_objects, monkeypatch
):
    with enabled_encryption():
        user = make_user("programme-roundtrip")
        source = make_space("programme-roundtrip")
        source.enabled_modules = [
            "membership", "events", "bookings", "reports", "evidence_uploads",
        ]
        source.save(update_fields=("enabled_modules",))
        with portable_import_case(
            source, user, prepare_source=create_programme_graph
        ) as case:
            case.decide_walk_in(user)
            graph = case.source_data

            def download(_bucket, key, destination, *, versioned):
                assert key == graph["certificate"].object_key
                assert versioned is True
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(CERTIFICATE_BYTES)
                return {
                    "size": len(CERTIFICATE_BYTES),
                    "sha256": hashlib.sha256(CERTIFICATE_BYTES).hexdigest(),
                    "version_id": "certificate-v1",
                    "content_type": "application/pdf",
                }

            absent = []
            monkeypatch.setattr(backup_storage, "download_object", download)
            monkeypatch.setattr(
                backup_storage,
                "assert_object_absent",
                lambda bucket, key: absent.append((bucket, key)),
            )
            records = capture_tenant_objects(
                case.root, source,
                {"private": "versioned", "public_image": "versioned"},
            )
            tombstone = next(row for row in records if row.get("retention_state"))
            assert tombstone["source_key"] == graph["photo"].object_key
            assert tombstone["expired_size_bytes"] == 321
            assert len(absent) == 2
            result = materialize_tenant(
                case.root,
                case.job,
                case.carried,
                target_identity={"name": "Moved Programme", "slug": "moved-programme"},
                batch_size=2,
            )

        target = Makerspace.objects.get(pk=result.target_makerspace_id)
        series = EventSeries.objects.get(makerspace=target)
        event = target.events.get()
        registration = event.registrations.get()
        check_in = EventCheckInEvent.objects.get(makerspace=target)
        survey = EventFeedbackSurvey.objects.get(event=event)
        response = EventFeedbackResponse.objects.get(survey=survey)
        certificate = EventAttendanceCertificate.objects.get(registration=registration)

        assert target.enabled_modules == source.enabled_modules
        assert (series.title, series.recurrence_rule, series.duration_minutes) == (
            "Monthly safety lab", "FREQ=MONTHLY;COUNT=3", 90,
        )
        assert (event.series_id, event.series_occurrence_key, event.series_revision) == (
            series.pk, "20260903T103000", 1,
        )
        assert registration.member_id == target.memberships.get().user_id
        assert registration.registered_via_makerspace_id == target.pk
        assert registration.payment_via_makerspace_id == target.pk
        assert registration.checkin_token != graph["registration"].checkin_token
        assert (registration.name, registration.email, registration.phone) == (
            "Archive Member", "member@example.test", "+15550001111",
        )
        assert check_in.event_id == event.pk
        assert check_in.registration_id == registration.pk
        assert check_in.actor_id == registration.member_id
        assert survey.questions == [QUESTION]
        assert json.loads(response.answers_snapshot) == {"rating": 5}
        assert response.registration_id == registration.pk
        assert certificate.response_id == response.pk
        assert certificate.recipient_name == "Archive Member"
        assert certificate.object_key != graph["certificate"].object_key
        assert memory_objects["private"][certificate.object_key] == CERTIFICATE_BYTES

        payment = Payment.objects.get(makerspace=target)
        assert payment.subject_type == Payment.SubjectType.EVENT_REGISTRATION
        assert payment.subject_id == registration.pk
        assert payment.member_id == registration.member_id
        assert payment.via_makerspace_id == target.pk
        assert str(payment.amount) == "25.00"

        photo = EvidencePhoto.objects.get(makerspace=target)
        state = EvidenceObjectRetentionState.objects.get(evidence=photo)
        assert state.status == EvidenceObjectRetentionState.Status.EXPIRED
        assert state.expired_size_bytes == 321
        assert state.object_expired_at == graph["expired"].object_expired_at
        assert EvidenceRetentionPolicy.objects.get(makerspace=target).object_retention_days == 30
        assert photo.object_key not in memory_objects["private"]

        rollup = ReportMetricRollup.objects.get(makerspace=target)
        assert (rollup.source_module, rollup.metric_key, rollup.sample_count) == (
            "events", "attended", 1,
        )
        assert str(rollup.value) == "1.000000"
        imported_audit = AuditLog.objects.get(
            makerspace=target, action="events.programme_fixture_created"
        )
        assert imported_audit.actor_id == registration.member_id
        assert imported_audit.target_type == "events.eventcheckinevent"
        assert imported_audit.target_id == str(check_in.pk)
        assert imported_audit.meta == {}

        # Mutable/bearer/global authority is intentionally reissued, never resurrected.
        assert not MemberCalendarFeed.objects.filter(membership__makerspace=target).exists()
        assert not EventCheckInStationCredential.objects.filter(event=event).exists()
        assert not EventSeriesOrganizer.objects.filter(series=series).exists()
        assert not EventOrganizer.objects.filter(event=event).exists()
        assert not OrganizationMakerspace.objects.filter(makerspace=target).exists()
        assert not ReportRollupCursor.objects.filter(makerspace=target).exists()
