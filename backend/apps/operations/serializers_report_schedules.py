from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.evidence.storage import StorageUnavailable
from apps.integrations.models_destinations import NotificationDestination
from apps.integrations.notification_enums import ChatNotificationChannel
from apps.operations.models_report_schedules import (
    MAX_RECIPIENT_EMAILS,
    ReportDelivery,
    ReportSchedule,
)
from apps.operations.report_delivery_storage import signed_download_url
from apps.operations.report_registry import REPORT_KEYS, REPORT_REGISTRY
from apps.payments.models import Payment


class ReportScheduleFiltersSerializer(serializers.Serializer):
    """The subset of manual-export query parameters a schedule may pin.

    `window_days` is the recurring-report shape ("the last 7 days, every Monday"); fixed
    `start`/`end` reproduce the same file each run and are mutually exclusive with it.
    """

    start = serializers.DateField(required=False)
    end = serializers.DateField(required=False)
    window_days = serializers.IntegerField(required=False, min_value=1, max_value=366)
    status = serializers.ChoiceField(choices=Payment.Status.choices, required=False)
    subject_type = serializers.ChoiceField(choices=Payment.SubjectType.choices, required=False)

    def validate(self, attrs):
        if attrs.get("window_days") and (attrs.get("start") or attrs.get("end")):
            raise serializers.ValidationError("Use either window_days or start/end, not both.")
        if attrs.get("start") and attrs.get("end") and attrs["start"] > attrs["end"]:
            raise serializers.ValidationError({"end": "End date must be on or after start date."})
        return attrs


class ReportDeliverySerializer(serializers.ModelSerializer):
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = ReportDelivery
        fields = ("id", "status", "error", "created_at", "expires_at", "download_url")
        read_only_fields = fields

    @extend_schema_field(OpenApiTypes.URI)
    def get_download_url(self, delivery):
        if not delivery.object_key or (delivery.expires_at and delivery.expires_at <= timezone.now()):
            return None
        try:
            return signed_download_url(delivery.object_key)
        except StorageUnavailable:
            return None


class ReportScheduleSerializer(serializers.ModelSerializer):
    report_key = serializers.ChoiceField(choices=[(key, key) for key in REPORT_KEYS])
    filters = serializers.JSONField(required=False)
    next_run_at = serializers.DateTimeField(required=False)
    recipient_emails = serializers.ListField(
        child=serializers.EmailField(), required=False, max_length=MAX_RECIPIENT_EMAILS,
    )
    destination = serializers.PrimaryKeyRelatedField(
        queryset=NotificationDestination.objects.all(), required=False, allow_null=True,
    )
    last_delivery = serializers.SerializerMethodField()

    class Meta:
        model = ReportSchedule
        fields = (
            "id", "makerspace", "report_key", "filters", "grain", "format", "cadence",
            "next_run_at", "last_run_at", "is_active", "destination", "recipient_emails",
            "created_by", "created_at", "updated_at", "last_delivery",
        )
        read_only_fields = ("id", "makerspace", "last_run_at", "created_by", "created_at", "updated_at")

    @extend_schema_field(ReportDeliverySerializer(allow_null=True))
    def get_last_delivery(self, schedule):
        delivery = schedule.deliveries.order_by("-created_at", "-id").first()
        return ReportDeliverySerializer(delivery).data if delivery else None

    def validate_filters(self, value):
        nested = ReportScheduleFiltersSerializer(data=value if value is not None else {})
        nested.is_valid(raise_exception=True)
        # Stored as JSON, so dates become ISO strings; the runner parses them back.
        return {
            key: item.isoformat() if hasattr(item, "isoformat") else item
            for key, item in nested.validated_data.items()
        }

    def validate_destination(self, destination):
        makerspace = self.context["makerspace"]
        if destination is None:
            return None
        # One message for both "not yours" and "not a room": no cross-tenant id probing.
        if destination.makerspace_id != makerspace.id or destination.channel not in ChatNotificationChannel.values:
            raise serializers.ValidationError("Unknown destination.")
        return destination

    def validate(self, attrs):
        current = self.instance
        report_key = attrs.get("report_key", getattr(current, "report_key", None))
        definition = REPORT_REGISTRY[report_key]
        if not definition.exportable:
            raise serializers.ValidationError({"report_key": "Report is not exportable."})
        grain = attrs.get("grain", getattr(current, "grain", "day"))
        allowed = definition.grains or ("day",)
        if grain not in allowed:
            raise serializers.ValidationError({"grain": f"Use one of: {', '.join(allowed)}."})
        destination = attrs.get("destination", getattr(current, "destination", None))
        emails = attrs.get("recipient_emails", getattr(current, "recipient_emails", None) or [])
        if destination is None and not emails:
            raise serializers.ValidationError(
                {"recipient_emails": "Choose a chat destination or at least one email address."}
            )
        if current is None and not attrs.get("next_run_at"):
            attrs["next_run_at"] = timezone.now()
        return attrs
