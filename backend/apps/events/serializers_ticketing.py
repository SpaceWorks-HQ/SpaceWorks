from rest_framework import serializers

from apps.events.models import EventCategory, EventInvite, EventPromoCode, EventTicketType


class InviteInputSerializer(serializers.Serializer):
    email = serializers.EmailField(required=False, allow_blank=True, write_only=True)
    max_uses = serializers.IntegerField(min_value=1, default=1, required=False)
    expires_at = serializers.DateTimeField(allow_null=True, required=False)


class InviteSerializer(serializers.ModelSerializer):
    code = serializers.CharField(read_only=True, help_text="Returned once on creation only.")

    class Meta:
        model = EventInvite
        fields = ("id", "max_uses", "uses", "expires_at", "revoked_at", "created_at", "code")
        read_only_fields = fields


class PromoInputSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=128, min_length=8, required=False, write_only=True)
    percent_off = serializers.IntegerField(min_value=0, max_value=100, default=0, required=False)
    amount_off = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0, default=0, required=False)
    max_uses = serializers.IntegerField(min_value=1, default=1, required=False)
    expires_at = serializers.DateTimeField(allow_null=True, required=False)


class PromoSerializer(serializers.ModelSerializer):
    code = serializers.CharField(read_only=True, help_text="Returned once on creation only.")

    class Meta:
        model = EventPromoCode
        fields = ("id", "percent_off", "amount_off", "max_uses", "uses", "expires_at", "revoked_at", "created_at", "code")
        read_only_fields = fields


class TicketInputSerializer(serializers.ModelSerializer):
    class Meta:
        model = EventTicketType
        fields = ("name", "amount", "audience", "capacity", "sales_start_at", "sales_end_at")


class TicketSerializer(TicketInputSerializer):
    class Meta(TicketInputSerializer.Meta):
        fields = ("id", *TicketInputSerializer.Meta.fields, "is_active")
        read_only_fields = fields


class CategoryInputSerializer(serializers.ModelSerializer):
    class Meta:
        model = EventCategory
        fields = ("name", "slug")


class CategorySerializer(CategoryInputSerializer):
    class Meta(CategoryInputSerializer.Meta):
        fields = ("id", "name", "slug")
        read_only_fields = fields


class InviteListSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = InviteSerializer(many=True)


class PromoListSerializer(InviteListSerializer):
    results = PromoSerializer(many=True)


class TicketListSerializer(InviteListSerializer):
    results = TicketSerializer(many=True)


class CategoryListSerializer(InviteListSerializer):
    results = CategorySerializer(many=True)
