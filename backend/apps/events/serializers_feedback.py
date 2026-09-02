import json

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.events.feedback_validation import validate_feedback_schema
from apps.events.models import EventAttendanceCertificate


class FeedbackSurveyWriteSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    thank_you_text = serializers.CharField(
        allow_blank=True,
        default="",
        max_length=2_000,
        required=False,
    )
    questions = serializers.JSONField()
    certificate_enabled = serializers.BooleanField(default=False, required=False)

    def validate_questions(self, value):
        return validate_feedback_schema(value)


class FeedbackSurveySerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    title = serializers.CharField(read_only=True)
    thank_you_text = serializers.CharField(read_only=True)
    questions = serializers.JSONField(read_only=True)
    is_open = serializers.BooleanField(read_only=True)
    certificate_enabled = serializers.BooleanField(read_only=True)
    answered_question_ids = serializers.ListField(
        child=serializers.CharField(), read_only=True,
    )
    opened_at = serializers.DateTimeField(allow_null=True, read_only=True)
    closed_at = serializers.DateTimeField(allow_null=True, read_only=True)
    response_count = serializers.IntegerField(read_only=True, required=False)


class FeedbackSurveyAdminEnvelopeSerializer(serializers.Serializer):
    survey = FeedbackSurveySerializer(allow_null=True)


class CertificateSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = EventAttendanceCertificate
        fields = ("id", "status", "revision", "issued_at", "rendered_at", "revoked_at")
        read_only_fields = fields


class FeedbackResponseSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    answers = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField(read_only=True)
    identity = serializers.SerializerMethodField()
    certificate = serializers.SerializerMethodField()

    @extend_schema_field(serializers.JSONField())
    def get_answers(self, obj):
        return json.loads(obj.answers_snapshot)

    @extend_schema_field(serializers.DictField(allow_null=True))
    def get_identity(self, obj):
        if obj.registration_id is None:
            return None
        return {
            "registration_id": obj.registration_id,
            "name": obj.registration.name,
            "email": obj.registration.email,
        }

    @extend_schema_field(CertificateSummarySerializer(allow_null=True))
    def get_certificate(self, obj):
        certificate = max(obj.certificates.all(), key=lambda item: item.revision, default=None)
        return None if certificate is None else CertificateSummarySerializer(certificate).data


class FeedbackResponseListSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = FeedbackResponseSerializer(many=True)


class FeedbackFormSerializer(serializers.Serializer):
    event = serializers.DictField(read_only=True)
    survey = FeedbackSurveySerializer(read_only=True)
    mode = serializers.ChoiceField(choices=("anonymous", "certificate"), read_only=True)
    requires_auth = serializers.BooleanField(read_only=True)
    certificate = CertificateSummarySerializer(allow_null=True, read_only=True, required=False)


class FeedbackSubmissionSerializer(serializers.Serializer):
    answers = serializers.DictField(required=False, default=dict)
    email = serializers.EmailField(required=False)


class FeedbackSubmissionResponseSerializer(serializers.Serializer):
    thank_you_text = serializers.CharField()
    certificate = CertificateSummarySerializer(allow_null=True)


class CertificateDownloadSerializer(serializers.Serializer):
    url = serializers.URLField()
    expires_at = serializers.DateTimeField()


class CertificateRevokeSerializer(serializers.Serializer):
    reason = serializers.ChoiceField(
        choices=(EventAttendanceCertificate.RevocationReason.STAFF_REVOKED,),
    )


class AttendanceCorrectionResponseSerializer(serializers.Serializer):
    registration_id = serializers.IntegerField()
    status = serializers.CharField()
    revoked_certificates = serializers.IntegerField()
