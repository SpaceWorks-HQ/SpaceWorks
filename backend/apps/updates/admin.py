from django.contrib import admin

from apps.separability.tombstones import app_is_tombstoned
from config.admin_access import SuperuserOnlyModelAdmin

from apps.updates.models import PlatformUpdateSettings


class PlatformUpdateSettingsAdmin(SuperuserOnlyModelAdmin, admin.ModelAdmin):
    list_display = (
        "automatic_updates_enabled",
        "status",
        "current_version",
        "available_version",
        "last_checked_at",
    )
    readonly_fields = (
        "status",
        "current_version",
        "available_version",
        "target_version",
        "update_requested_at",
        "last_checked_at",
        "last_updated_at",
        "last_backup_at",
        "last_backup_name",
        "last_error",
        "updated_at",
    )

    def has_add_permission(self, request):
        return not PlatformUpdateSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


# See the note in apps/payments/admin.py: autodiscovery runs before ready(), so this must
# read the setting rather than the runtime manifest.
if not app_is_tombstoned("updates"):
    admin.site.register(PlatformUpdateSettings, PlatformUpdateSettingsAdmin)
