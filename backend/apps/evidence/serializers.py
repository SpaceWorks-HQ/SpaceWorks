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


class EvidenceRetentionPolicySerializer(serializers.Serializer):
    makerspace_id = serializers.IntegerField()
    platform_default_days = serializers.IntegerField()
    override_days = serializers.IntegerField(allow_null=True)
    effective_days = serializers.IntegerField()
    object_expiry_enabled = serializers.BooleanField()


class EvidenceRetentionPatchSerializer(serializers.Serializer):
    object_retention_days = serializers.IntegerField(
        allow_null=True,
        min_value=30,
        max_value=3650,
    )


class EvidenceRetentionPreviewRequestSerializer(serializers.Serializer):
    limit = serializers.IntegerField(default=100, min_value=1, max_value=1000)


class EvidenceRetentionPreviewResponseSerializer(serializers.Serializer):
    as_of = serializers.DateTimeField()
    policy_days = serializers.IntegerField()
    cutoff = serializers.DateTimeField()
    object_candidates = serializers.IntegerField()
    candidate_bytes = serializers.IntegerField()
    has_more = serializers.BooleanField()
