from decimal import Decimal

from django.utils import timezone
from rest_framework import serializers

from apps.inventory import public_image_storage
from apps.machines import services
from apps.machines.models import (
    Machine,
    MachineDocument,
    MachineErrorLog,
    MachineOperator,
    MachineType,
    MachineUsageEntry,
)
from apps.machines.printer_capabilities import validate_machine_payload
from apps.warranty.models import Warranty
from apps.warranty.status import STATUS_UNKNOWN, warranty_status
from apps.machines.serializers_machine_types import MachineTypeSerializer


class MachineOperatorSerializer(serializers.ModelSerializer):
    user = serializers.IntegerField(source='user_id', read_only=True)
    username = serializers.CharField(source='user.username', read_only=True)
    assigned_by_username = serializers.CharField(
        source='assigned_by.username',
        read_only=True,
        allow_null=True,
    )

    class Meta:
        model = MachineOperator
        fields = [
            'id',
            'user',
            'username',
            'access_level',
            'assigned_by_username',
            'assigned_at',
        ]
        read_only_fields = fields


class MachineUsageEntrySerializer(serializers.ModelSerializer):
    logged_by_username = serializers.CharField(
        source='logged_by.username',
        read_only=True,
        allow_null=True,
    )

    class Meta:
        model = MachineUsageEntry
        fields = [
            'id',
            'hours',
            'source',
            'note',
            'logged_by_username',
            'created_at',
        ]
        read_only_fields = fields


class MachineDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = MachineDocument
        fields = [
            'id',
            'doc_type',
            'original_filename',
            'content_type',
            'size_bytes',
            'created_at',
        ]
        read_only_fields = fields


class MachineErrorLogSerializer(serializers.ModelSerializer):
    logged_by_username = serializers.CharField(
        source='logged_by.username',
        read_only=True,
        allow_null=True,
    )

    class Meta:
        model = MachineErrorLog
        fields = [
            'id',
            'severity',
            'message',
            'logged_by_username',
            'created_at',
        ]
        read_only_fields = fields


class MachineSerializer(serializers.ModelSerializer):
    machine_type = MachineTypeSerializer(read_only=True)
    machine_type_id = serializers.PrimaryKeyRelatedField(
        queryset=MachineType.objects.all(),
        source='machine_type',
        write_only=True,
    )
    usage_hours = serializers.SerializerMethodField()
    image_url = serializers.SerializerMethodField()
    warranty_status = serializers.SerializerMethodField()
    can_operate = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()
    can_delegate = serializers.SerializerMethodField()
    can_retire = serializers.SerializerMethodField()
    can_unretire = serializers.SerializerMethodField()
    # Retained through Phase 0A because the current frontend still reads it.
    can_manage = serializers.SerializerMethodField()

    class Meta:
        model = Machine
        fields = [
            'id',
            'makerspace',
            'machine_type',
            'machine_type_id',
            'name',
            'location',
            'notes',
            'status',
            'firmware_version',
            'camera_feed_url',
            'type_payload',
            'image_url',
            'warranty_status',
            'is_public',
            'is_active',
            'usage_hours',
            'can_operate',
            'can_edit',
            'can_delegate',
            'can_retire',
            'can_unretire',
            'can_manage',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'makerspace',
            'status',
            'is_public',
            'is_active',
            'created_at',
            'updated_at',
        ]

    def get_usage_hours(self, obj) -> Decimal:
        if hasattr(obj, 'usage_total'):
            return obj.usage_total
        return services.machine_usage_total(obj)

    def validate(self, attrs):
        # The type cannot change after creation, so an update must be validated
        # against the persisted type rather than a discarded request value.
        machine_type = self.instance.machine_type if self.instance is not None else attrs.get("machine_type")
        supplied = "type_payload" in self.initial_data
        if self.instance is None and not supplied:
            # Preserve the existing machine-create API while giving a newly
            # created printer an explicit, honest model placeholder.
            type_payload = {"model": "Unspecified"}
            attrs["type_payload"] = type_payload
        else:
            type_payload = attrs.get("type_payload", getattr(self.instance, "type_payload", {}))
        if self.instance is not None and not supplied and not type_payload:
            return attrs
        validate_machine_payload(machine_type, type_payload)
        return attrs

    def get_image_url(self, obj) -> str | None:
        return public_image_storage.public_url(obj.image_key) or None

    def get_warranty_status(self, obj) -> str:
        try:
            warranty = obj.warranty
        except Warranty.DoesNotExist:
            return STATUS_UNKNOWN
        return warranty_status(warranty, timezone.localdate())

    def _capabilities(self, obj):
        from apps.machines import access

        # A list view bulk-computes capabilities once (O(1) queries) and passes them
        # via context; fall back to a per-object computation for the detail view.
        cap_map = self.context.get('machine_capabilities')
        if cap_map is not None and obj.pk in cap_map:
            return cap_map[obj.pk]
        cache = getattr(self, '_capability_cache', {})
        if obj.pk in cache:
            return cache[obj.pk]
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        capabilities = (
            access.machine_capabilities(user, obj)
            if user is not None
            else {key: False for key in access._CAPABILITY_KEYS}
        )
        cache[obj.pk] = capabilities
        self._capability_cache = cache
        return capabilities

    def get_can_operate(self, obj) -> bool:
        return self._capabilities(obj)['can_operate']

    def get_can_edit(self, obj) -> bool:
        return self._capabilities(obj)['can_edit']

    def get_can_delegate(self, obj) -> bool:
        return self._capabilities(obj)['can_delegate']

    def get_can_retire(self, obj) -> bool:
        return self._capabilities(obj)['can_retire']

    def get_can_unretire(self, obj) -> bool:
        return self._capabilities(obj)['can_unretire']

    def get_can_manage(self, obj) -> bool:
        return self._capabilities(obj)['can_edit']
