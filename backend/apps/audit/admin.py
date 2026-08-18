from django.contrib import admin
from unfold.admin import ModelAdmin

from apps.audit.models import AuditLog, AuditMacKey
from config.admin_access import SuperuserOnlyModelAdmin


@admin.register(AuditLog)
class AuditLogAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    list_display = (
        "created_at",
        "actor",
        "action",
        "makerspace",
        "target_type",
        "target_id",
    )
    list_filter = ("action", "makerspace", "created_at")
    search_fields = (
        "action",
        "target_type",
        "target_id",
        "actor__username",
        "actor__email",
        "makerspace__name",
        "makerspace__slug",
    )
    readonly_fields = (
        "event_uuid",
        "actor",
        "action",
        "target_type",
        "target_id",
        "makerspace",
        "meta",
        "row_mac",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AuditMacKey)
class AuditMacKeyAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    list_display = ("makerspace", "created_at")
    list_filter = ("makerspace", "created_at")
    readonly_fields = ("makerspace", "created_at")
    exclude = ("wrapped_key",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
