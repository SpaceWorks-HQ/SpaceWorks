"""Serializers for the staff membership-plan, term and invitation-request surfaces."""
import re

from rest_framework import serializers

from apps.makerspaces.models import InvitationRequest, MembershipPlan, MembershipTerm

_CURRENCY = re.compile(r"^[A-Za-z]{3}$")


class MembershipPlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = MembershipPlan
        fields = [
            "id", "name", "interval", "custom_days", "amount", "currency", "is_active",
            "created_at", "updated_at",
        ]
        # `makerspace` comes from the URL, never the body: accepting it would let a
        # manager in one space price memberships in another.
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_currency(self, value):
        if not _CURRENCY.match(value or ""):
            raise serializers.ValidationError("Use a three-letter ISO 4217 code.")
        return value.lower()

    def validate(self, attrs):
        interval = attrs.get("interval", getattr(self.instance, "interval", None))
        custom_days = attrs.get("custom_days", getattr(self.instance, "custom_days", None))
        if interval == MembershipPlan.Interval.CUSTOM_DAYS:
            if not custom_days:
                raise serializers.ValidationError(
                    {"custom_days": "Required for a custom-days interval."}
                )
        elif custom_days is not None:
            # Silently normalising would hide a client bug; refusing keeps the row honest.
            raise serializers.ValidationError(
                {"custom_days": "Only a custom-days interval takes a day count."}
            )
        return attrs


class MembershipTermSerializer(serializers.ModelSerializer):
    plan_name = serializers.CharField(source="plan.name", read_only=True)

    class Meta:
        model = MembershipTerm
        fields = [
            "id", "membership", "plan", "plan_name", "starts_at", "ends_at", "status",
            "renewal_payment", "created_by", "created_at",
        ]
        read_only_fields = fields


class MembershipTermCreateSerializer(serializers.Serializer):
    plan_id = serializers.IntegerField()
    starts_at = serializers.DateTimeField(required=False, allow_null=True)


class InvitationRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvitationRequest
        fields = [
            "id", "name", "email", "phone", "message", "status", "handled_by",
            "handled_at", "created_at",
        ]
        read_only_fields = fields
