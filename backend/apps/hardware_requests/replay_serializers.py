"""Version-one envelopes; the same normalized envelope is sent to both routes."""

from django.core.validators import MaxLengthValidator
from rest_framework import serializers

from apps.evidence.serializers import EvidenceUrlResponseSerializer
from apps.hardware_requests.kiosk_serializers import KioskEvidencePrepareSerializer
from apps.hardware_requests.replay_payload_serializers import REPLAY_PAYLOADS, ReplayPayloadField
from apps.hardware_requests.replay_failures import ReplayFailure

KINDS = ("assign_box", "reviewed_issue", "reviewed_return", "direct_handout", "direct_return")


class ReplayEnvelopeSerializer(serializers.Serializer):
    client_command_id = serializers.UUIDField()
    kind = serializers.ChoiceField(choices=KINDS)
    version = serializers.IntegerField(min_value=1)
    aggregate_id = serializers.UUIDField()
    sequence = serializers.IntegerField(min_value=1, max_value=10000)
    predecessor_client_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    client_created_at = serializers.DateTimeField()
    payload = ReplayPayloadField()
    evidence = KioskEvidencePrepareSerializer(required=False, allow_null=True, default=None)

    def to_internal_value(self, data):
        if isinstance(data, dict) and (data.get("kind") not in KINDS or str(data.get("version")) != "1"):
            raise ReplayFailure("unsupported_operation_version")
        if isinstance(data, dict) and set(data) - set(self.fields):
            raise ReplayFailure("invalid_command")
        return super().to_internal_value(data)

    def validate(self, attrs):
        if attrs["version"] != 1:
            raise ReplayFailure("unsupported_operation_version")
        if (attrs["sequence"] == 1) != (attrs["predecessor_client_id"] is None):
            raise ReplayFailure("predecessor_missing")
        inner = REPLAY_PAYLOADS[attrs["kind"]](data=attrs["payload"])
        # Explicit bounds on free text and lists; never silently fingerprint ignored keys.
        if set(attrs["payload"]) - set(inner.fields):
            raise ReplayFailure("invalid_command")
        for field in inner.fields.values():
            if isinstance(field, serializers.CharField):
                field.max_length = min(field.max_length or 4000, 4000)
                field.validators.append(MaxLengthValidator(field.max_length))
        _bound_payload(attrs["payload"])
        inner.is_valid(raise_exception=True)
        attrs["payload"] = inner.validated_data
        evidence = attrs["evidence"]
        if attrs["kind"] == "assign_box":
            if evidence is not None:
                raise ReplayFailure("invalid_command")
        else:
            expected = "return" if attrs["kind"].endswith("return") else "issue"
            if evidence is None or evidence["evidence_type"] != expected:
                raise ReplayFailure("evidence_invalid")
            evidence.setdefault("size_bytes", None)
            from django.conf import settings
            if evidence["size_bytes"] is not None and not 1 <= evidence["size_bytes"] <= settings.EVIDENCE_MAX_BYTES:
                raise ReplayFailure("evidence_invalid")
        if attrs["kind"] == "direct_return" and "loan_id" not in attrs["payload"] and attrs["predecessor_client_id"] is None:
            raise ReplayFailure("predecessor_missing")
        return attrs


def _bound_payload(value, depth=0, field=None):
    if depth > 8 or (isinstance(value, str) and len(value) > 4000):
        raise ReplayFailure("invalid_command")
    if isinstance(value, (list, dict)):
        limit = 3550 if depth == 1 and field == "kit_checklist" and isinstance(value, list) else 100
        if len(value) > limit:
            raise ReplayFailure("invalid_command")
        if isinstance(value, dict):
            for key, item in value.items():
                _bound_payload(item, depth + 1, key)
        else:
            for item in value:
                _bound_payload(item, depth + 1)


class ReplayResultSerializer(serializers.Serializer):
    replay_id = serializers.UUIDField()
    client_command_id = serializers.UUIDField()
    state = serializers.ChoiceField(choices=["prepared", "claimed", "succeeded", "failed"])
    kind = serializers.CharField()
    expires_at = serializers.DateTimeField()
    evidence_id = serializers.IntegerField(allow_null=True)
    result_request_id = serializers.IntegerField(allow_null=True)
    result_loan_id = serializers.IntegerField(allow_null=True)
    result_return_event_id = serializers.IntegerField(allow_null=True)
    failure_code = serializers.CharField(allow_null=True)
    failure_detail = serializers.CharField(allow_null=True)
    upload = EvidenceUrlResponseSerializer(required=False, allow_null=True)
