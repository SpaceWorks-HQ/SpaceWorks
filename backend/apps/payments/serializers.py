from rest_framework import serializers

from apps.payments.models import Payment
from apps.payments.subjects import subject_label


class MemberPaymentSerializer(serializers.ModelSerializer):
    subject_label = serializers.SerializerMethodField()
    checkout_url = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        fields = ("id", "subject_type", "subject_label", "status", "checkout_url", "created_at")

    def get_subject_label(self, payment) -> str:
        labels = self.context.get("payment_subject_labels", {})
        return subject_label(payment, labels)

    def get_checkout_url(self, payment) -> str:
        return payment.stripe_checkout_url if payment.status == Payment.Status.PENDING else ""


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
    class Meta(MemberPaymentSerializer.Meta):
        fields = MemberPaymentSerializer.Meta.fields + ("amount", "currency")
