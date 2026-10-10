"""Read-only `/control/` view of the beat-less scheduler's last runs.

`run_scheduled_tasks` records each task's last run and last error in `PeriodicTaskRun`,
and the cron drivers swallow its exit code (`|| true` in the cloud compose file and the
single-box runner) so one failing task cannot stop the loop. Without this page that
record was invisible: a reminder sweep could fail every night with nothing in any console.
Rows are written only by the command, so nothing here is editable.
"""

from django.contrib import admin
from unfold.admin import ModelAdmin

from apps.operations.models_scheduling import PeriodicTaskRun
from config.admin_access import SuperuserOnlyModelAdmin


@admin.register(PeriodicTaskRun)
class PeriodicTaskRunAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    list_display = ("name", "last_run_at", "status", "last_error")
    search_fields = ("name",)
    ordering = ("name",)
    readonly_fields = ("name", "last_run_at", "last_error")
    fields = readonly_fields

    @admin.display(description="Last run")
    def status(self, obj):
        return "Failed" if obj.last_error else "OK"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
