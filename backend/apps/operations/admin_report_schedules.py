"""Read-only `/control/` view of report schedules and their deliveries.

Schedules are created and edited through the staff API so the RBAC check against the
report's action and the audit entries always fire; the admin is an inspection surface.
"""

from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from apps.operations.models_report_schedules import ReportDelivery, ReportSchedule
from config.admin_access import SuperuserOnlyModelAdmin


class ReportDeliveryInline(TabularInline):
    model = ReportDelivery
    extra = 0
    can_delete = False
    readonly_fields = ("status", "error", "object_key", "created_at", "expires_at")
    fields = readonly_fields

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(ReportSchedule)
class ReportScheduleAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    list_display = (
        "id", "makerspace", "report_key", "cadence", "format", "is_active", "next_run_at", "last_run_at",
    )
    list_filter = ("cadence", "format", "is_active", "makerspace")
    readonly_fields = (
        "makerspace", "report_key", "filters", "grain", "format", "cadence", "next_run_at",
        "last_run_at", "is_active", "destination", "recipient_emails", "created_by",
        "created_at", "updated_at",
    )
    fields = readonly_fields
    inlines = (ReportDeliveryInline,)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
