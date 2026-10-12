"""Report preferences reuse SavedView, with a bounded report-specific state contract."""

from rest_framework import serializers

from apps.operations.models_saved_views import SavedView
from apps.operations.report_registry import REPORT_KEYS, REPORT_REGISTRY
from apps.operations.serializers_report_schedules import ReportScheduleFiltersSerializer
from apps.operations.serializers_report_views_filters import allowed_report_filters


class ReportViewStateSerializer(serializers.Serializer):
    report_key = serializers.ChoiceField(choices=REPORT_KEYS)
    filters = ReportScheduleFiltersSerializer(required=False, default=dict)
    grain = serializers.CharField(required=False, max_length=8)
    columns = serializers.ListField(child=serializers.CharField(max_length=80), max_length=100, default=list)

    def to_internal_value(self, data):
        # Nested serializers receive raw data here, before DRF drops unknown keys.
        if isinstance(data, dict) and set(data) - set(self.fields):
            raise serializers.ValidationError({"non_field_errors": ["Unknown report-state key."]})
        return super().to_internal_value(data)

    def validate(self, attrs):
        current = getattr(self.root, "instance", None)
        if current is not None:
            attrs = {**current.state, **attrs}
        attrs.setdefault("filters", {})
        attrs.setdefault("columns", [])
        if "report_key" not in attrs:
            raise serializers.ValidationError({"report_key": "Choose a report."})
        definition = REPORT_REGISTRY[attrs["report_key"]]
        attrs.setdefault("grain", (definition.grains or ("day",))[0])
        if not definition.previewable:
            raise serializers.ValidationError({"report_key": "Report cannot be opened as a saved view."})
        if attrs["grain"] not in (definition.grains or ("day",)):
            raise serializers.ValidationError({"grain": "Unsupported report grain."})
        columns = attrs["columns"]
        if len(columns) != len(set(columns)) or set(columns) - set(definition.fields):
            raise serializers.ValidationError({"columns": "Choose distinct registered report columns."})
        filters = attrs["filters"]
        if set(filters) - allowed_report_filters(attrs["report_key"]):
            raise serializers.ValidationError({"filters": "Unsupported filters for this report."})
        attrs["filters"] = {key: item.isoformat() if hasattr(item, "isoformat") else item for key, item in filters.items()}
        return attrs


class SavedReportViewSerializer(serializers.ModelSerializer):
    state = ReportViewStateSerializer()

    class Meta:
        model = SavedView
        fields = ("id", "makerspace", "owner", "name", "state", "shared", "created_at", "updated_at")
        read_only_fields = ("id", "makerspace", "owner", "created_at", "updated_at")


class SavedReportViewListSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = SavedReportViewSerializer(many=True)
