"""OpenAPI shapes for the configuration-only pack protocol."""
from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field

from apps.data_export.space_pack_configuration import SECTIONS, SETTINGS_FIELDS
from apps.makerspaces.models import SpacePackProfile
from apps.makerspaces.opening_hours_schema import OpeningHoursField
from apps.makerspaces.space_pack_validation import StrictFieldsMixin, row_serializer


class PackSettingsSerializer(serializers.Serializer):
    """Schema only: actual writes validate through MakerspaceSerializer."""

    def get_fields(self):
        from .serializers_makerspaces import MakerspaceSerializer
        fields = MakerspaceSerializer().get_fields()
        selected = {key: fields[key] for key in SETTINGS_FIELDS}
        for field in selected.values():
            field.required = True
            field.default = serializers.empty
        return selected


class PackOpeningHoursSerializer(serializers.Serializer):
    timezone = serializers.CharField()
    opening_hours = OpeningHoursField()


class PackBookingRulesSerializer(serializers.Serializer):
    """Query-free shape: bookings may be tombstoned on this deployment."""
    name = serializers.CharField(max_length=200)
    min_booking_duration_minutes = serializers.IntegerField(min_value=1)
    max_booking_duration_minutes = serializers.IntegerField(min_value=1)
    booking_lead_time_minutes = serializers.IntegerField(min_value=0)
    max_booking_advance_days = serializers.IntegerField(min_value=1)
    approval_mode = serializers.ChoiceField(choices=["instant", "approve"])


def configuration_schema(section):
    if section.model == "bookings.BookableSpace":
        return PackBookingRulesSerializer(many=True)
    return type(row_serializer(section))(many=bool(section.identity), allow_null=not section.identity)


PackConfigurationSerializer = type("PackConfigurationSerializer", (serializers.Serializer,), {
    "__module__": __name__,
    "modules": serializers.ListField(child=serializers.CharField()),
    "features": serializers.ListField(child=serializers.CharField()),
    "settings": PackSettingsSerializer(),
    "opening_hours": PackOpeningHoursSerializer(),
    **{key: configuration_schema(spec) for key, spec in SECTIONS.items()},
})


@extend_schema_field(PackConfigurationSerializer)
class PackConfigurationField(serializers.JSONField):
    """Keep signed/checksummed input intact; domain validation runs after verification."""


class SpacePackSerializer(StrictFieldsMixin, serializers.Serializer):
    format = serializers.ChoiceField(choices=["spaceworks-space-pack"])
    version = serializers.IntegerField(min_value=1, max_value=1)
    configuration = PackConfigurationField(help_text="Configuration-only sections; see docs/SPACE-PACKS.md.")
    checksum = serializers.CharField(min_length=64, max_length=64)

    def to_internal_value(self, data):
        # DRF IntegerField coerces strings and booleans; the versioned checksum
        # protocol must validate the original JSON type before that conversion.
        from apps.makerspaces.space_pack_format import open_pack
        open_pack(data)
        return super().to_internal_value(data)


class PackImportSerializer(StrictFieldsMixin, serializers.Serializer):
    pack = SpacePackSerializer()
    dry_run = serializers.BooleanField(default=True)
    base_checksum = serializers.CharField(min_length=64, max_length=64, required=False)


class PackChangeSerializer(serializers.Serializer):
    section = serializers.CharField()
    key = serializers.CharField()
    before = serializers.JSONField(allow_null=True)
    after = serializers.JSONField(allow_null=True)


class PackPreviewSerializer(serializers.Serializer):
    base_checksum = serializers.CharField()
    applied = serializers.BooleanField()
    changes = PackChangeSerializer(many=True)


class PackProfileSerializer(StrictFieldsMixin, serializers.ModelSerializer):
    pack = SpacePackSerializer()

    class Meta:
        model = SpacePackProfile
        fields = ["id", "name", "pack", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class PackErrorSerializer(serializers.Serializer):
    code = serializers.CharField(required=False)
    detail = serializers.CharField(required=False)
    fields = serializers.JSONField(required=False)
    feature = serializers.CharField(required=False)
    module = serializers.CharField(required=False)
    purpose = serializers.CharField(required=False)
