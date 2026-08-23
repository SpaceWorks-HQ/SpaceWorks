from django.contrib import admin
from unfold.admin import ModelAdmin

from config.admin_access import SuperuserOnlyModelAdmin
from apps.separability.tombstones import app_is_tombstoned

from .models import (
    DisclosureClosureApproval,
    TenantDumpCapture,
    TenantMigrationExportJob,
)


class ReadOnlyMigrationAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class DisclosureClosureApprovalAdmin(ReadOnlyMigrationAdmin):
    list_display = (
        "id", "makerspace", "closure_digest", "approved_by", "approved_at", "revoked_at",
    )
    list_filter = ("makerspace", "approved_at", "revoked_at")
    readonly_fields = tuple(field.name for field in DisclosureClosureApproval._meta.fields)


class TenantMigrationExportJobAdmin(ReadOnlyMigrationAdmin):
    list_display = (
        "export_job", "closure_digest", "archive_digest", "format_version",
    )
    list_filter = ("export_job__makerspace", "format_version")
    readonly_fields = tuple(field.name for field in TenantMigrationExportJob._meta.fields)


class TenantDumpCaptureAdmin(ReadOnlyMigrationAdmin):
    list_display = (
        "id", "makerspace", "status", "source_postgres_major", "created_at", "published_at",
    )
    list_filter = ("status", "source_encryption_mode", "created_at")
    readonly_fields = tuple(field.name for field in TenantDumpCapture._meta.fields)

    def resolve_hidden_lookup(self):
        return None


if not app_is_tombstoned("tenant_migration"):
    admin.site.register(DisclosureClosureApproval, DisclosureClosureApprovalAdmin)
    admin.site.register(TenantMigrationExportJob, TenantMigrationExportJobAdmin)
    admin.site.register(TenantDumpCapture, TenantDumpCaptureAdmin)
