from rest_framework import serializers

from apps.machines.models import MachineType


class MachineTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = MachineType
        fields = [
            'id',
            'slug',
            'name',
            'icon',
            'is_builtin',
            'managing_action',
            'capability_config',
            'makerspace',
        ]
        read_only_fields = ['managing_action', 'makerspace', 'capability_config']


class _CustomMachineTypeConfigSerializer(serializers.ModelSerializer):
    def validate(self, attrs):
        attrs = super().validate(attrs)
        config = attrs.get("capability_config", getattr(self.instance, "capability_config", None))
        if config is None:
            raise serializers.ValidationError({"capability_config": "Custom machine types require structural configuration."})
        return attrs

    def validate_capability_config(self, value):
        from apps.machines.metering import validate_type_config
        try:
            validate_type_config(value, is_custom=True)
        except Exception as exc:
            raise serializers.ValidationError(getattr(exc, "messages", [str(exc)])) from exc
        return value


class MachineTypeCreateSerializer(_CustomMachineTypeConfigSerializer):
    class Meta:
        model = MachineType
        fields = ['slug', 'name', 'icon', 'capability_config']


class MachineTypeUpdateSerializer(_CustomMachineTypeConfigSerializer):
    class Meta:
        model = MachineType
        fields = ['name', 'icon', 'capability_config']

    def validate_name(self, value):
        duplicate = (
            MachineType.objects.filter(
                makerspace_id=self.instance.makerspace_id,
                name__iexact=value,
            )
            .exclude(pk=self.instance.pk)
            .exists()
        )
        if duplicate:
            raise serializers.ValidationError(
                'A machine type with this name already exists in this makerspace.'
            )
        return value
