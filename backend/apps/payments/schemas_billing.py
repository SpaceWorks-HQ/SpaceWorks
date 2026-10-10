"""Field-validation responses are distinct from typed ledger business errors."""

from drf_spectacular.utils import PolymorphicProxySerializer
from rest_framework import serializers

from apps.hardware_requests.exceptions import ErrorSerializer


class BillingPolicyValidationErrorSerializer(serializers.Serializer):
    payment_terms_days = serializers.ListField(child=serializers.CharField(), required=False)
    reminder_days_before = serializers.JSONField(required=False)
    reminder_days_after = serializers.JSONField(required=False)
    max_reminders = serializers.ListField(child=serializers.CharField(), required=False)
    non_field_errors = serializers.ListField(child=serializers.CharField(), required=False)


class ManualRefundValidationErrorSerializer(serializers.Serializer):
    amount = serializers.ListField(child=serializers.CharField(), required=False)
    reason = serializers.ListField(child=serializers.CharField(), required=False)
    # Missing receipt -> list of errors; supplied receipt -> nested field errors.
    receipt = serializers.JSONField(required=False)
    non_field_errors = serializers.ListField(child=serializers.CharField(), required=False)


class PaymentFilterValidationErrorSerializer(serializers.Serializer):
    due_state = serializers.ListField(child=serializers.CharField(), required=False)
    status = serializers.ListField(child=serializers.CharField(), required=False)
    subject_type = serializers.ListField(child=serializers.CharField(), required=False)
    for_recording = serializers.ListField(child=serializers.CharField(), required=False)


def validation_response(name, serializer):
    return PolymorphicProxySerializer(
        component_name=name, serializers=[ErrorSerializer, serializer],
        resource_type_field_name=None,
    )


BILLING_POLICY_ERROR = validation_response("BillingPolicyError", BillingPolicyValidationErrorSerializer)
MANUAL_REFUND_ERROR = validation_response("ManualRefundError", ManualRefundValidationErrorSerializer)
PAYMENT_FILTER_ERROR = validation_response("PaymentFilterError", PaymentFilterValidationErrorSerializer)
