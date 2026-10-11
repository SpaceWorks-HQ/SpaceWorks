"""Creation-only setup uses the same profile validators as later settings edits."""
from rest_framework import serializers
from apps.admin_api.serializers_makerspace_profile import MakerspaceProfileSerializer
from apps.makerspaces.module_registry import MODULE_KEYS


class FirstStaffInviteSerializer(serializers.Serializer):
    email = serializers.EmailField()
    role_slug = serializers.ChoiceField(choices=["space_manager", "inventory_manager", "machine_manager"])


class CreationProfileSerializer(MakerspaceProfileSerializer):
    """Explicit fields override a pack; omitted fields keep its configuration."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if not field.read_only:
                field.required = False

    def to_internal_value(self, data):
        # Nested serializers receive data through run_validation, not initial_data.
        if isinstance(data, dict):
            unknown = set(data) - {"timezone", "country", "opening_hours", "default_currency"}
            if unknown:
                raise serializers.ValidationError({name: ["Unknown profile field."] for name in sorted(unknown)})
        return super().to_internal_value(data)

    def validate(self, attrs):
        return attrs


class MakerspaceCreationSetupSerializer(serializers.Serializer):
    profile = CreationProfileSerializer(required=False)
    modules = serializers.ListField(child=serializers.ChoiceField(choices=sorted(MODULE_KEYS)), max_length=60, required=False)
    first_staff_invite = FirstStaffInviteSerializer(required=False)


class CreationInviteDeliverySerializer(serializers.Serializer):
    accept_url = serializers.CharField()
    delivery_status = serializers.CharField()
