"""Raw-column regression sweep for every scoped PII registry entry."""

from datetime import timedelta
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.contrib.admin.sites import AdminSite
from django.db import connection
from django.test import override_settings
from django.utils import timezone

from apps.bookings.models import BookableSpace, Booking
from apps.encryption.crypto import is_envelope
from apps.encryption.registry import ALL_FIELDS
from apps.events.models import (
    Event,
    EventAttendanceCertificate,
    EventFeedbackResponse,
    EventFeedbackSurvey,
    EventRegistration,
)
from apps.hardware_requests.models import HardwareRequest
from apps.integrations.admin_email_logs import EmailLogAdmin
from apps.integrations.models import EmailLog
from apps.makerspaces.models import Makerspace
from apps.machines.models import (
    Machine,
    MachineServiceRequest,
    MachineType,
    MachineUsageEntry,
    ServiceBucket,
)
from tests.encryption.conftest import enabled_encryption

pytestmark = pytest.mark.django_db


def _objects():
    stamp = uuid4().hex[:10]
    space = Makerspace.objects.create(name="Sweep", slug=f"sweep-{stamp}")
    user = get_user_model().objects.create_user(username=f"sweep-{stamp}")
    now = timezone.now()
    event = Event.objects.create(makerspace=space, title="Sweep event", starts_at=now, ends_at=now + timedelta(hours=1))
    bookable = BookableSpace.objects.create(makerspace=space, name="Sweep bench")
    machine_type = MachineType.objects.create(makerspace=space, slug=f"sweep-{stamp}", name="Sweep machine")
    machine = Machine.objects.create(makerspace=space, machine_type=machine_type, name="Sweep machine")
    service_bucket = ServiceBucket.objects.create(machine=machine, name="Sweep service")
    registration = EventRegistration.objects.create(
        event=event, name="Base", email=f"base-{stamp}@example.test", phone="1",
    )
    survey = EventFeedbackSurvey.objects.create(
        event=event, title="Sweep survey",
        questions=[{"id": "q1", "label": "Rating", "type": "number", "options": [], "required": True}],
    )
    # event_feedback_response_mode_matches_identity: a response carries its registration
    # only when a certificate was requested; an anonymous one must stay unattributed.
    response = EventFeedbackResponse.objects.create(
        survey=survey, registration=registration, answers_snapshot="{}",
        certificate_requested=True,
    )
    return {
        "hardware_requests.HardwareRequest": HardwareRequest.objects.create(makerspace=space, requester=user, requester_username=user.username),
        "events.EventRegistration": registration,
        "events.EventFeedbackResponse": response,
        "events.EventAttendanceCertificate": EventAttendanceCertificate.objects.create(
            response=response, registration=registration, revision=1,
            recipient_name="Base", event_title="Sweep event",
            event_starts_at=now, event_ends_at=now + timedelta(hours=1),
            issuer_name="Sweep", object_key=f"certificates/sweep-{stamp}.pdf",
        ),
        "bookings.Booking": Booking.objects.create(space=bookable, name="Base", email=f"booking-{stamp}@example.test", phone="1", starts_at=now + timedelta(days=1), ends_at=now + timedelta(days=1, hours=1)),
        "machines.MachineServiceRequest": MachineServiceRequest.objects.create(bucket=service_bucket, requester=user, title="Sweep service"),
        "machines.MachineUsageEntry": MachineUsageEntry.objects.create(machine=machine, logged_by=user),
        "integrations.EmailLog": EmailLog.objects.create(makerspace=space, to_email=f"mail-{stamp}@example.test", subject="Base", text_body="", html_body=""),
    }


def _sentinel(item):
    token = f"SENTINEL-{item.model_label.replace('.', '-')}-{item.field_name}-{uuid4().hex[:8]}"
    return f"{token.lower()}@example.test" if "email" in item.field_name else token


