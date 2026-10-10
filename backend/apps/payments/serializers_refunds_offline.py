"""Receipt metadata for an offline refund or a cash deposit release."""

from datetime import timedelta

from django.utils import timezone
from rest_framework import serializers

from apps.payments.models import ManualSettlement
from apps.payments.serializers_reconciliation import PaymentRefundRequestSerializer


class ManualRefundReceiptSerializer(serializers.Serializer):
    method = serializers.ChoiceField(choices=ManualSettlement.Method.choices)
    reference = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
    refunded_at = serializers.DateTimeField()

    def validate_refunded_at(self, value):
        if value > timezone.now() + timedelta(minutes=5):
            raise serializers.ValidationError("A refund cannot be dated in the future.")
        return value


class PaymentOfflineRefundSerializer(PaymentRefundRequestSerializer):
    receipt = ManualRefundReceiptSerializer()
