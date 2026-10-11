from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from apps.accounts import rbac
from apps.operations.report_schedule_rules import ReportConditionField, validate_condition, validate_roles

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
from apps.operations.serializers_report_views_filters import allowed_report_filters
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
    months = serializers.IntegerField(required=False, min_value=1, max_value=120)

    def to_internal_value(self, data):
        # Nested serializers receive raw data here, before DRF drops unknown keys.
        if isinstance(data, dict) and set(data) - set(self.fields):
            raise serializers.ValidationError("Unknown report filter.")
        return super().to_internal_value(data)

    def validate(self, attrs):
        if attrs.get("window_days") and (attrs.get("start") or attrs.get("end")):
            raise serializers.ValidationError("Use either window_days or start/end, not both.")
        if attrs.get("start") and attrs.get("end") and attrs["start"] > attrs["end"]:
            raise serializers.ValidationError({"end": "End date must be on or after start date."})
        return attrs


@extend_schema_field(ReportScheduleFiltersSerializer)
class ReportScheduleFiltersField(serializers.JSONField):
    """Typed filter schema with JSON storage and nested boundary validation."""


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
    filters = ReportScheduleFiltersField(required=False)
    condition = ReportConditionField(required=False)
    recipient_roles = serializers.ListField(child=serializers.SlugField(max_length=80), required=False, max_length=20)
    recipient_actions = serializers.ListField(child=serializers.ChoiceField(choices=sorted(rbac.ROLE_GRANTABLE_ACTIONS)), required=False, max_length=20)
    next_run_at = serializers.DateTimeField(required=False)
    recipient_emails = serializers.ListField(
        child=serializers.EmailField(), required=False, max_length=MAX_RECIPIENT_EMAILS,
    )
    destination = serializers.PrimaryKeyRelatedField(
        queryset=NotificationDestination.objects.all(), required=False, allow_null=True,
    )
    last_delivery = serializers.SerializerMethodField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "request" in self.context and "makerspace" in self.context:
            # Scope before resolving a submitted ID, including the DRF field lookup.
            actor = self.context["request"].user
            destinations = NotificationDestination.objects.none()
            for action in {definition.required_action for definition in REPORT_REGISTRY.values()}:
                destinations = destinations | rbac.scope_by_action(actor, action, NotificationDestination.objects.all())
            self.fields["destination"].queryset = destinations.filter(makerspace=self.context["makerspace"])

    class Meta:
        model = ReportSchedule
        fields = (
            "id", "makerspace", "report_key", "filters", "grain", "format", "cadence",
            "next_run_at", "last_run_at", "is_active", "destination", "recipient_emails",
            "created_by", "created_at", "updated_at", "last_delivery",
            "condition", "recipient_roles", "recipient_actions",
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
        # Same refusal as creating a room on that channel: every run would only SKIP.
        from apps.integrations.dispatch_channels import channel_module_blocks

        if channel_module_blocks(makerspace, destination.channel):
            raise serializers.ValidationError(f"The {destination.channel} module is not installed.")
        return destination

    def validate_recipient_emails(self, emails):
        # Staff targets use live selectors. Explicit addresses are for external
        # recipients; legacy schedules are still reauthorized by the runner.
        from apps.makerspaces.models import MakerspaceMembership
        space = self.context["makerspace"]
        members = MakerspaceMembership.objects.none()
        for action in {definition.required_action for definition in REPORT_REGISTRY.values()}:
            members = members | rbac.scope_by_action(self.context["request"].user, action, MakerspaceMembership.objects.all())
        known = {email.lower() for email in members.filter(makerspace=space).values_list("user__email", flat=True) if email}
        existing = {email.strip().lower() for email in getattr(self.instance, "recipient_emails", [])}
        if known & ({email.strip().lower() for email in emails} - existing):
            raise serializers.ValidationError("Use a recipient role or action for makerspace staff.")
        return emails

    def validate(self, attrs):
        current = self.instance
        report_key = attrs.get("report_key", getattr(current, "report_key", None))
        definition = REPORT_REGISTRY[report_key]
        filters = attrs.get("filters", getattr(current, "filters", {}))
        if set(filters) - (allowed_report_filters(report_key) | {"window_days"}):
            raise serializers.ValidationError({"filters": "Unsupported filters for this report."})
        condition = attrs.get("condition", getattr(current, "condition", {}))
        try:
            validated = validate_condition(condition, definition)
        except serializers.ValidationError as exc:
            raise serializers.ValidationError({"condition": exc.detail}) from exc
        if "condition" in attrs:
            attrs["condition"] = validated
        roles = attrs.get("recipient_roles", getattr(current, "recipient_roles", []))
        if roles:
            try:
                validate_roles(self.context["request"].user, self.context["makerspace"], roles, definition.required_action)
            except serializers.ValidationError as exc:
                raise serializers.ValidationError({"recipient_roles": exc.detail}) from exc
        if not definition.exportable:
            raise serializers.ValidationError({"report_key": "Report is not exportable."})
        # The manual export refuses a report whose source module is off; a schedule for it
        # could only ever skip, so it is refused with the same 400 naming the module.
        from apps.makerspaces.guards import require_module

        for module in definition.required_modules:
            require_module(self.context["makerspace"], module)
        if not definition.schedulable:
            # Email/chat delivery would broaden custody of this report's data.
            raise serializers.ValidationError({"report_key": "Report cannot be scheduled."})
        fmt = attrs.get("format", getattr(current, "format", "csv"))
        if fmt not in definition.allowed_formats:
            raise serializers.ValidationError({"format": "Format not allowed for this report."})
        grain = attrs.get("grain", getattr(current, "grain", (definition.grains or ("day",))[0]))
        if current is None and "grain" not in attrs:
            attrs["grain"] = grain
        allowed = definition.grains or ("day",)
        if grain not in allowed:
            raise serializers.ValidationError({"grain": f"Use one of: {', '.join(allowed)}."})
        destination = attrs.get("destination", getattr(current, "destination", None))
        emails = attrs.get("recipient_emails", getattr(current, "recipient_emails", None) or [])
        actions = attrs.get("recipient_actions", getattr(current, "recipient_actions", []))
        if destination is None and not emails and not roles and not actions:
            raise serializers.ValidationError(
                {"recipient_emails": "Choose a destination, email, role or action recipient."}
            )
        if current is None and not attrs.get("next_run_at"):
            attrs["next_run_at"] = timezone.now()
        return attrs
