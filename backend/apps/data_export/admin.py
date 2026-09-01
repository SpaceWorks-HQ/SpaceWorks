from django.contrib import admin
from unfold.admin import ModelAdmin

from apps.data_export.models import DataExportJob
from config.admin_access import SuperuserOnlyModelAdmin


@admin.register(DataExportJob)
class DataExportJobAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    list_display = (
        "id", "makerspace", "fidelity", "status", "accounted_size_bytes", "created_at",
    )
    list_filter = ("makerspace", "fidelity", "status", "created_at")
    search_fields = ("id", "makerspace__name", "makerspace__slug", "requested_by__username")
    readonly_fields = tuple(field.name for field in DataExportJob._meta.fields)
    fields = readonly_fields

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
