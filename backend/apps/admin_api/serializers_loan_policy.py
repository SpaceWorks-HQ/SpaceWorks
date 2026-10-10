from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field

from apps.makerspaces.models_loan_policy import MakerspaceLoanPolicy, validate_reminder_offsets


@extend_schema_field({
    "type": "array", "items": {"type": "integer", "minimum": -8760, "maximum": 8760},
    "maxItems": 100, "uniqueItems": True,
    "description": "Signed whole hours from due time: negative before, zero due, positive overdue.",
})
class LoanReminderOffsetsField(serializers.JSONField):
    pass


class ReturnPolicySerializer(serializers.ModelSerializer):
    # Backward compatible: id is the makerspace id, as on the original route.
    id = serializers.IntegerField(source="makerspace_id", read_only=True)
    loan_reminder_offsets_hours = LoanReminderOffsetsField(required=False)

    class Meta:
        model = MakerspaceLoanPolicy
        fields = [
            "id", "default_loan_days", "loan_renewal_mode", "loan_max_renewals",
            "loan_renewal_days", "loan_max_active", "loan_max_items",
            "loan_reminder_offsets_hours", "loan_escalate_overdue_days",
        ]

    def validate_loan_reminder_offsets_hours(self, value):
        from django.core.exceptions import ValidationError

        try:
            validate_reminder_offsets(value)
        except ValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc
        return sorted(value)
