from django.contrib import admin

from apps.devices.admin import ReadOnlyDeviceAdmin
from apps.devices.models import LabelPrintCommand, LabelPrintResult
from apps.separability.tombstones import app_is_tombstoned


class LabelPrintCommandAdmin(ReadOnlyDeviceAdmin):
    list_display = ("batch_title_snapshot", "makerspace", "device", "result", "created_at")
    list_filter = ("result", "makerspace")


class LabelPrintResultAdmin(ReadOnlyDeviceAdmin):
    list_display = ("label_command", "operation_id", "outcome", "response_result", "created_at")


if not app_is_tombstoned("devices"):
    admin.site.register(LabelPrintCommand, LabelPrintCommandAdmin)
    admin.site.register(LabelPrintResult, LabelPrintResultAdmin)
