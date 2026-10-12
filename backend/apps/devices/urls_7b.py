from django.urls import path

from .views_commands import DeviceCommandAckView, DeviceCommandLeaseView
from .views_printer_protocol import DevicePrinterResultView, DevicePrinterTelemetryView
from .views_printers import (
    PrinterBindingDetailView, PrinterBindingListView, PrinterJobApplyView,
    PrinterJobDetailView, PrinterJobListView,
)

urlpatterns = [
    path("admin/makerspace/<int:makerspace_id>/device-printer-bindings", PrinterBindingListView.as_view(), name="admin-printer-binding-list"),
    path("admin/device-printer-bindings/<uuid:pk>", PrinterBindingDetailView.as_view(), name="admin-printer-binding-detail"),
    path("admin/makerspace/<int:makerspace_id>/printer-jobs", PrinterJobListView.as_view(), name="admin-printer-job-list"),
    path("admin/printer-jobs/<uuid:pk>", PrinterJobDetailView.as_view(), name="admin-printer-job-detail"),
    path("admin/printer-jobs/<uuid:pk>/apply", PrinterJobApplyView.as_view(), name="admin-printer-job-apply"),
    path("device/commands/lease", DeviceCommandLeaseView.as_view(), name="device-command-lease"),
    path("device/commands/<uuid:pk>/ack", DeviceCommandAckView.as_view(), name="device-command-ack"),
    path("device/printer-jobs/<uuid:pk>/telemetry", DevicePrinterTelemetryView.as_view(), name="device-printer-job-telemetry"),
    path("device/printer-jobs/<uuid:pk>/result", DevicePrinterResultView.as_view(), name="device-printer-job-result"),
]
