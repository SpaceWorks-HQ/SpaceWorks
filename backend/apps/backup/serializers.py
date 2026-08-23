from rest_framework import serializers

from apps.backup.models import (
    ARCHIVE_PURGE_WARNING,
    BackupArchive,
    DeploymentRecoveryState,
    PlatformBackupSettings,
    RestoreOperation,
)
from apps.backup.recovery import RESIDUAL_RISK


class BackupArchiveSerializer(serializers.ModelSerializer):
    purge_warning = serializers.SerializerMethodField()

    class Meta:
        model = BackupArchive
        fields = (
            "id", "scope", "makerspace", "status", "manifest", "size_bytes",
            "age_encrypted", "failure_detail", "started_at", "completed_at",
            "expires_at", "created_at", "purge_warning",
        )
        read_only_fields = fields

    def get_purge_warning(self, _instance) -> str:
        return ARCHIVE_PURGE_WARNING


class BackupArchiveCreateSerializer(serializers.Serializer):
    pass


class BackupDownloadSerializer(serializers.Serializer):
    url = serializers.URLField()
    expires_at = serializers.DateTimeField()
    purge_warning = serializers.CharField()


class PlatformBackupSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlatformBackupSettings
        fields = (
            "automatic_backups_enabled", "retention_days", "last_scheduled_at",
            "last_success_at", "last_error", "updated_at",
        )
        read_only_fields = ("last_scheduled_at", "last_success_at", "last_error", "updated_at")


class RestoreOperationSerializer(serializers.ModelSerializer):
    class Meta:
        model = RestoreOperation
        fields = (
            "id", "archive", "kind", "stage", "decision", "restore_diff",
            "decision_deadline_at", "supervisor_heartbeat_at", "error_detail",
            "requested_by_username_snapshot", "requested_at", "completed_at", "updated_at",
        )
        read_only_fields = fields


class RestoreCreateSerializer(serializers.Serializer):
    archive = serializers.PrimaryKeyRelatedField(
        queryset=BackupArchive.objects.filter(
            scope=BackupArchive.Scope.DEPLOYMENT,
            status=BackupArchive.Status.AVAILABLE,
        )
    )
    kind = serializers.ChoiceField(choices=RestoreOperation.Kind.choices)


class RestoreDecisionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(
        choices=(
            RestoreOperation.Decision.PROCEED,
            RestoreOperation.Decision.RESET,
            RestoreOperation.Decision.ABORT,
        )
    )


class RecoveryStateSerializer(serializers.ModelSerializer):
    residual_risk = serializers.SerializerMethodField()

    class Meta:
        model = DeploymentRecoveryState
        fields = (
            "mode", "auth_generation", "active_restore", "recovery_principal",
            "quarantine_reason", "quarantined_at", "acknowledged_at",
            "acknowledged_by", "acknowledgement", "residual_risk", "updated_at",
        )
        read_only_fields = fields

    def get_residual_risk(self, _instance) -> str:
        return RESIDUAL_RISK


class RecoveryAcknowledgeSerializer(serializers.Serializer):
    acknowledgement = serializers.CharField()
