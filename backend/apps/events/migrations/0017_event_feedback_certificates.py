import uuid

import apps.events.feedback_validation
from django.conf import settings
import django.core.validators
from django.db import migrations, models
import django.db.models.deletion


RESPONSE_TRIGGER = """
CREATE OR REPLACE FUNCTION events_reject_feedback_response_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' AND current_setting('app.allow_immutable_delete', true) = 'on' THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'append-only/immutable table: % not allowed', TG_OP;
END;
$$;
CREATE TRIGGER events_feedback_response_immutable
BEFORE UPDATE OR DELETE ON events_eventfeedbackresponse
FOR EACH ROW EXECUTE FUNCTION events_reject_feedback_response_mutation();
"""

CERTIFICATE_TRIGGER = """
CREATE OR REPLACE FUNCTION events_guard_certificate_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF current_setting('app.allow_immutable_delete', true) = 'on' THEN
            RETURN OLD;
        END IF;
        RAISE EXCEPTION 'immutable certificate delete not allowed';
    END IF;
    IF NEW.response_id IS DISTINCT FROM OLD.response_id OR
       NEW.registration_id IS DISTINCT FROM OLD.registration_id OR
       NEW.serial IS DISTINCT FROM OLD.serial OR
       NEW.revision IS DISTINCT FROM OLD.revision OR
       NEW.recipient_name IS DISTINCT FROM OLD.recipient_name OR
       NEW.event_title IS DISTINCT FROM OLD.event_title OR
       NEW.event_starts_at IS DISTINCT FROM OLD.event_starts_at OR
       NEW.event_ends_at IS DISTINCT FROM OLD.event_ends_at OR
       NEW.issuer_name IS DISTINCT FROM OLD.issuer_name OR
       NEW.object_key IS DISTINCT FROM OLD.object_key OR
       NEW.content_type IS DISTINCT FROM OLD.content_type OR
       NEW.issued_at IS DISTINCT FROM OLD.issued_at THEN
        RAISE EXCEPTION 'certificate issuance snapshots are immutable';
    END IF;
    IF OLD.status = 'active' AND (
        NEW.size_bytes IS DISTINCT FROM OLD.size_bytes OR
        NEW.sha256 IS DISTINCT FROM OLD.sha256 OR
        NEW.rendered_at IS DISTINCT FROM OLD.rendered_at
    ) THEN
        RAISE EXCEPTION 'active certificate artifact is immutable';
    END IF;
    IF NEW.status <> OLD.status AND NOT (
        (OLD.status IN ('pending', 'failed') AND NEW.status = 'rendering') OR
        (OLD.status = 'rendering' AND NEW.status IN ('active', 'failed')) OR
        (OLD.status = 'active' AND NEW.status = 'revoked')
    ) THEN
        RAISE EXCEPTION 'invalid certificate status transition: % to %', OLD.status, NEW.status;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER events_certificate_guard
BEFORE UPDATE OR DELETE ON events_eventattendancecertificate
FOR EACH ROW EXECUTE FUNCTION events_guard_certificate_mutation();
"""

REVERSE_SQL = """
DROP TRIGGER IF EXISTS events_certificate_guard ON events_eventattendancecertificate;
DROP FUNCTION IF EXISTS events_guard_certificate_mutation();
DROP TRIGGER IF EXISTS events_feedback_response_immutable ON events_eventfeedbackresponse;
DROP FUNCTION IF EXISTS events_reject_feedback_response_mutation();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("events", "0016_event_check_in_history"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="EventFeedbackSurvey",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=200)),
                ("thank_you_text", models.TextField(blank=True, validators=[django.core.validators.MaxLengthValidator(2000)])),
                ("questions", models.JSONField(default=list, validators=[apps.events.feedback_validation.validate_feedback_schema])),
                ("is_open", models.BooleanField(default=False)),
                ("certificate_enabled", models.BooleanField(default=False)),
                ("answered_question_ids", models.JSONField(blank=True, default=list)),
                ("opened_at", models.DateTimeField(blank=True, null=True)),
                ("closed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("event", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="feedback_survey", to="events.event")),
            ],
            options={
                "constraints": [models.CheckConstraint(condition=models.Q(("is_open", False), models.Q(("questions", []), _negated=True), _connector="OR"), name="event_feedback_open_has_questions")],
            },
        ),
        migrations.CreateModel(
            name="EventFeedbackResponse",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("answers_snapshot", models.TextField()),
                ("certificate_requested", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("registration", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="feedback_responses", to="events.eventregistration")),
                ("survey", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="responses", to="events.eventfeedbacksurvey")),
            ],
            options={
                "ordering": ["created_at", "id"],
                "indexes": [models.Index(fields=["survey", "created_at", "id"], name="event_feedback_response_idx")],
                "constraints": [
                    models.CheckConstraint(condition=models.Q(models.Q(("certificate_requested", False), ("registration__isnull", True)), models.Q(("certificate_requested", True), ("registration__isnull", False)), _connector="OR"), name="event_feedback_response_mode_matches_identity"),
                    models.UniqueConstraint(condition=models.Q(("registration__isnull", False)), fields=("survey", "registration"), name="uniq_event_feedback_registration"),
                ],
            },
        ),
        migrations.CreateModel(
            name="EventAttendanceCertificate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("serial", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("revision", models.PositiveIntegerField()),
                ("recipient_name", models.TextField()),
                ("event_title", models.CharField(max_length=200)),
                ("event_starts_at", models.DateTimeField()),
                ("event_ends_at", models.DateTimeField()),
                ("issuer_name", models.CharField(max_length=200)),
                ("object_key", models.CharField(max_length=512, unique=True)),
                ("content_type", models.CharField(default="application/pdf", max_length=64)),
                ("size_bytes", models.PositiveBigIntegerField(blank=True, null=True)),
                ("sha256", models.CharField(blank=True, max_length=64)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("rendering", "Rendering"), ("active", "Active"), ("failed", "Failed"), ("revoked", "Revoked")], default="pending", max_length=16)),
                ("issued_at", models.DateTimeField(auto_now_add=True)),
                ("rendered_at", models.DateTimeField(blank=True, null=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("revocation_reason", models.CharField(blank=True, choices=[("attendance_corrected", "Attendance corrected"), ("event_cancelled", "Event cancelled"), ("staff_revoked", "Staff revoked")], max_length=32)),
                ("registration", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="attendance_certificates", to="events.eventregistration")),
                ("response", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="certificates", to="events.eventfeedbackresponse")),
                ("revoked_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["registration_id", "revision"],
                "constraints": [
                    models.UniqueConstraint(fields=("registration", "revision"), name="uniq_event_certificate_revision"),
                    models.UniqueConstraint(condition=models.Q(("status", "revoked"), _negated=True), fields=("registration",), name="uniq_live_event_certificate"),
                ],
            },
        ),
        migrations.RunSQL(RESPONSE_TRIGGER + CERTIFICATE_TRIGGER, REVERSE_SQL),
    ]
