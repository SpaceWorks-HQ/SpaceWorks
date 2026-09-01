from rest_framework import serializers
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field

from apps.events.models import EventSeries
from apps.forms_schema.serializers import CustomFormSchemaField
from apps.inventory import public_image_storage


class EventSeriesWriteSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    description = serializers.CharField(allow_blank=True, default="", required=False)
    location = serializers.CharField(allow_blank=True, default="", max_length=255, required=False)
    location_kind = serializers.ChoiceField(
        choices=(('indoor', 'Indoor'), ('outdoor', 'Outdoor'), ('other', 'Other')),
        default="other", required=False,
    )
    custom_form = CustomFormSchemaField(allow_null=True, required=False)
    capacity = serializers.IntegerField(default=0, min_value=0, required=False)
    payment_amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=0, default=0, required=False,
    )
    registration_requires_approval = serializers.BooleanField(default=False, required=False)
    registration_cutoff_lead_minutes = serializers.IntegerField(
        allow_null=True, default=None, min_value=0, required=False,
    )
    is_public = serializers.BooleanField(default=False, required=False)
    recurrence_timezone = serializers.CharField(max_length=64)
    dtstart_local_date = serializers.DateField()
    dtstart_local_time = serializers.TimeField()
    recurrence_rule = serializers.CharField(max_length=500)
    duration_minutes = serializers.IntegerField(min_value=1)
    effective_from = serializers.DateTimeField(required=False, write_only=True)


class EventSeriesSummarySerializer(serializers.ModelSerializer):
    makerspace_id = serializers.IntegerField(read_only=True)
    next_occurrence_at = serializers.SerializerMethodField()
    future_occurrence_count = serializers.SerializerMethodField()

    class Meta:
        model = EventSeries
        fields = (
            "id", "public_token", "makerspace_id", "title", "status",
            "recurrence_timezone", "dtstart_local_date", "dtstart_local_time",
            "recurrence_rule", "duration_minutes", "revision", "next_occurrence_at",
            "future_occurrence_count", "last_materialized_at",
            "last_generation_error_code", "updated_at",
        )
        read_only_fields = fields

    @extend_schema_field(OpenApiTypes.DATETIME)
    def get_next_occurrence_at(self, obj):
        value = getattr(obj, "next_occurrence_at", None)
        if value is not None:
            return value
        row = obj.occurrences.filter(status__in=("draft", "published")).order_by("starts_at").first()
        return row.starts_at if row else None

    @extend_schema_field(OpenApiTypes.INT)
    def get_future_occurrence_count(self, obj):
        value = getattr(obj, "future_occurrence_count", None)
        if value is not None:
            return value
        return obj.occurrences.filter(status__in=("draft", "published")).count()


class EventSeriesDetailSerializer(EventSeriesSummarySerializer):
    created_by_id = serializers.IntegerField(allow_null=True, read_only=True)
    image_url = serializers.SerializerMethodField()

    class Meta(EventSeriesSummarySerializer.Meta):
        fields = EventSeriesSummarySerializer.Meta.fields + (
            "description", "location", "location_kind", "custom_form", "capacity",
            "payment_amount", "registration_requires_approval",
            "registration_cutoff_lead_minutes", "is_public", "created_by_id", "created_at",
            "image_url",
        )

    @extend_schema_field(OpenApiTypes.URI)
    def get_image_url(self, obj):
        return public_image_storage.public_url(obj.image_key) or None


class EventSeriesMutationResponseSerializer(serializers.Serializer):
    series = EventSeriesDetailSerializer(read_only=True)
    created_occurrence_ids = serializers.ListField(child=serializers.IntegerField(), read_only=True)
    removed_occurrence_ids = serializers.ListField(child=serializers.IntegerField(), read_only=True)
    affected_count = serializers.IntegerField(read_only=True)


class EventSeriesListResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.CharField(allow_null=True)
    previous = serializers.CharField(allow_null=True)
    results = EventSeriesSummarySerializer(many=True)
