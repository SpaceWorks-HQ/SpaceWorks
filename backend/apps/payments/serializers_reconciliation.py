from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.payments.models import ManualSettlement, Payment, Refund
from apps.payments.subjects import subject_label


class RefundSerializer(serializers.ModelSerializer):
    class Meta:
        model = Refund
        fields = ("id", "amount", "currency", "status", "provider", "reason", "method", "reference", "refunded_at", "created_at", "settled_at", "amends", "corrected")
        read_only_fields = fields

    corrected = serializers.SerializerMethodField()

    def get_corrected(self, refund) -> bool:
        return hasattr(refund, "amended_by")


class StaffSettlementSerializer(serializers.ModelSerializer):
    """The receipt that currently stands for a charge settled at the desk.

    `corrected` says an earlier receipt was replaced through amend-settlement; the chain
    itself stays in the ledger and the audit log.
    """

    recorded_at = serializers.DateTimeField(source="created_at", read_only=True)
    corrected = serializers.SerializerMethodField()

    class Meta:
        model = ManualSettlement
        fields = ("id", "method", "reference", "received_at", "recorded_at", "corrected")
        read_only_fields = fields

    def get_corrected(self, receipt) -> bool:
        return receipt.amends_id is not None


def refunded_total(payment):
    """Use the list annotation, or prefetched succeeded lines for a single payment."""
    annotated = getattr(payment, "refunded_amount", None)
    if annotated is not None:
        return annotated
    return sum(
        (refund.amount for refund in payment.refunds.all() if refund.status == Refund.Status.SUCCEEDED
         and not hasattr(refund, "amended_by")),
        Decimal("0.00"),
    )


class PaymentReconciliationSerializer(serializers.ModelSerializer):
    due_state = serializers.SerializerMethodField()
    due_date = serializers.SerializerMethodField()
    subject_label = serializers.SerializerMethodField()
    refunded_amount = serializers.SerializerMethodField()
    refunds = RefundSerializer(many=True, read_only=True)
    settlement = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        fields = (
            "id",
            "subject_type",
            "subject_id",
            "subject_label",
            "status",
            "due_at", "due_date", "due_state",
            "amount",
            "currency",
            "refunded_amount",
            "refunds",
            "settlement",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_due_state(self, payment) -> str:
        from apps.payments.due_dates import due_state
        return due_state(payment)

    def get_due_date(self, payment) -> str | None:
        from apps.makerspaces.local_time import to_local
        return to_local(payment.makerspace, payment.due_at).date().isoformat() if payment.due_at else None

    @extend_schema_field(StaffSettlementSerializer(allow_null=True))
    def get_settlement(self, payment):
        if payment.status != Payment.Status.PAID_OFFLINE:
            return None
        receipts = self.context.get("payment_settlements")
        receipt = (
            receipts.get(payment.pk)
            if receipts is not None
            else ManualSettlement.effective_for(payment)
        )
        return StaffSettlementSerializer(receipt).data if receipt is not None else None

    def get_subject_label(self, payment) -> str:
        return subject_label(
            payment,
            self.context.get("payment_subject_labels", {}),
        )

    def get_refunded_amount(self, payment) -> Decimal:
        return refunded_total(payment)


class PaymentListFilterSerializer(serializers.Serializer):
    due_state = serializers.ChoiceField(choices=["overdue", "due_today", "upcoming"], required=False)
    for_recording = serializers.BooleanField(required=False, default=False)
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


class ManualSettlementSerializer(serializers.Serializer):
    """The receipt required to mark a charge paid offline.

    Method and received date are REQUIRED: the point of the ledger is that a settled
    charge can always say how and when the money arrived, and an optional field would
    quietly reproduce the bare boolean it replaces. `reference` stays optional because
    cash genuinely has none.
    """

    method = serializers.ChoiceField(choices=ManualSettlement.Method.choices)
    reference = serializers.CharField(
        max_length=64, required=False, allow_blank=True, default=""
    )
    received_at = serializers.DateTimeField()

    def validate_received_at(self, value):
        # A receipt dated in the future is an operator slip, not a record of money that
        # has already changed hands. Small tolerance for clock skew between devices.
        if value > timezone.now() + timedelta(minutes=5):
            raise serializers.ValidationError("A settlement cannot be received in the future.")
        return value


class PaymentBulkOfflineSerializer(PaymentBulkActionSerializer):
    settlement = ManualSettlementSerializer()


class PaymentOfflineSerializer(serializers.Serializer):
    settlement = ManualSettlementSerializer()


class PaymentRefundRequestSerializer(serializers.Serializer):
    amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0.01")
    )
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
