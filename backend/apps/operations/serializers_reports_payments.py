from rest_framework import serializers

from apps.operations.serializers_reports_base import (
    ReportRowsFieldMixin,
    TypedReportBaseSerializer,
)
from apps.payments.models import Payment


class PaymentReportFilterSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Payment.Status.choices, required=False)
    subject_type = serializers.ChoiceField(
        choices=Payment.SubjectType.choices, required=False
    )


class PaymentReconciliationReportRowSerializer(TypedReportBaseSerializer):
    currency = serializers.CharField()
    subject_type = serializers.CharField()
    status = serializers.CharField()
    payment_count = serializers.IntegerField()
    amount_total = serializers.DecimalField(max_digits=20, decimal_places=2)
    outstanding_amount = serializers.DecimalField(max_digits=20, decimal_places=2)
    settlement_method = serializers.CharField(allow_blank=True)
    refunded_amount = serializers.DecimalField(max_digits=20, decimal_places=2)


class PaymentReconciliationReportSerializer(ReportRowsFieldMixin):
    typed_rows = PaymentReconciliationReportRowSerializer(many=True)
