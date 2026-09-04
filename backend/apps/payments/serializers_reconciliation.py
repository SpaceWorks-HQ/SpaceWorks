from decimal import Decimal

from rest_framework import serializers

from apps.payments.models import Payment, Refund
from apps.payments.subjects import subject_label


class RefundSerializer(serializers.ModelSerializer):
    class Meta:
        model = Refund
        fields = ("id", "amount", "currency", "status", "reason", "created_at", "settled_at")
        read_only_fields = fields


class PaymentReconciliationSerializer(serializers.ModelSerializer):
    subject_label = serializers.SerializerMethodField()
    refunded_amount = serializers.SerializerMethodField()
    refunds = RefundSerializer(many=True, read_only=True)

    class Meta:
        model = Payment
        fields = (
            "id",
            "subject_type",
            "subject_id",
            "subject_label",
            "status",
            "amount",
            "currency",
            "refunded_amount",
            "refunds",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_subject_label(self, payment) -> str:
        return subject_label(
            payment,
            self.context.get("payment_subject_labels", {}),
        )

    def get_refunded_amount(self, payment) -> Decimal:
        # `list_payments` annotates this; a single freshly reconciled row computes it.
        annotated = getattr(payment, "refunded_amount", None)
        if annotated is not None:
            return annotated
        return sum(
            (refund.amount for refund in payment.refunds.all() if refund.status == Refund.Status.SUCCEEDED),
            Decimal("0.00"),
        )


class PaymentListFilterSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Payment.Status.choices, required=False)
    subject_type = serializers.ChoiceField(
        choices=Payment.SubjectType.choices, required=False
    )


class PaymentBulkActionSerializer(serializers.Serializer):
    ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), allow_empty=False
    )

    def validate_ids(self, value):
        if len(value) != len(set(value)):
            raise serializers.ValidationError("Payment IDs must be unique.")
        return value


class PaymentRefundRequestSerializer(serializers.Serializer):
    amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0.01")
    )
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
