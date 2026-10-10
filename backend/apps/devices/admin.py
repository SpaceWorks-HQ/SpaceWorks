"""Read-only superadmin views of device identity and provenance.

No add/change/delete and no actions: status and key material move only through the
audited services, and the admin must not become a shortcut around them. Registered
only while the app ships (``app_is_tombstoned`` -- the manifest is not populated yet
when admin autodiscovery runs).
"""

from django.contrib import admin
from unfold.admin import ModelAdmin

from apps.devices.models import Device, DeviceEnrollment, DeviceEvent
from apps.separability.tombstones import app_is_tombstoned
from config.admin_access import SuperuserOnlyModelAdmin


class ReadOnlyDeviceAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class DeviceAdmin(ReadOnlyDeviceAdmin):
    list_display = ("name", "makerspace", "kind", "status", "key_version", "last_seen_at")
    list_filter = ("kind", "status", "makerspace")
    search_fields = ("name", "makerspace__name")


class DeviceEnrollmentAdmin(ReadOnlyDeviceAdmin):
    list_display = ("device", "makerspace", "purpose", "created_at", "expires_at", "used_at", "revoked_at")
    list_filter = ("purpose", "makerspace")
    exclude = ("token_digest", "challenge_digest")


class DeviceEventAdmin(ReadOnlyDeviceAdmin):
    list_display = ("device_name", "makerspace", "event_type", "outcome", "device_key_version", "created_at")
    list_filter = ("event_type", "makerspace")


if not app_is_tombstoned("devices"):
    admin.site.register(Device, DeviceAdmin)
    admin.site.register(DeviceEnrollment, DeviceEnrollmentAdmin)
    admin.site.register(DeviceEvent, DeviceEventAdmin)

from . import admin_printers  # noqa: F401 -- read-only registration side effects
