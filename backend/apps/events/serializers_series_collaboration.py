from rest_framework import serializers
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field

from apps.events.models import EventSeriesCollaborator


class SeriesCollaboratorReplaceSerializer(serializers.Serializer):
    slugs = serializers.ListField(child=serializers.SlugField(), allow_empty=True)


class SeriesCollaborationRespondSerializer(serializers.Serializer):
    accept = serializers.BooleanField()


class SeriesCollaboratorSerializer(serializers.ModelSerializer):
    series_id = serializers.IntegerField(read_only=True)
    makerspace_id = serializers.IntegerField(read_only=True)
    makerspace_name = serializers.CharField(source="makerspace.name", read_only=True)
    makerspace_slug = serializers.SlugField(source="makerspace.slug", read_only=True)
    invited_by_id = serializers.IntegerField(allow_null=True, read_only=True)
    responded_by_id = serializers.IntegerField(allow_null=True, read_only=True)

    class Meta:
        model = EventSeriesCollaborator
        fields = (
            "id", "series_id", "makerspace_id", "makerspace_name", "makerspace_slug",
            "status", "invited_by_id", "responded_by_id", "created_at", "responded_at",
        )
        read_only_fields = fields


class SeriesCollaborationInboxSerializer(serializers.ModelSerializer):
    series_id = serializers.IntegerField(read_only=True)
    series_title = serializers.CharField(source="series.title", read_only=True)
    host_name = serializers.CharField(source="series.makerspace.name", read_only=True)
    host_slug = serializers.SlugField(source="series.makerspace.slug", read_only=True)
    next_occurrence_at = serializers.SerializerMethodField()

    class Meta:
        model = EventSeriesCollaborator
        fields = (
            "id", "series_id", "series_title", "host_name", "host_slug", "status",
            "next_occurrence_at", "created_at", "responded_at",
        )
        read_only_fields = fields

    @extend_schema_field(OpenApiTypes.DATETIME)
    def get_next_occurrence_at(self, obj):
        occurrence = obj.series.occurrences.filter(status="published").order_by("starts_at").first()
        return occurrence.starts_at if occurrence else None
