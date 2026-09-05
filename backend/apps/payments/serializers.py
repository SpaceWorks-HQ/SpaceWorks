from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.payments.models import Payment
from apps.payments.subjects import subject_label


class MemberSettlementSerializer(serializers.Serializer):
    """The receipt for a charge staff settled in person, shown back to the payer."""

    method = serializers.CharField()
    received_at = serializers.DateTimeField()
    reference = serializers.CharField()


class MemberPaymentSerializer(serializers.ModelSerializer):
    subject_label = serializers.SerializerMethodField()
    checkout_url = serializers.SerializerMethodField()
    online_payment_available = serializers.SerializerMethodField()
    settlement = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        # `amount` and `currency` are the member's OWN debt. They were staff-private
        # while a Stripe link always carried the figure; with cash settlement the payer
        # has no other way to learn what to bring to the desk, so withholding it made
        # the charge unpayable. The queryset is already scoped to this member.
        fields = (
            "id", "subject_type", "subject_label", "status", "amount", "currency",
            "checkout_url", "online_payment_available", "settlement", "created_at",
        )

    def get_subject_label(self, payment) -> str:
        labels = self.context.get("payment_subject_labels", {})
        return subject_label(payment, labels)

    def get_checkout_url(self, payment) -> str:
        return payment.stripe_checkout_url if payment.status == Payment.Status.PENDING else ""

    def get_online_payment_available(self, payment) -> bool:
        """Whether offering to pay online is honest for this charge.

        Resolved once per makerspace by the view and passed in: doing it per row would
        re-read settings and credentials for every charge in the list. Falls back to a
        live check only when a caller has not supplied it.
        """
        cached = self.context.get("online_payment_available")
        if cached is not None:
            return bool(cached)
        from apps.payments.availability import online_payments_enabled_for

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
    # Amount and currency moved onto the member serializer, so staff inherit them.
    class Meta(MemberPaymentSerializer.Meta):
        fields = MemberPaymentSerializer.Meta.fields
