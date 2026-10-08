"""Bounded, discriminated kiosk online-command and work-package schemas (phase 9b).

Each command payload reuses the existing staff serializer for the same workflow, so
the kiosk cannot accept a field the staff route would refuse. Unknown kinds and
versions fail closed.
"""

from rest_framework import serializers

from apps.boxes.serializers import QrResolveSerializer
from apps.evidence.models import EvidencePhoto
from apps.hardware_requests.direct_loan_serializers import (
    DirectLoanIssueSerializer,
    DirectLoanReturnSerializer,
)
from apps.hardware_requests.kiosk_command_policy import OPERATIONS
from apps.hardware_requests.serializers import (
    AssignBoxSerializer,
    IssueRequestSerializer,
    ReturnRequestSerializer,
)


class _RequestRef(serializers.Serializer):
    request_id = serializers.IntegerField(min_value=1)


class _LoanRef(serializers.Serializer):
    loan_id = serializers.IntegerField(min_value=1)


class KioskAssignBoxSerializer(_RequestRef, AssignBoxSerializer):
    pass


class KioskReviewedIssueSerializer(_RequestRef, IssueRequestSerializer):
    pass


class KioskReviewedReturnSerializer(_RequestRef, ReturnRequestSerializer):
    pass


class KioskDirectReturnSerializer(_LoanRef, DirectLoanReturnSerializer):
    pass


PAYLOAD_SERIALIZERS = {
    "resolve_qr": QrResolveSerializer,
    "assign_box": KioskAssignBoxSerializer,
    "reviewed_issue": KioskReviewedIssueSerializer,
    "reviewed_return": KioskReviewedReturnSerializer,
    "direct_handout": DirectLoanIssueSerializer,
    "direct_return": KioskDirectReturnSerializer,
}
assert set(PAYLOAD_SERIALIZERS) == set(OPERATIONS)


class KioskOnlineCommandSerializer(serializers.Serializer):
    version = serializers.ChoiceField(choices=[1])
    kind = serializers.ChoiceField(choices=sorted(OPERATIONS))
    payload = serializers.DictField()

    def validate(self, attrs):
        inner = PAYLOAD_SERIALIZERS[attrs["kind"]](data=attrs["payload"])
        inner.is_valid(raise_exception=True)
        attrs["payload"] = inner.validated_data
        return attrs


class KioskOnlineCommandResultSerializer(serializers.Serializer):
    kind = serializers.CharField()
    result = serializers.DictField()


class KioskWorkPackageRequestSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["reviewed_request", "direct_loan"])
    id = serializers.IntegerField(min_value=1)


class KioskWorkLineSerializer(serializers.Serializer):
    item_id = serializers.IntegerField()
    label = serializers.CharField()
    quantity = serializers.IntegerField()
    returned = serializers.IntegerField()


class KioskWorkPackageSerializer(serializers.Serializer):
    kind = serializers.CharField()
    id = serializers.IntegerField()
    status = serializers.CharField()
    display_label = serializers.CharField()
    person_display = serializers.CharField(allow_blank=True)
    box = serializers.CharField(allow_null=True)
    lines = KioskWorkLineSerializer(many=True)
    return_resolutions = serializers.ListField(child=serializers.CharField())
    expires_at = serializers.DateTimeField()
    command_age_limit_seconds = serializers.IntegerField()
    evidence_max_bytes = serializers.IntegerField()


class KioskEvidencePrepareSerializer(serializers.Serializer):
    evidence_type = serializers.ChoiceField(choices=EvidencePhoto.EvidenceType.choices)
    content_type = serializers.CharField()
    size_bytes = serializers.IntegerField(required=False, allow_null=True, min_value=0)

    def validate_content_type(self, value):
        from django.conf import settings

        if value not in settings.EVIDENCE_ALLOWED_MIME:
            raise serializers.ValidationError("Unsupported evidence content type.")
        return value
