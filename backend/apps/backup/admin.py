from django.contrib import admin
from unfold.admin import ModelAdmin

from apps.backup.models import (
    ArchiveCustodyAlarmDelivery,
    ArchiveRecipientReservation,
    B1ActivationState,
    BackupArchive,
    BackupArtifactComponent,
    BackupArtifactLedger,
    BackupComponentRecipient,
    BackupLease,
    DeploymentRecoveryState,
    MakerspaceArchiveCustodyState,
    MakerspaceTenantExitCustodyState,
    PlatformBackupSettings,
    RestoreOperation,
    RestoreRollbackObject,
    TenantExitCustodyAlarmDelivery,
)
from config.admin_access import SuperuserOnlyModelAdmin


class ReadOnlyBackupAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(BackupArchive)
class BackupArchiveAdmin(ReadOnlyBackupAdmin):
    list_display = ("id", "scope", "makerspace", "status", "size_bytes", "created_at")
    list_filter = ("scope", "makerspace", "status", "created_at")
    readonly_fields = tuple(field.name for field in BackupArchive._meta.fields)


@admin.register(RestoreOperation)
class RestoreOperationAdmin(ReadOnlyBackupAdmin):
    list_display = ("id", "kind", "stage", "decision", "requested_at")
    list_filter = ("kind", "stage", "decision", "requested_at")
    readonly_fields = tuple(field.name for field in RestoreOperation._meta.fields)


@admin.register(MakerspaceArchiveCustodyState)
class MakerspaceArchiveCustodyStateAdmin(ReadOnlyBackupAdmin):
    list_display = (
        "makerspace",
        "state",
        "reason_code",
        "alarm_episode",
        "entered_at",
        "cleared_at",
    )
    list_filter = ("state", "reason_code")
    readonly_fields = tuple(
        field.name for field in MakerspaceArchiveCustodyState._meta.fields
    )

    def resolve_hidden_lookup(self):
        # This deployment alarm must remain visible even when its makerspace has
        # intentionally hidden ordinary tenant data from the control plane.
        return None


@admin.register(ArchiveCustodyAlarmDelivery)
class ArchiveCustodyAlarmDeliveryAdmin(ReadOnlyBackupAdmin):
    list_display = (
        "id",
        "makerspace",
        "alarm_revision",
        "cycle",
        "channel",
        "status",
        "attempts",
        "updated_at",
    )
    list_filter = ("channel", "status", "created_at")
    readonly_fields = tuple(
        field.name for field in ArchiveCustodyAlarmDelivery._meta.fields
    )

    def resolve_hidden_lookup(self):
        # Platform custody operations remain visible when the affected tenant has
        # deliberately hidden ordinary tenant data from the control plane.
        return None


@admin.register(MakerspaceTenantExitCustodyState)
class MakerspaceTenantExitCustodyStateAdmin(ReadOnlyBackupAdmin):
    list_display = (
        "makerspace", "state", "reason_code", "alarm_episode", "entered_at", "cleared_at",
    )
    list_filter = ("state", "reason_code")
    readonly_fields = tuple(
        field.name for field in MakerspaceTenantExitCustodyState._meta.fields
    )

    def resolve_hidden_lookup(self):
        return None


@admin.register(TenantExitCustodyAlarmDelivery)
class TenantExitCustodyAlarmDeliveryAdmin(ReadOnlyBackupAdmin):
    list_display = (
        "id", "makerspace", "alarm_revision", "cycle", "channel", "status", "attempts",
    )
    list_filter = ("channel", "status", "created_at")
    readonly_fields = tuple(
        field.name for field in TenantExitCustodyAlarmDelivery._meta.fields
    )

    def resolve_hidden_lookup(self):
        return None


for model in (
    PlatformBackupSettings,
    DeploymentRecoveryState,
    BackupLease,
    RestoreRollbackObject,
    ArchiveRecipientReservation,
    B1ActivationState,
    BackupArtifactLedger,
    BackupArtifactComponent,
    BackupComponentRecipient,
):
    admin.site.register(model, ReadOnlyBackupAdmin)
