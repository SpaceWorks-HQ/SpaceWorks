"""Staff payload contracts with server-owned evidence and optional chained loan ID."""

from drf_spectacular.utils import PolymorphicProxySerializer, extend_schema_field
from rest_framework import serializers

from apps.hardware_requests.direct_loan_serializers import DirectLoanIssueSerializer
from apps.hardware_requests.kiosk_serializers import (
    KioskAssignBoxSerializer, KioskDirectReturnSerializer,
    KioskReviewedIssueSerializer, KioskReviewedReturnSerializer,
)


class ReplayReviewedIssueSerializer(KioskReviewedIssueSerializer):
    evidence_id = None


class ReplayReviewedReturnSerializer(KioskReviewedReturnSerializer):
    evidence_id = None


class ReplayDirectHandoutSerializer(DirectLoanIssueSerializer):
    evidence_id = None


class ReplayDirectReturnSerializer(KioskDirectReturnSerializer):
    evidence_id = None
    loan_id = serializers.IntegerField(min_value=1, required=False)


REPLAY_PAYLOADS = {
    "assign_box": KioskAssignBoxSerializer,
    "reviewed_issue": ReplayReviewedIssueSerializer,
    "reviewed_return": ReplayReviewedReturnSerializer,
    "direct_handout": ReplayDirectHandoutSerializer,
    "direct_return": ReplayDirectReturnSerializer,
}


@extend_schema_field(PolymorphicProxySerializer(
    component_name="ReplayDomainPayload", serializers=list(REPLAY_PAYLOADS.values()),
    resource_type_field_name=None,
))
class ReplayPayloadField(serializers.DictField):
    pass
