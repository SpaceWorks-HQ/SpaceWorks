"""Response serializers specific to the staff machine-type access list."""

from rest_framework import serializers

from apps.machines.models import MachineType


class MachineTypeAccessSerializer(serializers.ModelSerializer):
    can_create_machine = serializers.BooleanField(read_only=True)

    class Meta:
        model = MachineType
        fields = (
            "id",
            "slug",
            "name",
            "icon",
            "is_builtin",
            "managing_action",
            "capability_config",
            "makerspace",
            "can_create_machine",
        )
        read_only_fields = fields
