from django.conf import settings
from rest_framework import serializers

from apps.evidence.models import EvidencePhoto


class EvidenceUrlRequestSerializer(serializers.Serializer):
    evidence_type = serializers.ChoiceField(choices=EvidencePhoto.EvidenceType.choices)
    content_type = serializers.CharField()
    size_bytes = serializers.IntegerField(required=False, allow_null=True, min_value=0)

    def validate_content_type(self, value):
        if value not in settings.EVIDENCE_ALLOWED_MIME:
            raise serializers.ValidationError("Unsupported evidence content type.")
        return value


class EvidenceUrlResponseSerializer(serializers.Serializer):
    evidence_id = serializers.IntegerField()
    upload_url = serializers.URLField()
    fields = serializers.DictField()
    object_key = serializers.CharField()
    method = serializers.CharField(required=False)
    headers = serializers.DictField(required=False)


class EvidenceGetResponseSerializer(serializers.Serializer):
    url = serializers.URLField()
    expires_in = serializers.IntegerField()


class EvidenceExpiredResponseSerializer(serializers.Serializer):
    code = serializers.CharField()
    detail = serializers.CharField()
    object_expired_at = serializers.DateTimeField()


class EvidenceCleaningResponseSerializer(serializers.Serializer):
    code = serializers.CharField()
    detail = serializers.CharField()


class EvidenceRetentionPolicySerializer(serializers.Serializer):
    makerspace_id = serializers.IntegerField()
    platform_default_days = serializers.IntegerField()
    override_days = serializers.IntegerField(allow_null=True)
    effective_days = serializers.IntegerField()
    object_expiry_enabled = serializers.BooleanField()
    abandoned_upload_cleanup_enabled = serializers.BooleanField()
    abandoned_upload_platform_default_days = serializers.IntegerField()
    abandoned_upload_override_days = serializers.IntegerField(allow_null=True)
    abandoned_upload_effective_days = serializers.IntegerField()
    abandoned_upload_global_enabled = serializers.BooleanField()


class EvidenceRetentionPatchSerializer(serializers.Serializer):
    """True partial update: supply any subset; an empty body is rejected."""

    object_retention_days = serializers.IntegerField(
        required=False, allow_null=True, min_value=30, max_value=3650,
    )
    abandoned_upload_cleanup_enabled = serializers.BooleanField(required=False)
    abandoned_upload_retention_days = serializers.IntegerField(
        required=False, allow_null=True, min_value=1, max_value=3650,
    )

    def validate_abandoned_upload_retention_days(self, value):
        # Checked against the CURRENT presign TTL, so a stale value can never be saved.
        if value is not None and value * 86400 <= settings.EVIDENCE_URL_TTL_SECONDS:
            raise serializers.ValidationError(
                "Abandoned-upload age must be longer than the evidence upload URL lifetime."
            )
        return value

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Provide at least one policy field.")
        return attrs


class EvidenceRetentionPreviewRequestSerializer(serializers.Serializer):
    limit = serializers.IntegerField(default=100, min_value=1, max_value=1000)


class EvidenceRetentionPreviewResponseSerializer(serializers.Serializer):
    as_of = serializers.DateTimeField()
    policy_days = serializers.IntegerField()
    cutoff = serializers.DateTimeField()
    object_candidates = serializers.IntegerField()
    candidate_bytes = serializers.IntegerField()
    has_more = serializers.BooleanField()
    abandoned_upload_cutoff = serializers.DateTimeField(allow_null=True)
    abandoned_upload_candidates = serializers.IntegerField()
    abandoned_upload_candidate_bytes = serializers.IntegerField()
    abandoned_upload_has_more = serializers.BooleanField()
    late_write_receipts = serializers.IntegerField()
    late_write_receipts_due = serializers.IntegerField()

