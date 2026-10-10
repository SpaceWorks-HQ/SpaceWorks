from decimal import Decimal

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.payments.models import Payment
from apps.payments.subjects import subject_label
from apps.payments.serializers_reconciliation import refunded_total


class MemberSettlementSerializer(serializers.Serializer):
    """The receipt for a charge staff settled in person, shown back to the payer."""

    method = serializers.CharField()
    received_at = serializers.DateTimeField()
    reference = serializers.CharField()


class MemberRefundSerializer(serializers.Serializer):
    """Money sent back on the member's own charge. Never names the staff member."""

    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    currency = serializers.CharField()
    status = serializers.CharField()
    reason = serializers.CharField()
    settled_at = serializers.DateTimeField(allow_null=True)
    method = serializers.CharField(allow_blank=True)
    reference = serializers.CharField(allow_blank=True)
    refunded_at = serializers.DateTimeField(allow_null=True)


class MemberPaymentSerializer(serializers.ModelSerializer):
    due_state = serializers.SerializerMethodField()
    due_date = serializers.SerializerMethodField()
    subject_label = serializers.SerializerMethodField()
    checkout_url = serializers.SerializerMethodField()
    online_payment_available = serializers.SerializerMethodField()
    settlement = serializers.SerializerMethodField()
    # The receipt for money sent back. `Refund.reason` was always meant to be shown on
    # the receipt, yet the payer had no way to see that a refund existed at all.
    refunded_amount = serializers.SerializerMethodField()
    refunds = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        # `amount` and `currency` are the member's OWN debt. They were staff-private
        # while a Stripe link always carried the figure; with cash settlement the payer
        # has no other way to learn what to bring to the desk, so withholding it made
        # the charge unpayable. The queryset is already scoped to this member.
        fields = (
            "id", "subject_type", "subject_label", "status", "amount", "currency",
            "due_at", "due_date", "due_state",
            "checkout_url", "online_payment_available", "settlement",
            "refunded_amount", "refunds", "created_at",
        )

    def get_refunded_amount(self, payment) -> Decimal:
        return refunded_total(payment)

    @extend_schema_field(MemberRefundSerializer(many=True))
    def get_refunds(self, payment):
        return MemberRefundSerializer([row for row in payment.refunds.all() if not hasattr(row, "amended_by")], many=True).data

    def get_due_state(self, payment) -> str:
        from apps.payments.due_dates import due_state
        return due_state(payment)

    def get_due_date(self, payment) -> str | None:
        from apps.makerspaces.local_time import to_local
        return to_local(payment.makerspace, payment.due_at).date().isoformat() if payment.due_at else None

    def get_subject_label(self, payment) -> str:
        labels = self.context.get("payment_subject_labels", {})
        return subject_label(payment, labels)

    def get_checkout_url(self, payment) -> str:
        # Either rail: a Razorpay link lives only in the generic column, and reading the
        # Stripe one alone hid every live Razorpay link from the member who owed it.
        from apps.payments.checkout_expiry import live_checkout_url

        return live_checkout_url(payment)

    def get_online_payment_available(self, payment) -> bool:
        """Whether offering to pay online is honest for this charge.

        Resolved once per makerspace by the view and passed in: doing it per row would
        re-read settings and credentials for every charge in the list. Falls back to a
        live check only when a caller has not supplied it.
        """
        from apps.payments.availability import online_payments_enabled_for

        rails = self.context.get("payment_rails")
        if rails is not None:
            # Keyed by (owning makerspace, subject type): both decide the answer, and a
            # member list can mix charges owned by different spaces.
            key = (payment.makerspace_id, payment.subject_type)
            if key in rails:
                return bool(rails[key])
        return online_payments_enabled_for(payment)

    @extend_schema_field(MemberSettlementSerializer(allow_null=True))
    def get_settlement(self, payment):
        if payment.status != Payment.Status.PAID_OFFLINE:
            return None
        receipts = self.context.get("payment_settlements")
        receipt = (
            receipts.get(payment.pk)
            if receipts is not None
            else _effective_settlement(payment)
        )
        if receipt is None:
            return None
        return MemberSettlementSerializer(receipt).data


def _effective_settlement(payment):
    from apps.payments.models import ManualSettlement

    return ManualSettlement.effective_for(payment)


class WebhookResponseSerializer(serializers.Serializer):
    """Every provider webhook answers `{"detail": ...}`, acknowledged or refused."""

    detail = serializers.CharField()


class CheckoutUrlSerializer(serializers.Serializer):
    checkout_url = serializers.URLField()


class ArchivedPaymentMakerspaceSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    slug = serializers.SlugField()
    name = serializers.CharField()


class ArchivedPaymentSummarySerializer(serializers.Serializer):
    makerspace = ArchivedPaymentMakerspaceSerializer()
    pending_count = serializers.IntegerField(min_value=0)
    total_count = serializers.IntegerField(min_value=1)


class StaffPaymentSerializer(MemberPaymentSerializer):
    # Amount and currency moved onto the member serializer, so staff inherit them. The
    # refund lines are NOT inherited: this serializer renders one embedded summary per
    # machine-service row, staff read refunds on the reconciliation list instead, and a
    # per-row refund query would grow the service queue's query count with its length.
    refunded_amount = None
    refunds = None
    # Machine-queue summaries do not render aging. Keep local-day lookups on the
    # ledger/history surfaces whose queries fetch the owning makerspace in bulk.
    due_state = None
    due_date = None

    class Meta(MemberPaymentSerializer.Meta):
        fields = tuple(
            name for name in MemberPaymentSerializer.Meta.fields
            if name not in {"refunded_amount", "refunds", "due_at", "due_date", "due_state"}
        )