@pytest.mark.parametrize("item", ALL_FIELDS, ids=lambda item: f"{item.model_label}.{item.field_name}")
def test_every_mapped_value_is_an_envelope_and_not_a_raw_database_leak(item, caplog):
    with enabled_encryption():
        row = _objects()[item.model_label]
        value = _sentinel(item)
        if item.model_label == "machines.MachineUsageEntry":
            # The typed usage ledger is append-only. Its scoped PII must be
            # encrypted at creation rather than through an invalid update.
            row = MachineUsageEntry.objects.create(
                machine=row.machine,
                logged_by=row.logged_by,
                **{item.field_name: value},
            )
        elif item.model_label == "events.EventFeedbackResponse":
            # Feedback answers are an immutable snapshot. Written anonymously here so the
            # identity-mode check constraint holds without a second registration.
            row = EventFeedbackResponse.objects.create(
                survey=row.survey,
                registration=None,
                certificate_requested=False,
                **{item.field_name: value},
            )
        elif item.model_label == "events.EventAttendanceCertificate":
            # Certificate issuance snapshots are immutable, uniq_live_event_certificate
            # allows one non-revoked certificate per registration, and a database trigger
            # refuses a pending -> revoked shortcut. So the sentinel certificate is issued
            # for a FRESH registration rather than contorting the base row.
            stamp = uuid4().hex[:8]
            fresh = EventRegistration.objects.create(
                event=row.registration.event,
                name="Sweep",
                email=f"sweep-cert-{stamp}@example.test",
                phone="1",
            )
            fresh_response = EventFeedbackResponse.objects.create(
                survey=row.response.survey,
                registration=fresh,
                certificate_requested=True,
                answers_snapshot="{}",
            )
            row = EventAttendanceCertificate.objects.create(
                response=fresh_response,
                registration=fresh,
                revision=1,
                event_title=row.event_title,
                event_starts_at=row.event_starts_at,
                event_ends_at=row.event_ends_at,
                issuer_name=row.issuer_name,
                object_key=f"certificates/sweep-{stamp}.pdf",
                **{item.field_name: value},
            )
        else:
            setattr(row, item.field_name, value)
            row.save(update_fields=[item.field_name])
        assert getattr(row, item.field_name) == value
        column = row._meta.get_field(item.field_name).column
        with connection.cursor() as cursor:
            cursor.execute(f'SELECT "{column}" FROM "{row._meta.db_table}" WHERE id = %s', [row.pk])
            raw = cursor.fetchone()[0]
            assert raw.startswith("pii:gcm:v1:")
            for field in ALL_FIELDS:
                model = __import__("django.apps", fromlist=["apps"]).apps.get_model(field.model_label)
                db_column = model._meta.get_field(field.field_name).column
                cursor.execute(f'SELECT "{db_column}" FROM "{model._meta.db_table}"')
                assert all(value not in str(cell) and value.lower() not in str(cell).lower() for (cell,) in cursor.fetchall())
        assert value not in caplog.text


def test_email_log_platform_contract_and_admin_surface_remain_pii_safe(monkeypatch):
    from apps.integrations.dispatch import dispatch_email

    with enabled_encryption():
        monkeypatch.setattr("apps.integrations.dispatch._deliver", lambda log: log)
        platform = dispatch_email(to_email="platform@example.test", subject="secret", text_body="body", sync=True)
        makerspace = _objects()["integrations.EmailLog"]
        with connection.cursor() as cursor:
            cursor.execute('SELECT "to_email", "subject", "text_body" FROM "integrations_emaillog" WHERE id = %s', [makerspace.pk])
            assert all(not value or is_envelope(value) for value in cursor.fetchone())
            cursor.execute('SELECT "to_email", "subject", "text_body" FROM "integrations_emaillog" WHERE id = %s', [platform.pk])
            assert cursor.fetchone() == ("", "Platform email", "")
        admin = EmailLogAdmin(EmailLog, AdminSite())
        assert "to_email" not in admin.search_fields and "subject" not in admin.search_fields
        assert not getattr(EmailLogAdmin.recipient_display, "admin_order_field", None)


def test_flag_off_platform_logs_preserve_values_and_historical_redaction():
    with override_settings(PII_ENCRYPTION_ENABLED=False):
        ordinary = EmailLog.objects.create(to_email="reset@example.test", subject="Reset", text_body="body")
        historical = EmailLog.objects.create(to_email="", subject="Platform email", text_body="", html_body="")
        ordinary.refresh_from_db()
        historical.refresh_from_db()
        assert (ordinary.to_email, ordinary.subject) == ("reset@example.test", "Reset")
        assert (historical.to_email, historical.subject, historical.text_body) == ("", "Platform email", "")
