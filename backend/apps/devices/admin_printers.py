"""Read-only printer history; all mutations use scoped services."""
from django.contrib import admin
from unfold.admin import ModelAdmin
from config.admin_access import SuperuserOnlyModelAdmin
from apps.devices.models import DeviceCommand, PrinterDeviceBinding, PrinterJob, PrinterJobConsumption
from apps.separability.tombstones import app_is_tombstoned


class PrinterReadOnlyAdmin(SuperuserOnlyModelAdmin, ModelAdmin):
    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class CommandAdmin(PrinterReadOnlyAdmin):
    exclude = ("lease_token_digest",)


if not app_is_tombstoned("devices"):
    admin.site.register(DeviceCommand, CommandAdmin)
    for model in (PrinterDeviceBinding, PrinterJob, PrinterJobConsumption):
        admin.site.register(model, PrinterReadOnlyAdmin)
