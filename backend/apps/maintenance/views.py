from apps.maintenance.views_documents import (
    MaintenanceLogDocumentDetailView,
    MaintenanceLogDocumentFinalizeView,
    MaintenanceLogDocumentPresignView,
    MaintenanceLogDocumentUrlView,
)
from apps.maintenance.views_logs import MaintenanceLogListCreateView
from apps.maintenance.views_schedules import (
    MaintenanceScheduleDeactivateView,
    MaintenanceScheduleDetailView,
    MaintenanceScheduleListCreateView,
)

__all__ = [
    "MaintenanceLogDocumentDetailView",
    "MaintenanceLogDocumentFinalizeView",
    "MaintenanceLogDocumentPresignView",
    "MaintenanceLogDocumentUrlView",
    "MaintenanceLogListCreateView",
    "MaintenanceScheduleDeactivateView",
    "MaintenanceScheduleDetailView",
    "MaintenanceScheduleListCreateView",
]
