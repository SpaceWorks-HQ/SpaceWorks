from rest_framework import serializers

from apps.updates.models import PlatformUpdateSettings
from apps.updates.recovery import is_stuck
from apps.updates.rollback import active_rollback, snapshot_refusal


class PlatformUpdateSettingsSerializer(serializers.ModelSerializer):
    is_stuck = serializers.SerializerMethodField()
    rollback_available = serializers.SerializerMethodField()
    rollback_refusal = serializers.SerializerMethodField()
    rollback_refusal_detail = serializers.SerializerMethodField()
    rollback_active = serializers.SerializerMethodField()

    class Meta:
        model = PlatformUpdateSettings
        fields = (
            "automatic_updates_enabled", "channel", "status", "current_version",
            "available_version", "target_version", "update_requested_at", "last_checked_at",
            "last_updated_at", "last_backup_at", "last_backup_name", "last_error", "updated_at",
            "release_notes", "release_url", "running_since", "is_stuck", "pre_update_version",
            "pre_update_archive", "rollback_restore", "rollback_available", "rollback_refusal", "rollback_refusal_detail", "rollback_active",
        )
        read_only_fields = tuple(field for field in fields if field not in {"automatic_updates_enabled", "channel"})

    def get_is_stuck(self, obj) -> bool:
        return is_stuck(obj)

    def get_rollback_available(self, obj) -> bool:
        return snapshot_refusal(obj) is None

    def get_rollback_refusal(self, obj) -> str:
        refusal = snapshot_refusal(obj)
        return refusal[0] if refusal else ""

    def get_rollback_refusal_detail(self, obj) -> str:
        refusal = snapshot_refusal(obj)
        return refusal[1] if refusal else ""

    def get_rollback_active(self, obj) -> bool:
        return active_rollback(obj)


class UpdateRollbackSerializer(serializers.Serializer):
    archive_id = serializers.UUIDField(allow_null=True)
    confirm_version = serializers.CharField(allow_blank=True, max_length=80)
    confirm_data_loss = serializers.BooleanField()


class UpdateRefusalSerializer(serializers.Serializer):
    reason = serializers.CharField()
    detail = serializers.CharField()
